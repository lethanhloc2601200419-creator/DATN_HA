# 📋 UI/Frontend Inventory - Quỹ Nhân Ái

## 1. Cấu trúc thư mục Frontend

Dự án sử dụng Django làm backend với hệ thống template HTML/Django Template Language (DTL). Các file frontend tập trung tại:

- **Client-side (Người dùng):**
  - Templates: `client/templates/client/`
  - Static: `client/static/client/` (js, img)
- **Admin-side (Quản trị):**
  - Templates: `admin_panel/templates/admin_panel/`
  - Static: `admin_panel/static/admin_panel/` (js)
- **Shared/Global:**
  - `charity-design-system.md`: Tài liệu hướng dẫn design system.
  - `blockchain_assets/`: Chứa file ABI cho tương tác blockchain.
  - `campaigns/`: Hình ảnh liên quan đến các chiến dịch.

### Danh sách file quan trọng:
- `client/templates/client/base_client.html`: Layout chung của client.
- `client/templates/client/trangchu.html`: Trang chủ.
- `client/templates/client/chitiet_chiendich.html`: Chi tiết chiến dịch & Bỏ phiếu.
- `client/templates/client/ungho.html`: Form ủng hộ.
- `client/templates/client/saoke.html`: Trang sao kê minh bạch.
- `client/templates/client/biendong_sodu.html`: Biến động số dư tài chính.
- `client/templates/client/ban_do_thien_nguyen.html`: Bản đồ địa điểm thiện nguyện.
- `admin_panel/templates/admin_panel/trangchu.html`: Dashboard quản trị.

---

## 2. Global Styles

Dự án áp dụng một Design System thống nhất dựa trên CSS Variables, được định nghĩa trong `:root` của `base_client.html`.

### Color Palette (Primary: #1e3a8a)
- `--primary-800: #1e3a8a`: Màu thương hiệu chính (Buttons, Icons).
- `--primary-950: #0a1628`: Text trên nền tối, Footer background.
- `--accent-500: #f97316`: Màu cam nổi bật cho nút "Quyên góp ngay".
- `--success-600: #16a34a`: Trạng thái thành công / Đã giải ngân.
- `--danger-600: #dc2626`: Trạng thái khẩn cấp / Từ chối.
- `--neutral-900: #111827`: Màu chữ chính.
- `--white: #ffffff`: Nền chính.

### Typography
- **Font-family:** 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif (Import từ Google Fonts).
- **Font-size base:** 15px.
- **Heading scale:** H1 (32px/42px), H2 (24px), H3 (18px).

### Spacing & Shape
- --radius-md: 10px, --radius-lg: 16px.
- Shadow cards và buttons được định nghĩa qua biến --shadow-card, --shadow-btn.

---

## 3. Vấn đề UI/UX phát hiện

1. **Code trùng lặp:** CSS Variables và Base Styles được khai báo lặp lại trong `base_client.html` và `gioithieu.html`. Nên tách ra file `global.css`.
2. **Inline Style:** Còn nhiều đoạn `style="..."` trực tiếp trong template (ví dụ: `chitiet_chiendich.html`), gây khó khăn cho việc bảo trì.
3. **Accessibility:** Một số ảnh chưa có `alt` text chuẩn hoặc sử dụng `onerror` để load ảnh placeholder từ service ngoài (`placehold.co`).
4. **Responsive:** Trang admin (`admin_panel/trangchu.html`) sử dụng layout sidebar cố định `250px`, có thể gặp vấn đề trên màn hình rất nhỏ nếu không xử lý toggle sidebar.
5. **Thiếu Semantic HTML:** Một số section quan trọng vẫn dùng `<div>` thay vì `<section>`, `<article>`, `<header>` để tối ưu SEO và Accessibility.

---

## PHẦN BỔ SUNG LẦN 2
### 1. base_client.html (Toàn bộ CSS & Footer)

**1a. Footer HTML:**
```html
<footer class="pt-5 pb-3 mt-5">
    <div class="container">
        <div class="row">
            <div class="col-md-4">
                <h5 class="fw-bold text-white mb-4">Về Quỹ Nhân Ái</h5>
                <p class="small opacity-75">Nền tảng gây quỹ từ thiện minh bạch ứng dụng công nghệ Blockchain, giúp kết nối những tấm lòng vàng đến với những hoàn cảnh khó khăn một cách tin cậy nhất.</p>
                <div class="d-flex gap-3 mt-3">
                    <a href="#" class="text-white opacity-50"><i class="fab fa-facebook fa-lg"></i></a>
                    <a href="#" class="text-white opacity-50"><i class="fab fa-youtube fa-lg"></i></a>
                    <a href="#" class="text-white opacity-50"><i class="fab fa-tiktok fa-lg"></i></a>
                </div>
            </div>
            <div class="col-md-2 offset-md-1">
                <h5 class="fw-bold text-white mb-4">Liên kết</h5>
                <ul class="list-unstyled small opacity-75">
                    <li class="mb-2"><a href="{% url 'client:trangchu' %}" class="text-white text-decoration-none">Trang chủ</a></li>
                    <li class="mb-2"><a href="{% url 'client:gioithieu' %}" class="text-white text-decoration-none">Giới thiệu</a></li>
                    <li class="mb-2"><a href="{% url 'client:saoke' %}" class="text-white text-decoration-none">Sao kê</a></li>
                    <li class="mb-2"><a href="{% url 'client:ban_do_thien_nguyen' %}" class="text-white text-decoration-none">Bản đồ</a></li>
                </ul>
            </div>
            <div class="col-md-4 offset-md-1">
                <h5 class="fw-bold text-white mb-4">Liên hệ</h5>
                <p class="small opacity-75 mb-2"><i class="fas fa-map-marker-alt me-2"></i> Số 1 Đại Cồ Việt, Hai Bà Trưng, Hà Nội</p>
                <p class="small opacity-75 mb-2"><i class="fas fa-phone-alt me-2"></i> 1900 xxxx</p>
                <p class="small opacity-75 mb-2"><i class="fas fa-envelope me-2"></i> hotro@quynhanai.vn</p>
            </div>
        </div>
        <hr class="mt-5 opacity-25">
        <div class="d-flex justify-content-between align-items-center small opacity-50">
            <p class="m-0">&copy; 2026 Quỹ Nhân Ái. All rights reserved.</p>
            <p class="m-0">Powered by Blockchain Technology</p>
        </div>
    </div>
</footer>
```

