from django.contrib import admin
from django.db.models import Sum
from .models import BankStatement, CampaignDisbursement, Campaign


@admin.register(BankStatement)
class BankStatementAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign', 'transaction_type', 'amount', 'source', 'description', 'transaction_date', 'created_at')
    list_filter = ('transaction_type', 'source', 'campaign')
    search_fields = ('description', 'reference_number', 'sender_name')
    ordering = ('-created_at',)

    readonly_fields = (
        'campaign', 'donation', 'transaction_date', 'transaction_type',
        'amount', 'balance', 'reference_number', 'description',
        'sender_account', 'sender_name', 'source', 'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        campaigns_with_finance = []
        for camp in Campaign.objects.all().order_by('-created_at')[:20]:
            statements = BankStatement.objects.filter(campaign=camp)
            total_in = statements.filter(transaction_type='in').aggregate(t=Sum('amount'))['t'] or 0
            total_out = statements.filter(transaction_type='out').aggregate(t=Sum('amount'))['t'] or 0
            if total_in or total_out:
                campaigns_with_finance.append({
                    'campaign': camp,
                    'total_in': total_in,
                    'total_out': total_out,
                    'balance': total_in - total_out,
                })

        extra_context['campaigns_finance'] = campaigns_with_finance
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(CampaignDisbursement)
class CampaignDisbursementAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign', 'title', 'amount', 'status', 'reporter', 'created_at')
    list_filter = ('status', 'campaign')
    search_fields = ('title', 'description', 'recipient_name')
    ordering = ('-created_at',)
