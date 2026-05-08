"""
client/payos_payout.py — PayOS Payout API adapter (MOCK).

==================================================================
PURPOSE
------------------------------------------------------------------
Tách hẳn integration "chuyển tiền ra ngân hàng tổ chức" khỏi luồng
PayOS Payment (incoming). Module này chỉ lo 1 việc:
   Backend yêu cầu PayOS chuyển fiat từ escrow → account của Org.

Hiện tại đang là MOCK (không gọi API thật) vì:
   1) PayOS Payout API cần approve từ phía PayOS + credentials riêng.
   2) Cho phép phát triển + test end-to-end luồng multisig → burn
      mà chưa cần gọi bank thật → không gây thất thoát tiền thật.

Khi có credentials thật, thay 2 hàm `request_payout` và
`verify_webhook_signature` bằng implementation gọi PayOS API
theo doc chính thức (xem các TODO ở dưới).

==================================================================
PUBLIC API
------------------------------------------------------------------
    request_payout(proposal)            → dict {payout_id, status, ...}
    verify_webhook_signature(payload, sig) → bool
    parse_webhook(payload)              → dict {payout_id, bank_tx_id, status}

==================================================================
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Dict


# --------------------------------------------------------------------------
# Cấu hình từ Django settings / env. Khi đổi sang real API, thêm vào
# doantn/settings.py: PAYOS_PAYOUT_ENDPOINT, PAYOS_PAYOUT_API_KEY, PAYOS_PAYOUT_CHECKSUM.
# --------------------------------------------------------------------------
PAYOS_PAYOUT_MOCK = True  # TODO: set False khi tích hợp thật
PAYOS_PAYOUT_WEBHOOK_SECRET = os.getenv('PAYOS_PAYOUT_WEBHOOK_SECRET', 'mock-secret-change-me')


def request_payout(proposal) -> Dict[str, Any]:
    """
    Gửi request payout cho 1 DisbursementProposal đã ở trạng thái ready_to_payout.

    Input  : proposal (admin_panel.models.DisbursementProposal)
    Output : {
        'payout_id'    : str  — id giao dịch PayOS trả về (để tra cứu)
        'status'       : 'pending' | 'failed'
        'mock'         : bool — đánh dấu đây là mock call
        'provider_raw' : dict — response gốc (để audit)
    }

    Raises: PayoutRequestError nếu có lỗi network/config.

    TODO (real integration):
        1. Validate proposal.campaign.organization có bank_account_* hợp lệ.
        2. POST {PAYOS_PAYOUT_ENDPOINT}/payouts với body:
             {
               "referenceId"   : f"proposal-{proposal.id}",
               "amount"        : int(proposal.amount_requested),
               "toAccount"     : { "accountNo": ..., "accountName": ..., "bin": ... },
               "description"   : proposal.purpose,
               "webhookUrl"    : SITE_URL + reverse('client:payos_payout_webhook'),
               "signature"     : hmac_sha256(checksum_key, canonical_payload)
             }
        3. Parse response → trả về dict với status mapping.
        4. Đừng wait webhook ở đây — chỉ return payout_id để DB track.
    """
    if not PAYOS_PAYOUT_MOCK:
        # ------------------------------------------------------------------
        # TODO: REAL IMPLEMENTATION
        # ------------------------------------------------------------------
        raise NotImplementedError(
            "PayOS Payout real API chưa được implement. "
            "Set PAYOS_PAYOUT_MOCK=True để dùng mock, "
            "hoặc implement theo doc PayOS Payout."
        )

    # -------------------- MOCK FLOW --------------------
    # Sinh payout_id ngẫu nhiên có cấu trúc như format PayOS thật
    # (xấp xỉ: ISO date + random 10 chars).
    mock_payout_id = f"PAYOUT-{int(time.time())}-{secrets.token_hex(5).upper()}"

    org = getattr(proposal.campaign, 'organization', None)
    org_bank = org.bank_account_number if org else 'N/A'

    print(
        f"💸 [PAYOS/MOCK] request_payout proposal={proposal.id} "
        f"amount={proposal.amount_requested:,}đ → bank={org_bank} "
        f"→ payout_id={mock_payout_id}"
    )

    return {
        'payout_id': mock_payout_id,
        'status': 'pending',  # webhook sẽ xác nhận sau
        'mock': True,
        'provider_raw': {
            'note': 'MOCK — no real bank transfer executed',
            'amount': int(proposal.amount_requested),
            'toAccount': org_bank,
            'referenceId': f"proposal-{proposal.id}",
        },
    }


def simulate_webhook_success(proposal) -> Dict[str, Any]:
    """
    [MOCK-ONLY] Trong luồng thật, webhook do PayOS gửi về. Ở chế độ mock,
    admin có thể gọi hàm này để tự giả webhook success (dùng cho dev/test).

    Trả về payload giống real PayOS webhook để pipeline downstream test được.
    """
    mock_bank_tx_id = f"VN{int(time.time())}{secrets.token_hex(3).upper()}"
    payload = {
        'payoutId': proposal.payos_payout_id or f'PAYOUT-MOCK-{proposal.id}',
        'referenceId': f'proposal-{proposal.id}',
        'bankTransactionId': mock_bank_tx_id,
        'status': 'SUCCESS',
        'amount': int(proposal.amount_requested),
        'timestamp': int(time.time()),
    }
    # Tự sign để pass verify_webhook_signature().
    sig = _compute_hmac(payload)
    payload['signature'] = sig
    return payload


def verify_webhook_signature(payload: Dict[str, Any], signature: str, checksum_key: str) -> bool:
    """
    Xác minh HMAC webhook. Ở mock chỉ so sánh với HMAC tự sinh bằng secret local.

    TODO (real integration):
        - PayOS sẽ sign webhook bằng CHECKSUM_KEY. Replicate đúng thuật toán
          canonical-form + HMAC-SHA256 theo doc official.
        - Reject nếu timestamp lệch >5 phút (chống replay).
    """
    if not signature:
        return False
    expected = _compute_hmac(payload, checksum_key)
    # constant-time compare
    return hmac.compare_digest(expected, signature)


def parse_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trích các field quan trọng từ webhook payload (for payment success).

    Returns dict với keys:
        orderCode   : PayOS orderCode (proposal.id)
        bank_tx_id  : Bank Transaction ID — LÀ FIELD QUAN TRỌNG NHẤT,
                      sẽ được lưu on-chain qua finalizeBurnWithBankTx().
        status      : 'success' | 'failed'
        amount      : int (VND)
    """
    # For payment webhook, status is 'success' if code == '00'
    code = payload.get('code')
    status = 'success' if code == '00' else 'failed'
    return {
        'orderCode': payload.get('orderCode'),
        'bank_tx_id': payload.get('counterAccountBankId') or payload.get('transactionNo'),
        'status': status,
        'amount': int(payload.get('amount') or 0),
    }


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------
def _compute_hmac(payload: Dict[str, Any], checksum_key: str) -> str:
    """
    HMAC-SHA256 hex của canonical JSON (sorted keys), trừ field 'signature'.
    """
    filtered = {k: v for k, v in payload.items() if k != 'signature'}
    # Canonical = key=value sorted, nối bằng '&' (đơn giản, khớp mock doc).
    canonical = '&'.join(f"{k}={filtered[k]}" for k in sorted(filtered.keys()))
    mac = hmac.new(
        checksum_key.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256,
    )
    return mac.hexdigest()


