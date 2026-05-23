from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0030_disbursementproposal_payos_order_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='campaign',
            name='beneficiary_ward',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