**1b. Toàn bộ CSS trong <style>:**
```css
:root {
    --primary-950: #0a1628;
    --primary-900: #0f2044;
    --primary-800: #1e3a8a;
    --primary-700: #2a4fa3;
    --primary-600: #3b6ac7;
    --primary-500: #4f84e0;
    --primary-400: #7aaaf0;
    --primary-300: #a8c5f8;
    --primary-200: #d0e2fd;
    --primary-100: #e8f1fe;
    --primary-50: #f3f7ff;
    --accent-500: #f97316;
    --accent-400: #fb923c;
    --accent-100: #fff7ed;
    --success-600: #16a34a;
    --success-100: #f0fdf4;
    --danger-600: #dc2626;
    --danger-100: #fef2f2;
    --warning-600: #ca8a04;
    --warning-100: #fefce8;
    --neutral-900: #111827;
    --neutral-700: #374151;
    --neutral-500: #6b7280;
    --neutral-300: #d1d5db;
    --neutral-100: #f9fafb;
    --white: #ffffff;
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 16px;
    --radius-xl: 24px;
    --radius-full: 9999px;
    --shadow-card: 0 1px 4px rgba(30, 58, 138, 0.08), 0 0 0 0.5px rgba(30, 58, 138, 0.10);
    --shadow-btn: 0 2px 8px rgba(30, 58, 138, 0.25);
    --shadow-modal: 0 8px 32px rgba(15, 32, 68, 0.18);
    --font-sans: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif;
    --primary-color: var(--primary-800);
    --text-dark: var(--neutral-900);
    --bg-light: var(--primary-50);
}
body { font-family: var(--font-sans); background-color: var(--white); color: var(--neutral-900); }
a { color: var(--primary-600); text-decoration: none; }
a:hover { color: var(--primary-800); }
.navbar { background: var(--white); border-bottom: 1px solid var(--primary-200); box-shadow: 0 2px 10px rgba(15, 32, 68, 0.05); padding: 12px 0; }
.nav-link { font-weight: 600; color: var(--neutral-700) !important; margin: 0 10px; }
.nav-link:hover { color: var(--primary-800) !important; }
footer { background: var(--primary-950); color: var(--primary-300); padding-top: 3rem; margin-top: 3rem; }

.text-primary { color: var(--primary-600) !important; }
.text-danger { color: var(--accent-500) !important; }
.text-muted, .text-secondary { color: var(--neutral-500) !important; }
.bg-light { background-color: var(--neutral-100) !important; }
.bg-primary { background-color: var(--primary-800) !important; }
.bg-danger { background-color: var(--accent-500) !important; }
.border { border-color: var(--primary-200) !important; }
.border-primary { border-color: var(--primary-600) !important; }
.border-success { border-color: var(--success-600) !important; }
.border-danger { border-color: var(--danger-600) !important; }
.btn-primary, .btn-success {
    background: var(--primary-800);
    border-color: var(--primary-800);
    color: var(--white);
    box-shadow: var(--shadow-btn);
}
.btn-primary:hover, .btn-success:hover {
    background: var(--primary-700);
    border-color: var(--primary-700);
    color: var(--white);
}
.btn-danger, .btn-accent {
    background: var(--accent-500);
    border-color: var(--accent-500);
    color: var(--white);
}
.btn-danger:hover, .btn-accent:hover {
    background: var(--accent-400);
    border-color: var(--accent-400);
    color: var(--white);
}
.btn-warning {
    background: var(--warning-600);
    border-color: var(--warning-600);
    color: var(--white);
}
.btn-warning:hover {
    background: var(--warning-600);
    border-color: var(--warning-600);
    color: var(--white);
}
.btn-outline-primary {
    color: var(--primary-800);
    border-color: var(--primary-800);
}
.btn-outline-primary:hover {
    color: var(--white);
    background: var(--primary-700);
    border-color: var(--primary-700);
}
.btn-outline-danger {
    color: var(--primary-800);
    border-color: var(--primary-800);
}
.btn-outline-danger:hover {
    color: var(--white);
    background: var(--primary-700);
    border-color: var(--primary-700);
}
.btn-outline-secondary {
    color: var(--primary-700);
    border-color: var(--primary-200);
}
.btn-outline-secondary:hover {
    color: var(--primary-800);
    background: var(--primary-50);
    border-color: var(--primary-300);
}
.progress {
    background-color: var(--primary-100);
    border-radius: var(--radius-full);
}
.progress-bar { background-color: var(--primary-800) !important; }
.progress-bar.bg-success { background-color: var(--success-600) !important; }
.progress-bar.bg-danger { background-color: var(--danger-600) !important; }
.badge.bg-success-subtle { background-color: var(--success-100) !important; color: var(--success-600) !important; }
.badge.bg-danger-subtle { background-color: var(--danger-100) !important; color: var(--danger-600) !important; }
.form-control, .form-select, .form-textarea {
    border: 1px solid var(--neutral-300);
    border-radius: var(--radius-md);
}
.form-control:focus, .form-select:focus, .form-textarea:focus {
    border-color: var(--primary-600);
    box-shadow: 0 0 0 3px var(--primary-100);
}

/* Toast Notification System */
.toast-container {
    position: fixed;
    top: 80px;
    right: 20px;
    z-index: 9999;
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-width: 420px;
    width: 100%;
}
.toast-notification {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 16px 20px;
    border-radius: 12px;
    background: var(--white);
    box-shadow: 0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06);
    border-left: 4px solid var(--neutral-500);
    transform: translateX(120%);
    opacity: 0;
    transition: all 0.4s cubic-bezier(0.22, 1, 0.36, 1);
    cursor: pointer;
    position: relative;
    overflow: hidden;
}
.toast-notification.show {
    transform: translateX(0);
    opacity: 1;
}
.toast-notification.hide {
    transform: translateX(120%);
    opacity: 0;
}
.toast-notification .toast-icon {
    font-size: 20px;
    min-width: 24px;
    text-align: center;
    margin-top: 1px;
}
.toast-notification .toast-body {
    flex: 1;
    font-size: 14px;
    font-weight: 500;
    color: var(--neutral-900);
    line-height: 1.5;
}
.toast-notification .toast-close {
    background: none;
    border: none;
    color: var(--neutral-500);
    font-size: 18px;
    cursor: pointer;
    padding: 0;
    line-height: 1;
    transition: color 0.2s;
}
.toast-notification .toast-close:hover { color: var(--neutral-900); }
.toast-notification .toast-progress {
    position: absolute;
    bottom: 0;
    left: 4px;
    right: 0;
    height: 3px;
    border-radius: 0 0 12px 0;
    background: currentColor;
    opacity: 0.3;
    transform-origin: left;
    animation: toastProgress 5s linear forwards;
}
@keyframes toastProgress {
    from { transform: scaleX(1); }
    to { transform: scaleX(0); }
}
.toast-notification.toast-success { border-left-color: var(--success-600); }
.toast-notification.toast-success .toast-icon { color: var(--success-600); }
.toast-notification.toast-success .toast-progress { color: var(--success-600); }
.toast-notification.toast-error { border-left-color: var(--danger-600); }
.toast-notification.toast-error .toast-icon { color: var(--danger-600); }
.toast-notification.toast-error .toast-progress { color: var(--danger-600); }
.toast-notification.toast-warning { border-left-color: var(--warning-600); }
.toast-notification.toast-warning .toast-icon { color: var(--warning-600); }
.toast-notification.toast-warning .toast-progress { color: var(--warning-600); }
.toast-notification.toast-info { border-left-color: var(--primary-600); }
.toast-notification.toast-info .toast-icon { color: var(--primary-600); }
.toast-notification.toast-info .toast-progress { color: var(--primary-600); }
```
#### 2.1. gioithieu.html
```html
{% block extra_css %}
<style>
:root {
            --primary-950: #0a1628;
            --primary-900: #0f2044;
            --primary-800: #1e3a8a;
            --primary-700: #2a4fa3;
            --primary-600: #3b6ac7;
            --primary-500: #4f84e0;
            --primary-300: #a8c5f8;
            --primary-200: #d0e2fd;
            --primary-100: #e8f1fe;
            --primary-50: #f3f7ff;
            --neutral-900: #111827;
            --neutral-700: #374151;
            --neutral-500: #6b7280;
            --neutral-100: #f9fafb;
            --white: #ffffff;
        }
        /* Palette chuẩn theo design system charity */
        body { 
            font-family: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif; 
            line-height: 1.6; 
            color: var(--primary-950); 
            margin: 0; 
            padding: 0; 
            background-color: var(--white); 
        }
        
        /* Header nổi bật */
        header { 
            background: linear-gradient(120deg, var(--primary-800) 0%, var(--primary-700) 100%);
            color: var(--white); 
            padding: 80px 0; 
            text-align: center;
            clip-path: ellipse(100% 100% at 50% 0%); /* Tạo đường cong nhẹ phía dưới */
        }
        header h1 { margin: 0; font-size: 3em; font-weight: 800; text-transform: uppercase; }
        header p { font-size: 1.2em; opacity: 0.9; }

        .container { width: 90%; max-width: 1200px; margin: auto; padding: 40px 20px; }

        /* Phần sứ mệnh */
        .mission-section { 
            display: flex; 
            gap: 40px;
            align-items: center; 
            padding: 40px 0; 
        }
        .mission-text h2 { 
            color: var(--primary-800); 
            font-size: 2.2em;
            margin-bottom: 20px;
            position: relative;
        }
        .mission-text h2::after {
            content: "";
            display: block;
            width: 60px;
            height: 4px;
            background: var(--primary-800);
            margin-top: 10px;
        }

        /* Giá trị cốt lõi với màu sắc đậm đà */
        .core-values { 
            background: var(--neutral-100); 
            padding: 60px 30px; 
            text-align: center;
            border-radius: 30px;
            border: 1px solid var(--primary-200);
        }
        .value-box { 
            display: inline-block; 
            width: 30%; 
            padding: 35px 20px; 
            margin: 1%; 
            background: var(--white); 
            border-radius: 20px; 
            border-bottom: 5px solid var(--primary-800); /* Viền đậm phía dưới */
            box-shadow: 0 10px 30px rgba(0,0,0,0.08);
            transition: all 0.3s ease;
            vertical-align: top;
        }
        .value-box:hover { transform: translateY(-10px); background: var(--primary-50); }
        .value-box h3 { color: var(--primary-900); font-size: 1.5em; margin-bottom: 15px; }

        /* Nút kêu gọi hành động đậm chất */
        .cta { 
            text-align: center; 
            padding: 100px 0; 
        }
        .btn { 
            display: inline-block; 
            background: var(--primary-800); 
            color: var(--white); 
            padding: 18px 45px; 
            text-decoration: none; 
            border-radius: 50px; 
            font-size: 1.1em;
            font-weight: bold;
            box-shadow: 0 10px 20px rgba(30, 58, 138, 0.22);
            transition: 0.3s;
        }
        .btn:hover { 
            background: var(--primary-900); 
            box-shadow: 0 15px 25px rgba(15, 32, 68, 0.28);
            transform: scale(1.05);
        }

        footer { 
            text-align: center; 
            padding: 40px; 
            background: var(--primary-950); /* Xám đậm gần đen để nổi bật nội dung trên */
            color: var(--primary-300); 
        }
        strong { color: var(--primary-800); font-weight: 700; }

        @media (max-width: 768px) {
            .value-box { width: 90%; margin-bottom: 20px; }
            .mission-section { flex-direction: column; text-align: center; }
        }
</style>
{% endblock %}

{% block content %}
<header>
    <h1>CHÚNG TÔI LÀ AI?</h1>
    <p>Nơi sức mạnh cộng đồng được lan tỏa mạnh mẽ nhất</p>
</header>

<div class="container">
    <section class="mission-section">
        <div class="mission-text">
            <h2>Sứ mệnh của sự Minh Bạch</h2>
            <p>
                <strong>Quỹ nhân ái</strong> ra đời with mục tiêu trở thành nền tảng gây quỹ 
                trực tuyến <strong>sáng nhất, sạch nhất và hiệu quả nhất</strong> tại Việt Nam. 
                Chúng tôi sử dụng công nghệ để biến những số liệu khô khan thành những câu chuyện 
                đầy cảm hứng và sự tin tưởng tuyệt đối.
            </p>
            <p>
                Sắc hồng đậm trên website tượng trưng cho nhiệt huyết rực cháy của những người làm 
                thiện nguyện, kết hợp cùng tone xám hiện đại thể hiện sự bền vững và chuyên nghiệp.
            </p>
        </div>
    </section>

    <section class="core-values">
        <h2 style="color: var(--primary-950); margin-bottom: 50px; font-size: 2.5em;">Tại sao tin tưởng chúng tôi?</h2>
        <div class="value-box">
            <h3>Công Nghệ Dẫn Đầu</h3>
            <p>Hệ thống xử lý giao dịch tức thì, tích hợp mã QR cá nhân hóa cho từng chiến dịch.</p>
        </div>
        <div class="value-box">
            <h3>Xác Thực 100%</h3>
            <p>Mọi cá nhân/tổ chức kêu gọi đều phải qua quy trình xác minh danh tính nghiêm ngặt.</p>
        </div>
        <div class="value-box">
            <h3>Kết Nối Thẳng</h3>
            <p>Tiền ủng hộ được chuyển trực tiếp đến mục tiêu, giảm thiểu tối đa chi phí trung gian.</p>
        </div>
    </section>

    <section class="cta">
        <h2 style="font-size: 2.5em; margin-bottom: 20px;">Bạn đã sẵn sàng đồng hành?</h2>
        <p style="font-size: 1.2em; color: var(--neutral-500); margin-bottom: 40px;">Hàng ngàn hoàn cảnh đang chờ đợi sự tiếp sức từ phía bạn.</p>
        <a href="{% url 'client:trangchu' %}" class="btn">Bắt đầu ngay bây giờ</a>
    </section>
</div>
{% endblock %}
```

