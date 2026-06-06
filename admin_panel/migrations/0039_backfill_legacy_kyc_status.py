# Generated manually for fix_to_chuc.md task — Bước 7 (legacy backfill).
#
# Migration này backfill 2 việc cho legacy data:
#
# 1. KYC status cho Organization legacy:
#    Trước khi có flow KYC chính thức, các Organization được tạo qua admin
#    (`them_tochuc`) có `is_verified=True` nhưng `kyc_status` mặc định là
#    'draft' (do field được thêm sau). Sau khi `_get_user_role` chuyển sang
#    dùng `is_verified=True AND kyc_status='approved'` để xác định partner
#    role, các org legacy này sẽ silent lockout manager khỏi admin panel.
#    → Backfill `kyc_status='approved'` cho mọi org đã verified nhưng chưa
#      approved. KHÔNG đụng tới submitted/under_review/rejected/suspended.
#
# 2. account_source cho UserProfile legacy:
#    Migration 0038 backfill `account_source='google'` cho profile có wallet
#    (tài khoản Web3Auth/Google). Còn lại để '' (BLOCKED khỏi form đăng ký
#    tổ chức). Tuy nhiên web users đăng ký qua `/dang-ky/` TRƯỚC migration
#    0038 cũng có `account_source=''` (không có wallet). Họ là tài khoản web
#    hợp lệ nhưng bị lockout.
#    → Backfill `account_source='web'` cho profile KHÔNG có wallet/eoa/smart
#      address nào → most likely là web user thực sự.
#    Profile có wallet đã được set 'google' ở 0038 — không bị đụng.

from django.db import migrations, models
from django.utils import timezone


def _backfill_legacy_kyc_status(apps, schema_editor):
    Organization = apps.get_model('admin_panel', 'Organization')
    now = timezone.now()
    legacy_qs = Organization.objects.filter(is_verified=True).exclude(kyc_status='approved')
    updated = 0
    for org in legacy_qs:
        org.kyc_status = 'approved'
        if not org.verified_at:
            org.verified_at = now
        if not org.kyc_reviewed_at:
            org.kyc_reviewed_at = now
        org.save(update_fields=['kyc_status', 'verified_at', 'kyc_reviewed_at'])
        updated += 1
    if updated:
        print(f"  ↳ backfilled kyc_status='approved' cho {updated} org legacy.")


def _backfill_legacy_web_accounts(apps, schema_editor):
    """
    Set `account_source='web'` cho profile thuộc về user web hợp lệ
    (không có wallet/eoa/smart_account address) đang stuck với account_source=''.

    Heuristic: nếu profile chưa có địa chỉ on-chain nào → user chưa từng
    qua flow Web3Auth/Google → coi là tài khoản web nội bộ. Profile có wallet
    đã được 0038 set thành 'google' rồi nên không bị filter này chạm tới.
    """
    UserProfile = apps.get_model('admin_panel', 'UserProfile')
    no_wallet_filter = (
        (models.Q(wallet_address__isnull=True) | models.Q(wallet_address=''))
        & (models.Q(eoa_address__isnull=True) | models.Q(eoa_address=''))
        & (models.Q(smart_account_address__isnull=True) | models.Q(smart_account_address=''))
    )
    qs = UserProfile.objects.filter(account_source='').filter(no_wallet_filter)
    updated = qs.update(account_source='web')
    if updated:
        print(f"  ↳ backfilled account_source='web' cho {updated} profile legacy không có wallet.")


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0038_userprofile_account_source'),
    ]

    operations = [
        migrations.RunPython(_backfill_legacy_kyc_status, _noop_reverse),
        migrations.RunPython(_backfill_legacy_web_accounts, _noop_reverse),
    ]
