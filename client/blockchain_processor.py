"""
Async blockchain processor for donations (luồng v2).

Luồng mới sau khi user thanh toán VNPay thành công:
    Giao dịch A: recordBankDonation(cid, donor_addr, donor_name, amountVND, vnpayRef, ts)
                 → Ghi sao kê ngân hàng lên blockchain (minh bạch)
    Giao dịch B: donateOnBehalf(cid, donor_addr) payable=amount_e_wei
                 → Admin tự động nạp ETH thay user vào smart contract campaign
    Giao dịch C: recordGasCost(cid, gasA + gasB, "auto_fund")
                 → Ghi tổng phí gas A+B lên contract để lúc giải ngân trừ ra

User KHÔNG cần MetaMask. Toàn bộ chạy nền trong thread riêng.
"""
import threading
import time
import traceback
from decimal import Decimal
from django.conf import settings
from django.utils import timezone

from admin_panel.models import Donation
from .blockchain import BlockchainService, get_eth_vnd_rate, ZERO_ADDRESS, invalidate_campaign_cache


# Timeout (seconds) to wait for a transaction receipt on Sepolia.
# Much longer than the default 120s so low gas-price txs can still be picked up.
BLOCKCHAIN_RECEIPT_TIMEOUT = 600  # 10 minutes

WEI_IN_ETH = Decimal('1000000000000000000')

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


def _wait_receipt_safe(bc, tx_hash, label=''):
    """Đợi receipt nhưng KHÔNG raise nếu timeout — cho phép tiếp tục."""
    try:
        receipt = bc.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=BLOCKCHAIN_RECEIPT_TIMEOUT)
        print(f"✅ [BG] {label} confirmed (tx={tx_hash})")
        return receipt
    except Exception as e:
        print(f"⚠️ [BG] {label} chưa confirm trong timeout: {e}")
        return None


def _gas_fee_from_receipt(bc, receipt, fallback_gas_price):
    if not receipt:
        return 0, Decimal('0')
    gas_used = receipt.get('gasUsed', 0) or 0
    price = receipt.get('effectiveGasPrice', fallback_gas_price)
    fee_wei = int(gas_used) * int(price)
    fee_eth = Decimal(str(fee_wei)) / WEI_IN_ETH
    return fee_wei, fee_eth


