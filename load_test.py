import requests
import threading
from concurrent.futures import ThreadPoolExecutor
# --- CẤU HÌNH THÔNG SỐ TEST ---
BASE_URL = 'https://web-production-9c2ee.up.railway.app' # Thay đổi cổng nếu server bạn chạy cổng khác (vd: 8080)
LOGIN_URL = f'{BASE_URL}/admin/dangnhap/' # Đường dẫn form đăng nhập
DONATE_URL = f'{BASE_URL}/ung-ho/58/' # Đổi số 1 thành ID chiến dịch đang mở (Active) trong DB của bạn
USERNAME = 'locwara10'      # Điền tên đăng nhập của bạn vào đây
PASSWORD = 'j1001656592302'          # Điền mật khẩu vào đây
CONCURRENT_REQUESTS = 30  # Số người bấm nút "Quyên góp" CÙNG MỘT LÚC
# Khởi tạo một phiên (Session) để lưu trữ Cookie và CSRF Token như trình duyệt thật
session = requests.Session()
def login():
        print("1. Đang truy cập trang đăng nhập để lấy CSRF Token...")
        session.get(LOGIN_URL)
        csrftoken = session.cookies.get('csrftoken')

        print("2. Đang gửi request đăng nhập...")
        login_data = {
            'username': USERNAME,
            'password': PASSWORD,
            'csrfmiddlewaretoken': csrftoken,
        }

        res = session.post(LOGIN_URL, data=login_data, headers={'Referer': LOGIN_URL})

        if 'sessionid' in session.cookies:
            print("✅ Đăng nhập giả lập THÀNH CÔNG!\n")
            return True
        else:
            print(f"❌ Đăng nhập THẤT BẠI. Mã lỗi (Status code): {res.status_code}")
            if res.status_code == 403:
                print("👉 Lỗi bảo mật CSRF (Thường do sai link Referer hoặc Token bị rớt).")
            elif "Tên đăng nhập hoặc mật khẩu không đúng" in res.text:
                print("👉 Lỗi: Sai Username hoặc Password thật!")
            return False
def send_donation_request(request_id):
    csrftoken = session.cookies.get('csrftoken')
    # Payload giống hệt lúc ấn submit form /ung-ho/
    data = {
        'amount': '50000', # 50,000 VNĐ
        'message': f'Load testing request #{request_id}',
        'payment_method': 'payos',
        'csrfmiddlewaretoken': csrftoken
    }
    try:
        # Bắn request POST giả lập người dùng
        res = session.post(DONATE_URL, data=data, headers={'Referer': DONATE_URL}, timeout=120)
        # HTTP 302 (Redirect) thường nghĩa là tạo đơn thành công và đang chuyển hướng sang trang mã QR / Cảm ơn
        if res.status_code in [200, 302]:
            print(f"✅ Thread {request_id:02d}: Thành công tạo đơn! (Mã lỗi: {res.status_code})")
        elif res.status_code == 500:
            print(f"🔥 Thread {request_id:02d}: Server bị crash 500!")
        else:
            print(f"⚠️ Thread {request_id:02d}: Lỗi {res.status_code}")
    except requests.exceptions.RequestException as e:
        # Nếu server không chịu tải nổi, kết nối sẽ bị rớt (Connection Refused / Timeout)
        print(f"❌ Thread {request_id:02d}: Server sập hoặc không phản hồi (Timeout)!")
if __name__ == "__main__":
    print(f"=== BẮT ĐẦU KIỂM THỬ TẢI (TẠO ĐƠN HÀNG) ===")
    if login():
        print(f"3. Chuẩn bị bắn {CONCURRENT_REQUESTS} request TẠO ĐƠN HÀNG cùng lúc...")
        # Dùng ThreadPoolExecutor để chạy song song 50 request (concurrency)
        with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as executor:
            for i in range(CONCURRENT_REQUESTS):
                executor.submit(send_donation_request, i)
        print("\n=== HOÀN TẤT KIỂM THỬ TẢI ===")
        print("Bạn hãy mở trang Admin để kiểm tra xem có đúng 50 đơn hàng mới được tạo hay không.")