import django.contrib.postgres.fields
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('admin_panel', '0011_merge_20260311_0326'),
    ]

    operations = [
        migrations.AddField(
            model_name='disbursementproposal',
            name='purpose',
            field=models.CharField(blank=True, max_length=500, null=True, verbose_name='Mục đích giải ngân'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='recipient_name',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Đơn vị thụ hưởng'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='proof_images',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.TextField(), blank=True, null=True, size=None, verbose_name='Ảnh minh chứng'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_proposals', to=settings.AUTH_USER_MODEL, verbose_name='Người tạo'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_proposals', to=settings.AUTH_USER_MODEL, verbose_name='Người duyệt'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='voting_days',
            field=models.IntegerField(default=7, verbose_name='Số ngày bỏ phiếu'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='blockchain_proposal_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='eth_tx_hash',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='TxHash tạo proposal'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='disbursement_eth_tx_hash',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='TxHash giải ngân'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='executed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='disbursementproposal',
            name='end_date',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Hạn bỏ phiếu'),
        ),
        migrations.AlterField(
            model_name='disbursementproposal',
            name='evidence_url',
            field=models.TextField(blank=True, null=True, verbose_name='Link minh chứng'),
        ),
        migrations.AlterField(
            model_name='disbursementproposal',
            name='status',
            field=models.CharField(choices=[('pending', 'Chờ duyệt'), ('voting', 'Đang bỏ phiếu'), ('approved', 'Đã thông qua'), ('rejected', 'Bị từ chối'), ('executed', 'Đã giải ngân')], default='pending', max_length=20),
        ),
        migrations.AlterField(
            model_name='disbursementproposal',
            name='title',
            field=models.CharField(max_length=255, verbose_name='Tiêu đề'),
        ),
        migrations.AlterField(
            model_name='disbursementproposal',
            name='amount_requested',
            field=models.DecimalField(decimal_places=0, max_digits=15, verbose_name='Số tiền yêu cầu'),
        ),
        migrations.AlterField(
            model_name='disbursementproposal',
            name='description',
            field=models.TextField(verbose_name='Mô tả chi tiết'),
        ),
        migrations.AlterModelOptions(
            name='disbursementproposal',
            options={'ordering': ['-created_at'], 'verbose_name': 'Đề xuất giải ngân', 'verbose_name_plural': 'Danh sách đề xuất giải ngân'},
        ),
    ]
