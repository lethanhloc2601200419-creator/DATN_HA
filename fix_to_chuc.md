# Kế hoạch sửa luồng `to-chuc`

## Mục tiêu
1. Chỉ cho người dùng đã đăng nhập bằng tài khoản web nội bộ sử dụng form đăng ký tổ chức ở `/to-chuc/#dangky-section`.
2. Không cho tài khoản Google dùng form này.
3. Hồ sơ gửi từ form phải đi vào hàng chờ duyệt ở trang quản lý tổ chức của admin.
4. Trang quản lý tổ chức bỏ nút tạo tổ chức thủ công, thay bằng nút xem/duyệt hồ sơ tổ chức chờ duyệt.
5. Khi admin duyệt, hệ thống phải tạo tổ chức chính thức trong database và chuyển tài khoản người gửi thành tài khoản tổ chức.

## Phạm vi ảnh hưởng
- `client/views.py`
- `client/templates/client/tochuc_list.html`
- `client/forms.py` hoặc form đăng ký nếu cần tách validation
- `admin_panel/views.py`
- `admin_panel/templates/admin_panel/quanlytochuc.html`
- `admin_panel/models.py` nếu cần thêm field/trạng thái cho user hoặc organization
- `admin_panel/urls.py` nếu cần thêm route cho review/approve/reject
- `doantn/settings.py` hoặc lớp auth middleware/context nếu cần phân biệt tài khoản web và Google
- migrations liên quan

## Giả định hiện tại
- Tổ chức đã có model `Organization`.
- Hồ sơ KYC đã có `OrganizationRepresentative`.
- Người dùng web đang là `User` + `UserProfile`.
- Hệ thống chưa có cờ rõ ràng để phân biệt “tài khoản web nội bộ” và “tài khoản Google”, nên cần bổ sung hoặc suy ra từ dữ liệu hiện có.

## Bước 1. Chốt tiêu chí tài khoản được phép dùng form
1. Xác định cách nhận diện tài khoản web nội bộ.
2. Đánh dấu rõ tài khoản Google để chặn ở form đăng ký tổ chức.
3. Nếu chưa có field phân loại, thêm field vào profile/user:
   - Ví dụ `UserProfile.account_source` hoặc `UserProfile.is_google_account`.
4. Khi login Google, gắn cờ tương ứng.
5. Khi login/đăng ký web nội bộ, gắn cờ web account.

## Bước 2. Chặn form đăng ký tổ chức với người không hợp lệ
1. Bọc route `/to-chuc/#dangky-section` bằng `login_required`.
2. Chỉ cho phép người đã đăng nhập bằng tài khoản web nội bộ vào phần gửi hồ sơ.
3. Nếu user chưa đăng nhập:
   - redirect về trang login web.
4. Nếu user là tài khoản Google:
   - ẩn form đăng ký tổ chức.
   - hiển thị thông báo không đủ điều kiện.
5. Nếu user đã là tài khoản tổ chức hoặc đã nộp hồ sơ:
   - hiển thị trạng thái hồ sơ thay vì cho nộp lại.

## Bước 3. Chuẩn hóa dữ liệu hồ sơ gửi lên
1. Khi user submit form, lưu hồ sơ ở trạng thái `submitted`.
2. Liên kết hồ sơ với `User` gửi form.
3. Liên kết `Organization` tạm với hồ sơ nếu cần.
4. Lưu đầy đủ:
   - thông tin tổ chức
   - thông tin người đại diện
   - tài liệu pháp lý
   - trạng thái KYC
   - thời điểm gửi
5. Không tạo tổ chức “chính thức” ngay khi user mới gửi form.

## Bước 4. Đổi UI trang quản lý tổ chức
1. Bỏ nút “Thêm tổ chức mới” trên trang quản lý tổ chức.
2. Thay bằng nút “Duyệt tổ chức” hoặc “Hồ sơ chờ duyệt”.
3. Khi bấm vào nút đó:
   - mở danh sách các hồ sơ đang chờ duyệt.
4. Mỗi hồ sơ phải mở được chi tiết form:
   - thông tin tổ chức
   - người đại diện
   - giấy tờ đính kèm
   - ngân hàng / ví
5. Duyệt xong phải cập nhật trạng thái ngay trong UI.

