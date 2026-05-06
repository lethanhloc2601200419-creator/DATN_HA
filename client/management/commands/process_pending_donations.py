"""
Management command to backup-process donations whose blockchain step didn't finish.

Usage:
    python manage.py process_pending_donations                 # one-shot
    python manage.py process_pending_donations --loop --sleep=60  # daemon mode

Logic:
    - Pick donations with status=completed (VNPay paid) and blockchain_status in
      ('pending', 'failed') OR blockchain_status='processing' but last started > 15 min ago.
    - Call process_donation_blockchain() synchronously for each.
"""
import time
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from admin_panel.models import Donation
from client.blockchain_processor import process_donation_blockchain


class Command(BaseCommand):
    help = "Retry blockchain sync for donations stuck in pending/failed state."

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true', help='Run forever in a loop')
        parser.add_argument('--sleep', type=int, default=60, help='Seconds between iterations in loop mode')
        parser.add_argument('--max-retries', type=int, default=5, help='Skip donations with retry_count >= this')
        parser.add_argument('--stuck-minutes', type=int, default=15, help='Reset processing status after this many minutes')

    def handle(self, *args, **options):
        loop = options['loop']
        sleep_s = options['sleep']
        max_retries = options['max_retries']
        stuck_minutes = options['stuck_minutes']

        while True:
            self._run_once(max_retries, stuck_minutes)
            if not loop:
                break
            time.sleep(sleep_s)

    def _run_once(self, max_retries, stuck_minutes):
        stuck_threshold = timezone.now() - timedelta(minutes=stuck_minutes)

        # Condition: VNPay paid but blockchain not confirmed
        qs = Donation.objects.filter(
            status='completed',
            payment_method='vnpay',
        ).filter(
            Q(blockchain_status='pending') |
            Q(blockchain_status='failed', blockchain_retry_count__lt=max_retries) |
            Q(blockchain_status='processing', blockchain_started_at__lt=stuck_threshold)
        ).order_by('id')

        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS(f"[{timezone.now():%H:%M:%S}] No pending donations."))
            return

        self.stdout.write(self.style.WARNING(f"[{timezone.now():%H:%M:%S}] Found {count} donations to process."))

        for donation in qs:
            self.stdout.write(f"  -> Donation #{donation.id} (status={donation.blockchain_status}, retry={donation.blockchain_retry_count})")
            try:
                success, err = process_donation_blockchain(donation.id)
                if success:
                    self.stdout.write(self.style.SUCCESS(f"     ✓ Confirmed"))
                else:
                    self.stdout.write(self.style.ERROR(f"     ✗ {err}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     ✗ Exception: {e}"))