#### 2.2. saoke.html
```html
{% block content %}
<div class="container py-5">
    <div class="text-center mb-5">
        <h1 class="fw-bold text-primary">SAO KÊ MINH BẠCH - BLOCKCHAIN</h1>
        <p class="text-muted">
            Mọi khoản đóng góp đều được ghi nhận vĩnh viễn trên mạng lưới Blockchain Sepolia. 
            <br>Không ai có thể sửa đổi hoặc xóa bỏ.
        </p>
        <div class="row justify-content-center g-3 mt-2">
            <div class="col-auto">
                <div class="card px-4 py-2 shadow-sm border-primary">
                    <span class="small text-muted">💰 Tổng ủng hộ</span>
                    <span class="h4 text-danger fw-bold mb-0">{{ total_system_amount|intcomma }} VNĐ</span>
                </div>
            </div>
            {% if total_gas_vnd %}
            <div class="col-auto">
                <div class="card px-4 py-2 shadow-sm border-warning">
                    <span class="small text-muted">⛽ Tổng phí Gas Blockchain</span>
                    <span class="h4 text-warning fw-bold mb-0">-{{ total_gas_vnd|intcomma }} VNĐ</span>
                </div>
            </div>
            <div class="col-auto">
                <div class="card px-4 py-2 shadow-sm border-success">
                    <span class="small text-muted">💎 Thực nhận (giải ngân tối đa)</span>
                    <span class="h4 text-success fw-bold mb-0">{{ total_net_amount|intcomma }} VNĐ</span>
                </div>
            </div>
            {% endif %}
        </div>
    </div>

    <div class="card shadow border-0 rounded-4 overflow-hidden">
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-hover table-striped align-middle mb-0">
                    <thead class="bg-primary text-white">
                        <tr>
                            <th class="py-3 ps-4">Thời gian</th>
                            <th class="py-3">Người ủng hộ</th>
                            <th class="py-3">Số tiền</th>
                            <th class="py-3">Chiến dịch</th>
                            <th class="py-3">Lời nhắn</th>
                            <th class="py-3 text-center">Chứng thực Blockchain (Proof)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for item in donations %}
                        <tr>
                            <td class="ps-4 text-muted small">
                                {{ item.created_at|date:"H:i d/m/Y" }}
                            </td>

                            <td>
                                <div class="d-flex align-items-center">
                                    <div class="bg-light rounded-circle d-flex justify-content-center align-items-center me-2 fw-bold text-primary" 
                                         style="width: 35px; height: 35px; font-size: 14px;">
                                        {{ item.donor_name|slice:":1"|upper }}
                                    </div>
                                    <span class="fw-bold text-dark">
                                        {% if item.is_anonymous %}
                                            Mạnh thường quân
                                        {% else %}
                                            {{ item.donor_name }}
                                        {% endif %}
                                    </span>
                                </div>
                            </td>

                            <td>
                                <div class="fw-bold text-success">+{{ item.amount|intcomma }} đ</div>
                                {% if item.gas_fee_vnd %}
                                <div class="small text-warning" title="Phí gas blockchain đã trừ">
                                    ⛽ -{{ item.gas_fee_vnd|intcomma }} đ
                                </div>
                                <div class="small text-muted fw-bold" title="Số tiền thực nhận sau phí gas">
                                    → {{ item.net_amount|intcomma }} đ
                                </div>
                                endif %}
                            </td>

                            <td>
                                <a href="{% url 'client:chitiet_chiendich' item.campaign.id %}" class="text-decoration-none text-secondary small fw-bold">
                                    {{ item.campaign.title|truncatechars:30 }}
                                </a>
                            </td>

                            <td class="small fst-italic text-muted">
                                "{{ item.message|default:"Không có lời nhắn"|truncatechars:40 }}"
                            </td>

                            <td class="text-center">
                                {% if item.eth_tx_hash %}
                                    <a href="https://sepolia.etherscan.io/tx/{{ item.eth_tx_hash }}" target="_blank" class="text-decoration-none">
                                        <div class="badge bg-success-subtle text-success border border-success px-3 py-2 rounded-pill d-inline-flex align-items-center gap-2" title="Bấm để kiểm tra trên Etherscan">
                                            <i class="bi bi-shield-fill-check"></i>
                                            <span>Đã xác thực</span>
                                            <small class="font-monospace text-dark ms-1 opacity-75">
                                                {{ item.eth_tx_hash|slice:":6" }}...{{ item.eth_tx_hash|slice:"-4:" }}
                                                <i class="bi bi-box-arrow-up-right ms-1" style="font-size: 10px;"></i>
                                            </small>
                                        </div>
                                    </a>
                                {% else %}
                                    <span class="badge bg-secondary-subtle text-secondary px-3 py-2 rounded-pill">
                                        <i class="bi bi-hourglass-split"></i> Đang đồng bộ...
                                    </span>
                                {% endif %}
                            </td>
                        </tr>
                        {% empty %}
                        <tr>
                            <td colspan="6" class="text-center py-5 text-muted">
                                <i class="bi bi-inbox fs-1 d-block mb-3"></i>
                                Chưa có giao dịch nào. Hãy là người đầu tiên ủng hộ!
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<style>
    .bg-success-subtle { background-color: var(--success-100) !important; }
    .table-hover tbody tr:hover { background-color: var(--neutral-100); }
    .badge:hover { transform: translateY(-1px); transition: 0.2s; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
</style>
{% endblock %}
```
#### 2.3. biendong_sodu.html
```html
{% block extra_css %}
<style>
    .finance-hero {
        background: linear-gradient(135deg, var(--primary-950) 0%, var(--primary-900) 50%, var(--primary-900) 100%);
        padding: 60px 0 80px;
        color: white;
        position: relative;
        overflow: hidden;
    }
    .finance-hero::before {
        content: '';
        position: absolute;
        top: -50%; left: -50%;
        width: 200%; height: 200%;
        background: radial-gradient(circle, rgba(255,255,255,0.03) 0%, transparent 60%);
        animation: pulse-bg 8s ease-in-out infinite;
    }
    @keyframes pulse-bg {
        0%, 100% { transform: scale(1); }
        50% { transform: scale(1.1); }
    }
    .stat-card {
        background: rgba(255,255,255,0.1);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.15);
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        transition: all 0.3s ease;
    }
    .stat-card:hover {
        transform: translateY(-4px);
        background: rgba(255,255,255,0.15);
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    }
    .stat-card .stat-icon {
        width: 50px; height: 50px;
        border-radius: 12px;
        display: flex; align-items: center; justify-content: center;
        font-size: 22px;
        margin: 0 auto 12px;
    }
    .stat-card h3 { font-size: 1.8rem; font-weight: 800; margin: 0; }
    .stat-card p { font-size: 0.85rem; opacity: 0.7; margin: 4px 0 0; text-transform: uppercase; letter-spacing: 1px; }

    .filter-bar {
        background: white;
        border-radius: 16px;
        padding: 20px 28px;
        margin-top: -40px;
        position: relative;
        z-index: 10;
        box-shadow: 0 10px 40px rgba(0,0,0,0.08);
        border: 1px solid var(--primary-200);
    }

    .campaign-summary-card {
        background: white;
        border-radius: 14px;
        padding: 20px;
        border: 1px solid var(--primary-200);
        transition: all 0.3s ease;
        height: 100%;
    }
    .campaign-summary-card:hover {
        box-shadow: 0 8px 25px rgba(0,0,0,0.08);
        transform: translateY(-3px);
        border-color: transparent;
    }

    .txn-table {
        background: white;
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 5px 20px rgba(0,0,0,0.05);
        border: 1px solid var(--primary-200);
    }
    .txn-table thead th {
        background: var(--neutral-100);
        border-bottom: 2px solid var(--primary-200);
        font-weight: 700;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--neutral-500);
        padding: 14px 16px;
    }
    .txn-table tbody td {
        padding: 14px 16px;
        vertical-align: middle;
        border-bottom: 1px solid var(--primary-200);
    }
    .txn-table tbody tr {
        transition: background 0.2s;
    }
    .txn-table tbody tr:hover {
        background: var(--primary-50);
    }

    .badge-in {
        background: var(--success-100);
        color: var(--success-600);
        font-weight: 700;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.8rem;
    }
    .badge-out {
        background: var(--danger-100);
        color: var(--danger-600);
        font-weight: 700;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.8rem;
    }
    .amount-in { color: var(--success-600); font-weight: 700; }
    .amount-out { color: var(--danger-600); font-weight: 700; }

    .source-badge {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .source-vnpay { background: var(--primary-100); color: var(--primary-700); }
    .source-casso { background: var(--accent-100); color: var(--warning-600); }
    .source-mock { background: var(--primary-100); color: var(--primary-700); }
    .source-manual { background: var(--primary-100); color: var(--primary-900); }

    .progress-thin { height: 6px; border-radius: 3px; }
    .live-dot {
        width: 8px; height: 8px;
        background: var(--success-600);
        border-radius: 50%;
        display: inline-block;
        animation: blink 1.5s ease-in-out infinite;
    }
    @keyframes blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
    }
</style>
{% endblock %}

{% block content %}

<!-- HERO SECTION -->
<section class="finance-hero">
    <div class="container position-relative">
        <div class="text-center mb-5">
            <div class="d-inline-flex align-items-center gap-2 mb-3 px-3 py-2 rounded-pill" style="background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2);">
                <span class="live-dot"></span>
                <span class="small fw-bold" style="letter-spacing: 1px;">REALTIME TRACKING</span>
            </div>
            <h1 class="fw-bold display-5 mb-3">Biến động số dư</h1>
            <p class="opacity-75 fs-6 mb-0" style="max-width: 600px; margin: 0 auto;">
                Minh bạch 100% mọi khoản tiền VÀO và RA. Ai cũng có thể kiểm tra, không thể sửa đổi hay xóa bỏ.
            </p>
        </div>

        <div class="row g-3 justify-content-center">
            <div class="col-md-3">
                <div class="stat-card">
                    <div class="stat-icon" style="background: rgba(40,167,69,0.2);">
                        <i class="fas fa-arrow-down" style="color: var(--success-600);"></i>
                    </div>
                    <h3>{{ total_in|intcomma }} đ</h3>
                    <p>Tổng tiền vào</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card">
                    <div class="stat-icon" style="background: rgba(220,53,69,0.2);">
                        <i class="fas fa-arrow-up" style="color: var(--danger-600);"></i>
                    </div>
                    <h3>{{ total_out|intcomma }} đ</h3>
                    <p>Tổng tiền ra</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card">
                    <div class="stat-icon" style="background: rgba(0,123,255,0.2);">
                        <i class="fas fa-wallet" style="color: var(--primary-600);"></i>
                    </div>
                    <h3>{{ total_balance|intcomma }} đ</h3>
                    <p>Số dư hiện tại</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="stat-card">
                    <div class="stat-icon" style="background: rgba(255,193,7,0.2);">
                        <i class="fas fa-exchange-alt" style="color: var(--warning-600);"></i>
                    </div>
                    <h3>{{ total_transactions|intcomma }}</h3>
                    <p>Tổng giao dịch</p>
                </div>
            </div>
        </div>
    </div>
</section>

<!-- FILTER BAR -->
<div class="container">
    <div class="filter-bar">
        <form method="get" class="row g-3 align-items-end">
            <div class="col-md-5">
                <label class="form-label fw-bold small text-muted">LỌC THEO CHIẾN DỊCH</label>
                <select name="campaign" class="form-select">
                    <option value="">— Tất cả chiến dịch —</option>
                    {% for c in all_campaigns %}
                    <option value="{{ c.id }}" {% if selected_campaign == c.id|stringformat:"d" %}selected{% endif %}>{{ c.title|truncatechars:50 }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="col-md-4">
                <label class="form-label fw-bold small text-muted">LOẠI GIAO DỊCH</label>
                <select name="type" class="form-select">
                    <option value="">Tất cả (Vào + Ra)</option>
                    <option value="in" {% if selected_type == "in" %}selected{% endif %}>💰 Tiền VÀO</option>
                    <option value="out" {% if selected_type == "out" %}selected{% endif %}>💸 Tiền RA (Giải ngân)</option>
                </select>
            </div>
            <div class="col-md-3">
                <button type="submit" class="btn btn-dark w-100 fw-bold py-2">
                    <i class="fas fa-filter me-2"></i> Lọc
                </button>
            </div>
        </form>
    </div>
</div>

<!-- CAMPAIGN SUMMARY -->
{% if campaigns_summary %}
<div class="container mt-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h6 class="text-uppercase fw-bold text-danger small mb-1">Tổng hợp</h6>
            <h4 class="fw-bold m-0">Tài chính theo chiến dịch</h4>
        </div>
    </div>

    <div class="row g-3">
        {% for item in campaigns_summary %}
        <div class="col-md-6 col-lg-4">
            <div class="campaign-summary-card">
                <div class="d-flex align-items-start justify-content-between mb-3">
                    <div style="flex: 1; min-width: 0;">
                        <h6 class="fw-bold mb-1 text-truncate" title="{{ item.campaign.title }}">{{ item.campaign.title|truncatechars:35 }}</h6>
                        <span class="small text-muted">{{ item.count }} giao dịch</span>
                    </div>
                    <a href="?campaign={{ item.campaign.id }}" class="btn btn-sm btn-outline-primary rounded-pill" title="Xem chi tiết">
                        <i class="fas fa-eye"></i>
                    </a>
                </div>

                <div class="d-flex justify-content-between mb-2">
                    <div>
                        <div class="small text-muted">Tiền vào</div>
                        <div class="fw-bold text-success">+{{ item.total_in|intcomma }}đ</div>
                    </div>
                    <div class="text-end">
                        <div class="small text-muted">Tiền ra</div>
                        <div class="fw-bold text-danger">-{{ item.total_out|intcomma }}đ</div>
                    </div>
                </div>

                {% if item.total_in %}
                <div class="progress progress-thin mb-2">
                    <div class="progress-bar bg-success" style="width: {% widthratio item.total_in item.total_in 100 %}%"></div>
                    {% if item.total_out %}
                    <div class="progress-bar bg-danger" style="width: {% widthratio item.total_out item.total_in 100 %}%"></div>
                    {% endif %}
                </div>
                {% endif %}

                <div class="text-center pt-2 border-top">
                    <span class="small fw-bold" style="color: var(--primary-900);">Còn lại: {{ item.balance|intcomma }}đ</span>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}

<!-- TRANSACTION TABLE -->
<div class="container mt-5 mb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
            <h6 class="text-uppercase fw-bold text-danger small mb-1">Chi tiết</h6>
            <h4 class="fw-bold m-0">Lịch sử giao dịch</h4>
        </div>
        <div class="d-flex align-items-center gap-2">
            <span class="badge-in"><i class="fas fa-arrow-down me-1"></i> Tiền vào</span>
            <span class="badge-out"><i class="fas fa-arrow-up me-1"></i> Tiền ra</span>
        </div>
    </div>

    <div class="txn-table">
        <div class="table-responsive">
            <table class="table mb-0">
                <thead>
                    <tr>
                        <th style="width: 50px;">#</th>
                        <th>Thời gian</th>
                        <th>Loại</th>
                        <th>Số tiền</th>
                        <th>Chiến dịch</th>
                        <th>Nội dung</th>
                        <th>Nguồn</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in statements %}
                    <tr>
                        <td class="text-muted small">{{ s.id }}</td>
                        <td>
                            <div class="fw-bold small">{{ s.transaction_date|date:"H:i" }}</div>
                            <div class="text-muted" style="font-size: 0.75rem;">{{ s.transaction_date|date:"d/m/Y" }}</div>
                        </td>
                        <td>
                            {% if s.transaction_type == 'in' %}
                                <span class="badge-in"><i class="fas fa-arrow-down me-1"></i> Tiền vào</span>
                            {% else %}
                                <span class="badge-out"><i class="fas fa-arrow-up me-1"></i> Tiền ra</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if s.transaction_type == 'in' %}
                                <span class="amount-in">+{{ s.amount|intcomma }}đ</span>
                            {% else %}
                                <span class="amount-out">-{{ s.amount|intcomma }}đ</span>
                            {% endif %}
                        </td>
                        <td>
                            <a href="{% url 'client:chitiet_chiendich' s.campaign.id %}" class="text-decoration-none">
                                <span class="fw-bold text-dark small">{{ s.campaign.title|truncatechars:30 }}</span>
                            </a>
                        </td>
                        <td>
                            <span class="small text-muted">{{ s.description|default:"—"|truncatechars:50 }}</span>
                        </td>
                        <td>
                            {% if s.source == 'vnpay' %}
                                <span class="source-badge source-vnpay"><i class="fas fa-credit-card"></i> VNPay</span>
                            {% elif s.source == 'casso' %}
                                <span class="source-badge source-casso"><i class="fas fa-university"></i> Casso</span>
                            {% elif s.source == 'mock' %}
                                <span class="source-badge source-mock"><i class="fas fa-flask"></i> Mock</span>
                            {% else %}
                                <span class="source-badge source-manual"><i class="fas fa-pen"></i> Thủ công</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% empty %}
                    <tr>
                        <td colspan="7" class="text-center py-5">
                            <div class="mb-3">
                                <i class="fas fa-inbox fa-3x text-muted opacity-50"></i>
                            </div>
                            <h5 class="text-muted fw-bold">Chưa có giao dịch nào</h5>
                            <p class="text-muted small">Khi có người ủng hộ hoặc tổ chức giải ngân, giao dịch sẽ hiển thị ở đây.</p>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- INFO SECTION -->
<div class="container mb-5">
    <div class="row g-4">
        <div class="col-md-4">
            <div class="d-flex gap-3 p-4 rounded-4" style="background: var(--success-100);">
                <i class="fas fa-shield-alt fa-2x" style="color: var(--success-600);"></i>
                <div>
                    <h6 class="fw-bold mb-1" style="color: var(--success-600);">Không thể sửa đổi</h6>
                    <small class="text-muted">Mọi bản ghi sao kê đã tạo không thể chỉnh sửa hoặc xóa bỏ.</small>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="d-flex gap-3 p-4 rounded-4" style="background: var(--primary-100);">
                <i class="fas fa-eye fa-2x" style="color: var(--primary-700);"></i>
                <div>
                    <h6 class="fw-bold mb-1" style="color: var(--primary-700);">Ai cũng xem được</h6>
                    <small class="text-muted">Trang này không yêu cầu đăng nhập. Bất kỳ ai cũng có thể kiểm tra.</small>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="d-flex gap-3 p-4 rounded-4" style="background: var(--accent-100);">
                <i class="fas fa-sync-alt fa-2x" style="color: var(--warning-600);"></i>
                <div>
                    <h6 class="fw-bold mb-1" style="color: var(--warning-600);">Cập nhật tự động</h6>
                    <small class="text-muted">Dữ liệu được ghi nhận tự động từ VNPay & ngân hàng qua webhook.</small>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

#### 2.4. ungho.html
```html
{% block content %}
<div class="container py-5">
    <div class="row justify-content-center">
        <div class="col-md-7 mb-4">
            <div class="card shadow-sm border-0 h-100">
                <div class="card-header bg-white py-3 border-bottom">
                    <h5 class="fw-bold m-0 text-danger"><i class="fas fa-heart me-2"></i>Ủng hộ Chiến dịch</h5>
                </div>
                <div class="card-body p-4">
                    <form method="POST">
                        {% csrf_token %}
                        <input type="hidden" name="device_fingerprint" id="deviceFingerprintInput">
                        
                        <div class="mb-4">
                            <label class="fw-bold mb-2">Bạn muốn ủng hộ bao nhiêu?</label>
                            <div class="input-group input-group-lg">
                                <input type="number" name="amount" class="form-control fw-bold text-danger" placeholder="Nhập số tiền (VD: 100000)" required min="2000">
                                <span class="input-group-text fw-bold">VNĐ</span>
                            </div>
                            <div class="mt-2">
                                <button type="button" class="btn btn-outline-secondary btn-sm me-1 rounded-pill px-3" onclick="setAmount(50000)">50k</button>
                                <button type="button" class="btn btn-outline-secondary btn-sm me-1 rounded-pill px-3" onclick="setAmount(100000)">100k</button>
                                <button type="button" class="btn btn-outline-secondary btn-sm me-1 rounded-pill px-3" onclick="setAmount(200000)">200k</button>
                                <button type="button" class="btn btn-outline-secondary btn-sm rounded-pill px-3" onclick="setAmount(500000)">500k</button>
                            </div>
                        </div>

                        {% if not user.is_authenticated %}
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <label class="small fw-bold">Họ và tên</label>
                                <input type="text" name="donor_name" class="form-control" required>
                            </div>
                            <div class="col-md-6">
                                <label class="small fw-bold">Email (nhận thư cảm ơn)</label>
                                <input type="email" name="donor_email" class="form-control">
                            </div>
                        </div>
                        {% else %}
                        <div class="alert alert-info py-2 small rounded-3">
                            <i class="fas fa-user-check me-1"></i> Bạn đang ủng hộ với tài khoản: <strong>{{ user.username }}</strong>
                        </div>
                        {% endif %}

                        <div class="mb-4">
                            <label class="fw-bold mb-2">Lời nhắn yêu thương</label>
                            <textarea name="message" class="form-control" rows="3" placeholder="Gửi lời chúc đến hoàn cảnh..."></textarea>
                        </div>

                        <div class="mb-4">
                            <label class="fw-bold mb-2">Hình thức thanh toán</label>
                            <div class="border rounded p-3 mb-2 bg-light">
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="payment_method" id="payos" value="payos" checked>
                                    <label class="form-check-label fw-bold" for="payos">
                                        <i class="fas fa-qrcode me-2 text-danger"></i> Thanh toán qua PayOS
                                    </label>
                                    <div class="small text-muted ms-4 mt-1">Hệ thống tạo checkout URL và VietQR để bạn thanh toán trực tuyến.</div>
                                </div>
                            </div>
                        </div>

                        <button type="submit" class="btn btn-danger w-100 py-3 fw-bold fs-5 shadow-sm rounded-pill">
                            TIẾP TỤC ỦNG HỘ <i class="fas fa-arrow-right ms-2"></i>
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <div class="col-md-4">
            <div class="card shadow-sm border-0 sticky-top" style="top: 100px;">
               <img src="{{ campaign.cover_image_url|default:campaign.avatar_image_url }}" 
         class="w-100 object-fit-cover" 
         style="height: 400px;" 
         alt="{{ campaign.title }}"
         onerror="this.src='https://placehold.co/800x400?text=Chiến+dịch';">
    
                <div class="card-body">
                    <h6 class="fw-bold mb-3 lh-base">{{ campaign.title }}</h6>
                    
                    <div class="d-flex justify-content-between small mb-1">
                        <span class="text-muted">Tiến độ</span>
                        <span class="fw-bold text-danger">{{ campaign.get_percentage|stringformat:".1f" }}%</span>
                    </div>
                    <div class="progress mb-3" style="height: 6px;">
                        <div class="progress-bar bg-primary" style="width: {{ campaign.get_percentage|stringformat:'.0f' }}%"></div>
                    </div>

                    <ul class="list-unstyled small text-muted bg-light p-3 rounded mb-0">
                        <li class="mb-2 d-flex justify-content-between">
                            <span>Mục tiêu:</span> 
                            <span class="fw-bold text-dark">{{ campaign.target_amount|intcomma }} đ</span>
                        </li>
                        <li class="d-flex justify-content-between">
                            <span>Đã quyên góp:</span> 
                            <span class="fw-bold text-danger">{{ campaign.current_amount|intcomma }} đ</span>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```
#### 2.5. camon.html
```html
{% block extra_css %}
<style>
:root {
            --primary-950: #0a1628;
            --primary-900: #0f2044;
            --primary-800: #1e3a8a;
            --primary-700: #2a4fa3;
            --primary-600: #3b6ac7;
            --primary-500: #4f84e0;
            --primary-300: #a8c5f8;
            --primary-200: #d0e2fd;
            --primary-100: #e8f1fe;
            --primary-50: #f3f7ff;
            --neutral-900: #111827;
            --neutral-700: #374151;
            --neutral-500: #6b7280;
            --neutral-300: #d1d5db;
            --neutral-100: #f9fafb;
            --white: #ffffff;
            --success-600: #16a34a;
        }
        body { font-family: 'Be Vietnam Pro', sans-serif; background-color: var(--primary-50); }
        .card-receipt { border: none; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); overflow: hidden; }
        .receipt-header { background: var(--primary-800); color: white; padding: 40px 20px; text-align: center; position: relative; }
        .receipt-header::after {
            content: ""; position: absolute; bottom: -10px; left: 0; width: 100%; height: 20px;
            background: radial-gradient(circle, transparent 10px, var(--white) 11px); background-size: 20px 20px;
        }
        .hash-box { background: var(--neutral-100); border: 1px dashed var(--neutral-300); padding: 15px; border-radius: 8px; font-family: monospace; font-size: 0.85rem; word-break: break-all; color: var(--neutral-700); }
        .label-hash { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; font-weight: bold; color: var(--neutral-500); }
