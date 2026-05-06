"""
Async blockchain processor for donations — V3 SIMPLIFIED FLOW.

Trước đây (contract cũ v2) luồng này là 3 giao dịch:
    A: recordBankDonation  - B: donateOnBehalf  - C: recordGasCost
Contract mới DCPManager v3 chỉ còn 1 giao dịch cần thiết:
    recordDonation(campaignId, donor, fiatAmount)
Phí gas do Admin tự trả (Admin Relayer / Gas Station pattern).

File này giờ chỉ đóng vai trò RETRY ASYNC cho luồng PayOS webhook:
    - Webhook chính (_trigger_record_donation_bridge) đã gọi recordDonation đồng bộ.
    - Nếu thất bại, admin/management command có thể gọi start_blockchain_thread()
      để retry bất đồng bộ.

Các hàm OBSOLETE (init_campaign / donate_on_behalf / record_gas_cost /
record_bank_donation) đã được chuyển thành NotImplementedError stubs trong
client/blockchain.py và KHÔNG còn gọi ở đây nữa.
"""
import threading
import traceback
from django.utils import timezone

from admin_panel.models import Donation
from .blockchain import BlockchainService, invalidate_campaign_cache


# Prevent the same donation from being processed twice simultaneously.
_processing_lock = threading.Lock()
_currently_processing = set()


def _mark_processing(donation_id):
    with _processing_lock:
        if donation_id in _currently_processing:
            return False
        _currently_processing.add(donation_id)
        return True


def _unmark_processing(donation_id):
    with _processing_lock:
        _currently_processing.discard(donation_id)


def process_donation_blockchain(donation_id):
    """
    V3 flow: chỉ gọi recordDonation(campaignId, donor, fiatAmount).
    Returns (success: bool, error_msg: str or None).

    Yêu cầu: campaign đã được createCampaign on-chain trước đó. Nếu chưa,
    recordDonation sẽ revert với "Chien dich khong ton tai" — admin cần vào
    trang quản lý chiến dịch và bấm duyệt lại (sẽ trigger _sync_campaign_to_blockchain).
    """
    if not _mark_processing(donation_id):
        return False, "Donation đang được xử lý ở luồng khác."

    try:
        donation = Donation.objects.get(id=donation_id)
    except Donation.DoesNotExist:
        _unmark_processing(donation_id)
        return False, "Donation không tồn tại."

    # Skip if already confirmed
    if donation.blockchain_status == 'confirmed' and donation.eth_tx_hash:
        _unmark_processing(donation_id)
        return True, None

    # Mark as processing
    donation.blockchain_status = 'processing'
    donation.blockchain_started_at = timezone.now()
    donation.blockchain_error = None
    donation.blockchain_retry_count = (donation.blockchain_retry_count or 0) + 1
    donation.save(update_fields=[
        'blockchain_status', 'blockchain_started_at',
        'blockchain_error', 'blockchain_retry_count',
    ])

    try:
        bc = BlockchainService()

        # Kiểm tra campaign đã tồn tại on-chain chưa (createCampaign đã chạy?)
        if not bc.is_campaign_active(donation.campaign.id):
            raise Exception(
                f"Chiến dịch #{donation.campaign.id} chưa được tạo on-chain. "
                "Hãy vào 'Quản lý chiến dịch' → bấm 'Duyệt' để đồng bộ lên blockchain trước."
            )

        donor_addr = donation.donor_wallet_address or bc.get_fallback_donor_address()
        amount_vnd = int(donation.amount)

        print(f"🟦 [BG] recordDonation(cid={donation.campaign.id}, donor={donor_addr}, amount={amount_vnd} VND)...")
        tx_result = bc.trigger_record_donation(
            campaign_id=donation.campaign.id,
            donor_address=donor_addr,
            fiat_amount=amount_vnd,
        )
        tx_hash = tx_result['tx_hash'] if isinstance(tx_result, dict) else str(tx_result)

        donation.eth_tx_hash = tx_hash
        donation.blockchain_status = 'confirmed'
        donation.blockchain_completed_at = timezone.now()
        donation.blockchain_error = None
        donation.blockchain_retry_count = 0
        donation.is_blockchain_synced = True
        donation.save()

        invalidate_campaign_cache(donation.campaign.id)
        print(f"🎉 [BG] Donation #{donation_id} recordDonation OK (tx={tx_hash}).")
        return True, None

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        print(f"❌ [BG] Lỗi blockchain cho Donation #{donation_id}: {error_msg}")
        traceback.print_exc()
        try:
            donation.blockchain_status = 'failed'
            donation.blockchain_error = error_msg[:500]
            donation.blockchain_completed_at = timezone.now()
            donation.save(update_fields=[
                'blockchain_status', 'blockchain_error', 'blockchain_completed_at',
            ])
        except Exception:
            pass
        return False, error_msg

    finally:
        # Close Django DB connection for this thread to avoid connection leaks
        try:
            from django.db import connection
            connection.close()
        except Exception:
            pass
        _unmark_processing(donation_id)


def start_blockchain_thread(donation_id):
    """Spawn a daemon thread to run process_donation_blockchain in background."""
    thread = threading.Thread(
        target=process_donation_blockchain,
        args=(donation_id,),
        daemon=True,
        name=f"BlockchainWorker-{donation_id}",
    )
    thread.start()
    print(f"🚀 [BG] Spawned blockchain retry thread for Donation #{donation_id}")
    return thread
