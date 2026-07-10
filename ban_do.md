# 🗺️ KẾ HOẠCH NÂNG CẤP TRANG "BẢN ĐỒ THIỆN NGUYỆN"

> URL: https://web-production-9c2ee.up.railway.app/ban-do-thien-nguyen/
> File: `client/templates/client/ban_do_thien_nguyen.html` + `client/views.py::ban_do_page`

---

## 1. HIỆN TRẠNG (Trước khi nâng cấp)

| Mục | Trạng thái |
|---|---|
| Nguồn dữ liệu | `TargetProgram` (chương trình mục tiêu) — KHÔNG phải Chiến dịch |
| Marker | Mặc định Leaflet (xanh dương đơn giản) |
| Popup | Ảnh + tên + địa chỉ + 1 button "Xem chi tiết & Ủng hộ" |
| Click vào popup | Đi đến `/chuong-trinh/<id>/` (trang chương trình) |
| Filter / Search | ❌ Không có |
| Sidebar danh sách | ❌ Không có |
| Statistics tổng | ❌ Không có |
| Clustering | ❌ Không có (nếu có >100 điểm sẽ rối) |
| Custom marker | ❌ Không phân biệt theo trạng thái |
| Mobile UX | ⚠️ Map full-screen 80vh, không có cách xem danh sách |
| Legend / chú thích | ❌ Không có |
| Geolocation | ❌ Không có |

**Vấn đề chính user nêu:**
- Marker chỉ show **chương trình** thay vì **chiến dịch** (Campaign).
- Click vào nên đi tới **trang chi tiết chiến dịch** (`/chien-dich/<id>/`).
- Cần "nhiều tính năng lên" — sidebar, filter, search, stats, v.v.

---

## 2. MỤC TIÊU SAU NÂNG CẤP

### 2.1. Chuyển nguồn dữ liệu: `TargetProgram` → `Campaign`
- Lấy các `Campaign` có `beneficiary_lat`/`beneficiary_lng` (nếu thiếu thì fallback sang `target_program.beneficiary_lat/lng`).
- Chỉ lấy chiến dịch có `status` ∈ `{'active', 'completed', 'ended'}` (không lấy `pending`/`hidden`/`rejected`).
- Mỗi chiến dịch là **1 marker** trên bản đồ.
- Click → `/chien-dich/<id>/` (`client:chitiet_chiendich`).

### 2.2. UI/UX hoàn toàn mới — Layout 3 vùng

```
┌──────────────────────────────────────────────────────────────────┐
│  HERO BAR: tiêu đề + mô tả + 4 chỉ số nhanh                      │
│  [📍 12 chiến dịch] [🏞 8 tỉnh] [💰 1.2 tỷ đã quyên] [👥 432 nhà]│
├──────────────────────────────────────────────────────────────────┤
│  TOOLBAR: 🔎 Search | Trạng thái | Danh mục | Vùng | Reset | 📍Me│
├──────────────┬───────────────────────────────────────────────────┤
│              │                                                   │
│  SIDEBAR     │                                                   │
│  Danh sách   │              MAP (Leaflet)                        │
│  chiến dịch  │              + clustering                         │
│  (cards)     │              + custom markers                     │
│  (scroll)    │              + popup giàu thông tin               │
│              │              + legend góc dưới                    │
│              │                                                   │
│  300px       │              flex-1                               │
└──────────────┴───────────────────────────────────────────────────┘
```

### 2.3. Tính năng chi tiết

#### A. Hero Stats Bar (đầu trang)
4 ô chỉ số nhanh, format đẹp:
- 📍 **Tổng số chiến dịch** trên bản đồ
- 🏞 **Số tỉnh/thành** đã có dấu chân
- 💰 **Tổng tiền đã quyên góp** (sum `current_amount`)
- 👥 **Tổng số lượt ủng hộ** (sum `support_count`)

