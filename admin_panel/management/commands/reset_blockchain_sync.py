"""
Management command: RESET cờ on-chain của các Campaign về trạng thái "chưa sync".

Dùng khi:
  - Migrate contract (VD: V3 → V4): đổi CONTRACT_ADDRESS, các campaign cũ mang
    cờ is_onchain=True nhưng thật ra chỉ tồn tại trên contract V3 — cần wipe
    cờ để script sync tạo lại trên V4.
  - Debug: muốn ép re-sync một số campaign cụ thể.

Model/field reference (V4 "Double Integrity"):
  - admin_panel.models.Campaign  (KHÔNG phải client.models)
  - is_onchain  (KHÔNG phải is_synced)
  - blockchain_tx_hash, blockchain_synced_at, blockchain_sync_error

Usage:
    # Dry-run: xem sẽ reset campaign nào
    python manage.py reset_blockchain_sync --dry-run

    # Reset toàn bộ campaign đang status='active'
    python manage.py reset_blockchain_sync --all

    # Chỉ reset 1 vài campaign cụ thể
    python manage.py reset_blockchain_sync --ids 12,44,45

    # Reset cả campaign ở status khác (hiếm dùng)
    python manage.py reset_blockchain_sync --all --include-non-active
"""
from django.core.management.base import BaseCommand, CommandError

from admin_panel.models import Campaign


class Command(BaseCommand):
    help = (
        "Reset cờ on-chain (is_onchain, blockchain_tx_hash, blockchain_synced_at, "
        "blockchain_sync_error) về trạng thái chưa sync. Dùng khi migrate contract."
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Chỉ liệt kê, không update DB.')
        parser.add_argument('--all', action='store_true',
                            help='Reset tất cả campaign (mặc định status=active).')
        parser.add_argument('--ids', type=str, default='',
                            help='CSV các Campaign.id cụ thể cần reset.')
        parser.add_argument('--include-non-active', action='store_true',
                            help='Khi --all: bao gồm cả campaign status != active.')
        parser.add_argument('--yes', action='store_true',
                            help='Bỏ qua prompt xác nhận (dùng trong script).')

    def handle(self, *args, **opts):
        if not opts['all'] and not opts['ids']:
            raise CommandError('Phải chọn --all hoặc --ids <csv>.')

        qs = Campaign.objects.all()
        if opts['ids']:
            try:
                wanted = [int(x.strip()) for x in opts['ids'].split(',') if x.strip()]
            except ValueError:
                raise CommandError('--ids phải là CSV các số nguyên.')
            qs = qs.filter(id__in=wanted)
        elif opts['all']:
            if not opts['include_non_active']:
                qs = qs.filter(status='active')

        qs = qs.order_by('id')
        total = qs.count()

        if total == 0:
            self.stdout.write(self.style.WARNING('Không có campaign nào khớp bộ lọc.'))
            return

        self.stdout.write(self.style.NOTICE(
            f'Sẽ reset cờ on-chain cho {total} campaign:'
        ))
        for c in qs.values('id', 'title', 'status', 'is_onchain', 'blockchain_tx_hash')[:50]:
            self.stdout.write(
                f"  #{c['id']:>4} [{c['status']:>8}] is_onchain={c['is_onchain']!s:>5}  "
                f"tx={(c['blockchain_tx_hash'] or '-')[:14]}…  {c['title'][:50]}"
            )
        if total > 50:
            self.stdout.write(f'  ... và {total - 50} campaign nữa.')

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('[DRY-RUN] Không có gì được ghi.'))
            return

        if not opts['yes']:
            confirm = input(f'\nXác nhận reset {total} campaign? [y/N]: ').strip().lower()
            if confirm not in ('y', 'yes'):
                self.stdout.write(self.style.ERROR('Hủy bỏ.'))
                return

        updated = qs.update(
            is_onchain=False,
            blockchain_tx_hash=None,
            blockchain_synced_at=None,
            blockchain_sync_error=None,
        )
        self.stdout.write(self.style.SUCCESS(
            f'✅ Đã reset {updated} campaign. '
            'Giờ chạy: python manage.py sync_campaigns_to_blockchain'
        ))
