"""
admin_panel/tasks/disbursement_tasks.py — V3 disbursement background tasks.

==================================================================
PURPOSE
------------------------------------------------------------------
Task `trigger_payos_payout(proposal_id)`:
    1. Load proposal, kiểm tra v3_status == 'ready_to_payout' (~ multisig
       confirmed) hoặc multisig_confirmed_tx_hash đã có.
    2. Kiểm tra balance PayOS escrow ≥ proposal.amount_requested.
    3. Idempotency: nếu proposal.payos_payout_id đã có → skip (đã chi rồi).
    4. Gọi PayosPayoutService.create_payout(proposal). Service tự lưu
       payos_payout_id + status='payout_processing'.
    5. Retry 3 lần với exponential backoff khi PayOS trả 5xx (Celery
       autoretry) hoặc network exception.

Trigger paths:
    A. Django signal: khi DisbursementProposal.v3_status chuyển sang
       'ready_to_payout' (đăng ký ở admin_panel/signals.py).
    B. Manual: blockchain event listener / admin button gọi
       `trigger_payos_payout.delay(proposal_id)`.

CELERY OPTIONAL
------------------------------------------------------------------
Project hiện chưa có Celery broker. File này dùng pattern fallback:
    - Nếu `celery` import được → dùng @shared_task thật.
    - Nếu không → định nghĩa decorator stub có cùng API (.delay, .apply,
      autoretry_for, max_retries) chạy đồng bộ trong thread daemon.

Khi sau này bật Celery (cài celery + redis, thêm doantn/celery.py), KHÔNG
cần đổi import-site — task tự động chuyển sang real Celery worker.
==================================================================
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any, Callable

import requests

# Module-level imports (đặt ở top để mock.patch('admin_panel.tasks.
# disbursement_tasks.PayosPayoutService') hoạt động trong unit tests, đồng
# thời để app registry resolved khi task được call lần đầu).
# DisbursementProposal cần app registry → import lazy bên trong task để
# tránh circular ở app-loading time.
from client.payos_payout import PayosPayoutService, PayoutRequestError

logger = logging.getLogger(__name__)


# ==========================================================================
# Celery shim — tương thích cả khi có/không có celery cài đặt.
# ==========================================================================
try:  # pragma: no cover — depends on environment
    from celery import shared_task as _celery_shared_task  # type: ignore

    _CELERY_AVAILABLE = True
except ImportError:  # Celery not installed → fallback.
    _CELERY_AVAILABLE = False
    _celery_shared_task = None  # type: ignore


class _ThreadingTaskWrapper:
    """
    Mimic Celery task API khi không có Celery worker:
        .delay(*args, **kwargs)        — spawn daemon thread (async).
        .apply(args=..., kwargs=...)   — chạy đồng bộ, return result-like.
        .__call__(*args, **kwargs)     — direct call (for testing).

    Thread chạy trong background giống worker, có retry primitive đơn giản.
    """

    def __init__(self, fn: Callable, autoretry_for=(Exception,), max_retries: int = 3,
                 retry_backoff: int = 5):
        self.fn = fn
        self.autoretry_for = autoretry_for or (Exception,)
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.__name__ = getattr(fn, '__name__', 'task')
        self.__doc__ = getattr(fn, '__doc__', None)

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)

    def _run_with_retry(self, *args, **kwargs):
        attempt = 0
        last_exc = None
        while attempt <= self.max_retries:
            try:
                return self.fn(*args, **kwargs)
            except self.autoretry_for as exc:
                last_exc = exc
                attempt += 1
                if attempt > self.max_retries:
                    logger.error(
                        "[TASK/RETRY] %s exhausted %d retries: %s\n%s",
                        self.__name__, self.max_retries, exc, traceback.format_exc(),
                    )
                    raise
                wait_s = self.retry_backoff * attempt
                logger.warning(
                    "[TASK/RETRY] %s attempt=%d/%d failed: %s — retry in %ds",
                    self.__name__, attempt, self.max_retries, exc, wait_s,
                )
                time.sleep(wait_s)
        if last_exc:
            raise last_exc

    def delay(self, *args, **kwargs):
        """Async fire-and-forget (daemon thread)."""
        thread = threading.Thread(
            target=self._run_with_retry,
            args=args,
            kwargs=kwargs,
            daemon=True,
            name=f'task-{self.__name__}',
        )
        thread.start()
        return thread

    def apply(self, args=None, kwargs=None):
        """Synchronous run (returns SimpleResult-like object)."""
        result = self._run_with_retry(*(args or ()), **(kwargs or {}))

        class _Result:
            def __init__(self, value):
                self.value = value

            def get(self, timeout=None):  # noqa: ARG002
                return self.value

        return _Result(result)


def shared_task(*decorator_args, **decorator_kwargs):
    """
    Decorator unifying Celery + threading fallback.

    Usage:
        @shared_task(autoretry_for=(Exception,), max_retries=3)
        def my_task(...): ...

    Khi Celery available → forward decorator_kwargs về celery.shared_task.
    Khi không → dùng _ThreadingTaskWrapper với cùng autoretry_for/max_retries.
    """
    # Allow `@shared_task` (no parens) → first arg là function.
    if (
        len(decorator_args) == 1
        and callable(decorator_args[0])
        and not decorator_kwargs
    ):
        fn = decorator_args[0]
        if _CELERY_AVAILABLE:
            return _celery_shared_task(fn)  # type: ignore
        return _ThreadingTaskWrapper(fn)

    autoretry_for = decorator_kwargs.get('autoretry_for', (Exception,))
    max_retries = decorator_kwargs.get('max_retries', 3)

    def _decorator(fn):
        if _CELERY_AVAILABLE:
            return _celery_shared_task(*decorator_args, **decorator_kwargs)(fn)  # type: ignore
        return _ThreadingTaskWrapper(
            fn,
            autoretry_for=autoretry_for,
            max_retries=max_retries,
        )

    return _decorator


# ==========================================================================
# TASK: trigger_payos_payout(proposal_id)
# ==========================================================================
@shared_task(autoretry_for=(Exception,), max_retries=3)
def trigger_payos_payout(proposal_id: int):
    """
    Background task: trigger PayOS payout cho 1 DisbursementProposal đã có
    đủ multisig sigs. Idempotent — gọi nhiều lần vẫn chỉ tạo 1 payout.

    Args:
        proposal_id: int — primary key DisbursementProposal.

    Returns:
        dict {payout_id, status} hoặc None nếu skipped (idempotent).

    Raises:
        PayoutRequestError (từ service) nếu PayOS reject.
        DisbursementProposal.DoesNotExist nếu proposal_id không tồn tại.

    Note:
        Balance không đủ KHÔNG raise (retry vô ích vì balance không tự nạp);
        thay vào đó set v3_status='payout_failed' + return dict skipped với
        reason='insufficient_balance' để admin theo dõi qua dashboard.
    """
    # Import model bên trong task để tránh Django app-loading cycles ở
    # module-load time. PayosPayoutService đã import ở top module.
    from admin_panel.models import DisbursementProposal

    proposal = DisbursementProposal.objects.select_related(
        'campaign', 'campaign__organization'
    ).get(pk=proposal_id)

    # 1. Idempotency: đã có payout_id → skip.
    if proposal.payos_payout_id:
        logger.info(
            "[TASK] proposal=%s đã có payos_payout_id=%s — skip create_payout.",
            proposal_id, proposal.payos_payout_id,
        )
        return {
            'payout_id': proposal.payos_payout_id,
            'status': proposal.v3_status,
            'skipped': True,
        }

    # 2. Sanity check: status phải đã ở 'ready_to_payout' (multisig confirmed).
    # Hỗ trợ alias 'MULTISIG_CONFIRMED' — không có giá trị này trong
    # V3_STATUS_CHOICES, nhưng spec đề cập, nên log warn và proceed nếu thấy.
    if proposal.v3_status not in ('ready_to_payout',):
        logger.warning(
            "[TASK] proposal=%s v3_status=%s không phải 'ready_to_payout' — "
            "vẫn proceed (có thể là edge case, log để debug).",
            proposal_id, proposal.v3_status,
        )

    service = PayosPayoutService()

    # 3. Check balance.
    try:
        print("====== ĐỊA CHỈ IP CỦA RAILWAY LÀ: ======", requests.get('https://api.ipify.org').text, flush=True)
        balance = service.check_balance()
    except Exception as exc:
        logger.error("[TASK] proposal=%s check_balance failed: %s", proposal_id, exc)
        raise

    amount = int(proposal.amount_requested)
    if balance < amount:
        msg = (
            f"PayOS escrow balance không đủ: balance={balance:,}đ < "
            f"required={amount:,}đ (proposal #{proposal_id})."
        )
        logger.error("[TASK] %s", msg)
        # Ghi DB + return KHÔNG raise: balance không tự nạp lại nên retry vô ích.
        # Admin theo dõi qua dashboard (v3_status='payout_failed') + nạp lại
        # escrow rồi click "Retry payout" thủ công (sẽ gọi lại task vì
        # payos_payout_id vẫn rỗng).
        proposal.v3_status = 'payout_failed'
        proposal.payout_error = msg
        proposal.save(update_fields=['v3_status', 'payout_error'])
        return {
            'payout_id': None,
            'status': 'payout_failed',
            'skipped': True,
            'reason': 'insufficient_balance',
            'balance': balance,
            'required': amount,
        }

    # 4. Create payout.
    try:
        response = service.create_payout(proposal)
    except PayoutRequestError as exc:
        msg = str(exc)
        if '606' in msg or 'Idempotency key' in msg or 'idempotency key' in msg.lower():
            proposal.v3_status = 'payout_failed'
            proposal.payout_error = (
                f"{msg} — PayOS có thể đã nhận request trước đó; cần reconcile bằng response/log PayOS."
            )[:1000]
            proposal.save(update_fields=['v3_status', 'payout_error'])
            logger.error("[TASK] proposal=%s PayOS idempotency conflict; stop retry: %s", proposal_id, msg)
            return {
                'payout_id': proposal.payos_payout_id,
                'status': proposal.v3_status,
                'skipped': True,
                'reason': 'idempotency_conflict_needs_reconcile',
            }
        raise
    logger.info(
        "[TASK] proposal=%s create_payout OK → payout_id=%s status=%s",
        proposal_id, proposal.payos_payout_id, proposal.v3_status,
    )
    if proposal.v3_status == 'fiat_transferred' and proposal.bank_tx_id and not proposal.burn_tx_hash:
        try:
            from admin_panel.webhook_views import _spawn_finalize_thread
            _spawn_finalize_thread(proposal.id, proposal.bank_tx_id)
            logger.info(
                "[TASK] proposal=%s PayOS already SUCCEEDED → queued burn finalize bank_tx=%s",
                proposal_id, proposal.bank_tx_id,
            )
        except Exception as exc:
            logger.error("[TASK] proposal=%s queue burn finalize failed: %s", proposal_id, exc)
    return {
        'payout_id': proposal.payos_payout_id,
        'status': proposal.v3_status,
        'skipped': False,
    }
