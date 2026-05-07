"""
Management command: backfill on-chain createCampaign cho các chiến dịch
đã có trong DB nhưng chưa được sync lên DCPManager V4 (smart2.sol).

====================================================================
 LOCATION & MODEL REFERENCE (V4 "Double Integrity" architecture)
====================================================================
 - Model   : admin_panel.models.Campaign    (KHÔNG nằm ở client.models)
 - Field   : is_onchain  (BooleanField)     (KHÔNG phải is_synced)
 - Related :
     * blockchain_tx_hash       — tx hash createCampaign gần nhất
     * blockchain_synced_at     — timestamp sync thành công
     * blockchain_sync_error    — thông điệp lỗi gần nhất (None nếu OK)

Usage:
    # Liệt kê (dry-run) các campaign cần sync
    python manage.py sync_campaigns_to_blockchain --dry-run

    # Chạy thật: chỉ sync các campaign chưa on-chain
    python manage.py sync_campaigns_to_blockchain

    # Chỉ sync 1 vài campaign cụ thể
    python manage.py sync_campaigns_to_blockchain --ids 44,45

    # Ép sync lại (bỏ qua cờ is_onchain), reset per-campaign trước khi gọi RPC
    python manage.py sync_campaigns_to_blockchain --force

    # MIGRATION V3 → V4: reset TOÀN BỘ cờ on-chain về False rồi sync lại
    # (dùng khi đổi CONTRACT_ADDRESS sang contract V4 mới)
    python manage.py sync_campaigns_to_blockchain --reset-all
"""
from django.core.management.base import BaseCommand

from admin_panel.models import Campaign
from admin_panel.blockchain_utils import sync_single_campaign


class Command(BaseCommand):
    help = (
        "Đồng bộ các Campaign status='active' lên DCPManager V4 (Admin Relayer). "
        "Dùng --reset-all khi migrate V3→V4."
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Chỉ liệt kê, không gọi RPC.')
        parser.add_argument('--ids', type=str, default='',
                            help='CSV các Campaign.id cụ thể cần sync.')
        parser.add_argument('--force', action='store_true',
                            help='Bỏ qua cờ is_onchain và sync lại (per-campaign reset).')
        parser.add_argument('--reset-all', action='store_true',
                            help=('Trước khi sync, RESET toàn bộ is_onchain/blockchain_tx_hash/'
                                  'blockchain_synced_at/blockchain_sync_error về rỗng cho các '
                                  'campaign trong queryset. Dùng khi migrate sang contract mới (V3→V4).'))

    def handle(self, *args, **opts):
        qs = Campaign.objects.filter(status='active')
        if opts['ids']:
            try:
                wanted = [int(x.strip()) for x in opts['ids'].split(',') if x.strip()]
                qs = qs.filter(id__in=wanted)
            except ValueError:
                self.stderr.write('--ids phải là CSV các số nguyên.')
                return

        # --reset-all: wipe cờ sync cho toàn bộ queryset (kể cả campaign đang is_onchain=True)
        # để ép chạy lại createCampaign trên contract mới.
        if opts['reset_all']:
            reset_qs = qs  # reset TRƯỚC khi filter is_onchain=False
            reset_count = reset_qs.update(
                is_onchain=False,
                blockchain_tx_hash=None,
                blockchain_synced_at=None,
                blockchain_sync_error=None,
            )
            self.stdout.write(self.style.WARNING(
                f'🔄 [RESET-ALL] Đã reset cờ sync cho {reset_count} campaign. '
                'Bắt đầu re-sync lên contract mới...'
            ))

        # --force và --reset-all đều bypass filter is_onchain=False
        if not (opts['force'] or opts['reset_all']):
            qs = qs.filter(is_onchain=False)

        qs = qs.order_by('id')
        total = qs.count()
        self.stdout.write(self.style.NOTICE(f'Tìm thấy {total} campaign cần sync.'))

        if total == 0:
            self.stdout.write(self.style.WARNING(
                'Không có campaign nào khớp bộ lọc.\n'
                '  • Nếu bạn vừa đổi CONTRACT_ADDRESS (V3→V4), chạy với --reset-all.\n'
                '  • Kiểm tra: Campaign.objects.filter(status="active").count() '
                'trong shell để xem có bao nhiêu campaign đang active.'
            ))
            return

        if opts['dry_run']:
            for c in qs:
                org_wallet = getattr(c.organization, 'wallet_address', None) or '(chưa có ví)'
                self.stdout.write(
                    f'  #{c.id}  {c.title[:60]:60s}  '
                    f'is_onchain={c.is_onchain}  org_wallet={org_wallet}'
                )
            return

        ok = 0
        fail = 0
        already = 0
        for c in qs:
            self.stdout.write(f'→ Sync Campaign #{c.id} "{c.title[:60]}"...')
            try:
                # Per-campaign reset nếu dùng --force (reset-all đã wipe bulk ở trên)
                if opts['force'] and not opts['reset_all']:
                    c.is_onchain = False
                    c.blockchain_tx_hash = None
                sync_single_campaign(c.id)
                c.refresh_from_db()
                if c.is_onchain:
                    ok += 1
                    self.stdout.write(self.style.SUCCESS(f'   OK (tx={c.blockchain_tx_hash})'))
                else:
                    err = (c.blockchain_sync_error or '').lower()
                    # Contract reverts với "Chien dich da ton tai" khi ID đã tồn tại on-chain.
                    # Đây không phải lỗi thật — đánh dấu is_onchain=True và bỏ qua.
                    if 'da ton tai' in err or 'already exists' in err:
                        c.is_onchain = True
                        c.blockchain_sync_error = None
                        c.save(update_fields=['is_onchain', 'blockchain_sync_error'])
                        already += 1
                        self.stdout.write(self.style.WARNING('   ĐÃ TỒN TẠI on-chain → đánh dấu is_onchain=True.'))
                    else:
                        fail += 1
                        self.stdout.write(self.style.ERROR(f'   FAIL ({(c.blockchain_sync_error or "")[:200]})'))
            except Exception as exc:
                fail += 1
                self.stdout.write(self.style.ERROR(f'   FAIL ({type(exc).__name__}: {exc})'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Hoàn tất: {ok} tạo mới, {already} đã tồn tại on-chain, {fail} thất bại / {total} tổng.'
        ))
