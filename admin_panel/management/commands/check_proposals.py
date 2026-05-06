from django.core.management.base import BaseCommand
from django.utils import timezone
from admin_panel.models import DisbursementProposal
from admin_panel.disbursement_utils import check_and_execute_proposal


class Command(BaseCommand):
    help = 'Kiểm tra các đề xuất giải ngân đã hết hạn bỏ phiếu và tự động thực thi hoặc từ chối'

    def handle(self, *args, **options):
        expired_proposals = DisbursementProposal.objects.filter(
            status='voting',
            end_date__lte=timezone.now(),
        )

        count = expired_proposals.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS('Không có đề xuất nào hết hạn.'))
            return

        self.stdout.write(f'Tìm thấy {count} đề xuất đã hết hạn bỏ phiếu...')

        for proposal in expired_proposals:
            self.stdout.write(f'  Đang xử lý #{proposal.id}: {proposal.title}...')
            executed, error = check_and_execute_proposal(proposal)
            if error:
                self.stdout.write(self.style.ERROR(f'  ❌ Blockchain error: {error}'))
            if executed:
                self.stdout.write(self.style.SUCCESS(f'    ✅ Đã giải ngân: {proposal.amount_requested:,}đ'))
            else:
                proposal.refresh_from_db()
                if proposal.status == 'rejected':
                    self.stdout.write(self.style.WARNING(f'    ❌ Đã từ chối (không đủ phiếu đồng ý)'))
                else:
                    self.stdout.write(self.style.NOTICE(f'    ⏳ Chưa xử lý được'))

        self.stdout.write(self.style.SUCCESS('Hoàn tất kiểm tra!'))
