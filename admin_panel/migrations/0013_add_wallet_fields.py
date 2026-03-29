from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0012_update_disbursementproposal'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='wallet_address',
            field=models.CharField(blank=True, max_length=42, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='wallet_address',
            field=models.CharField(blank=True, max_length=42, null=True),
        ),
        migrations.AddField(
            model_name='donation',
            name='donor_wallet_address',
            field=models.CharField(blank=True, max_length=42, null=True),
        ),
        migrations.AddField(
            model_name='donation',
            name='send_eth_tx_hash',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='Tx Admin cap ETH'),
        ),
        migrations.AddField(
            model_name='donation',
            name='donated_eth_wei',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=30, null=True),
        ),
        migrations.AddField(
            model_name='donation',
            name='gas_subsidy_wei',
            field=models.DecimalField(blank=True, decimal_places=0, max_digits=30, null=True),
        ),
    ]
