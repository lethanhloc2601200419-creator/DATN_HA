# KẾ HOẠCH CẢI THIỆN GIAO DIỆN TOÀN BỘ FRONTEND — Quỹ Nhân Ái

> **Hướng dẫn tracking:** Sau khi hoàn thành mỗi file, cập nhật `[ ]` → `[x]` và ghi timestamp vào cột **Hoàn thành lúc**.

---

## TỔNG TIẾN ĐỘ

| Nhóm | Tổng file | Đã xong | Còn lại |
|------|-----------|---------|---------|
| 🌐 Global (base) | 1 | 1 | 0 |
| 👤 Client Templates | 12 | 12 | 0 |
| 🔧 Admin Templates | 11 | 11 | 0 |
| **Tổng cộng** | **24** | **24** | **0** |

---

## BẢNG THEO DÕI TIẾN ĐỘ CHÍNH

| # | Nhóm | File | Mức phức tạp | Trạng thái | Hoàn thành lúc |
|---|------|------|-------------|-----------|----------------|
| 1 | Global | `base_client.html` | 🔴 Cao | `[x]` Đã xong | 2026-05-27 10:30 |
| 2 | Client | `trangchu.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 10:45 |
| 3 | Client | `gioithieu.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 10:50 |
| 4 | Client | `saoke.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 11:00 |
| 5 | Client | `biendong_sodu.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 11:10 |
| 6 | Client | `ban_do_thien_nguyen.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 11:30 |
| 7 | Client | `chitiet_chiendich.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 11:45 |
| 8 | Client | `chitiet_chuongtrinh.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 11:55 |
| 9 | Client | `taochiendich.html` | 🔴 Cao | `[x]` Đã xong | 2026-05-27 12:15 |
| 10 | Client | `ungho.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 12:25 |
| 11 | Client | `camon.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 12:35 |
| 12 | Client | `payment_success.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 12:45 |
| 13 | Client | `payment_failed.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 12:50 |
| 14 | Admin | `trangchu.html` (admin) | 🔴 Cao | `[x]` Đã xong | 2026-05-27 13:15 |
| 15 | Admin | `dangnhap.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 13:25 |
| 16 | Admin | `dangky.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 13:35 |
| 17 | Admin | `quanlychiendich.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 14:15 |
| 18 | Admin | `quanlychuongtrinh.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 14:30 |
| 19 | Admin | `quanly_quyengop.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 14:45 |
| 20 | Admin | `quanly_giaingan.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 15:00 |
| 21 | Admin | `giamsat_giaingan.html` | 🟡 Trung bình | `[x]` Đã xong | 2026-05-27 15:15 |
| 22 | Admin | `quanlytochuc.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 15:25 |
| 23 | Admin | `quanlydanhmuc.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 15:35 |
| 24 | Admin | `sua_quyengop.html` | 🟢 Thấp | `[x]` Đã xong | 2026-05-27 15:45 |

---

## PHẦN A — TIÊU CHUẨN THIẾT KẾ ĐÃ ÁP DỤNG

### A1. Charity/Nonprofit Visual Standards
- **Color psychology:**
    - **Navy Blue (#1e3a8a):** Chuyên nghiệp, ổn định, tin tưởng. Dùng cho Navigation, Heading, Brand.
    - **Orange (#f97316):** Nhiệt huyết, thúc đẩy hành động. Dùng DUY NHẤT cho nút Donate CTA.
- **Quy tắc màu:**
    - Primary `--primary-800` → Brand identity
    - Accent `--accent-500` → Donate CTA (cam)
    - Success `--success-600` → Blockchain verified, trạng thái tốt
    - Danger `--danger-600` → CHỈ lỗi nghiêm trọng, KHÔNG dùng cho donate
- **Typography:** Base 16px | H1 40-48px | H2 30-32px | H3 22-24px | line-height body 1.6 | heading 1.2
- **Font weight:** 400 body / 600 label-nav / 700 heading / 800 display-stats
- **Spacing:** Bội số 8px (8/16/24/32/48/64/96px)
- **Border-radius:** 6px input / 12px card / 16px panel / 9999px pill
- **Shadow:** Card `0 2px 12px rgba(30,58,138,0.08)` | Button hover `0 4px 16px rgba(249,115,22,0.3)`

---

## PHẦN C — KẾ HOẠCH & CHECKLIST CHI TIẾT (ĐÃ HOÀN TẤT)

### 🌐 FILE 1/24 — base_client.html
- [x] Dọn dẹp và chuẩn hóa toàn bộ CSS Variables trong `:root`
- [x] Thêm hamburger `navbar-toggler` button cho mobile
- [x] Thêm active state cho nav-link dựa trên `request.path`
- [x] Chuẩn hóa CSS Navbar & Footer
- [x] Thêm class `.btn-accent` và `.card-charity`
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 10:30

### 👤 FILE 2/24 — trangchu.html
- [x] Hero section: dark overlay gradient, text rõ hơn
- [x] Stats-box: floating card, font 800
- [x] Campaign cards: shadow nhất quán, radius 12px
- [x] Nút "Ủng hộ ngay" màu cam
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 10:45

### 👤 FILE 3/24 — gioithieu.html
- [x] XÓA toàn bộ `:root { }` duplicate
- [x] Header gradient SVG wave
- [x] Mission section & Value boxes thêm icon FA
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 10:50

### 👤 FILE 4/24 — saoke.html
- [x] Hero stats gradient background
- [x] Table `thead` background primary
- [x] Thay toàn bộ `bi-*` icon sang `fas fa-*`
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 11:00

### 👤 FILE 5/24 — biendong_sodu.html
- [x] Chuyển inline style sang CSS class
- [x] Stat icons màu sắc nhất quán
- [x] Table responsive
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 11:10

### 👤 FILE 6/24 — ban_do_thien_nguyen.html
- [x] Hero gradient `--primary-800`
- [x] Map container tối ưu chiều cao
- [x] Toolbar search pill shape, icon `fas fa-search`
- [x] Sidebar shadow & scroll riêng biệt
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 11:30

### 👤 FILE 7/24 — chitiet_chiendich.html
- [x] Sidebar nút "ỦNG HỘ NGAY" cam, pill
- [x] Progress bar radius-full
- [x] Donor table avatar initial circle
- [x] Voting panel 2 màu (yes/no) chuẩn design
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 11:45

### 👤 FILE 8/24 — chitiet_chuongtrinh.html
- [x] Đổi `text-danger` → `text-primary` cho tiêu đề
- [x] Ảnh radius-lg, shadow
- [x] Target amount card background primary-50
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 11:55

### 👤 FILE 9/24 — taochiendich.html
- [x] Build multi-step form (3 bước) hoàn chỉnh
- [x] Image preview JS tích hợp
- [x] Progress indicator (step 1/2/3)
- [x] Leaflet map picker tích hợp
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 12:15

### 👤 FILE 10/24 — ungho.html
- [x] Nút submit cam (`btn-accent`)
- [x] Quick amount buttons pill shape
- [x] Payment method radio cards
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 12:25

### 👤 FILE 11/24 — camon.html
- [x] Receipt header gradient primary
- [x] Icon check animation bounce
- [x] Hash boxes monospace, background neutral-100
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 12:35

### 👤 FILE 12/24 — payment_success.html
- [x] Header xanh success-600
- [x] Trạng thái processing/success phân biệt màu sắc
- [x] Giữ nguyên toàn bộ ID cho JS polling
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 12:45

### 👤 FILE 13/24 — payment_failed.html
- [x] Icon X đỏ danger-600
- [x] Centered card layout
- [x] Nút retry pill
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 12:50

### 🔧 FILE 14/24 — admin/trangchu.html (Dashboard)
- [x] Sidebar fixed, toggle + backdrop mobile
- [x] Stat cards 4 cột desktop
- [x] Thống nhất CSS Scope cho Admin Panel
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 13:15

### 🔧 FILE 15/24 — admin/dangnhap.html
- [x] Centered card layout, full-height
- [x] Form label stacked
- [x] Nút đăng nhập pill primary
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 13:25

### 🔧 FILE 16/24 — admin/dangky.html
- [x] Layout centered card đồng nhất dangnhap
- [x] Form fields label rõ ràng
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 13:35

### 🔧 FILE 17/24 — admin/quanlychiendich.html
- [x] Breadcrumb Dashboard / Quản lý chiến dịch
- [x] Table header primary, hover effect
- [x] Status badges chuẩn design
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 14:15

### 🔧 FILE 18/24 — admin/quanlychuongtrinh.html
- [x] Breadcrumb điều hướng
- [x] Đồng bộ layout với quanlychiendich
- [x] Gom action buttons vào btn-group
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 14:30

### 🔧 FILE 19/24 — admin/quanly_quyengop.html
- [x] Stat cards border-left màu sắc
- [x] Toolbar lọc nâng cao
- [x] Cột Blockchain validation icon xanh/đỏ
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 14:45

### 🔧 FILE 20/24 — admin/quanly_giaingan.html
- [x] Workflow V3 states chuẩn màu
- [x] V3 Audit Trail Timeline
- [x] EIP-712 signature progress bar
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 15:00

### 🔧 FILE 21/24 — admin/giamsat_giaingan.html
- [x] Proposal Card layout (2 cột)
- [x] Wallet status banner chuẩn design
- [x] Nút ký duyệt (Sign EIP-712) cam nổi bật
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 15:15

### 🔧 FILE 22/24 — admin/quanlytochuc.html
- [x] Table hover, logo rounded border
- [x] Gom action buttons gom vào btn-group
- [x] Modal thêm/sửa tổ chức chuẩn form stacked
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 15:25

### 🔧 FILE 23/24 — admin/quanlydanhmuc.html
- [x] CRUD layout chuyên nghiệp
- [x] Slug indicator code style
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 15:35

### 🔧 FILE 24/24 — admin/sua_quyengop.html
- [x] Card Modal trung tâm
- [x] Blockchain warning box nổi bật
- [x] Form input focus hiệu ứng shadow
- [x] **Trạng thái:** `[x]` Đã xong | 2026-05-27 15:45

---

## PHẦN F — KẾT QUẢ RÀ SOÁT CUỐI CÙNG

```
GLOBAL (tất cả file):
[x] Không còn :root{} duplicate
[x] Không còn inline style="color/background/margin/padding"
[x] 100% icon chuyển sang Font Awesome 6
[x] Toàn bộ Django tags, logic backend được bảo toàn
[x] Responsive đạt chuẩn mobile/tablet/desktop

CLIENT PAGES:
[x] Navbar đồng bộ, có hamburger mobile
[x] Nút hành động chính (Donate) duy nhất màu cam
[x] Progress bar đồng bộ xanh Navy
[x] Bo góc card 12px nhất quán

ADMIN PAGES:
[x] Sidebar toggle mượt mà trên mobile
[x] Có breadcrumb trên mọi trang quản lý
[x] Table bọc .table-responsive scroll ngang ổn định
[x] Form label stacked chuẩn dashboard hiện đại
```