def process_donation_blockchain(donation_id):
    """
    Core worker: process one donation's blockchain side synchronously.
    Luồng mới: A (recordBankDonation) → B (donateOnBehalf) → C (recordGasCost).
    Returns (success: bool, error_msg: str or None).
    """
    if not _mark_processing(donation_id):
        return False, "Donation đang được xử lý ở luồng khác."

    try:
        donation = Donation.objects.get(id=donation_id)
    except Donation.DoesNotExist:
        _unmark_processing(donation_id)
        return False, "Donation không tồn tại."

    # Skip if already confirmed
    if donation.blockchain_status == 'confirmed' and donation.donate_onbehalf_tx_hash:
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

        # Step 0: Ensure campaign is initialized on-chain
        if not bc.is_campaign_active(donation.campaign.id):
            org = donation.campaign.organization
            if not org or not org.wallet_address:
                raise Exception("Chiến dịch chưa được khởi tạo on-chain và tổ chức chưa có ví.")
            tx_hash_init = bc.init_campaign(
                campaign_id=donation.campaign.id,
                org_name=org.name,
                org_address=org.wallet_address,
            )
            print(f"⏳ [BG] Đang đợi initCampaign confirm (tx={tx_hash_init})...")
            _wait_receipt_safe(bc, tx_hash_init, 'initCampaign')
            donation.init_campaign_tx_hash = tx_hash_init
            donation.save(update_fields=['init_campaign_tx_hash'])

        # Lấy tỉ giá một lần dùng chung
        eth_vnd_rate = get_eth_vnd_rate()
        fixed_gwei = getattr(settings, 'ADMIN_GAS_PRICE_GWEI', None)
        fallback_gas_price = bc.w3.to_wei(fixed_gwei, 'gwei') if fixed_gwei else bc.w3.eth.gas_price

        donor_addr = donation.donor_wallet_address or ZERO_ADDRESS
        donor_name = donation.donor_name or 'Ẩn danh'
        vnpay_ref = donation.vnpay_transaction_no or donation.transaction_id or f"donation-{donation.id}"
        ts_unix = int(donation.created_at.timestamp()) if donation.created_at else int(time.time())
        amount_vnd = int(donation.amount)

        # ==========================================================
        # GIAO DỊCH A: recordBankDonation
        # ==========================================================
        print(f"🟦 [BG] Đang gửi giao dịch A (recordBankDonation)...")
        tx_a = bc.record_bank_donation(
            campaign_id=donation.campaign.id,
            donor_address=donor_addr,
            donor_name=donor_name,
            amount_vnd=amount_vnd,
            vnpay_ref=vnpay_ref,
            timestamp_unix=ts_unix,
        )
        donation.bank_record_tx_hash = tx_a
        donation.save(update_fields=['bank_record_tx_hash'])
        print(f"   → Tx A: {tx_a}")

        # ==========================================================
        # GIAO DỊCH B: donateOnBehalf (admin nạp ETH thay user)
        # ==========================================================
        amount_e_eth = Decimal(str(amount_vnd)) / eth_vnd_rate
        amount_e_wei = int(amount_e_eth * WEI_IN_ETH)

        print(f"🟩 [BG] Đang gửi giao dịch B (donateOnBehalf={amount_e_eth:.10f} ETH)...")
        tx_b = bc.donate_on_behalf(
            campaign_id=donation.campaign.id,
            donor_address=donor_addr,
            amount_e_wei=amount_e_wei,
        )
        donation.donate_onbehalf_tx_hash = tx_b
        donation.donated_eth_wei = amount_e_wei
        donation.save(update_fields=['donate_onbehalf_tx_hash', 'donated_eth_wei'])
        print(f"   → Tx B: {tx_b}")

        # ==========================================================
        # Đợi receipt cho A và B (tuần tự vì đã broadcast xong, chỉ đợi mine)
        # ==========================================================
        print("⏳ [BG] Đợi receipt cho tx A và B...")
        receipt_a = _wait_receipt_safe(bc, tx_a, 'recordBankDonation')
        receipt_b = _wait_receipt_safe(bc, tx_b, 'donateOnBehalf')

        gas_a_wei, gas_a_eth = _gas_fee_from_receipt(bc, receipt_a, fallback_gas_price)
        gas_b_wei, gas_b_eth = _gas_fee_from_receipt(bc, receipt_b, fallback_gas_price)

        donation.bank_record_gas_wei = gas_a_wei
        donation.bank_record_gas_vnd = int(gas_a_eth * eth_vnd_rate)
        donation.donate_onbehalf_gas_wei = gas_b_wei
        donation.donate_onbehalf_gas_vnd = int(gas_b_eth * eth_vnd_rate)

        total_gas_wei = int(gas_a_wei) + int(gas_b_wei)
        total_gas_eth = Decimal(str(total_gas_wei)) / WEI_IN_ETH
        donation.total_admin_gas_wei = total_gas_wei
        donation.total_admin_gas_vnd = int(total_gas_eth * eth_vnd_rate)

        # Backward-compat: các trường cũ dùng cho saoke/chitiet_chiendich
        donation.gas_fee_eth = total_gas_eth
        donation.gas_fee_vnd = donation.total_admin_gas_vnd
        donation.admin_send_eth_gas_fee_wei = total_gas_wei
        donation.admin_send_eth_gas_fee_vnd = donation.total_admin_gas_vnd
        donation.net_amount = max(0, amount_vnd - int(donation.total_admin_gas_vnd or 0))

        donation.save(update_fields=[
            'bank_record_gas_wei', 'bank_record_gas_vnd',
            'donate_onbehalf_gas_wei', 'donate_onbehalf_gas_vnd',
            'total_admin_gas_wei', 'total_admin_gas_vnd',
            'gas_fee_eth', 'gas_fee_vnd',
            'admin_send_eth_gas_fee_wei', 'admin_send_eth_gas_fee_vnd',
            'net_amount',
        ])

        print(f"⛽ [BG] Gas A={donation.bank_record_gas_vnd:,}đ | Gas B={donation.donate_onbehalf_gas_vnd:,}đ | Tổng={donation.total_admin_gas_vnd:,}đ")

        # ==========================================================
        # GIAO DỊCH C: recordGasCost (ghi tổng gas A+B lên contract)
        # Chỉ gọi nếu cả A và B đã confirm và có gas thực
        # ==========================================================
        if total_gas_wei > 0 and receipt_a and receipt_b:
            try:
                print(f"📝 [BG] Đang ghi recordGasCost({total_gas_wei} wei) lên contract...")
                tx_c = bc.record_gas_cost(
                    campaign_id=donation.campaign.id,
                    amount_wei=total_gas_wei,
                    reason=f"auto_fund_donation_{donation.id}",
                )
                donation.record_gascost_tx_hash = tx_c
                donation.save(update_fields=['record_gascost_tx_hash'])
                _wait_receipt_safe(bc, tx_c, 'recordGasCost')
                print(f"   → Tx C: {tx_c}")
            except Exception as gc_err:
                # Không critical - chỉ log lại
                print(f"⚠️ [BG] recordGasCost lỗi (không critical): {gc_err}")

        # ==========================================================
        # Hoàn tất
        # ==========================================================
        donation.blockchain_status = 'confirmed'
        donation.blockchain_completed_at = timezone.now()
        donation.blockchain_error = None
        donation.blockchain_retry_count = 0
        donation.is_blockchain_synced = True
        # Giữ eth_tx_hash = tx B (giao dịch chính) để backward-compat với template cũ
        donation.eth_tx_hash = donation.donate_onbehalf_tx_hash
        donation.save()

        invalidate_campaign_cache(donation.campaign.id)
        print(f"🎉 [BG] Donation #{donation_id} hoàn tất luồng blockchain async.")
        return True, None

    except Exception as e:
        error_msg = str(e)
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
    print(f"🚀 [BG] Spawned blockchain thread for Donation #{donation_id}")
    return thread
