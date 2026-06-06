
from django.urls import path
from client import views as client

app_name = 'client' 
urlpatterns = [
    path('', client.trangchu, name='trangchu'),
    path('gioithieu/', client.gioithieu, name='gioithieu'),
    path('ung-ho/<int:pk>/', client.ungho, name='ungho'),
    path('thanh-toan/payos/<int:donation_id>/return/', client.payos_return, name='payos_return'),
    path('thanh-toan/payos/<int:donation_id>/cancel/', client.payos_cancel, name='payos_cancel'),
    
    # Trang cảm ơn sau khi ủng hộ xong
    path('cam-on/<int:pk>/', client.camon, name='camon'),
    path('sao-ke-minh-bach/', client.saoke, name='saoke'),
    path('chien-dich/<int:pk>/', client.chitiet_chiendich, name='chitiet_chiendich'),
    path('ban-do-thien-nguyen/', client.ban_do_page, name='ban_do_thien_nguyen'),
    path('chuong-trinh/<int:program_id>/', client.chitiet_chuongtrinh, name='chitiet_chuongtrinh'),
    path('chien-dich/<int:campaign_id>/vote/<int:proposal_id>/', client.vote_proposal, name='vote_proposal'),
    path('bien-dong-so-du/', client.biendong_sodu, name='biendong_sodu'),

    # =====================================================
    # API: Webhook & Thống kê tài chính
    # =====================================================
    path('api/auth/web3-login/', client.api_web3_login, name='api_web3_login'),
    path('api/auth/wallet-sync/', client.api_wallet_sync, name='api_wallet_sync'),
    path('api/webhook/payos/', client.payos_webhook_view, name='payos_webhook'),
    path('api/webhook/bank-statement/', client.api_webhook_bank_statement, name='api_webhook_bank_statement'),
    path('api/mock/bank-statement/', client.api_mock_bank_statement, name='api_mock_bank_statement'),
    path('api/campaigns/<int:campaign_id>/finance/', client.api_campaign_finance, name='api_campaign_finance'),
    path('api/donations/confirm/', client.api_confirm_donation, name='api_confirm_donation'),
    path('api/donations/<int:donation_id>/blockchain-status/', client.api_donation_blockchain_status, name='api_donation_blockchain_status'),
    path('api/donations/<int:donation_id>/retry-blockchain/', client.api_retry_donation_blockchain, name='api_retry_donation_blockchain'),
    
    path('to-chuc/', client.tochuc_list, name='tochuc_list'),
    path('to-chuc/sua-ho-so/', client.tochuc_edit_pending, name='tochuc_edit_pending'),
    path('to-chuc/huy-ho-so/', client.tochuc_cancel_pending, name='tochuc_cancel_pending'),
    path('dang-ky-to-chuc/', client.guest_register_organization, name='guest_register_organization'),
    path('to-chuc/<slug:slug>/', client.tochuc_detail, name='tochuc_detail'),

    path('export-donation-pdf/<int:donation_id>/', client.export_donation_pdf, name='export_donation_pdf'),
    path('lich-su-quyen-gop/', client.lichsu_quyen_gop, name='lichsu_quyen_gop'),
    path('export-donation-report/', client.export_donation_report, name='export_donation_report'),
    path('ho-so/', client.profile_view, name='profile'),
]