def create_payment_link(client_id, api_key, checksum_key, amount, order_code, description):
    """
    Tạo PayOS Payment Link cho admin scan QR và thanh toán thủ công.
    """
    if PAYOS_PAYOUT_MOCK:
        return {
            'checkoutUrl': f'https://my.payos.vn/checkout?orderCode={order_code}',
            'qrCode': f'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=https://my.payos.vn/checkout?orderCode={order_code}',
            'paymentLinkId': f'mock-link-{order_code}',
        }

    # Real PayOS API call
    try:
        from payos import PayOS
        payos_client = PayOS(client_id=client_id, api_key=api_key, checksum_key=checksum_key)
        response = payos_client.createPaymentLink({
            'orderCode': int(order_code),  # Ensure unique per org
            'amount': int(amount),
            'description': description,
            'cancelUrl': 'https://web-production-e589d.up.railway.app/admin/giaingan/',  # Redirect back
            'returnUrl': 'https://web-production-e589d.up.railway.app/admin/giaingan/',  # Redirect back
        })
        return {
            'checkoutUrl': response['checkoutUrl'],
            'qrCode': response['qrCode'],
            'paymentLinkId': response['paymentLinkId'],
        }
    except Exception as e:
        print(f"PAYOS ERROR: Failed to create payment link for orderCode {order_code}: {e}")
        raise e


class PayoutRequestError(Exception):
    """Raised khi request_payout thất bại (network / config / PayOS reject)."""
    pass
