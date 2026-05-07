from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_panel'

    def ready(self):
        # Import signals để Django wire các receiver (pre_save/post_save)
        # tự động khi app load. KHÔNG xóa dòng này — nếu bỏ, auto-sync
        # Campaign → blockchain sẽ không hoạt động.
        from admin_panel import signals  # noqa: F401
