# 🛡️ Tài liệu Kỹ thuật: Chức năng Ủng hộ Ẩn danh (Anonymous Donation)

## 1. Mục tiêu
Cho phép người dùng đã đăng nhập (Google/Email) thực hiện quyên góp mà không hiển thị danh tính cá nhân (Tên, Email) trên các nền tảng công khai như:
- Trang Sao kê (Public Ledger).
- Giao diện thanh toán PayOS (Buyer Information).
- Lịch sử đóng góp công khai của chiến dịch.

## 2. Cơ chế Masking Dữ liệu (Data Masking)
Khi người dùng bật chế độ **"Ủng hộ ẩn danh"**, hệ thống sẽ thực hiện tráo đổi thông tin trước khi gửi đi:

| Trường dữ liệu | Trạng thái Công khai | Trạng thái Ẩn danh |
| :--- | :--- | :--- |
| `donor_name` | Tên từ Profile/Google | "Mạnh thường quân" |
| `donor_email` | Email thật của User | `[địa_chỉ_ví]@anonymous.fund` |
| `is_anonymous` | `False` | `True` |

*Lưu ý: Địa chỉ ví được lấy từ `request.user.profile.smart_account_address` hoặc `wallet_address`. Nếu không có ví, sẽ dùng một chuỗi hash định danh duy nhất dựa trên User ID.*

## 3. Quy trình thực hiện (Workflow)

### Bước 1: Frontend (ungho.html)
- Thêm một `input type="checkbox"` (dạng toggle switch) với name `is_anonymous`.
- Hiển thị cảnh báo: *"Khi chọn ẩn danh, thông tin cá nhân của bạn sẽ được bảo mật trên PayOS và trang sao kê."*

### Bước 2: Backend xử lý Form (client/views.py -> ungho)
- Kiểm tra `request.POST.get('is_anonymous')`.
- Nếu `True`:
    - Gán `donation.is_anonymous = True`.
    - Gán `donation.donor_name = "Mạnh thường quân"`.
    - Tạo email ảo: `donation.donor_email = f"{wallet_address}@anonymous.fund"`.

### Bước 3: Tích hợp PayOS (client/views.py -> _create_payos_payment_link)
- Sử dụng `donation.donor_name` và `donation.donor_email` đã được xử lý ở Bước 2 để truyền vào payload gửi sang PayOS.
- Điều này đảm bảo trên sao kê ngân hàng/PayOS chỉ hiện thông tin đã che.

### Bước 4: Hiển thị Sao kê (client/templates/client/saoke.html)
- Kiểm tra `item.is_anonymous`.
- Hiển thị "Mạnh thường quân" thay cho tên thật (Logic này đã có sẵn, cần kiểm tra lại độ ổn định).

## 4. Bảo mật & Đối soát
- **Admin Panel:** Admin vẫn có thể xem được `donor` thực sự (liên kết tới bảng User) để hỗ trợ khi có khiếu nại hoặc đối soát tài chính.
- **User Dashboard:** Người dùng vẫn thấy giao dịch này trong lịch sử cá nhân vì `donation.donor` vẫn được lưu đúng.
