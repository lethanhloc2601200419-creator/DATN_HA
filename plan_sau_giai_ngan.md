# Kế hoạch chi tiết: Chức năng "Minh chứng IPFS sau giải ngân"

Dựa trên yêu cầu, dưới đây là kế hoạch chi tiết để tích hợp tính năng upload và hiển thị minh chứng (proof) sau khi giải ngân hoàn tất.

## 1. Cập nhật Model (`admin_panel/models.py`)
Để lưu trữ dữ liệu minh chứng sau giải ngân cho từng đợt giải ngân cụ thể, ta sẽ thêm các trường vào model `DisbursementProposal`:
```python
# Trong class DisbursementProposal:
post_proof_general_desc = models.TextField(blank=True, null=True, verbose_name='Mô tả chung minh chứng sau giải ngân')
# Lưu trữ mảng JSON: [{"url": "link_anh", "desc": "Mô tả ảnh 1"}, ...]
post_proof_data = models.JSONField(blank=True, null=True, verbose_name='Dữ liệu ảnh và mô tả từng ảnh')
post_proof_ipfs_cid = models.CharField(max_length=255, blank=True, null=True, verbose_name='IPFS CID minh chứng sau giải ngân')
```
*Lưu ý: Sau khi thêm trường, cần chạy lệnh `python manage.py makemigrations` và `python manage.py migrate`.*

## 2. API Upload Minh chứng (`admin_panel/views.py` & `urls.py`)
Tạo một endpoint mới để xử lý form upload minh chứng:
- **Tên View:** `upload_post_disbursement_proof(request, proposal_id)`
- **Logic xử lý:**
  1. Kiểm tra quyền truy cập (chỉ cho phép Admin/Supervisor hoặc người tạo chiến dịch).
  2. Lấy `general_desc` từ request.
  3. Lặp qua các file ảnh được upload:
     - Tải ảnh lên Cloudinary (hoặc lưu local tạm thời).
     - Lấy `description` tương ứng cho từng ảnh.
  4. Gói tất cả dữ liệu (link ảnh + mô tả từng ảnh + mô tả chung) thành một chuỗi JSON.
  5. Gọi API của Pinata (`pinata.cloud/pinning/pinJSONToIPFS` hoặc ghi ra file `.json` rồi gọi `pinFileToIPFS`) để lưu bất biến dữ liệu này trên IPFS và lấy về `ipfs_cid`.
  6. Lưu `post_proof_general_desc`, `post_proof_data`, `post_proof_ipfs_cid` vào record `DisbursementProposal` tương ứng.
- **Cập nhật:** Đăng ký URL cho view này trong `admin_panel/urls.py`.

## 3. Cập nhật UI Quản lý Giải ngân (`admin_panel/templates/admin_panel/quanly_giaingan.html`)
- **Nút Hành động:** Trong bảng danh sách `proposals`, ở cột thao tác, nếu `item.obj.v3_status == 'completed_audited'`, hiển thị thêm nút **"Up minh chứng IPFS"**.
- **Modal Form (Giao diện chuẩn):**
  - Khi click vào nút, mở Modal (ví dụ `#postProofModal_{{ item.obj.id }}`).
  - Form sẽ có:
    - Textarea: "Mô tả chung cho minh chứng".
    - Input File (`multiple`): Cho phép chọn nhiều ảnh.
    - **Tương tác JavaScript:** Khi chọn file, JavaScript sẽ generate ra giao diện preview các ảnh đã chọn. Dưới mỗi preview sẽ có một input text để điền "Mô tả cho ảnh này".
  - Nút "Xác nhận & Upload" có tích hợp spinner loading trong lúc đợi gọi Pinata và Cloudinary.

## 4. Cập nhật UI Trang Chi tiết Chiến dịch (`client/templates/client/chitiet_chiendich.html`)
- **Hiển thị Số tiền đã giải ngân & Còn lại:**
  - Cập nhật phần sidebar (phía dưới thanh Progress Bar):
    - **Tổng số tiền đã giải ngân:** Dùng `campaign.disbursed_amount` hoặc tính tổng (`sum`) của các `proposal` đã `executed`.
    - **Số tiền còn lại trong quỹ:** `campaign.current_amount - campaign.disbursed_amount`.
- **Phần "Minh chứng sau giải ngân":**
  - Thêm một Section mới ở dưới phần Lịch sử giải ngân.
  - Lặp qua các đợt giải ngân đã hoàn tất (`campaign.proposals` có trạng thái `completed_audited`) mà có chứa `post_proof_data` hoặc `post_proof_ipfs_cid`.
  - Thiết kế hiển thị cho mỗi đợt:
    - Card header: Tên đợt giải ngân & Link tra cứu IPFS CID.
    - Card body: 
      - Đoạn văn text "Mô tả chung".
      - Dưới đó là lưới Grid hiển thị các ảnh (từ `post_proof_data`).
      - Dưới mỗi ảnh hiển thị đoạn mô tả tương ứng đính kèm của ảnh đó (nếu có).
