# Manually authored migration — add blockchain sync fields to Campaign model
# to support DCPManager v3 on-chain createCampaign(_cid, org_addr) flow.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0025_donation_device_fingerprint_donation_is_sybil_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='is_onchain',
            field=models.BooleanField(default=False, verbose_name='Đã tạo trên blockchain'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='blockchain_tx_hash',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='TxHash createCampaign'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='blockchain_synced_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Thời điểm đồng bộ on-chain'),
        ),
        migrations.AddField(
            model_name='campaign',
            name='blockchain_sync_error',
            field=models.TextField(blank=True, null=True, verbose_name='Lỗi đồng bộ blockchain (nếu có)'),
        ),
    ]