## Bước 5. Luồng duyệt của admin
1. Admin bấm vào một hồ sơ chờ duyệt.
2. Xem toàn bộ dữ liệu đã gửi.
3. Admin có các hành động:
   - thẩm định
   - duyệt
   - từ chối
4. Khi duyệt:
   - tạo `Organization` chính thức nếu bản ghi mới chỉ là hồ sơ tạm
   - chuyển `kyc_status` sang `approved`
   - bật `is_verified = True`
   - gán `verified_at`, `kyc_reviewed_at`, `kyc_reviewed_by`
   - chuyển user gửi hồ sơ thành tài khoản tổ chức
5. Khi từ chối:
   - giữ hồ sơ ở `rejected`
   - lưu lý do từ chối
   - không tạo tổ chức chính thức

## Bước 6. Chuyển user thành tài khoản tổ chức
1. Xác định cách gắn user với tổ chức sau khi duyệt.
2. Nếu chưa có cơ chế rõ ràng, bổ sung một trong hai hướng:
   - thêm `UserProfile.account_type = 'organization'`
   - hoặc dùng quan hệ `Organization.manager = user`
3. Sau khi duyệt:
   - user có quyền truy cập khu vực tổ chức
   - hiển thị như tài khoản tổ chức trên dashboard
4. Nếu cần, tự động gắn role/permission cho user theo mô hình hiện tại của project.

## Bước 7. Đồng bộ hiển thị trên client
1. Trên `/to-chuc/`:
   - user chưa login không thấy form gửi hồ sơ
   - user login Google không dùng được form
   - user login web nội bộ mới thấy form
2. Nếu user đã nộp hồ sơ:
   - hiển thị trạng thái đang chờ duyệt / đang thẩm định / từ chối
3. Nếu user đã được duyệt:
   - hiển thị thông tin tổ chức chính thức
   - không cho gửi lại hồ sơ

## Bước 8. Cập nhật route và action
1. Tách rõ các action:
   - gửi hồ sơ
   - duyệt hồ sơ
   - từ chối hồ sơ
   - xem chi tiết hồ sơ
2. Nếu cần, thêm route riêng cho admin review.
3. Giữ URL hiện tại không vỡ link cũ nếu có thể.

## Bước 9. Kiểm thử
1. Test user chưa login:
   - không mở được form đăng ký tổ chức.
2. Test user Google:
   - đăng nhập được nhưng không dùng form tổ chức.
3. Test user web nội bộ:
   - mở được form, submit được hồ sơ.
4. Test admin:
   - thấy danh sách hồ sơ chờ duyệt.
   - mở từng hồ sơ xem đủ dữ liệu.
   - duyệt xong tổ chức được tạo và user thành tài khoản tổ chức.
5. Test từ chối:
   - hồ sơ chuyển sang rejected.
   - không tạo tổ chức chính thức.

## Bước 10. Tiêu chí nghiệm thu
1. Form đăng ký tổ chức chỉ dùng được bởi tài khoản web nội bộ đã login.
2. Tài khoản Google không thể gửi hồ sơ tổ chức.
3. Admin không còn nút tạo tổ chức thủ công trong trang quản lý tổ chức.
4. Admin có danh sách hồ sơ chờ duyệt và xem được chi tiết form.
5. Duyệt hồ sơ xong tạo được tổ chức chính thức trong DB.
6. User gửi hồ sơ được nâng quyền / chuyển loại tài khoản thành tài khoản tổ chức.

## Rủi ro cần xử lý
1. Hiện tại chưa thấy field rõ ràng để phân biệt tài khoản web và Google.
2. Có thể đang có luồng login Google cho admin, không được vô tình chặn nhầm.
3. Cần tránh tạo `Organization` 2 lần nếu user submit lại.
4. Cần giữ tương thích với dữ liệu tổ chức đã có sẵn trong DB.

## Thứ tự triển khai đề xuất
1. Bổ sung phân loại tài khoản web vs Google.
2. Chặn form đăng ký tổ chức ở client.
3. Thay giao diện quản lý tổ chức thành màn review hồ sơ.
4. Hoàn thiện luồng duyệt/từ chối.
5. Đồng bộ role tài khoản tổ chức.
6. Viết test và chạy kiểm tra.
