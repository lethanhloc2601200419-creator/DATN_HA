
from django.urls import path
from admin_panel import views as admin

app_name = 'admin_panel' 
urlpatterns = [
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
    path('giaingan/duyet/<int:pk>/', admin.duyet_giaingan, name='duyet_giaingan'),
    path('giaingan/huy/<int:pk>/', admin.huy_giaingan, name='huy_giaingan'),
]
