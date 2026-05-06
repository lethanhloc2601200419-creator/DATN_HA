from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0016_remove_donation_admin_gas_fee_wei'),
    ]

    operations = [
        migrations.AddField(
            model_name='donation',
            name='admin_send_eth_gas_fee_wei',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=30, null=True),
        ),
        migrations.AddField(
            model_name='donation',
            name='admin_send_eth_gas_fee_vnd',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=15, null=True),
        ),
    ]