#### B. Toolbar (filter & search)
- 🔎 **Search box** (tên chiến dịch, tổ chức, địa chỉ) — debounce 300ms, lọc cả sidebar lẫn marker.
- 🎯 **Trạng thái** dropdown: Tất cả / Đang gây quỹ / Đã hoàn thành / Đã kết thúc.
- 🏷️ **Danh mục** dropdown: tự sinh từ `CampaignCategory`.
- 🗺️ **Vùng miền** chips/buttons: Tất cả / Bắc / Trung / Nam — fly map đến bbox tương ứng.
- 📍 **Locate me** button — `navigator.geolocation` zoom đến vị trí user.
- 🔄 **Reset** button — clear filter, fit bounds toàn bộ.

#### C. Sidebar danh sách (300px, scrollable)
Mỗi card:
- Cover image (height ~80px)
- Status badge (Đang gây quỹ / Đã hoàn thành) với màu semantic
- Title (truncate 2 dòng)
- Organization name (icon + tên)
- Progress bar + %
- Địa chỉ tóm tắt (`{ward}, {province}`)
- **Click card** → fly map đến marker + open popup + highlight border card.

Hover card → marker phóng to nhẹ (CSS transform).

#### D. Map (Leaflet 1.9.4)
- **Tile**: Carto Voyager (giữ như cũ, sạch + tiếng địa danh tốt).
- **Plugin**:
  - `leaflet.markercluster` (CDN) cho clustering.
  - Default zoom toàn Việt Nam `[16.047, 108.206], 6` rồi auto fitBounds.