</style>
{% endblock %}

{% block content %}
<div class="container py-5">
        <div class="row justify-content-center">
            <div class="col-md-6">
                <div class="card card-receipt">
                    <div class="receipt-header">
                        <div class="mb-3">
                            <i class="fas fa-check-circle fa-4x text-white"></i>
                        </div>
                        <h4 class="fw-bold mb-1">Cảm ơn bạn đã ủng hộ!</h4>
                        <p class="opacity-75 m-0 small">Giao dịch đã được ghi nhận vào hệ thống.</p>
                    </div>

                    <div class="card-body p-4 pt-5">
                        <div class="row mb-2">
                            <div class="col-5 text-muted small">Người ủng hộ:</div>
                            <div class="col-7 fw-bold text-end">{{ donation.donor_name|default:"Nhà hảo tâm ẩn danh" }}</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-5 text-muted small">Chiến dịch:</div>
                            <div class="col-7 fw-bold text-end text-primary">{{ donation.campaign.title|truncatechars:30 }}</div>
                        </div>
                        <div class="row mb-2">
                            <div class="col-5 text-muted small">Số tiền:</div>
                            <div class="col-7 fw-bold text-end text-danger fs-5">{{ donation.amount|intcomma }} đ</div>
                        </div>
                        <div class="row mb-4">
                            <div class="col-5 text-muted small">Thời gian:</div>
                            <div class="col-7 text-end small">{{ donation.created_at|date:"d/m/Y H:i" }}</div>
                        </div>

                        <div class="alert alert-light border">
                            <div class="d-flex align-items-center mb-2">
                                <i class="fas fa-link text-success me-2"></i>
                                <strong class="small text-uppercase">Chứng thực Blockchain</strong>
                            </div>
                            
                            <div class="mb-2">
                                <div class="label-hash">Mã Hash Giao dịch này (Current Hash)</div>
                                <div class="hash-box text-primary">{{ donation.hash }}</div>
                            </div>
                            
                            <div>
                                <div class="label-hash">Mã Hash Giao dịch trước (Previous Hash)</div>
                                <div class="hash-box text-muted">{{ donation.previous_hash }}</div>
                            </div>
                        </div>

                        <div class="d-grid gap-2 mt-4">
                            <a href="{% url 'client:trangchu' %}" class="btn btn-outline-primary fw-bold">
                                <i class="fas fa-home me-2"></i> Về trang chủ
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
{% endblock %}

