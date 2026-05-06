"""
Management command: backfill on-chain createCampaign cho các chiến dịch
đã có trong DB nhưng chưa được sync lên DCPManager v3.

Usage:
    python manage.py sync_campaigns_to_blockchain                # chạy thật
    python manage.py sync_campaigns_to_blockchain --dry-run      # chỉ liệt kê
    python manage.py sync_campaigns_to_blockchain --ids 44,45    # chỉ 1 vài cid
"""
from django.core.management.base import BaseCommand

from admin_panel.models import Campaign
from admin_panel.views import _sync_campaign_to_blockchain


class Command(BaseCommand):
    help = "Đồng bộ các Campaign status='active' lên DCPManager v3 (Admin Relayer)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Chỉ liệt kê, không gọi RPC.')
        parser.add_argument('--ids', type=str, default='', help='CSV các Campaign.id cụ thể cần sync.')
        parser.add_argument('--force', action='store_true',
                            help='Bỏ qua cờ is_onchain và sync lại (có thể revert nếu đã tồn tại).')

    def handle(self, *args, **opts):
        qs = Campaign.objects.filter(status='active')
        if opts['ids']:
            try:
                wanted = [int(x.strip()) for x in opts['ids'].split(',') if x.strip()]
                qs = qs.filter(id__in=wanted)
            except ValueError:
                self.stderr.write('--ids phải là CSV các số nguyên.')
                return

        if not opts['force']:
            qs = qs.filter(is_onchain=False)

        qs = qs.order_by('id')
        total = qs.count()
        self.stdout.write(self.style.NOTICE(f'Tìm thấy {total} campaign cần sync.'))

        if opts['dry_run']:
            for c in qs:
                org_wallet = getattr(c.organization, 'wallet_address', None) or '(chưa có ví)'
                self.stdout.write(f'  #{c.id}  {c.title[:60]:60s}  org_wallet={org_wallet}')
            return

        ok = 0
        fail = 0
        already = 0
        for c in qs:
            self.stdout.write(f'→ Sync Campaign #{c.id} "{c.title[:60]}"...')
            try:
                if opts['force']:
                    c.is_onchain = False
                    c.blockchain_tx_hash = None
                _sync_campaign_to_blockchain(c)
                c.refresh_from_db()
                if c.is_onchain:
                    ok += 1
                    self.stdout.write(self.style.SUCCESS(f'   OK (tx={c.blockchain_tx_hash})'))
                else:
                    err = (c.blockchain_sync_error or '').lower()
                    # Contract reverts with "Chien dich da ton tai" khi ID đã tồn tại on-chain.
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
