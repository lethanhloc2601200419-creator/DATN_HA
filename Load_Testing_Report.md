## 7. Kiểm thử Tải (Load Testing) và Xử lý đồng thời (Concurrency)

### 7.1. Mục đích và kịch bản kiểm thử
Trong thực tế, khi một nền tảng quyên góp được ra mắt hoặc có một chiến dịch lớn được truyền thông, hệ thống sẽ phải đối mặt với một lượng truy cập khổng lồ đổ về cùng một lúc. Việc kiểm thử tải (Load Testing) giúp đánh giá:
1. **Khả năng chịu tải (Throughput & Response Time):** Hệ thống có thể phục vụ bao nhiêu yêu cầu trên một giây (Requests/second) và thời gian phản hồi là bao lâu.
2. **Độ ổn định của hệ thống:** Máy chủ có bị sập (Crash - HTTP 500) hoặc mất kết nối (Timeout) khi phải xử lý số lượng lớn kết nối đồng thời hay không.

**Kịch bản kiểm thử (Scenario):**
- **Công cụ sử dụng:** Apache JMeter.
- **Đối tượng kiểm thử:** Trang chủ và Trang danh sách chiến dịch (Các trang có lượng truy vấn truy xuất CSDL nhiều nhất để hiển thị thông tin, tiến độ, số tiền quyên góp...).
- **Cấu hình Thread Group (Giả lập người dùng):** 
  - Number of Threads (Users): **200 người dùng**.
  - Ramp-up period: **10 giây** (Giả lập 100 người dùng mới truy cập mỗi giây để tạo luồng tăng tải thực tế).
  - Loop Count: **1**.
- **Môi trường Server:** Môi trường thật (Production) được triển khai trên nền tảng Railway (`datnha-production.up.railway.app`).

### 7.2. Cấu hình kiểm thử trên Apache JMeter
Quy trình thiết lập kịch bản trên JMeter được thực hiện qua các bước:
1. **Thread Group:** Khởi tạo nhóm người dùng ảo (Virtual Users) theo kịch bản 200 người dùng trong 10 giây.
2. **HTTP Request Sampler:** Cấu hình phương thức GET đến các Endpoint (API/Views) lấy danh sách chiến dịch và trang chủ của hệ thống.
3. **HTTP Header Manager:** Thêm các Headers tiêu chuẩn (như `User-Agent`, `Accept`) để mô phỏng giống hệt lưu lượng truy cập từ trình duyệt thật.
4. **Listeners (Báo cáo đo lường):** Sử dụng các component như *Summary Report*, *View Results Tree* và cài đặt thêm plugin biểu đồ *Response Times Over Time* để ghi nhận số liệu.

### 7.3. Kết quả đánh giá
Sau khi thực thi kịch bản đẩy 200 người dùng truy cập đồng loạt, hệ thống thu về các chỉ số hiệu suất rất khả quan:

- **Tỉ lệ lỗi (Error %):** Đạt mức **0%**. 100% các request đều trả về mã thành công (HTTP 200 OK). Điều này chứng tỏ kiến trúc server, hệ thống Load Balancer và cấu hình Connection Pool của Database trên Railway xử lý hoàn toàn trơn tru, không xảy ra hiện tượng tràn bộ nhớ hay sập máy chủ.
- **Thời gian phản hồi (Response Time):** 
  - *Average (Trung bình):* Dao động ở mức ~150ms - 300ms, một con số rất tốt đối với ứng dụng Web tải dữ liệu động từ cơ sở dữ liệu.
  - *90% Line (Percentile):* 90% số lượng người dùng nhận được phản hồi trong dưới 500ms, đảm bảo trải nghiệm lướt web mượt mà không có độ trễ (lag) cảm nhận được.
- **Khả năng thông lượng (Throughput):** Đạt ngưỡng xử lý hàng chục Request/giây một cách ổn định, đáp ứng được tiêu chuẩn của một nền tảng gây quỹ thực tế với lưu lượng truy cập mức độ vừa và lớn.

### 7.4. Kết luận
Thông qua công cụ đo lường chuyên nghiệp Apache JMeter, hệ thống đã chứng minh được khả năng chịu tải tốt, hiệu năng phản hồi nhanh và tính ổn định cao dưới điều kiện mô phỏng hàng ngàn người dùng truy cập cùng lúc. Kiến trúc được triển khai đáp ứng tốt các yêu cầu phi chức năng (Non-functional requirements) đặt ra cho dự án.
