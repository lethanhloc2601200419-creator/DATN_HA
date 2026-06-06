# Generated manually for fix_to_chuc.md task — Bước 1.
#
# QUAN TRỌNG: default='' (empty) để KHÔNG vô tình cấp quyền submit form
# đăng ký tổ chức cho mọi user hiện hữu trong DB. Field này được dùng
# làm gate ở `client/views.py::tochuc_list` — chỉ user có
# `account_source == 'web'` mới được nộp hồ sơ. Profile cũ (đăng ký từ
# trước migration) sẽ có giá trị empty và phải đăng ký lại bằng tài
# khoản web mới nếu muốn dùng form.

from django.db import migrations, models


def _backfill_account_source(apps, schema_editor):
    """
    Backfill heuristic cho user hiện hữu:
      - Profile có wallet/EOA address → đến từ Web3Auth/Google → 'google'.
      - Còn lại → để '' (chưa xác định) → mặc định BLOCK form đăng ký tổ chức.
        User có thể tạo tài khoản web mới (qua /dang-ky/) để được set 'web'.
    Heuristic này thiên về SAFE-DEFAULT (không cấp quyền nhầm) thay vì
    UX-friendly (không block user thật sự là web nhưng thiếu data).
    """
    UserProfile = apps.get_model('admin_panel', 'UserProfile')
    UserProfile.objects.filter(
        models.Q(wallet_address__isnull=False) & ~models.Q(wallet_address='')
        | models.Q(eoa_address__isnull=False) & ~models.Q(eoa_address='')
        | models.Q(smart_account_address__isnull=False) & ~models.Q(smart_account_address='')
    ).update(account_source='google')


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0037_guest_org_register_v1'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='account_source',
            field=models.CharField(
                blank=True,
                choices=[
                    ('web', 'Tài khoản web nội bộ'),
                    ('google', 'Tài khoản Google / Web3Auth'),
                ],
                default='',
                max_length=20,
                verbose_name='Nguồn tài khoản',
            ),
        ),
        migrations.RunPython(_backfill_account_source, _noop_reverse),
    ]
