
from django.urls import path
from admin_panel import views as admin
from admin_panel import webhook_views

app_name = 'admin_panel'
urlpatterns = [
    # ========== [V2] PayOS Payout webhook — platform-wide checksum ==========
    # Endpoint MỚI theo spec: POST /webhook/payos/payout/ (ở root level qua
    # doantn/urls.py + alias dưới /admin/ để tiện expose). Verify HMAC bằng
    # PAYOS_CHECKSUM_KEY platform-wide. Endpoint V3 cũ
    # (api/webhook/payos-payout/) verify per-organization vẫn giữ nguyên.
    path('webhook/payos/payout/', webhook_views.payos_payout_webhook,
         name='payos_payout_webhook_v2'),
    # Backward-compat: PayOS dashboard có thể trỏ về URL V3 cũ — proxy về V2
    # handler để không phải đổi config bên PayOS dashboard.
    path('webhook/payos/payout/legacy/', webhook_views.payos_payout_webhook_legacy_proxy,
         name='payos_payout_webhook_legacy_proxy'),

    # ========== [V3] 2-layer disbursement (EIP-712 + PayOS + burn) ==========
    # Đưa lên đầu để tránh bị catch bởi các route khác (như (?P<url>.*)$).
    # Phase 2: FE lấy EIP-712 payload để ký → POST signature về backend.
    path('api/v3/disbursement/<int:pk>/sign-payload/', admin.sign_payload_v3,
         name='sign_payload_v3'),
    path('api/v3/disbursement/<int:pk>/submit-signature/', admin.submit_signature_v3,
         name='submit_signature_v3'),
    # Phase 3a: Admin relayer submit 3 sigs lên smart3.
    path('api/v3/disbursement/<int:pk>/relay-multisig/',
         admin.v3_execute_multisig_relayer, name='v3_execute_multisig_relayer'),
    # Phase 3b: Admin trigger PayOS payout.
    path('api/v3/disbursement/<int:pk>/trigger-payout/',
         admin.v3_trigger_payos_payout, name='v3_trigger_payos_payout'),
    # Phase 4: PayOS payout webhook (uses org's checksum key)
    path('api/webhook/payos-payout/', admin.v3_payos_payout_webhook,
         name='payos_payout_webhook'),
    path('api/v3/disbursement/<int:pk>/simulate-webhook/',
         admin.v3_simulate_webhook, name='v3_simulate_webhook'),
    # [V3] PayOS return/cancel PUBLIC pages (không @login_required) — tránh PayOS
    # success page crash khi URL trả 302 redirect về login.
    path('giaingan/payos/<int:pk>/return/', admin.v3_payout_return,
         name='v3_payout_return'),
    path('giaingan/payos/<int:pk>/cancel/', admin.v3_payout_cancel,
         name='v3_payout_cancel'),

    path('trangchu/', admin.trangchu, name='trangchu'),
    path('dangnhap/', admin.dangnhap, name='dangnhap'),
    path('dangky/', admin.dangky, name='dangky'),

    # Đăng xuất (Mới)
    path('dangxuat/', admin.dangxuat, name='dangxuat'),
    #chức năng
    path('quanlydanhmuc/', admin.quanlydanhmuc, name='quanlydanhmuc'),
    path('danhmuc/toggle/<int:id>/', admin.toggle_category, name='toggle_category'),
    path('quanlytochuc', admin.quanlytochuc, name='quanlytochuc'),
    path('tochuc/them/', admin.them_tochuc, name='them_tochuc'),
    path('tochuc/sua/<int:pk>/', admin.sua_tochuc, name='sua_tochuc'),
    path('tochuc/khoa/<int:pk>/', admin.khoa_tochuc, name='khoa_tochuc'), # Chức năng Ẩn/Hiện
    path('tochuc/xoa/<int:pk>/', admin.xoa_tochuc, name='xoa_tochuc'),   # Chức năng Xóa vĩnh viễn
    path('quanlychuongtrinh/', admin.quanlychuongtrinh, name='quanlychuongtrinh'),
    path('chuongtrinh/them/', admin.them_chuongtrinh, name='them_chuongtrinh'),
    path('chuongtrinh/sua/<int:pk>/', admin.sua_chuongtrinh, name='sua_chuongtrinh'),
    path('chuongtrinh/khoa/<int:pk>/', admin.khoa_chuongtrinh, name='khoa_chuongtrinh'), # Ẩn/Hiện
    path('chuongtrinh/xoa/<int:pk>/', admin.xoa_chuongtrinh, name='xoa_chuongtrinh'),
    path('quanlychiendich/', admin.quanlychiendich, name='quanlychiendich'),
    path('chiendich/them/', admin.them_chiendich, name='them_chiendich'),
    path('chiendich/sua/<int:pk>/', admin.sua_chiendich, name='sua_chiendich'),
    # Các nút hành động: Duyệt, Hủy, Xóa
    path('chiendich/duyet/<int:pk>/', admin.duyet_chiendich, name='duyet_chiendich'),
    path('chiendich/nap-pool/', admin.nap_pool, name='nap_pool'),
    path('chiendich/huy/<int:pk>/', admin.huy_chiendich, name='huy_chiendich'),
    path('chiendich/xoa/<int:pk>/', admin.xoa_chiendich, name='xoa_chiendich'),
    path('quan-ly-quyen-gop/', admin.quanly_quyengop, name='quanly_quyengop'),
    path('sua-quyen-gop/<int:pk>/', admin.sua_quyengop, name='sua_quyengop'),

    # Giải ngân
    path('giaingan/', admin.quanly_giaingan, name='quanly_giaingan'),
    path('giaingan/them/', admin.tao_yeucau_giaingan, name='tao_yeucau_giaingan'),
    # [V3] Cổng thông tin dành riêng cho Giám sát viên (3rd party).
    # Chỉ user có ví trùng `supervisorWallet()` on-chain mới vào được.
    path('giamsat/giaingan/', admin.giamsat_giaingan, name='giamsat_giaingan'),
    path('api/ipfs/upload/', admin.ipfs_upload_view, name='ipfs_upload_view'),
    path('api/disbursement/approve/', admin.sync_disbursement_approval, name='sync_disbursement_approval'),
    path('giaingan/duyet/<int:pk>/', admin.duyet_giaingan, name='duyet_giaingan'),
    path('giaingan/sync-onchain/<int:pk>/', admin.sync_disbursement_onchain, name='sync_disbursement_onchain'),
    path('giaingan/huy/<int:pk>/', admin.huy_giaingan, name='huy_giaingan'),
    path('giaingan/thu-hoi-gas/', admin.thu_hoi_gas, name='thu_hoi_gas'),
]
