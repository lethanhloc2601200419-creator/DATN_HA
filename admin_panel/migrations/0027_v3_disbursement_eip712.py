# Generated manually for V3 workflow: EIP-712 off-chain multisig + PayOS Payout + burn-with-bankTxId.
# Tương ứng với:
#   - DisbursementProposal: thêm các trường v3_status, multisig_confirmed_*, payos_payout_*,
#     bank_tx_id, fiat_transferred_at, burn_tx_hash, burn_completed_at, payout_error,
#     signature_deadline.
#   - DisbursementSignature: bảng mới lưu 3 chữ ký EIP-712 (org/supervisor/admin).

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0026_campaign_blockchain_sync_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ---------- DisbursementProposal: V3 fields ----------
        migrations.AddField(
            model_name='disbursementproposal',
            name='v3_status',
            field=models.CharField(
                choices=[
                    ('v3_not_started', 'Chưa dùng luồng V3'),
                    ('pending_multisig', 'Chờ đủ 3 chữ ký EIP-712'),
                    ('ready_to_payout', 'Đã đủ 3 chữ ký - chờ chuyển fiat'),
                    ('payout_processing', 'Đang xử lý PayOS payout'),
                    ('fiat_transferred', 'Fiat đã chuyển - chờ burn VNDT'),
                    ('completed_audited', 'Hoàn tất + đã burn on-chain'),
                    ('payout_failed', 'PayOS payout thất bại'),
                ],
                default='v3_not_started',
                max_length=30,
                verbose_name='Trạng thái luồng V3 (EIP-712 + PayOS)',
            ),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='multisig_confirmed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Thời điểm đủ 3 sig'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='multisig_confirmed_tx_hash',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='TxHash recordMultisigApproval'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='signature_deadline',
            field=models.BigIntegerField(blank=True, null=True, verbose_name='Unix deadline cho các chữ ký EIP-712'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='payos_payout_id',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='PayOS Payout ID'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='payos_payout_requested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='bank_tx_id',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Bank Transaction ID (từ PayOS webhook)'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='fiat_transferred_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Thời điểm fiat đã chuyển'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='burn_tx_hash',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='TxHash finalizeBurnWithBankTx'),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='burn_completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='disbursementproposal',
            name='payout_error',
            field=models.TextField(blank=True, null=True, verbose_name='Lỗi PayOS/burn gần nhất'),
        ),

        # ---------- DisbursementSignature: bảng mới ----------
        migrations.CreateModel(
            name='DisbursementSignature',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[
                        ('organization', 'Tổ chức'),
                        ('supervisor', 'Giám sát viên'),
                        ('admin', 'Admin'),
                    ],
                    max_length=20,
                )),
                ('signer_address', models.CharField(max_length=42, verbose_name='Địa chỉ ví đã ký')),
                ('signature', models.TextField(verbose_name='Signature (hex 0x...)')),
                ('nonce', models.DecimalField(decimal_places=0, max_digits=78, verbose_name='Nonce (uint256)')),
                ('deadline', models.BigIntegerField(verbose_name='Unix deadline')),
                ('signed_amount', models.DecimalField(decimal_places=0, max_digits=78, verbose_name='Amount đã ký (uint256, raw 18 decimals)')),
                ('signed_recipient', models.CharField(max_length=42)),
                ('signed_ipfs_cid', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('proposal', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='offchain_signatures',
                    to='admin_panel.disbursementproposal',
                )),
                ('signed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Chữ ký EIP-712 giải ngân',
                'verbose_name_plural': 'Chữ ký EIP-712 giải ngân',
                'db_table': 'disbursement_signature',
                'unique_together': {('proposal', 'role')},
            },
        ),
    ]