#### 2.6. payment_success.html
```html
{% block content %}
<div class="container py-5">
    <div class="row justify-content-center">
        <div class="col-md-7">
            <div class="card card-receipt">
                <div class="receipt-header">
                    <div class="mb-3">
                        <i class="fas fa-check-circle fa-4x text-white"></i>
                    </div>
                    <h4 class="fw-bold mb-1">Ủng hộ thành công!</h4>
                    <p class="opacity-75 m-0 small">Cảm ơn bạn đã đóng góp. Giao dịch đang được xử lý.</p>
                </div>

                <div class="card-body p-4 pt-5">
                    <div id="bcCard" class="bc-card processing p-4">
                        <div class="d-flex align-items-center mb-3">
                            <i id="bcIcon" class="fas fa-spinner fa-spin text-primary me-2 fs-5"></i>
                            <strong id="bcTitle" class="small text-uppercase">Đang ghi giao dịch lên blockchain...</strong>
                        </div>
                        <div class="tx-row" id="txRowA">Giao dịch A: Ghi sao kê ngân hàng <span id="txBadgeA" class="badge bg-secondary">Chờ...</span></div>
                        <div class="tx-row" id="txRowB">Giao dịch B: Admin nạp ETH <span id="txBadgeB" class="badge bg-secondary">Chờ...</span></div>
                    </div>

                    <div class="d-grid gap-2 mt-4">
                        <a href="/" class="btn btn-outline-primary fw-bold">
                            <i class="fas fa-home me-2"></i> Về trang chủ
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

#### 2.7. payment_failed.html
```html
{% block content %}
<div class="container py-5 text-center">
    <i class="fas fa-times-circle fa-5x text-danger mb-4"></i>
    <h2 class="fw-bold">Thanh toán thất bại</h2>
    <p class="text-muted">{{ message|default:"Đã xảy ra lỗi trong quá trình thanh toán." }}</p>
    <a href="/" class="btn btn-primary mt-3">Quay lại trang chủ</a>
