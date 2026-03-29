
from django.urls import path
from client import views as client

app_name = 'client' 
urlpatterns = [
    path('', client.trangchu, name='trangchu'),
    path('gioithieu/', client.gioithieu, name='gioithieu'),
    path('ung-ho/<int:pk>/', client.ungho, name='ungho'),
    
    # Trang cảm ơn sau khi ủng hộ xong
    path('cam-on/<int:pk>/', client.camon, name='camon'),
    path('sao-ke-minh-bach/', client.saoke, name='saoke'),
    path('vnpay_return/', client.vnpay_return, name='vnpay_return'),
    path('chien-dich/<int:pk>/', client.chitiet_chiendich, name='chitiet_chiendich'),
    path('ban-do-thien-nguyen/', client.ban_do_page, name='ban_do_thien_nguyen'),
    path('chuong-trinh/<int:program_id>/', client.chitiet_chuongtrinh, name='chitiet_chuongtrinh'),
    path('chien-dich/<int:campaign_id>/vote/<int:proposal_id>/', client.vote_proposal, name='vote_proposal'),
    path('bien-dong-so-du/', client.biendong_sodu, name='biendong_sodu'),

    # =====================================================
    # API: Webhook & Thống kê tài chính
    # =====================================================
    path('api/webhook/bank-statement/', client.api_webhook_bank_statement, name='api_webhook_bank_statement'),
    path('api/mock/bank-statement/', client.api_mock_bank_statement, name='api_mock_bank_statement'),
    path('api/campaigns/<int:campaign_id>/finance/', client.api_campaign_finance, name='api_campaign_finance'),
    path('api/donations/confirm/', client.api_confirm_donation, name='api_confirm_donation'),
]
