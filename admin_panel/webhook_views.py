"""
admin_panel/webhook_views.py — PayOS Payout webhook handler (V2 spec).

==================================================================
PURPOSE
------------------------------------------------------------------
Endpoint: POST /webhook/payos/payout/

Luồng:
    1. PayOS POST JSON về sau khi bank transfer xong.
    2. Backend verify HMAC-SHA256 (PAYOS_PAYOUT_CHECKSUM_KEY — Kênh Chi) qua header `x-signature`.
    3. Parse event type / payoutId / status / bankTxId.
    4. SUCCEEDED → tìm proposal theo payos_payout_id, lưu bank_tx_id, gọi
       BlockchainService.finalize_disbursement → status='FINALIZED' +
       NotificationService.notify_disbursement_success.
    5. FAILED → status='PAYOUT_FAILED' + NotificationService.notify_disbursement_failed.
    6. RETURN HTTP 200 luôn (kể cả khi xử lý lỗi) để PayOS không retry loop.

Tương quan với endpoint V3 cũ (`/admin/api/webhook/payos-payout/`):
    - Endpoint V3 cũ verify sig theo CHECKSUM_KEY của TỪNG Organization
      (mỗi org có credentials PayOS riêng).
    - Endpoint mới (file này) verify theo PAYOS_PAYOUT_CHECKSUM_KEY (Kênh Chi platform-wide).
    - Cả hai cùng tồn tại: PayOS dashboard chỉ trỏ về 1 endpoint, dev tự
      chọn theo workflow phù hợp. Có 1 view proxy tự forward request từ
      endpoint cũ về handler mới khi cần.
==================================================================
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import traceback
from typing import Any, Dict

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from admin_panel.models import DisbursementProposal

logger = logging.getLogger(__name__)


# ==========================================================================
# Notification stub — admin/email/slack/...; thay bằng integration thật khi cần.
# ==========================================================================
class NotificationService:
    """
    Stub: log notification để dev thấy có gọi. Production sẽ thay bằng email
    (Django send_mail), Slack webhook, hoặc Django Notifications app.
    """

    @staticmethod
    def notify_disbursement_success(proposal):
        logger.info(
            "[NOTIFY] Disbursement SUCCESS proposal=%s amount=%s bank_tx=%s",
            proposal.id,
            proposal.amount_requested,
            proposal.bank_tx_id,
        )

    @staticmethod
    def notify_disbursement_failed(proposal):
        logger.warning(
            "[NOTIFY] Disbursement FAILED proposal=%s amount=%s payout_id=%s err=%s",
            proposal.id,
            proposal.amount_requested,
            proposal.payos_payout_id,
            proposal.payout_error,
        )


# ==========================================================================
# Signature verification (HMAC-SHA256 canonical body với PAYOS_PAYOUT_CHECKSUM_KEY).
# QUAN TRỌNG: dùng key của Kênh CHI (payout) — KHÔNG dùng PAYOS_CHECKSUM_KEY của
# Kênh THU (donation) vì PayOS sign webhook payout bằng checksum của Kênh Chi.
# ==========================================================================
def _verify_signature(raw_body: bytes, header_signature: str, checksum_key: str) -> bool:
    """
    Verify chữ ký webhook PayOS gửi qua header `x-signature`.
    Hai chiến lược (chọn cái nào match):
        A. HMAC trên RAW body bytes (đơn giản nhất, PayOS docs phổ biến).
        B. HMAC trên canonical sorted-keys của JSON body (legacy).
    Trả True nếu BẤT KỲ chiến lược nào match — robust với cả 2 phiên bản.
    """
    if not header_signature or not checksum_key:
        return False

    # Strategy A: raw body
    sig_raw = hmac.new(
        checksum_key.encode('utf-8'),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if hmac.compare_digest(sig_raw, header_signature):
        return True

    # Strategy B: canonical sorted JSON
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    parts = []
    for k in sorted(payload.keys()):
        if k == 'signature':
            continue
        v = payload[k]
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False, separators=(',', ':'))
        elif v is None:
            v = ''
        elif isinstance(v, bool):
            v = 'true' if v else 'false'
        else:
            v = str(v)
        parts.append(f"{k}={v}")
    canonical = '&'.join(parts)
    sig_canon = hmac.new(
        checksum_key.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig_canon, header_signature)


def _extract_payout_fields(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Trích các field quan trọng từ payload PayOS. Hỗ trợ cả 2 schema phổ biến:
        - flat: {payoutId, status, bankTransactionId, ...}
        - wrapped: {data: {payoutId, status, ...}, code, desc}
    """
    if isinstance(payload.get('data'), dict):
        data = payload['data']
    else:
        data = payload
    transactions = data.get('transactions') or data.get('payouts') or []
    if isinstance(transactions, dict):
        transactions = list(transactions.values())
    first_tx = transactions[0] if isinstance(transactions, list) and transactions and isinstance(transactions[0], dict) else {}

    payout_id = (
        data.get('payoutId')
        or data.get('payout_id')
        or data.get('id')
        or payload.get('payoutId')
        or payload.get('id')
        or first_tx.get('payoutId')
        or first_tx.get('id')
        or ''
    )
    status = (
        first_tx.get('state')
        or first_tx.get('status')
        or data.get('status')
        or data.get('approvalState')
        or payload.get('status')
        or ''
    ).upper()
    bank_tx_id = (
        first_tx.get('bankTransactionId')
        or first_tx.get('transactionNo')
        or first_tx.get('transactionId')
        or first_tx.get('reference')
        or data.get('bankTransactionId')
        or data.get('bank_tx_id')
        or data.get('transactionId')
        or data.get('transactionNo')
        or data.get('reference')
        or data.get('referenceId')
        or payload.get('bankTransactionId')
        or payload.get('referenceId')
        or ''
    )
    event = payload.get('event') or payload.get('type') or ''
    return {
        'event': str(event),
        'payout_id': str(payout_id),
        'status': str(status),
        'bank_tx_id': str(bank_tx_id),
    }