</div>
{% endblock %}

#### 2.8. chitiet_chuongtrinh.html
```html
{% block content %}
<div class="container py-5">
    <div class="row mb-5">
        <div class="col-md-5">
            {% if program.image %}
            <img src="{{ program.image.url }}" class="img-fluid rounded shadow w-100" style="object-fit: cover; height: 300px;">
            {% endif %}
        </div>
        <div class="col-md-7">
            <h2 class="fw-bold text-danger">{{ program.name }}</h2>
            <p class="text-muted"><i class="fas fa-building"></i> Tổ chức: <strong>{{ program.organization.name }}</strong></p>
            <p><i class="fas fa-map-marker-alt text-primary"></i> Địa điểm: {{ program.beneficiary_address|default:"Đang cập nhật" }}</p>
            <div class="card bg-light border-0 p-3 mb-3">
                <h5 class="fw-bold">Mục tiêu chương trình:</h5>
                <h3 class="text-success">{{ program.total_target_amount|intcomma }} VNĐ</h3>
            </div>
            <p>{{ program.description|linebreaksbr }}</p>
        </div>
    </div>
</div>
{% endblock %}


### 3. Bổ sung chitiet_chiendich.html (Sidebar & Story & Donors)

**Sidebar (Cột phải):**
```html
        <div class="col-lg-4">
            <div class="card border-0 shadow-sm rounded-4 p-4 sticky-top" style="top: 20px; z-index: 10;">
                <h5 class="fw-bold text-secondary mb-3">Tiến độ quyên góp</h5>
                <h2 class="fw-bold text-primary mb-1">{{ campaign.current_amount|intcomma }} đ</h2>
                <div class="progress mb-4" style="height: 10px;">
                    <div class="progress-bar bg-primary" role="progressbar" style="width: {% widthratio campaign.current_amount campaign.target_amount 100 %}%"></div>
                </div>
                <div class="d-grid gap-2">
                    <a href="{% url 'client:ungho' campaign.id %}" class="btn btn-accent btn-lg fw-bold rounded-pill">ỦNG HỘ NGAY</a>
                </div>
            </div>
        </div>
