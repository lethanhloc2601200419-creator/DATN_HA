from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0013_add_wallet_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='disbursementproposal',
            name='disbursement_gas_fee_wei',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=30, null=True, verbose_name='Gas admin trả cho executeDisbursement'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='disbursement_gas_fee_vnd',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=15, null=True, verbose_name='Phí gas giải ngân (VNĐ)'),
        ),
    ]
