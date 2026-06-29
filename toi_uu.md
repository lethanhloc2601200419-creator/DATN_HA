# Kế hoạch Tối ưu hoá Hiệu suất Website trên Production (Railway)

## 1. Mục tiêu
Giải quyết tình trạng web phản hồi chậm (đặc biệt khi bấm vào các trang chi tiết chiến dịch) trên môi trường production (Railway). Mọi thay đổi đảm bảo **tuyệt đối không** can thiệp hay làm hỏng bất kỳ logic nghiệp vụ nào hiện tại, đặc biệt là các chức năng liên quan đến thanh toán (PayOS, VNPay) và Web3 (Smart Contract).

## 2. Nguyên nhân gây chậm web hiện tại
- **Nghẽn cổ chai (Bottleneck) khi gọi Web3**: Hàm `get_campaign_onchain_stats` và `get_eth_vnd_rate` được gọi trực tiếp mỗi khi có user truy cập trang. Trên môi trường production, node RPC của mạng lưới Sepolia thường bị rate-limit hoặc delay dẫn đến server Django bị "treo" chờ phản hồi.
- **Cache không đồng bộ trên môi trường đa tiến trình**: Trên Railway, web được chạy bằng Gunicorn (nhiều worker). Bộ nhớ đệm tự chế bằng Dictionary (`_stats_cache`, `_rate_cache`) không được chia sẻ giữa các worker này, khiến request bị rớt ra ngoài và vẫn phải gọi lại API liên tục.
- **Lỗi tràn RAM do chế độ Debug**: Bật `DEBUG = True` trên production khiến Django lưu lại mọi câu truy vấn SQL vào bộ nhớ. Đồng thời cơ chế phục vụ file tĩnh (static files) nội bộ của Django cực kỳ chậm và tốn tài nguyên.

## 3. Các bước thực hiện chi tiết

### Bước 1: Quản lý File Tĩnh (Static Files) với WhiteNoise
- **Hành động**: Thêm thư viện `whitenoise` vào `requirements.txt`.
- **Lý do**: Khi tắt `DEBUG = False`, Django sẽ ngừng phục vụ file tĩnh. WhiteNoise giúp web render giao diện CSS/JS trên Railway với tốc độ rất nhanh, tích hợp sẵn nén gzip.

### Bước 2: Chuyển đổi Cơ chế Caching sang Database Cache của Django
- **Hành động**: 
  - Cấu hình `CACHES` trong `doantn/settings.py` để sử dụng `DatabaseCache`.
  - Không cần cài Redis phức tạp, tận dụng luôn Database Postgres đang có. Cần chạy lệnh `python manage.py createcachetable` trên Railway sau khi deploy để tạo bảng lưu cache.
- **Lý do**: Giúp tất cả các worker của Gunicorn cùng đọc và ghi chung vào một nguồn dữ liệu duy nhất. Không bị lọt request bắt API chạy lại liên tục.

### Bước 3: Cập nhật code Cache trong `client/blockchain.py`
- **Hành động**:
  - Đổi các biến `_rate_cache` và `_stats_cache` thành các lệnh gọi `django.core.cache.cache`.
  - Trong `get_eth_vnd_rate()`: Kiểm tra cache trước, nếu không có mới gọi request đến CoinGecko, sau đó lưu cache 5 phút.
  - Trong `get_campaign_onchain_stats()`: Kiểm tra cache trước, nếu không có mới gọi RPC đến Sepolia (`getCampaign`), sau đó lưu cache 2 phút.
  - Sửa logic hàm `invalidate_campaign_cache` để xóa đúng key từ django cache.
- **Lý do**: Giúp trang `chitiet_chiendich` load ngay lập tức vì data lấy thẳng từ Database/Cache của mình. Chỉ khi cache hết hạn mới tốn ~1 giây cập nhật từ Web3.

### Bước 4: Tinh chỉnh cấu hình `doantn/settings.py` cho Production
- **Hành động**:
  - Thêm `WhiteNoiseMiddleware` vào `MIDDLEWARE`.
  - Đổi `DEBUG = True` thành cấu hình lấy từ biến môi trường `DEBUG = env_bool('DEBUG', False)` (trên Railway, nếu không set biến này thì web tự động hiểu là False).
- **Lý do**: Để web chạy ở chế độ chuẩn của production, nhẹ và bảo mật hơn.

---

## 4. Kiểm thử sau khi triển khai
- Review lại toàn bộ code đã chỉnh sửa.
- Đảm bảo logic write (ví dụ: `recordDonation`, `proposeDisbursement`) KHÔNG thay đổi.
- Cuối cùng bạn chỉ việc push code lên Railway, chạy lệnh `python manage.py createcachetable` và tận hưởng web chạy cực kỳ mượt mà.