def _normalize_status(raw_status: str) -> str:
    """Normalize PayOS status → SUCCEEDED / FAILED / PROCESSING."""
    s = (raw_status or '').upper()
    if s in ('SUCCEEDED', 'SUCCESS', 'COMPLETED', 'COMPLETE', 'PAID'):
        return 'SUCCEEDED'
    if s in ('FAILED', 'FAILURE', 'REJECTED', 'CANCELED', 'CANCELLED', 'ERROR'):
        return 'FAILED'
    return 'PROCESSING'


# ==========================================================================
# Background blockchain finalize — chạy ngoài request thread để không
# timeout webhook (Sepolia RPC ~10-15s, PayOS chỉ chờ webhook ~5s).
# ==========================================================================
def _spawn_finalize_thread(proposal_id: int, bank_tx_id: str):
    """
    Spawn daemon thread gọi BlockchainService.finalize_disbursement.
    Dùng `transaction.on_commit` để chỉ chạy SAU KHI DB transaction commit
    (tránh thread đọc stale proposal). Nếu không có transaction → chạy ngay.
    """
    def _run():
        from django.db import connection
        try:
            from client.blockchain import BlockchainService
            proposal = DisbursementProposal.objects.select_related(
                'campaign', 'campaign__organization'
            ).get(pk=proposal_id)
            bc = BlockchainService()
            tx_hash = bc.finalize_disbursement(proposal, bank_tx_id)
            DisbursementProposal.objects.filter(pk=proposal_id).update(
                burn_tx_hash=tx_hash,
                burn_completed_at=timezone.now(),
                v3_status='completed_audited',
            )
            logger.info(
                "[WEBHOOK/BURN] proposal=%s tx=%s — finalize_disbursement OK",
                proposal_id, tx_hash,
            )
        except Exception as exc:
            logger.error(
                "[WEBHOOK/BURN] proposal=%s finalize_disbursement FAILED: %s\n%s",
                proposal_id, exc, traceback.format_exc(),
            )
            DisbursementProposal.objects.filter(pk=proposal_id).update(
                payout_error=f"finalize_disbursement failed: {exc}"[:1000],
            )
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _spawn():
        thread = threading.Thread(
            target=_run,
            daemon=True,
            name=f'payos-finalize-{proposal_id}',
        )
        thread.start()

    transaction.on_commit(_spawn)


# ==========================================================================
# MAIN ENDPOINT: POST /webhook/payos/payout/
# ==========================================================================
@csrf_exempt
@require_POST
def payos_payout_webhook(request: HttpRequest) -> HttpResponse:
    """
    PayOS gọi endpoint này sau khi bank transfer xong (hoặc thất bại).

    Wrap toàn bộ logic trong try/except để LUÔN trả 200 — PayOS sẽ retry
    loop nếu nhận non-2xx → spam khi backend lỗi tạm thời.
    """
    try:
        return _process_payout_webhook(request)
    except Exception as exc:
        logger.error(
            "[WEBHOOK] payos_payout_webhook UNEXPECTED ERROR: %s\n%s",
            exc, traceback.format_exc(),
        )
        # Trả 200 để PayOS không retry — đã log đủ để debug.
        return JsonResponse({'received': True, 'error': str(exc)[:200]}, status=200)


