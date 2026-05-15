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
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include
from admin_panel import views as admin_views
from admin_panel import webhook_views as admin_webhook_views


urlpatterns = [
    path('admin/', include('admin_panel.urls')),

    # --- Google OAuth callback (root level to match Google Cloud Console) ---
    path('accounts/google/login/callback/', admin_views.google_callback, name='google_callback'),

    # --- [V2] PayOS Payout webhook (root-level, đúng spec) ---
    # Spec yêu cầu URL: POST /webhook/payos/payout/. Mount root-level (không
    # qua /admin/) vì PayOS dashboard thường config webhook URL public.
    path('webhook/payos/payout/', admin_webhook_views.payos_payout_webhook,
         name='payos_payout_webhook_root'),

    # --- CLIENT (TRANG CHỦ) ---
    # Sửa 'client/' thành '' (rỗng) để nó làm trang chủ mặc định
    path('', include('client.urls')), 
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static('/campaigns/', document_root=settings.BASE_DIR / 'campaigns')
    urlpatterns += staticfiles_urlpatterns()
# urls.py — thêm tạm để debug
import requests
from django.http import JsonResponse

def my_ip(request):
    r = requests.get("https://api.ipify.org?format=json")
    return JsonResponse(r.json())