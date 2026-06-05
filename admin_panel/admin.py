from django.contrib import admin
from django.db.models import Sum
from django.utils import timezone
from .models import BankStatement, CampaignDisbursement, Campaign, Donation, Organization


@admin.action(description='Chuyển KYC sang đang thẩm định')
def mark_kyc_under_review(modeladmin, request, queryset):
    queryset.update(
        kyc_status='under_review',
        kyc_reviewed_at=None,
        kyc_reviewed_by=None,
        kyc_rejection_reason='',
    )


@admin.action(description='Duyệt KYC tổ chức')
def approve_kyc(modeladmin, request, queryset):
    now = timezone.now()
    queryset.update(
        kyc_status='approved',
        is_verified=True,
        verified_at=now,
        kyc_reviewed_at=now,
        kyc_reviewed_by=request.user,
        kyc_rejection_reason='',
    )


@admin.action(description='Đánh dấu ngân hàng đã xác thực')
def verify_bank_details(modeladmin, request, queryset):
    queryset.update(
        bank_verified_by_admin=True,
        bank_verified_at=timezone.now(),
        bank_verified_by=request.user,
    )


@admin.action(description='Đánh dấu ví đã xác thực')
def verify_wallet_details(modeladmin, request, queryset):
    queryset.update(
        wallet_verified_by_admin=True,
        wallet_verified_at=timezone.now(),
        wallet_verified_by=request.user,
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'manager', 'kyc_status', 'bank_verified_by_admin',
        'wallet_verified_by_admin', 'is_verified', 'verified_at', 'created_at',
    )
    list_filter = (
        'kyc_status', 'bank_verified_by_admin', 'wallet_verified_by_admin',
        'is_verified', 'created_at',
    )
    search_fields = (
        'name', 'slug', 'manager__username', 'manager__email',
        'bank_account_number', 'bank_account_name', 'wallet_address',
    )
    ordering = ('-created_at',)
    readonly_fields = (
        'slug', 'verified_at', 'kyc_submitted_at', 'kyc_reviewed_at', 'kyc_reviewed_by',
        'bank_verified_at', 'bank_verified_by', 'wallet_verified_at', 'wallet_verified_by',
        'created_at', 'updated_at',
    )
    fieldsets = (
        ('Thông tin tổ chức', {
            'fields': (
                'name', 'slug', 'description', 'logo_url', 'website', 'manager',
                'contact_person', 'contact_phone',
            ),
        }),
        ('Thông tin nhận tiền', {
            'fields': (
                'bank_name', 'bank_branch', 'bank_account_number',
                'bank_account_name', 'qr_code_url', 'wallet_address',
            ),
        }),
        ('Kiểm soát KYC', {
            'fields': (
                'license_document_url', 'kyc_status', 'kyc_rejection_reason',
                'kyc_submitted_at', 'kyc_reviewed_at', 'kyc_reviewed_by',
                'is_verified', 'verified_at',
            ),
        }),
        ('Xác thực tài khoản nhận quỹ', {
            'fields': (
                'bank_verified_by_admin', 'bank_verified_at', 'bank_verified_by',
                'wallet_verified_by_admin', 'wallet_verified_at', 'wallet_verified_by',
            ),
        }),
        ('PayOS Credentials', {
            'fields': (
                'payos_client_id', 'payos_api_key', 'payos_checksum_key',
            ),
        }),
        ('Dấu thời gian', {
            'fields': ('created_at', 'updated_at'),
        }),
    )
    actions = [mark_kyc_under_review, approve_kyc, verify_bank_details, verify_wallet_details]

    def save_model(self, request, obj, form, change):
        now = timezone.now()

        if obj.kyc_status == 'approved':
            obj.is_verified = True
            obj.verified_at = obj.verified_at or now
            obj.kyc_reviewed_at = now
            obj.kyc_reviewed_by = request.user
            obj.kyc_rejection_reason = ''
        elif obj.kyc_status in {'rejected', 'suspended', 'draft', 'submitted', 'under_review'}:
            obj.is_verified = False
            if obj.kyc_status == 'rejected':
                obj.kyc_reviewed_at = now
                obj.kyc_reviewed_by = request.user
            elif obj.kyc_status == 'under_review' and not obj.kyc_submitted_at:
                obj.kyc_submitted_at = now

        if obj.bank_verified_by_admin and not obj.bank_verified_at:
            obj.bank_verified_at = now
            obj.bank_verified_by = request.user
        if not obj.bank_verified_by_admin:
            obj.bank_verified_at = None
            obj.bank_verified_by = None

        if obj.wallet_verified_by_admin and not obj.wallet_verified_at:
            obj.wallet_verified_at = now
            obj.wallet_verified_by = request.user
        if not obj.wallet_verified_by_admin:
            obj.wallet_verified_at = None
            obj.wallet_verified_by = None

        super().save_model(request, obj, form, change)


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'campaign', 'amount', 'status', 'payment_method', 'order_code',
        'payos_transaction_id', 'blockchain_status', 'created_at',
    )
    list_filter = ('status', 'payment_method', 'blockchain_status', 'created_at')
    search_fields = (
        'campaign__title', 'donor_name', 'donor_email', 'transaction_id',
        'order_code', 'payos_transaction_id', 'payos_payment_link_id',
        'payos_reference', 'bank_transaction_no',
    )
    ordering = ('-created_at',)
    readonly_fields = (
        'hash', 'previous_hash', 'created_at', 'updated_at',
        'payos_webhook_received_at', 'payos_paid_at',
    )
    fieldsets = (
        ('Thông tin quyên góp', {
            'fields': (
                'campaign', 'donor', 'donor_name', 'donor_email', 'donor_phone',
                'amount', 'message', 'is_anonymous', 'status', 'payment_method',
            ),
        }),
        ('PayOS', {
            'fields': (
                'transaction_id', 'order_code', 'payos_transaction_id',
                'payos_payment_link_id', 'payos_reference', 'payos_checkout_url',
                'payos_qr_code', 'payos_webhook_received_at', 'payos_paid_at',
                'bank_transaction_no',
            ),
        }),
        ('Blockchain', {
            'fields': (
                'blockchain_status', 'eth_tx_hash', 'is_blockchain_synced',
                'blockchain_error', 'blockchain_started_at', 'blockchain_completed_at',
            ),
        }),
        ('Audit', {
            'fields': ('previous_hash', 'hash', 'created_at', 'updated_at'),
        }),
    )


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


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'organization', 'target_amount', 'status', 'is_protected_beneficiary', 'created_at')
    list_filter = ('status', 'is_protected_beneficiary', 'category', 'created_at')
    search_fields = ('title', 'slug', 'short_description', 'organization__name')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Thông tin cơ bản', {
            'fields': (
                'title', 'slug', 'creator', 'category', 'organization', 'target_program', 'occasion',
                'short_description', 'full_description', 'avatar_image_url', 'cover_image_url',
            ),
        }),
        ('Tài chính & Thời gian', {
            'fields': (
                'target_amount', 'current_amount', 'start_date', 'end_date',
                'locked_amount', 'disbursed_amount', 'approval_threshold_pct', 'voting_power_cap_pct',
            ),
        }),
        ('Thông tin người thụ hưởng', {
            'fields': (
                'is_protected_beneficiary',
                'beneficiary_province',
                'beneficiary_ward',
                'beneficiary_address',
                'beneficiary_lat',
                'beneficiary_lng',
            ),
        }),
        ('Quản trị & Blockchain', {
            'fields': (
                'status', 'charity_account_number', 'charity_account_name',
                'is_onchain', 'blockchain_tx_hash', 'blockchain_synced_at',
            ),
        }),
    )

    class Media:
        js = ('admin_panel/js/admin_campaign_toggle.js',)

@admin.register(CampaignDisbursement)
class CampaignDisbursementAdmin(admin.ModelAdmin):
    list_display = ('id', 'campaign', 'title', 'amount', 'status', 'reporter', 'created_at')
    list_filter = ('status', 'campaign')
    search_fields = ('title', 'description', 'recipient_name')
    ordering = ('-created_at',)
