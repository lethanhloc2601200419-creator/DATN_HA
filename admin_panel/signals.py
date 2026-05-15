"""
Signals for auto-syncing Campaign to Sepolia blockchain (DCPManager v4) +
auto-trigger PayOS payout khi DisbursementProposal đủ multisig confirmation.

Flow Campaign:
  1. `pre_save` ghi lại status cũ (`_original_status`) lên instance để phát hiện
     transition sang 'active'.
  2. `post_save` check:
       • Campaign mới tạo với status='active', HOẶC
       • Campaign existing vừa chuyển status sang 'active'
     → nếu chưa is_onchain thì spawn `threading.Thread` chạy `sync_single_campaign`
       trong background (vì RPC sepolia thường mất 10-15s).

Flow DisbursementProposal (V3):
  1. `pre_save` ghi lại v3_status cũ (`_original_v3_status`).
  2. `post_save` check transition sang 'ready_to_payout' (đã có 3 sig +
     multisig_confirmed_tx_hash) → fire `trigger_payos_payout.delay(proposal_id)`.
     Task tự idempotency-check qua proposal.payos_payout_id, nên admin click
     button "Trigger Payout" thủ công vẫn an toàn (chỉ chạy 1 lần).
     Disable bằng settings.V3_AUTO_TRIGGER_PAYOUT = False khi muốn admin
     control 100% manual.
"""
import threading

from django.conf import settings
from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from admin_panel.models import Campaign, DisbursementProposal
from admin_panel.blockchain_utils import sync_single_campaign


# Sentinel để phân biệt "chưa load từ DB" với "status=None"
_UNSET = object()


@receiver(pre_save, sender=Campaign)
def _cache_original_status(sender, instance, **kwargs):
    """
    Ghi lại status cũ (đọc từ DB) lên instance để `post_save` biết có phải
    transition sang 'active' không. Với instance mới (chưa có pk) thì set
    sentinel để phân biệt với update.
    """
    if not instance.pk:
        instance._original_status = _UNSET
        return
    try:
        old = Campaign.objects.only('status').get(pk=instance.pk)
        instance._original_status = old.status
    except Campaign.DoesNotExist:
        instance._original_status = _UNSET


@receiver(post_save, sender=Campaign)
def _auto_sync_campaign_to_blockchain(sender, instance, created, **kwargs):
    """
    Trigger background sync nếu:
      • Campaign mới tạo và status='active', HOẶC
      • Campaign existing vừa chuyển status từ khác → 'active'.
    Và campaign CHƯA on-chain (is_onchain=False).
    """
    # Opt-out: các call-site đã tự chạy sync đồng bộ (views._sync_campaign_to_blockchain)
    # có thể set `instance._skip_auto_sync = True` trước khi save để tránh
    # double-sync race (signal thread + synchronous RPC cùng gọi createCampaign).
    if getattr(instance, '_skip_auto_sync', False):
        return

    # Điều kiện 1: status phải là 'active' (trạng thái được duyệt)
    if instance.status != 'active':
        return

    # Điều kiện 2: chưa được sync lên on-chain
    if instance.is_onchain and instance.blockchain_tx_hash:
        return

    # Điều kiện 3: là campaign mới tạo HOẶC vừa transition sang 'active'
    original_status = getattr(instance, '_original_status', _UNSET)
    is_transition_to_active = (
        created
        or original_status is _UNSET
        or original_status != 'active'
    )
    if not is_transition_to_active:
        return

    # Chạy nền để không block request Django Admin (RPC ~10-15s trên Sepolia).
    # daemon=True để thread không chặn process shutdown.
    campaign_id = instance.pk

    def _spawn_thread():
        thread = threading.Thread(
            target=_run_sync_in_background,
            args=(campaign_id,),
            daemon=True,
            name=f'sync-campaign-{campaign_id}',
        )
        thread.start()

    # Dùng `transaction.on_commit` để đảm bảo thread chỉ start SAU khi transaction
    # ngoài đã commit. Nếu không có transaction đang mở, callback chạy ngay lập tức.
    # Lợi ích:
    #   • Thread đọc được campaign từ DB (không bị stale vì chưa commit)
    #   • Nếu transaction rollback → không spawn thread (không tạo on-chain ma)
    transaction.on_commit(_spawn_thread)


def _run_sync_in_background(campaign_id):
    """
    Wrapper gọi `sync_single_campaign` trong thread. Đảm bảo connection DB
    của thread mới được đóng sau khi xong (Django best-practice cho thread).
    """
    from django.db import connection
    try:
        sync_single_campaign(campaign_id)
    except Exception as exc:
        # sync_single_campaign vốn đã swallow exception, nhưng defensive log
        # thêm một lớp để không bao giờ crash background thread.
        print(f"❌ [SIGNAL] Background sync campaign #{campaign_id} gặp lỗi ngoài dự kiến: {exc}")
    finally:
        # Đóng DB connection của thread phụ để tránh leak (Django mở connection
        # theo thread-local, không auto-close khi thread kết thúc).
        try:
            connection.close()
        except Exception:
            pass


# ==========================================================================
# DisbursementProposal — auto-trigger PayOS payout khi multisig confirmed.
# ==========================================================================
_PROPOSAL_UNSET = object()


@receiver(pre_save, sender=DisbursementProposal)
def _cache_original_v3_status(sender, instance, **kwargs):
    """Lưu v3_status cũ để post_save phát hiện transition."""
    if not instance.pk:
        instance._original_v3_status = _PROPOSAL_UNSET
        return
    try:
        old = DisbursementProposal.objects.only('v3_status').get(pk=instance.pk)
        instance._original_v3_status = old.v3_status
    except DisbursementProposal.DoesNotExist:
        instance._original_v3_status = _PROPOSAL_UNSET


@receiver(post_save, sender=DisbursementProposal)
def _auto_trigger_payos_payout(sender, instance, created, **kwargs):
    """
    Fire `trigger_payos_payout.delay(proposal_id)` khi:
      • v3_status vừa chuyển sang 'ready_to_payout', VÀ
      • multisig_confirmed_tx_hash đã có (Phase 3a done), VÀ
      • payos_payout_id chưa có (chưa bị task khác chiếm),
      • settings.V3_AUTO_TRIGGER_PAYOUT bật (default False để safe).

    Task tự idempotent-check thêm 1 lớp nữa, nên dù call-site khác đã trigger
    thủ công thì signal này không gây double-spend.
    """
    # Opt-out global: dev có thể tắt auto-trigger qua settings.
    if not getattr(settings, 'V3_AUTO_TRIGGER_PAYOUT', False):
        return
    # Opt-out per-instance: caller đã tự trigger thì set _skip_auto_payout=True.
    if getattr(instance, '_skip_auto_payout', False):
        return

    if instance.v3_status != 'ready_to_payout':
        return
    if not instance.multisig_confirmed_tx_hash:
        return
    if instance.payos_payout_id:
        return  # đã có payout — task hoặc admin đã chi rồi.

    original = getattr(instance, '_original_v3_status', _PROPOSAL_UNSET)
    is_transition = (
        created
        or original is _PROPOSAL_UNSET
        or original != 'ready_to_payout'
    )
    if not is_transition:
        return

    proposal_id = instance.pk

    def _spawn():
        try:
            from admin_panel.tasks.disbursement_tasks import trigger_payos_payout
            trigger_payos_payout.delay(proposal_id)
        except Exception as exc:
            print(f"❌ [SIGNAL] Không trigger được payout cho proposal #{proposal_id}: {exc}")

    transaction.on_commit(_spawn)
