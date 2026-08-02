# BẢNG ĐO LƯỜNG THỜI GIAN PHẢN HỒI (PERFORMANCE METRICS)

*Mục đích: Đánh giá độ trễ của các thao tác tương tác với mạng lưới phi tập trung (Blockchain & IPFS).*

### 1. Bảng ghi nhận số liệu thực tế

| Lần đo | Ghi giao dịch lên Sepolia (giây) | Upload dữ liệu lên IPFS (giây) | Ghi chú / Trạng thái mạng |
| :---: | :---: | :---: | :--- |
| **1** | 7.58 | 3.17 | Mạng ổn định |
| **2** | 10.52 | 1.29 | Mạng ổn định |
| **3** | 8.68 | 1.83 | Mạng ổn định |
| **4** | 7.17 | 4.03 | Mạng ổn định |
| **5** | 46.26 | 2.92 | Khối (block) bị nghẽn (delay) |
| **Trung bình** | **16.04** | **2.65** | |

---

### 2. Hướng dẫn cách đo (Dành cho Tester)

*   **Thời gian ghi lên Sepolia:** 
    *   Tính từ lúc trình duyệt (hoặc server) bắt đầu gửi lệnh đẩy giao dịch lên mạng Sepolia (ví dụ lúc tạo đợt giải ngân) cho đến khi nhận được xác nhận (transaction confirmed/mined). 
    *   *Mẹo:* Bạn có thể bấm giờ thủ công hoặc xem trong logs của hệ thống / F12 console.
*   **Thời gian upload IPFS:** 
    *   Tính từ lúc nhấn nút "Upload" hoặc lưu hóa đơn/chứng từ lên IPFS cho đến khi nhận được mã CID (Content Identifier) trả về.

### 3. Nhận xét đánh giá (Dành cho Báo cáo)

*   **Sepolia Testnet:** Tốc độ xác nhận khối (block time) trung bình trên Sepolia thường dao động trong khoảng từ **12 đến 15 giây**. Nếu thời gian ghi nhận thực tế nằm trong khoảng này hoặc nhỉnh hơn một chút (do độ trễ mạng), hệ thống được đánh giá là hoạt động ổn định và đáp ứng tốt.
*   **IPFS:** Thời gian upload phụ thuộc vào dung lượng file (hình ảnh, PDF) và tình trạng của public/private node IPFS mà dự án đang sử dụng. Thông thường với file nhỏ (dưới 2MB), thời gian rơi vào khoảng **1-5 giây**.
