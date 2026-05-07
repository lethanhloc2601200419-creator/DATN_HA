"""
Blockchain sync utilities for Campaign model.

Đây là nơi tập trung logic gọi smart contract `createCampaign(_cid, org_addr,
_multisigVault)` trên DCPManager v4. Logic này được dùng bởi:

  1. View `_sync_campaign_to_blockchain` (trong admin_panel/views.py) khi admin
     bấm duyệt chiến dịch trên UI.
  2. Management command `sync_campaigns_to_blockchain` để backfill hàng loạt.
  3. Signal `post_save` trên Campaign (admin_panel/signals.py) — tự động sync
     khi campaign mới được tạo với status='active' hoặc chuyển sang 'active'.

Việc gom logic vào một chỗ giúp chúng ta KHÔNG duplicate code khi gọi
trigger_create_campaign từ nhiều nơi khác nhau.
"""
import re
import traceback

from django.utils import timezone

from client.blockchain import BlockchainService


def sync_single_campaign(campaign_id):
    """
    Đồng bộ một Campaign lên blockchain (DCPManager v4) bằng Admin Relayer.

    Tham số:
        campaign_id (int): ID của Campaign trong DB Django.

    Trả về:
        dict: {
            'ok': bool,                  # True nếu sync thành công
            'tx_hash': str | None,       # Tx hash createCampaign (nếu OK)
            'error': str | None,         # Chuỗi lỗi (nếu FAIL)
            'already_onchain': bool,     # True nếu campaign đã on-chain từ trước
        }

    Đặc điểm:
      • Idempotent: nếu campaign.is_onchain = True → bỏ qua, trả về already_onchain=True.
      • Mọi lỗi (thiếu ví tổ chức, revert, RPC timeout…) đều được ghi vào
        `blockchain_sync_error` để admin retry thủ công mà không chặn flow duyệt.
      • Không raise exception ra ngoài — signal/threading gọi hàm này sẽ an toàn.

    Lý do nhận `campaign_id` thay vì `campaign` instance:
      • Signal chạy trong thread riêng → tránh dính stale instance từ request cha.
      • Đảm bảo luôn đọc bản mới nhất từ DB (tránh race condition với pre_save hook).
    """
    # Lazy import để tránh circular import với admin_panel.models khi signal chưa sẵn sàng.
    from admin_panel.models import Campaign

    try:
        campaign = Campaign.objects.get(pk=campaign_id)
    except Campaign.DoesNotExist:
        return {
            'ok': False,
            'tx_hash': None,
            'error': f'Campaign #{campaign_id} không tồn tại.',
            'already_onchain': False,
        }

    # Idempotent guard: đã sync rồi thì không gọi lại RPC.
    if campaign.is_onchain and campaign.blockchain_tx_hash:
        print(f"ℹ️ [CHAIN SYNC] Campaign #{campaign.id} đã ở on-chain, bỏ qua.")
        return {
            'ok': True,
            'tx_hash': campaign.blockchain_tx_hash,
            'error': None,
            'already_onchain': True,
        }

    try:
        org = campaign.organization
        if not org:
            raise Exception("Chiến dịch chưa gắn tổ chức — không thể tạo trên blockchain.")
        wallet = (org.wallet_address or '').strip()
        if not wallet:
            raise Exception("Tổ chức chưa có địa chỉ ví Crypto (wallet_address) — không thể tạo trên blockchain.")
        if not re.match(r'^0x[0-9a-fA-F]{40}$', wallet):
            raise Exception(f"Địa chỉ ví tổ chức không hợp lệ (cần format 0x + 40 ký tự hex): {wallet}")

        bc = BlockchainService()
        result = bc.trigger_create_campaign(
            campaign_id=campaign.id,
            org_address=wallet,
        )
        tx_hash = result['tx_hash'] if isinstance(result, dict) else str(result)

        campaign.is_onchain = True
        campaign.blockchain_tx_hash = tx_hash
        campaign.blockchain_synced_at = timezone.now()
        campaign.blockchain_sync_error = None
        campaign.save(update_fields=[
            'is_onchain', 'blockchain_tx_hash',
            'blockchain_synced_at', 'blockchain_sync_error',
        ])
        print(f"✅ [CHAIN SYNC] createCampaign(cid={campaign.id}, org={wallet}) OK, tx={tx_hash}")
        return {
            'ok': True,
            'tx_hash': tx_hash,
            'error': None,
            'already_onchain': False,
        }
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        print(f"❌ [CHAIN SYNC] Lỗi createCampaign #{campaign.id}: {err_msg}")
        print(traceback.format_exc())
        try:
            campaign.is_onchain = False
            campaign.blockchain_sync_error = err_msg[:1000]
            campaign.blockchain_synced_at = timezone.now()
            campaign.save(update_fields=[
                'is_onchain', 'blockchain_sync_error', 'blockchain_synced_at',
            ])
        except Exception as save_exc:
            # Nếu ngay cả việc lưu lỗi cũng fail (DB down…) thì chỉ log, không raise.
            print(f"❌ [CHAIN SYNC] Không thể ghi blockchain_sync_error vào DB: {save_exc}")
        return {
            'ok': False,
            'tx_hash': None,
            'error': err_msg,
            'already_onchain': False,
        }
