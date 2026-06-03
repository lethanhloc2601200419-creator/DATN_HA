# 📄 KẾ HOẠCH TRIỂN KHAI CHỨNG NHẬN QUYÊN GÓP (TAX DEDUCTION)

> **Mục tiêu:** Cung cấp file PDF chứng nhận quyên góp có mã số thuế tổ chức và bằng chứng Blockchain để người dùng có thể sử dụng cho việc giảm trừ thuế cá nhân (giả định cho đồ án).

---

## 📝 DANH SÁCH CÔNG VIỆC (PROGRESS)

### 1. Database & Model Updates
- [x] **[1.1]** Thêm trường `tax_id` (Mã số thuế) vào model `Organization`. ✅
- [x] **[1.2]** Thực hiện migration để cập nhật DB. ✅
- [x] **[1.3]** Gán mã số thuế giả định cho Tổ chức có ID = 8. ✅

### 2. Backend - PDF Generation
- [x] **[2.1]** Cài đặt thư viện `xhtml2pdf` và cập nhật `requirements.txt`. ✅
- [x] **[2.2]** Tạo mẫu Certificate HTML (`donation_certificate_pdf.html`) với đầy đủ thông tin: ✅
    - Tên tổ chức, MST, Địa chỉ.
    - Tên người ủng hộ (hoặc Ví ẩn danh).
    - Số tiền, Ngày giờ, TxHash Blockchain.
    - Chữ ký & Dấu mộc (mock image).
- [x] **[2.3]** Viết View `export_donation_pdf` xử lý xuất file. ✅
- [x] **[2.4]** Cấu hình URL cho việc tải file. ✅

### 3. Frontend Integration
- [x] **[3.1]** Thêm nút "Tải Chứng Nhận (PDF)" tại trang `payment_success.html`. ✅
- [x] **[3.2]** Xây dựng trang "Lịch sử quyên góp cá nhân" (`/lich-su-quyen-gop/`). ✅
- [x] **[3.3]** Thêm bộ lọc thời gian (Từ ngày - Đến ngày) để tra cứu. ✅
- [x] **[3.4]** Chức năng "Xuất Báo Cáo Tổng Hợp (PDF)" cho khoảng thời gian đã chọn. ✅

### 4. Validation & Testing
- [ ] **[4.1]** Kiểm tra hiển thị PDF (tiếng Việt, định dạng, ảnh con dấu).
- [ ] **[4.2]** Kiểm tra logic ẩn danh (hiện ví thay tên trên PDF).
- [ ] **[4.3]** Final Review.

---

## 📊 TRẠNG THÁI HIỆN TẠI
- **Đang thực hiện:** Bước 4 (Kiểm thử cuối cùng).
- **Hoàn thành:** 90%.
