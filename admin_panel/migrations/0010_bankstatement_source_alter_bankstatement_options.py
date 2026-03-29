from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0009_donation_eth_tx_hash_donation_is_blockchain_synced_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankstatement',
            name='source',
            field=models.CharField(
                choices=[('vnpay', 'VNPay'), ('casso', 'Casso Webhook'), ('mock', 'Mock/Test'), ('manual', 'Nhập tay')],
                default='manual',
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name='bankstatement',
            options={'verbose_name': 'Sao kê ngân hàng', 'verbose_name_plural': 'Danh sách Sao kê ngân hàng'},
        ),
    ]