- **Custom markers (DivIcon)**: hình tròn pin với icon trái tim, màu theo status:
  - 🟠 `--accent-500` (#f97316) cho `active`
  - 🟢 `--success-600` (#16a34a) cho `completed`
  - ⚪ `--neutral-500` cho `ended`
  - Có hover scale 1.15.
- **Cluster icon**: tròn, màu primary, hiển thị số lượng.
- **Popup giàu thông tin** (width 280px):
  - Cover image (height 130px, object-cover)
  - Status badge + Category badge (nếu có)
  - Title (font-weight 700)
  - Organization line (`<i class="fas fa-building"></i> Tên tổ chức`)
  - Address line (`<i class="fas fa-map-marker-alt"></i> {address}`)
  - Progress: `120.000.000 / 200.000.000 VNĐ` + thanh progress
  - Stats nhỏ: `👥 X người ủng hộ · ⏰ còn Y ngày`
  - 2 buttons:
    - `btn-outline-primary`: "Xem chi tiết" → `/chien-dich/<id>/`
    - `btn-accent` (cam): "Ủng hộ ngay" → `/ung-ho/<id>/`

#### E. Legend (góc dưới phải bản đồ)
Card nhỏ, gập gọn được:
```
🟠 Đang gây quỹ
🟢 Đã hoàn thành
⚪ Đã kết thúc
```

#### F. Map controls
- Zoom in/out (mặc định Leaflet, đặt top-right cho thoáng).
- Fullscreen toggle (CSS class, không cần plugin).
- Reset view button.

#### G. Empty state
Khi filter ra 0 kết quả: hiện overlay sidebar với icon 🔍 + "Không tìm thấy chiến dịch nào phù hợp" + button "Xóa bộ lọc".

#### H. Mobile responsive
- ≥992px (lg): layout 2 cột (sidebar 300px + map flex-1).
- <992px: sidebar trượt thành **bottom-sheet** kéo lên (50% chiều cao), có handle bar; map chiếm full trên cùng. Toolbar gập gọn vào nút "🔧 Bộ lọc".

---

## 3. KIẾN TRÚC KỸ THUẬT

### 3.1. Backend (`client/views.py::ban_do_page`)

```python
def ban_do_page(request):
    campaigns = (
        Campaign.objects
        .filter(status__in=['active', 'completed', 'ended'])
        .filter(
            Q(beneficiary_lat__isnull=False, beneficiary_lng__isnull=False)
            | Q(target_program__beneficiary_lat__isnull=False,
                target_program__beneficiary_lng__isnull=False)
        )
        .select_related('organization', 'target_program', 'category')
        .order_by('-created_at')
    )

    map_data = []
    province_set = set()
    total_raised = 0
    total_supporters = 0
    for c in campaigns:
        lat = c.beneficiary_lat or (c.target_program and c.target_program.beneficiary_lat)
        lng = c.beneficiary_lng or (c.target_program and c.target_program.beneficiary_lng)
        if not lat or not lng:
            continue
        progress_pct = float(c.current_amount) / float(c.target_amount) * 100 if c.target_amount else 0
        days_left = max(0, (c.end_date - timezone.now().date()).days) if c.end_date else None
        province_set.add(c.beneficiary_province or '')
        total_raised += int(c.current_amount or 0)
        total_supporters += int(c.support_count or 0)
        map_data.append({
            'id': c.id,
            'title': c.title,
            'short_description': c.short_description or '',
            'lat': float(lat),
            'lng': float(lng),
            'address': c.beneficiary_address or '',
            'province': c.beneficiary_province or '',
            'ward': c.beneficiary_ward or '',
            'image': c.cover_image_url or c.avatar_image_url or '/static/images/default_program.jpg',
            'url_detail': f'/chien-dich/{c.id}/',
            'url_donate': f'/ung-ho/{c.id}/',
            'status': c.status,
            'status_label': c.get_status_display(),
            'category_id': c.category_id,
            'category_name': c.category.name if c.category else '',
            'organization_name': c.organization.name if c.organization else '',
            'organization_logo': c.organization.logo_url if c.organization else '',
            'target_amount': int(c.target_amount or 0),
            'current_amount': int(c.current_amount or 0),
            'progress_pct': min(100, round(progress_pct, 1)),
            'support_count': int(c.support_count or 0),
            'days_left': days_left,
            'end_date': c.end_date.isoformat() if c.end_date else '',
        })

    categories = list(
        CampaignCategory.objects
        .filter(is_active=True, campaign__in=campaigns)
        .distinct()
        .values('id', 'name')
    )

    context = {
        'map_data_json': json.dumps(map_data, ensure_ascii=False),
        'categories': categories,
        'stats': {
            'total_campaigns': len(map_data),
            'total_provinces': len([p for p in province_set if p]),
            'total_raised': total_raised,
            'total_supporters': total_supporters,
        },
    }
    return render(request, 'client/ban_do_thien_nguyen.html', context)
```

**Ghi chú:**
- Vẫn fallback toạ độ từ `target_program` để không mất marker khi creator không nhập GPS.
- `select_related` để tránh N+1.
- `categories` chỉ trả về danh mục có chiến dịch hiển thị, để dropdown gọn.
- Cần import `Q`, `CampaignCategory` (đã import sẵn `Campaign`).

### 3.2. Frontend (`client/templates/client/ban_do_thien_nguyen.html`)

**Cấu trúc:**
```
{% extends 'client/base_client.html' %}
{% block extra_css %}
  <link Leaflet 1.9.4 css>
  <link MarkerCluster css>
  <style>...all custom styles...</style>
{% endblock %}

{% block content %}
  <section class="map-hero">{4 stats}</section>
  <section class="map-toolbar">{search + filters + region chips + locate}</section>
  <section class="map-layout">
    <aside class="map-sidebar">
      <div class="sidebar-count">Hiển thị X / Y chiến dịch</div>
      <div class="sidebar-list" id="campaignList">{render bằng JS}</div>
    </aside>
    <div class="map-wrapper">
      <div id="charity_map"></div>
      <div class="map-legend">{3 dots + label}</div>
    </div>
  </section>
{% endblock %}

{% block extra_js %}
  <script Leaflet>
  <script MarkerCluster>
  <script>
    const RAW_DATA = JSON.parse(...);
    // 1. State: filters = { q, status, category, region }
    // 2. renderSidebar(filtered) — innerHTML cards
    // 3. renderMarkers(filtered) — clear + add to clusterGroup
    // 4. applyFilters() — filter RAW_DATA → call render*
    // 5. Bind events: search input (debounce), select change, region click,
    //    sidebar card click → flyTo + openPopup, locate me, reset
    // 6. Fit bounds initial
  </script>
{% endblock %}
```

**State JS (tối giản, không cần framework):**
```js
const state = {
  q: '',
  status: 'all',
  category: 'all',
  region: 'all',  // 'bac' | 'trung' | 'nam'
};

const REGION_PROVINCES = {
  bac: ['Hà Nội','Hải Phòng','Quảng Ninh','Lạng Sơn','Cao Bằng','Bắc Kạn',
        'Thái Nguyên','Bắc Giang','Phú Thọ','Vĩnh Phúc','Bắc Ninh','Hải Dương',
        'Hưng Yên','Hà Nam','Nam Định','Thái Bình','Ninh Bình','Hà Giang',
        'Tuyên Quang','Lào Cai','Yên Bái','Điện Biên','Lai Châu','Sơn La','Hòa Bình'],
  trung: ['Thanh Hóa','Nghệ An','Hà Tĩnh','Quảng Bình','Quảng Trị','Thừa Thiên Huế',
          'Đà Nẵng','Quảng Nam','Quảng Ngãi','Bình Định','Phú Yên','Khánh Hòa',
          'Ninh Thuận','Bình Thuận','Kon Tum','Gia Lai','Đắk Lắk','Đắk Nông','Lâm Đồng'],
  nam: ['TP.HCM','Hồ Chí Minh','Bình Phước','Bình Dương','Đồng Nai','Tây Ninh',
        'Bà Rịa - Vũng Tàu','Long An','Tiền Giang','Bến Tre','Trà Vinh','Vĩnh Long',
        'Đồng Tháp','An Giang','Kiên Giang','Cần Thơ','Hậu Giang','Sóc Trăng',
        'Bạc Liêu','Cà Mau'],
};
```

**Custom marker (DivIcon):**
```js
function buildIcon(status) {
  const color = status === 'active' ? '#f97316'
              : status === 'completed' ? '#16a34a'
              : '#6b7280';
  return L.divIcon({
    className: 'campaign-marker',
    html: `<div class="marker-pin" style="--pin-color:${color}">
             <i class="fas fa-heart"></i>
           </div>`,
    iconSize: [36, 44],
    iconAnchor: [18, 44],
    popupAnchor: [0, -40],
  });
}
```

**Cluster icon:**
```js
const cluster = L.markerClusterGroup({
  iconCreateFunction(c) {
    const n = c.getChildCount();
    return L.divIcon({
      className: 'campaign-cluster',
      html: `<div class="cluster-bubble"><span>${n}</span></div>`,
      iconSize: [44, 44],
    });
  },
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: true,
  maxClusterRadius: 50,
});
```

**Popup template (innerHTML):**
```js
function buildPopup(c) {
  const statusBadge = c.status === 'active'
    ? '<span class="popup-badge popup-badge-active">Đang gây quỹ</span>'
    : c.status === 'completed'
    ? '<span class="popup-badge popup-badge-completed">Hoàn thành</span>'
    : '<span class="popup-badge popup-badge-ended">Đã kết thúc</span>';
  const daysText = c.days_left !== null && c.days_left > 0
    ? `⏰ Còn ${c.days_left} ngày` : '⏰ Đã hết hạn';
  return `
    <div class="popup-card">
      <img src="${c.image}" class="popup-img" onerror="this.src='/static/images/default_program.jpg'">
      <div class="popup-body">
        <div class="popup-tags">${statusBadge}${c.category_name ? `<span class="popup-badge popup-badge-cat">${c.category_name}</span>` : ''}</div>
        <h6 class="popup-title">${escapeHtml(c.title)}</h6>
        ${c.organization_name ? `<div class="popup-org"><i class="fas fa-building"></i> ${escapeHtml(c.organization_name)}</div>` : ''}
        <div class="popup-addr"><i class="fas fa-map-marker-alt"></i> ${escapeHtml(c.address || c.province)}</div>
        <div class="popup-progress">
          <div class="popup-progress-text">
            <strong>${formatVnd(c.current_amount)}</strong>
            <span class="text-muted">/ ${formatVnd(c.target_amount)}</span>
          </div>
          <div class="popup-progress-track"><div class="popup-progress-fill" style="width:${c.progress_pct}%"></div></div>
          <div class="popup-progress-meta">
            <span>${c.progress_pct}% mục tiêu</span>
            <span>${c.support_count} người ủng hộ</span>
          </div>
        </div>
        <div class="popup-meta">${daysText}</div>
        <div class="popup-actions">
          <a href="${c.url_detail}" class="btn btn-sm btn-outline-primary flex-fill">Chi tiết</a>
          <a href="${c.url_donate}" class="btn btn-sm btn-accent flex-fill">Ủng hộ</a>
        </div>
      </div>
    </div>`;
}
```

**Sidebar card template:**
```js
function buildSidebarCard(c) {
  return `
    <div class="sb-card" data-id="${c.id}" data-lat="${c.lat}" data-lng="${c.lng}">
      <div class="sb-card-img-wrap">
        <img src="${c.image}" class="sb-card-img" onerror="this.src='/static/images/default_program.jpg'">
        <span class="sb-status sb-status-${c.status}">${c.status_label}</span>
      </div>
      <div class="sb-card-body">
        <div class="sb-title">${escapeHtml(c.title)}</div>
        ${c.organization_name ? `<div class="sb-org"><i class="fas fa-building"></i> ${escapeHtml(c.organization_name)}</div>` : ''}
        <div class="sb-progress-track"><div class="sb-progress-fill" style="width:${c.progress_pct}%"></div></div>
        <div class="sb-meta">
          <span>${c.progress_pct}%</span>
          <span><i class="fas fa-map-marker-alt"></i> ${escapeHtml(c.province || '—')}</span>
        </div>
      </div>
    </div>`;
}
```

### 3.3. Bộ thư viện CDN bổ sung

```html
<!-- MarkerCluster -->
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
```

---

## 4. STYLE GUIDE TUÂN THEO `charity-design-system.md`

| Phần tử | Token CSS |
|---|---|
| Marker `active` | `--accent-500` (#f97316) |
| Marker `completed` | `--success-600` |
| Marker `ended` | `--neutral-500` |
| Cluster bubble | `--primary-800` background, white text |
| Card sidebar | `box-shadow: var(--shadow-card)`, `border-radius: var(--radius-lg)` |
| Card sidebar selected | `border: 2px solid var(--primary-600)` |
| Stats card | `.card-stat` style (border-left primary) |
| Progress bar | Track `--primary-100`, fill `--primary-800`; nếu deadline ≤ 7 days → fill `--accent-500` |
| Toolbar bg | `--white` với `border-bottom: 1px solid var(--primary-200)` |
| Search input | `.form-control` chuẩn |
| Region chips | `.btn-sm` với active state đậm |
| Popup buttons | `btn-outline-primary` + `btn-accent` |

---

## 5. ROADMAP THỰC HIỆN

| Bước | Nội dung | File |
|---|---|---|
| 1 | Cập nhật view `ban_do_page` → trả Campaign + stats + categories | `client/views.py` |
| 2 | Viết lại template với layout 3 vùng + JS tương tác | `client/templates/client/ban_do_thien_nguyen.html` |
| 3 | Run `python manage.py check` + browser smoke test | terminal + browser-use |
| 4 | Code review (code-reviewer agent) | — |

---

## 6. EDGE CASES CẦN XỬ LÝ

- Campaign không có `cover_image_url` → fallback `avatar_image_url` → fallback `/static/images/default_program.jpg`.
- Campaign không có lat/lng + không có `target_program` → loại khỏi map, không gây lỗi.
- `target_amount = 0` → progress 0%, không chia 0.
- `end_date` đã qua → days_left hiển thị "Đã hết hạn".
- Filter trả 0 kết quả → empty state trong sidebar.
- Tên chiến dịch dài → CSS `-webkit-line-clamp: 2` cả ở popup lẫn sidebar.
- Tỉnh/thành có thể viết hoa-thường khác nhau → so sánh case-insensitive khi filter region.
- XSS: tất cả string từ user phải qua `escapeHtml()` trước khi `innerHTML`.

---

## 7. KHÔNG ĐƯA VÀO BẢN NÀY (để dành lần sau)

- Heatmap density (cần plugin nặng).
- Layer satellite/terrain switcher (cần thêm tile sources, có thể overkill).
- Routing/directions từ vị trí user → marker.
- Realtime update (websocket).
- Vẽ vùng/polygon biên giới tỉnh thành.
- Bookmark/follow chiến dịch từ map.

→ Có thể nâng cấp ở phase tiếp theo nếu user yêu cầu.