```

**Story & Recent Donors (Cột trái):**
```html
        <div class="col-lg-8">
            <h1 class="fw-bold mb-3 text-dark">{{ campaign.title }}</h1>
            <div class="campaign-content mt-4 lh-lg">
                <h4 class="fw-bold mb-3">Câu chuyện</h4>
                <p class="text-secondary">{{ campaign.full_description|linebreaks }}</p>
            </div>

            <div class="mt-5 p-4 bg-light rounded-4 border">
                <h4 class="fw-bold mb-4 border-start border-4 border-primary ps-3">🚀 Nhà hảo tâm vừa đóng góp</h4>
                <table class="table table-borderless">
                    {% for donate in donations %}
                    <tr class="border-bottom">
                        <td><strong>{{ donate.donor_name }}</strong></td>
                        <td class="text-end text-success fw-bold">+{{ donate.amount|intcomma }}đ</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
```
### 4. ban_do_thien_nguyen.html (Toàn bộ Structure)

```html
{% block content %}
<div class="map-page">
    <div class="container-xxl">
        <section class="map-hero">
            <h1>📍 Bản đồ hành trình thiện nguyện</h1>
            <p class="hero-sub">Mỗi điểm trên bản đồ là một câu chuyện...</p>
        </section>

        <section class="map-toolbar">
            <div class="toolbar-search">
                <i class="fas fa-search"></i>
                <input type="text" id="searchInput" placeholder="Tìm kiếm...">
            </div>
        </section>

        <section class="map-layout">
            <aside class="map-sidebar" id="mapSidebar">
                <div class="sidebar-header">Hiển thị <strong id="visibleCount">0</strong> chiến dịch</div>
                <div class="sidebar-list" id="campaignList"></div>
            </aside>
            <div class="map-wrapper"><div id="charity_map"></div></div>
        </section>
    </div>
</div>
{% endblock %}
```
