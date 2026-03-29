"""doantn URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf.urls.static import static
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from admin_panel import views as admin_views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin_panel/', include('admin_panel.urls')),

    # --- Google OAuth callback (root level to match Google Cloud Console) ---
    path('accounts/google/login/callback/', admin_views.google_callback, name='google_callback'),

    # --- CLIENT (TRANG CHỦ) ---
    # Sửa 'client/' thành '' (rỗng) để nó làm trang chủ mặc định
    path('', include('client.urls')), 
]

# --- CẤU HÌNH ĐỂ HIỂN THỊ ẢNH MEDIA (QUAN TRỌNG) ---
# Nếu thiếu đoạn này, ảnh upload lên sẽ không xem được
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)