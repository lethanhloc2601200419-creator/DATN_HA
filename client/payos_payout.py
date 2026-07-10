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
    create_payment_link(...)            → dict {checkoutUrl, qrCode, paymentLinkId}

==================================================================
"""
from __future__ import annotations

import hashlib
import hmac
import json as _json
import os
import secrets
import time
from typing import Any, Dict
from urllib.parse import quote as _quote

import requests as _http_requests

# Endpoint REST PayOS v2 — khớp với luồng donation (client/views.py) đang chạy ổn định.
_PAYOS_API_BASE = 'https://api-merchant.payos.vn'
_PAYOS_ENCODE_SAFE = "-_.!~*'()"


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


# --------------------------------------------------------------------------
# Helpers cho chữ ký HMAC-SHA256 của PayOS. Cấu hình CANONICAL phải KHỚP
# tuyệt đối với cách PayOS verify phía server (và cũng khớp với luồng donation
# ở `client/views.py::_build_payos_signature_payload`).
#
# Rule canonical:
#   * Chỉ ký trên subset field: amount, cancelUrl, description, orderCode, returnUrl.
#   * Sort keys ALPHABET — nếu lệch thứ tự → signature mismatch → PayOS trả code
#     `20` ("Ma xac thuc khong hop le").
#   * Value normalize: None / 'undefined' / 'null' → '', bool → 'true'/'false',
#     còn lại str(value). Với số nguyên: str(100000) = "100000" (không có dấu ,).
#   * Nối bằng '&': "amount=100000&cancelUrl=https://...&description=...".
# --------------------------------------------------------------------------
_SIGNATURE_FIELDS = ('amount', 'cancelUrl', 'description', 'orderCode', 'returnUrl')


def _normalize_payos_value(value):
    # Canonical normalization KHỚP HỆT `client/views.py::_normalize_payos_value` để
    # đảm bảo HMAC signature payout flow === donation flow (PayOS server side verify
    # theo cùng 1 thuật toán — chỉ khác checksum key giữa 2 luồng).
    if value in (None, 'undefined', 'null'):
        return ''
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, list):
        normalized_items = []
        for item in value:
            if isinstance(item, dict):
                normalized_items.append({k: _normalize_payos_value(v) for k, v in sorted(item.items())})
            else:
                normalized_items.append(_normalize_payos_value(item))
        return _json.dumps(normalized_items, ensure_ascii=False, separators=(',', ':'))
    if isinstance(value, dict):
        normalized_dict = {k: _normalize_payos_value(v) for k, v in sorted(value.items())}
        return _json.dumps(normalized_dict, ensure_ascii=False, separators=(',', ':'))
    return str(value)


def _build_payos_signature(payload: Dict[str, Any], checksum_key: str) -> str:
    """HMAC-SHA256 hex theo chuẩn PayOS cho checkout link."""
    canonical_parts = []
    for key in sorted(_SIGNATURE_FIELDS):
        canonical_parts.append(f"{key}={_normalize_payos_value(payload.get(key))}")
    canonical = '&'.join(canonical_parts)
    return hmac.new(
        checksum_key.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def create_payment_link(
    client_id,
    api_key,
    checksum_key,
    amount,
    order_code,
    description,
    cancel_url=None,
    return_url=None,
):
    """
    Tạo PayOS Payment Link (Checkout) cho luồng GIẢI NGÂN — mỗi Organization
    có bộ credentials (client_id / api_key / checksum_key) RIÊNG, không dùng
    credentials platform-wide của luồng donation.

    Implementation dùng REST API trực tiếp (POST /v2/payment-requests) với HMAC
    signature tự tính — KHỚP HỆT luồng donation (`client/views.py`) đang chạy
    ổn định, tránh bug "Application error" trên trang success PayOS khi dùng SDK.

    Parameters
    ----------
    client_id / api_key / checksum_key : str
        Credentials PayOS của Organization (lưu trong Organization model).
    amount : int
        Số tiền (VNĐ, integer).
    order_code : int
        Mã đơn hàng. BẮT BUỘC là integer duy nhất, tối đa 9007199254740991
        (Number.MAX_SAFE_INTEGER của JS). Caller chịu trách nhiệm sinh
        unique (thường dùng `int(f"{proposal.id}{int(time.time()*1000) % 100000}")`).
    description : str
        Mô tả giao dịch (PayOS giới hạn 25 ký tự).
    cancel_url / return_url : str
        URL redirect sau khi khách hủy / hoàn tất thanh toán.

    Returns
    -------
    dict | None
        `{'checkoutUrl', 'qrCode', 'paymentLinkId'}` nếu thành công.
        `None` nếu PayOS reject — lỗi đã được in ra stdout với flush=True.
        KHÔNG raise để caller (view) có thể render UI bình thường mà không
        crash 500.
    """
    # Validate credentials trước khi gọi API — tránh roundtrip network vô ích.
    if not (client_id and api_key and checksum_key):
        print(
            f"PAYOS ERROR: thiếu credentials cho orderCode={order_code} "
            f"(client_id={bool(client_id)}, api_key={bool(api_key)}, checksum_key={bool(checksum_key)})",
            flush=True,
        )
        return None

    # PayOS yêu cầu orderCode là số nguyên ≤ 9007199254740991 (Number.MAX_SAFE_INTEGER).
    try:
        order_code_int = int(order_code)
    except (TypeError, ValueError):
        print(f"PAYOS ERROR: orderCode không phải số nguyên: {order_code!r}", flush=True)
        return None
    if order_code_int <= 0 or order_code_int > 9007199254740991:
        print(
            f"PAYOS ERROR: orderCode={order_code_int} vượt quá giới hạn "
            f"(1..9007199254740991).",
            flush=True,
        )
        return None

    amount_int = int(amount)
    # PayOS description giới hạn 25 ký tự; cắt ngay để tránh contract error.
    description = (description or '')[:25] or f"DISBURSE{order_code_int}"[-25:]

    # Fallback URL KHÔNG được trỏ tới page auth-protected (`/admin/giaingan/`)
    # vì PayOS success page validate/render URL → trả 302 redirect sẽ khiến
    # Next.js page của PayOS crash "Application error". Chỉ dùng khi caller quên
    # truyền — trỏ tới root domain là an toàn nhất.
    fallback_url = 'https://web-production-9c2ee.up.railway.app/'
    cancel_url_final = cancel_url or fallback_url
    return_url_final = return_url or fallback_url

    # expiredAt: 15 phút từ hiện tại (khớp luồng donation). PayOS cần int timestamp.
    expired_at = int(time.time() + 15 * 60)

    # Payload format KHỚP HỆT luồng donation (`client/views.py::_create_payos_payment_link`):
    # đủ các field buyer* (empty string nếu không có) + items + expiredAt.
    # Thiếu `buyerEmail`/`buyerPhone` có thể khiến PayOS success page (Next.js) crash
    # khi render thông tin buyer → "Application error: a server-side exception".
    payload = {
        'orderCode': order_code_int,
        'amount': amount_int,
        'description': description,
        'buyerName': 'Quy to chuc',
        'buyerEmail': '',
        'buyerPhone': '',
        'items': [
            {
                'name': description[:25] or 'Giai ngan',
                'quantity': 1,
                'price': amount_int,
            }
        ],
        'cancelUrl': cancel_url_final,
        'returnUrl': return_url_final,
        'expiredAt': expired_at,
    }
    # Ký HMAC trên subset 5 field → gắn vào payload['signature']. KHÔNG ký trên
    # toàn payload vì PayOS server cũng chỉ verify subset này.
    payload['signature'] = _build_payos_signature(payload, checksum_key)

    try:
        response = _http_requests.post(
            f'{_PAYOS_API_BASE}/v2/payment-requests',
            json=payload,
            headers={
                'x-client-id': client_id,
                'x-api-key': api_key,
                'Content-Type': 'application/json',
            },
            timeout=20,
        )
    except _http_requests.RequestException as exc:
        # Network / DNS / timeout — in full traceback info để Railway logs thấy.
        print(
            f"PAYOS ERROR: network error khi gọi /v2/payment-requests cho orderCode={order_code_int} "
            f"— {type(exc).__name__}: {exc}",
            flush=True,
        )
        return None

    try:
        response_payload = response.json()
    except ValueError:
        response_payload = {'raw_text': response.text[:500]}

    # PayOS contract: code '00' = OK, các code khác là reject. Log FULL response
    # để biết lý do (sai API key, duplicate orderCode, IP whitelist, ...).
    if response.status_code >= 400 or response_payload.get('code') != '00' or 'data' not in response_payload:
        try:
            response_str = _json.dumps(response_payload, ensure_ascii=False)[:800]
        except (TypeError, ValueError):
            response_str = str(response_payload)[:800]
        print(
            f"PAYOS ERROR: createPaymentLink REJECTED orderCode={order_code_int} "
            f"amount={amount_int}đ status={response.status_code} response={response_str}",
            flush=True,
        )
        return None

    data = response_payload['data'] or {}
    checkout_url = data.get('checkoutUrl')
    qr_code = data.get('qrCode')
    payment_link_id = data.get('paymentLinkId')

    if not checkout_url:
        print(
            f"PAYOS ERROR: response code=00 nhưng thiếu checkoutUrl cho orderCode={order_code_int}. "
            f"Raw data: {data!r}",
            flush=True,
        )
        return None

    print(
        f"✅ PAYOS: tạo payment link OK — orderCode={order_code_int} amount={amount_int}đ "
        f"url={checkout_url[:80]}...",
        flush=True,
    )
    return {
        'checkoutUrl': checkout_url,
        'qrCode': qr_code,
        'paymentLinkId': payment_link_id,
    }


class PayoutRequestError(Exception):
    """Raised khi request_payout thất bại (network / config / PayOS reject)."""
    pass


# ==========================================================================
# PayosPayoutService — class wrapper cho PayOS Payout V1 API.
# --------------------------------------------------------------------------
# Ba method chính (theo spec task tích hợp):
#   1. check_balance()                 → int VND khả dụng trong escrow.
#   2. create_payout(proposal)         → POST /v1/payouts (idempotent qua
#                                        x-idempotency-key = proposal.id).
#   3. get_payout_status(payout_id)    → GET  /v1/payouts/{id}.
#
# Tuân thủ:
#   • KHÔNG hardcode credentials — đọc từ settings (env-driven).
#   • Idempotency: header x-idempotency-key = str(proposal.id) chống chi trùng
#     khi PayOS hoặc network retry.
#   • Signature: HMAC-SHA256 canonical body với PAYOS_CHECKSUM_KEY.
#   • Logging: in stdout (Railway logs) + raise PayoutRequestError có
#     message rõ để view layer surface lên UI.
#   • MOCK flag: mặc định True (PAYOS_PAYOUT_MOCK) để dev test không gây
#     thất thoát tiền thật. Khi có credentials Payout production thì set
#     env PAYOS_PAYOUT_MOCK=False.
# ==========================================================================
import logging as _logging

_logger = _logging.getLogger(__name__)

# Mapping bank_name → BIN (Vietnam Bank Identification Number, 6-digit, theo
# chuẩn PayOS / NAPAS). Dùng làm fallback khi Organization chưa có field bank_bin
# riêng (chưa migrate). Dev có thể bổ sung dần.
_BANK_NAME_TO_BIN = {
    'mb bank': '970422',
    'mbbank': '970422',
    'vietcombank': '970436',
    'vcb': '970436',
    'techcombank': '970407',
    'tcb': '970407',
    'bidv': '970418',
    'agribank': '970405',
    'vietinbank': '970415',
    'tpbank': '970423',
    'acb': '970416',
    'vpbank': '970432',
    'sacombank': '970403',
    'hdbank': '970437',
    'shb': '970443',
    'ocb': '970448',
    'msb': '970426',
    'eximbank': '970431',
    'lpbank': '970449',
    'lienvietpostbank': '970449',
    'seabank': '970440',
    'pgbank': '970430',
    'vib': '970441',
    'scb': '970429',
    'baovietbank': '970438',
    'vietabank': '970427',
    'vietbank': '970433',
    'kienlongbank': '970452',
    'pvcombank': '970412',
}


def _resolve_bank_bin(org) -> str:
    """
    Lấy BIN của tổ chức theo thứ tự ưu tiên:
        1. `org.bank_bin` nếu Organization model đã có field này.
        2. Mapping từ `org.bank_name` (case-insensitive, strip spaces).
        3. ''  (caller phải xử lý trường hợp trống — PayOS sẽ reject).
    """
    explicit = getattr(org, 'bank_bin', None)
    if explicit:
        return str(explicit).strip()
    name = (getattr(org, 'bank_name', '') or '').strip().lower()
    if not name:
        return ''
    # Match nguyên tên hoặc substring (vd 'MB Bank Hà Nội' → 'mb bank').
    if name in _BANK_NAME_TO_BIN:
        return _BANK_NAME_TO_BIN[name]
    for key, bin_code in _BANK_NAME_TO_BIN.items():
        if key in name:
            return bin_code
    return ''


def _build_idempotency_key(proposal_id) -> str:
    """
    Idempotency key = `proposal_{id}` để PayOS dedupe nếu task retry. Cùng
    proposal_id → cùng key → PayOS coi là cùng 1 lệnh chi.
    """
    return f"proposal_{int(proposal_id)}"


def _build_payout_signature(body: Dict[str, Any], checksum_key: str) -> str:
    """
    HMAC-SHA256 hex của canonical body (sorted keys, '&' separator) với
    PAYOS_CHECKSUM_KEY. Khớp thuật toán PayOS verify ở server-side.
    Bỏ qua field 'signature' nếu có để self-verify.
    """
    parts = []
    for k in sorted(body.keys()):
        if k == 'signature':
            continue
        v = body[k]
        if isinstance(v, (list, dict)):
            v = _json.dumps(v, ensure_ascii=False, separators=(',', ':'))
        elif v is None:
            v = ''
        elif isinstance(v, bool):
            v = 'true' if v else 'false'
        else:
            v = str(v)
        parts.append(f"{k}={v}")
    canonical = '&'.join(parts)
    return hmac.new(
        checksum_key.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def _first_payout_transaction(response_data: Dict[str, Any]) -> Dict[str, Any]:
    data = response_data.get('data') if isinstance(response_data, dict) else {}
    if not isinstance(data, dict):
        return {}
    transactions = data.get('transactions') or data.get('payouts') or []
    if isinstance(transactions, dict):
        transactions = list(transactions.values())
    if isinstance(transactions, list) and transactions and isinstance(transactions[0], dict):
        return transactions[0]
    return {}


def _extract_create_payout_id(response_data: Dict[str, Any]) -> str:
    data = response_data.get('data') if isinstance(response_data, dict) else {}
    if not isinstance(data, dict):
        data = {}
    tx = _first_payout_transaction(response_data)
    payout_id = (
        data.get('payoutId')
        or data.get('payout_id')
        or data.get('id')
        or response_data.get('payoutId')
        or response_data.get('id')
        or tx.get('payoutId')
        or tx.get('id')
        or ''
    )
    return str(payout_id)


def _extract_create_payout_status(response_data: Dict[str, Any]) -> str:
    data = response_data.get('data') if isinstance(response_data, dict) else {}
    if not isinstance(data, dict):
        data = {}
    tx = _first_payout_transaction(response_data)
    raw_status = (
        tx.get('state')
        or tx.get('status')
        or data.get('approvalState')
        or data.get('status')
        or response_data.get('status')
        or ''
    )
    status = str(raw_status or '').upper()
    if status in ('SUCCEEDED', 'SUCCESS', 'COMPLETED', 'COMPLETE', 'PAID'):
        return 'SUCCEEDED'
    if status in ('FAILED', 'FAILURE', 'REJECTED', 'CANCELED', 'CANCELLED', 'ERROR'):
        return 'FAILED'
    return 'PROCESSING'


def _extract_create_bank_tx_id(response_data: Dict[str, Any]) -> str:
    data = response_data.get('data') if isinstance(response_data, dict) else {}
    if not isinstance(data, dict):
        data = {}
    tx = _first_payout_transaction(response_data)
    bank_tx_id = (
        tx.get('bankTransactionId')
        or tx.get('transactionNo')
        or tx.get('transactionId')
        or tx.get('reference')
        or data.get('bankTransactionId')
        or data.get('transactionNo')
        or data.get('transactionId')
        or ''
    )
    return str(bank_tx_id)


class PayosPayoutService:
    """
    Adapter gọi PayOS Payout API v1 (https://api-merchant.payos.vn/v1/payouts).

    Khởi tạo KHÔNG nhận argument — đọc credentials từ Django settings.

    QUAN TRỌNG: Service này dùng Kênh CHI (payout) của PayOS, có bộ
    credentials RIÊNG hoàn toàn tách biệt với Kênh THU (donation):
        settings.PAYOS_PAYOUT_CLIENT_ID
        settings.PAYOS_PAYOUT_API_KEY
        settings.PAYOS_PAYOUT_CHECKSUM_KEY

    Tuyệt đối KHÔNG dùng `PAYOS_CLIENT_ID` / `PAYOS_API_KEY` /
    `PAYOS_CHECKSUM_KEY` (đó là key của Kênh Thu — sẽ bị PayOS reject
    với HTTP 401 hoặc signature mismatch nếu mix lẫn). KHÔNG có
    fallback sang Kênh Thu — thiếu credentials Kênh Chi → fail-loud
    để admin thấy ngay khi deploy thiếu env.
    """

    BASE_URL = _PAYOS_API_BASE  # https://api-merchant.payos.vn
    REQUEST_TIMEOUT = 20  # seconds

    def __init__(self):
        from django.conf import settings as dj_settings

        # CHỈ đọc PAYOS_PAYOUT_* (Kênh Chi). KHÔNG fallback sang PAYOS_*
        # (Kênh Thu) — spec tách hoàn toàn 2 kênh, mix sẽ khiến PayOS reject
        # signature hoặc (tệ hơn) chi nhầm từ bí danh khắc.
        self.client_id = getattr(dj_settings, 'PAYOS_PAYOUT_CLIENT_ID', None) or ''
        self.api_key = getattr(dj_settings, 'PAYOS_PAYOUT_API_KEY', None) or ''
        self.checksum_key = getattr(dj_settings, 'PAYOS_PAYOUT_CHECKSUM_KEY', None) or ''
        # Mock flag: nếu True → KHÔNG gọi PayOS thật, trả response mock.
        # Mặc định lấy từ module-level constant (PAYOS_PAYOUT_MOCK) hoặc env.
        self.mock_mode = bool(
            getattr(dj_settings, 'PAYOS_PAYOUT_MOCK', PAYOS_PAYOUT_MOCK)
        )
        if not self.mock_mode and not (self.client_id and self.api_key and self.checksum_key):
            raise PayoutRequestError(
                "PayOS Payout credentials chưa cấu hình đầy đủ "
                "(PAYOS_PAYOUT_CLIENT_ID / PAYOS_PAYOUT_API_KEY / PAYOS_PAYOUT_CHECKSUM_KEY). "
                "Lưu ý: KHÔNG dùng key Kênh Thu (PAYOS_CLIENT_ID/API_KEY/CHECKSUM_KEY) — "
                "PayOS sẽ reject signature."
            )

    # ---------------------------------------------------------------- helpers
    def _headers(self, idempotency_key: str = '', signature: str = '') -> Dict[str, str]:
        h = {
            'x-client-id': self.client_id,
            'x-api-key': self.api_key,
            'Content-Type': 'application/json',
        }
        if idempotency_key:
            h['x-idempotency-key'] = idempotency_key
        if signature:
            h['x-signature'] = signature
        return h

    # ---------------------------------------------------------------- 1. Balance
    def check_balance(self) -> int:
        """
        GET /v1/payouts-account/balance.
        Return: int VND khả dụng. Nếu MOCK → trả số dư khổng lồ để task không
        bị chặn. Nếu PayOS lỗi → raise PayoutRequestError.
        """
        if self.mock_mode:
            balance = 10_000_000_000  # 10 tỷ VND mock
            _logger.info(f"[PAYOS/MOCK] check_balance → {balance:,} VND")
            return balance

        url = f"{self.BASE_URL}/v1/payouts-account/balance"
        try:
            resp = _http_requests.get(
                url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT,
            )
        except _http_requests.RequestException as exc:
            _logger.error(f"[PAYOS] check_balance network error: {exc}")
            raise PayoutRequestError(f"PayOS check_balance network error: {exc}") from exc

        try:
            payload = resp.json()
        except ValueError:
            raise PayoutRequestError(
                f"PayOS check_balance trả về non-JSON (status={resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400 or payload.get('code') not in ('00', None):
            raise PayoutRequestError(
                f"PayOS check_balance reject status={resp.status_code} payload={payload}"
            )
        # PayOS contract: data.balance là int VND.
        data = payload.get('data') or {}
        balance = int(data.get('balance', 0))
        _logger.info(f"[PAYOS] check_balance → {balance:,} VND")
        return balance

    # ---------------------------------------------------------------- 2. Create payout
    def create_payout(self, proposal) -> Dict[str, Any]:
        """
        POST /v1/payouts cho 1 DisbursementProposal.

        Side-effects:
            - Lưu PayOS payout id vào proposal.payos_payout_id.
            - Lưu proposal.v3_status = 'payout_processing'.
            - Lưu proposal.payos_payout_requested_at = now.
            - Save proposal với update_fields giới hạn (idempotent re-call OK).

        Return: dict response gốc (đã merge mock fields nếu mock mode).
        Raise PayoutRequestError nếu PayOS reject hoặc network lỗi.
        """
        from django.utils import timezone as _tz

        amount = int(proposal.amount_requested)
        org = getattr(proposal.campaign, 'organization', None)
        if not org:
            raise PayoutRequestError(
                f"Proposal #{proposal.id} không có organization → không xác định được tài khoản nhận."
            )

        to_account = (
            getattr(proposal, 'recipient_bank_account', None)
            or getattr(org, 'bank_account_number', None)
            or ''
        ).strip()
        to_bin = (
            getattr(proposal, 'recipient_bank_bin', None)
            or _resolve_bank_bin(org)
            or ''
        ).strip()
        if not to_account or not to_bin:
            raise PayoutRequestError(
                f"Proposal #{proposal.id} thiếu thông tin ngân hàng "
                f"(account={to_account or 'EMPTY'}, bin={to_bin or 'EMPTY'}). "
                "Cập nhật Organization.bank_name (hoặc thêm field bank_bin) trước khi tạo payout."
            )

        body: Dict[str, Any] = {
            'amount': amount,
            'description': f"Giai ngan chien dich {proposal.campaign_id}"[:25],
            'referenceId': f"proposal_{proposal.id}",
            'toAccountNumber': to_account,
            'toBin': to_bin,
        }
        idempotency_key = _build_idempotency_key(proposal.id)

        if self.mock_mode:
            mock_payout_id = f"PAYOUT-{int(time.time())}-{secrets.token_hex(5).upper()}"
            response_data: Dict[str, Any] = {
                'code': '00',
                'desc': 'success (mock)',
                'data': {
                    'payoutId': mock_payout_id,
                    'referenceId': body['referenceId'],
                    'status': 'PROCESSING',
                    'amount': amount,
                    'toBin': to_bin,
                    'toAccountNumber': to_account,
                },
                'mock': True,
            }
            _logger.info(
                f"[PAYOS/MOCK] create_payout proposal={proposal.id} "
                f"amount={amount:,}đ → payout_id={mock_payout_id}"
            )
        else:
            sign_string = '&'.join(
                f"{key}={_quote(str(body[key]), safe=_PAYOS_ENCODE_SAFE)}"
                for key in sorted(body.keys())
            )
            signature = hmac.new(
                self.checksum_key.encode('utf-8'),
                sign_string.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()
            url = f"{self.BASE_URL}/v1/payouts"
            try:
                resp = _http_requests.post(
                    url,
                    json=body,
                    headers=self._headers(idempotency_key=idempotency_key, signature=signature),
                    timeout=self.REQUEST_TIMEOUT,
                )
            except _http_requests.RequestException as exc:
                _logger.error(f"[PAYOS] create_payout network error: {exc}")
                raise PayoutRequestError(f"PayOS create_payout network error: {exc}") from exc
            try:
                response_data = resp.json()
            except ValueError:
                raise PayoutRequestError(
                    f"PayOS create_payout non-JSON (status={resp.status_code}): {resp.text[:200]}"
                )
            if resp.status_code >= 400 or response_data.get('code') != '00':
                raise PayoutRequestError(
                    f"PayOS create_payout reject status={resp.status_code} payload={response_data}"
                )
            _logger.info(
                f"[PAYOS] create_payout proposal={proposal.id} "
                f"amount={amount:,}đ status={resp.status_code}"
            )

        payout_id = _extract_create_payout_id(response_data)
        if not payout_id:
            raise PayoutRequestError(
                f"PayOS create_payout không trả về payout id. Response: {response_data}"
            )

        # Persist tới DB — chỉ update các field cần thiết, không trigger save() đầy đủ.
        proposal.payos_payout_id = payout_id
        proposal.payos_payout_requested_at = _tz.now()
        update_fields = [
            'payos_payout_id', 'v3_status', 'payos_payout_requested_at',
        ]

        payout_status = _extract_create_payout_status(response_data)
        if payout_status == 'SUCCEEDED':
            bank_tx_id = _extract_create_bank_tx_id(response_data) or f"UNKNOWN-{payout_id}"
            proposal.bank_tx_id = bank_tx_id
            proposal.fiat_transferred_at = _tz.now()
            proposal.v3_status = 'fiat_transferred'
            proposal.payout_error = None
            update_fields += ['bank_tx_id', 'fiat_transferred_at', 'payout_error']
        elif payout_status == 'FAILED':
            proposal.v3_status = 'payout_failed'
            proposal.payout_error = str(response_data.get('desc') or 'PayOS payout failed')[:1000]
            update_fields += ['payout_error']
        else:
            proposal.v3_status = 'payout_processing'

        proposal.save(update_fields=update_fields)
        return response_data

    # ---------------------------------------------------------------- 3. Status
    def get_payout_status(self, payout_id: str) -> str:
        """
        GET /v1/payouts/{payout_id}.
        Return status string normalized: 'PROCESSING' | 'SUCCEEDED' | 'FAILED'.
        Mock mode: luôn trả 'PROCESSING' (caller nên dùng simulate_webhook để
        test SUCCEEDED).
        """
        if not payout_id:
            raise PayoutRequestError("payout_id không được để trống.")
        if self.mock_mode:
            return 'PROCESSING'

        url = f"{self.BASE_URL}/v1/payouts/{payout_id}"
        try:
            resp = _http_requests.get(
                url, headers=self._headers(), timeout=self.REQUEST_TIMEOUT,
            )
        except _http_requests.RequestException as exc:
            _logger.error(f"[PAYOS] get_payout_status network error: {exc}")
            raise PayoutRequestError(f"PayOS get_payout_status network error: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError:
            raise PayoutRequestError(
                f"PayOS get_payout_status non-JSON (status={resp.status_code}): {resp.text[:200]}"
            )
        if resp.status_code >= 400 or payload.get('code') != '00':
            raise PayoutRequestError(
                f"PayOS get_payout_status reject status={resp.status_code} payload={payload}"
            )
        data = payload.get('data') or {}
        raw_status = (data.get('status') or '').upper()
        # PayOS dùng nhiều status khác nhau theo doc (PROCESSING, SUCCEEDED,
        # SUCCESS, FAILED, CANCELED, ...). Normalize về 3 trạng thái chính.
        if raw_status in ('SUCCEEDED', 'SUCCESS', 'COMPLETED', 'COMPLETE'):
            return 'SUCCEEDED'
        if raw_status in ('FAILED', 'FAILURE', 'REJECTED', 'CANCELED', 'CANCELLED'):
            return 'FAILED'
        return 'PROCESSING'