def _process_payout_webhook(request: HttpRequest) -> HttpResponse:
    raw_body = request.body or b''
    header_sig = (
        request.headers.get('x-signature')
        or request.headers.get('X-Signature')
        or request.META.get('HTTP_X_SIGNATURE', '')
    ).strip()
    # Webhook payout do Kênh CHI sign → verify CHỈ bằng PAYOS_PAYOUT_CHECKSUM_KEY.
    # KHÔNG fallback sang PAYOS_CHECKSUM_KEY (Kênh Thu) — mix key sẽ verify sai
    # âm thầm. Thiếu key → mọi webhook reject + log warning rõ.
    checksum_key = getattr(settings, 'PAYOS_PAYOUT_CHECKSUM_KEY', '') or ''
    if not checksum_key:
        logger.error(
            "[WEBHOOK] PAYOS_PAYOUT_CHECKSUM_KEY chưa cấu hình — mọi webhook payout sẽ bị reject. "
            "Set biến này trong .env (lấy từ PayOS dashboard → Kênh Chi).",
        )

    # 1. Verify signature.
    if not _verify_signature(raw_body, header_sig, checksum_key):
        logger.warning(
            "[WEBHOOK] Invalid signature. header=%s body_len=%d",
            header_sig[:16], len(raw_body),
        )
        # Vẫn trả 200 để PayOS không retry (khả năng cao là attacker).
        return JsonResponse({'received': True, 'error': 'invalid_signature'}, status=200)

    # 2. Parse body.
    try:
        payload = json.loads(raw_body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError) as exc:
        logger.error("[WEBHOOK] Cannot parse body: %s", exc)
        return JsonResponse({'received': True, 'error': 'invalid_json'}, status=200)

    fields = _extract_payout_fields(payload if isinstance(payload, dict) else {})
    payout_id = fields['payout_id']
    status = _normalize_status(fields['status'])
    bank_tx_id = fields['bank_tx_id']

    logger.info(
        "[WEBHOOK] received event=%s payout_id=%s status=%s bank_tx=%s",
        fields['event'], payout_id, status, bank_tx_id,
    )

    if not payout_id:
        logger.error("[WEBHOOK] payload thiếu payoutId. payload=%s", str(payload)[:500])
        return JsonResponse({'received': True, 'error': 'missing_payout_id'}, status=200)

    proposal = DisbursementProposal.objects.filter(payos_payout_id=payout_id).first()
    if not proposal:
        logger.error("[WEBHOOK] không tìm thấy proposal cho payout_id=%s", payout_id)
        return JsonResponse({'received': True, 'error': 'proposal_not_found'}, status=200)

    # 3. Branch by status.
    if status == 'SUCCEEDED':
        _handle_succeeded(proposal, bank_tx_id)
    elif status == 'FAILED':
        _handle_failed(proposal, payload)
    else:
        # PROCESSING / unknown → chỉ log, không update.
        logger.info(
            "[WEBHOOK] proposal=%s status=%s (no-op)", proposal.id, status,
        )

    return JsonResponse({'received': True}, status=200)


def _handle_succeeded(proposal: DisbursementProposal, bank_tx_id: str):
    """Branch SUCCEEDED: lưu bank_tx, status, spawn burn thread, notify."""
    # Idempotency: nếu đã xử lý SUCCESS rồi (burn_tx_hash hoặc completed_audited)
    # → skip để tránh double burn.
    if proposal.v3_status == 'completed_audited' and proposal.burn_tx_hash:
        logger.info(
            "[WEBHOOK] proposal=%s đã completed_audited, skip duplicate webhook.",
            proposal.id,
        )
        return

    if not bank_tx_id:
        bank_tx_id = f"UNKNOWN-{proposal.payos_payout_id}"
        logger.warning(
            "[WEBHOOK] proposal=%s SUCCESS nhưng PayOS không trả bankTxId — dùng fallback %s",
            proposal.id, bank_tx_id,
        )

    with transaction.atomic():
        proposal.bank_tx_id = bank_tx_id
        proposal.fiat_transferred_at = timezone.now()
        # `FINALIZED` (theo spec) map sang `fiat_transferred` (đã chuyển fiat,
        # đang chờ burn on-chain). Sau khi burn xong, thread sẽ update tiếp
        # thành `completed_audited`.
        proposal.v3_status = 'fiat_transferred'
        proposal.payout_error = None
        proposal.save(update_fields=[
            'bank_tx_id', 'fiat_transferred_at', 'v3_status', 'payout_error',
        ])

    _spawn_finalize_thread(proposal.id, bank_tx_id)
    NotificationService.notify_disbursement_success(proposal)


def _handle_failed(proposal: DisbursementProposal, payload: Dict[str, Any]):
    """Branch FAILED: status=PAYOUT_FAILED, lưu payout_error, notify."""
    error_msg = (
        payload.get('desc')
        or payload.get('errorMessage')
        or payload.get('message')
        or 'PayOS payout failed (no detail)'
    )
    proposal.v3_status = 'payout_failed'
    proposal.payout_error = str(error_msg)[:1000]
    proposal.save(update_fields=['v3_status', 'payout_error'])
    NotificationService.notify_disbursement_failed(proposal)


# ==========================================================================
# PROXY: forward request từ endpoint V3 cũ về handler mới (backward-compat).
# ==========================================================================
@csrf_exempt
@require_POST
def payos_payout_webhook_legacy_proxy(request: HttpRequest) -> HttpResponse:
    """
    Proxy: PayOS dashboard có thể vẫn trỏ về URL cũ
    `/admin/api/webhook/payos-payout/`. View này forward request thẳng
    sang handler mới để tránh PayOS phải đổi config.

    NOTE: Endpoint V3 cũ (`v3_payos_payout_webhook` trong views.py) verify
    sig theo per-organization checksum, KHÁC với platform-wide ở đây. Proxy
    này CHỈ active khi caller chấp nhận platform-wide verification — dev có
    thể vô hiệu hóa proxy bằng cách remove URL pattern.
    """
    return payos_payout_webhook(request)
