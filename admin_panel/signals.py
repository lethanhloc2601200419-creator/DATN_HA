"""
Signals for auto-syncing Campaign to Sepolia blockchain (DCPManager v4).

Flow:
  1. `pre_save` ghi lại status cũ (`_original_status`) lên instance để phát hiện
     transition sang 'active'.
  2. `post_save` check:
       • Campaign mới tạo với status='active', HOẶC
       • Campaign existing vừa chuyển status sang 'active'
     → nếu chưa is_onchain thì spawn `threading.Thread` chạy `sync_single_campaign`
       trong background (vì RPC sepolia thường mất 10-15s).

Tại sao dùng threading thay vì Celery/RQ?
  Dự án hiện chưa có message broker; threading daemon đủ nhẹ cho một tx/lần
  duyệt. Nếu sau này scale lên thì thay handler bằng `.delay()` của Celery.
"""
import threading

from django.db import transaction
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from admin_panel.models import Campaign
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
