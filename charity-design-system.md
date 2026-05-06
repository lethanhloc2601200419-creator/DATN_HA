# 🎨 Charity Website — Design System
> Áp dụng nhất quán cho **mọi trang** của website thiện nguyện.  
> Màu gốc: `#1e3a8a` · Nền: `#ffffff`

---

## 1. CSS Variables — Dán vào `:root` của mọi trang

```css
:root {
  /* === PRIMARY PALETTE (xoay quanh #1e3a8a) === */
  --primary-950: #0a1628;   /* text trên nền tối đậm */
  --primary-900: #0f2044;   /* heading chính, footer bg */
  --primary-800: #1e3a8a;   /* ★ MÀU CHÍNH — button, icon accent */
  --primary-700: #2a4fa3;   /* hover state của primary */
  --primary-600: #3b6ac7;   /* link, border active */
  --primary-500: #4f84e0;   /* icon fill, highlight */
  --primary-400: #7aaaf0;   /* placeholder, muted icon */
  --primary-300: #a8c5f8;   /* border nhẹ, divider có màu */
  --primary-200: #d0e2fd;   /* border mặc định */
  --primary-100: #e8f1fe;   /* nền badge, hover bg */
  --primary-50:  #f3f7ff;   /* nền section xen kẽ */

  /* === ACCENT (CTA nổi bật — quyên góp, tham gia) === */
  --accent-500: #f97316;    /* button "Quyên góp ngay" */
  --accent-400: #fb923c;    /* hover accent */
  --accent-100: #fff7ed;    /* nền badge accent */

  /* === SEMANTIC === */
  --success-600: #16a34a;
  --success-100: #f0fdf4;
  --danger-600:  #dc2626;
  --danger-100:  #fef2f2;
  --warning-600: #ca8a04;
  --warning-100: #fefce8;

  /* === NEUTRAL === */
  --neutral-900: #111827;   /* body text */
  --neutral-700: #374151;   /* label, secondary text */
  --neutral-500: #6b7280;   /* muted/caption */
  --neutral-300: #d1d5db;   /* border input */
  --neutral-100: #f9fafb;   /* nền trang thay thế */
  --white:       #ffffff;   /* nền chính */

  /* === SPACING & SHAPE === */
  --radius-sm:   6px;
  --radius-md:   10px;
  --radius-lg:   16px;
  --radius-xl:   24px;
  --radius-full: 9999px;

  /* === SHADOWS === */
  --shadow-card: 0 1px 4px rgba(30,58,138,0.08), 0 0 0 0.5px rgba(30,58,138,0.10);
  --shadow-btn:  0 2px 8px rgba(30,58,138,0.25);
  --shadow-modal:0 8px 32px rgba(15,32,68,0.18);

  /* === TYPOGRAPHY === */
  --font-sans: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif;
  --font-display: 'Merriweather', Georgia, serif; /* dùng cho H1 hero */
}
```

---

## 2. Màu sắc theo vai trò (Usage Map)

| Vai trò | Token | Hex |
|---|---|---|
| Màu thương hiệu chính | `--primary-800` | `#1e3a8a` |
| Button chính (donate, submit) | `--primary-800` | `#1e3a8a` |
| Button CTA nổi bật | `--accent-500` | `#f97316` |
| Hover button chính | `--primary-700` | `#2a4fa3` |
| Link / text có màu | `--primary-600` | `#3b6ac7` |
| Nền trang | `--white` | `#ffffff` |
| Nền section xen kẽ | `--primary-50` | `#f3f7ff` |
| Nền card | `--white` | `#ffffff` |
| Nền card nổi bật | `--primary-800` | `#1e3a8a` |
| Border mặc định | `--primary-200` | `#d0e2fd` |
| Border input | `--neutral-300` | `#d1d5db` |
| Header background | `--white` | `#ffffff` |
| Footer background | `--primary-950` | `#0a1628` |
| Body text | `--neutral-900` | `#111827` |
| Text phụ / muted | `--neutral-500` | `#6b7280` |
| Progress bar | `--primary-800` | `#1e3a8a` |

---

## 3. Typography

```css
/* Font chữ — import vào <head> */
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap');

body {
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.65;
  color: var(--neutral-900);
  background: var(--white);
}

/* Scale */
h1 { font-size: 32px; font-weight: 700; color: var(--primary-950); line-height: 1.2; }
h2 { font-size: 24px; font-weight: 700; color: var(--primary-900); line-height: 1.3; }
h3 { font-size: 18px; font-weight: 600; color: var(--primary-800); line-height: 1.4; }
h4 { font-size: 15px; font-weight: 600; color: var(--neutral-700); }

p  { font-size: 14px; color: var(--neutral-700); line-height: 1.65; }

.eyebrow {  /* nhãn nhỏ trên heading */
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--primary-600);
}

.caption { font-size: 12px; color: var(--neutral-500); }

a { color: var(--primary-600); text-decoration: none; }
a:hover { color: var(--primary-800); text-decoration: underline; }
```

---

## 4. Buttons

```css
/* Reset chung */
.btn {
  font-family: var(--font-sans);
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  border: none;
  border-radius: var(--radius-md);
  transition: background 0.15s, transform 0.1s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn:active { transform: scale(0.97); }

/* Primary — hành động chính */
.btn-primary {
  background: var(--primary-800);
  color: var(--white);
  padding: 11px 24px;
  font-size: 14px;
  box-shadow: var(--shadow-btn);
}
.btn-primary:hover { background: var(--primary-700); }

/* Accent — CTA quyên góp */
.btn-accent {
  background: var(--accent-500);
  color: var(--white);
  padding: 11px 24px;
  font-size: 14px;
}
.btn-accent:hover { background: var(--accent-400); }

/* Outline */
.btn-outline {
  background: transparent;
  color: var(--primary-800);
  padding: 10px 22px;
  font-size: 14px;
  border: 1.5px solid var(--primary-800);
}
.btn-outline:hover { background: var(--primary-50); }

/* Ghost */
.btn-ghost {
  background: transparent;
  color: var(--primary-700);
  padding: 10px 18px;
  font-size: 14px;
}
.btn-ghost:hover { background: var(--primary-100); }

/* Small */
.btn-sm {
  background: var(--primary-100);
  color: var(--primary-800);
  padding: 6px 14px;
  font-size: 12px;
  border-radius: var(--radius-sm);
}

/* Icon button */
.btn-icon {
  width: 40px; height: 40px;
  border-radius: 50%;
  background: var(--primary-100);
  color: var(--primary-800);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px;
}
```

---

## 5. Header

```css
.site-header {
  background: var(--white);
  border-bottom: 1px solid var(--primary-200);
  position: sticky;
  top: 0;
  z-index: 100;
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 2rem;
}

.header-inner {
  width: 100%; max-width: 1200px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
}

/* Logo */
.logo {
  display: flex; align-items: center; gap: 10px;
  text-decoration: none;
}
.logo-icon {
  width: 36px; height: 36px;
  border-radius: var(--radius-sm);
  background: var(--primary-800);
  color: var(--white);
  font-weight: 700; font-size: 16px;
  display: flex; align-items: center; justify-content: center;
}
.logo-text {
  font-size: 17px; font-weight: 700;
  color: var(--primary-900);
}

/* Nav */
.nav { display: flex; gap: 28px; }
.nav-link { font-size: 14px; color: var(--neutral-700); font-weight: 500; }
.nav-link:hover, .nav-link.active { color: var(--primary-800); text-decoration: none; }

/* Mobile: ẩn nav, hiện hamburger */
@media (max-width: 768px) {
  .nav { display: none; }
  .nav.open { display: flex; flex-direction: column; position: absolute; top: 64px; left: 0; right: 0; background: var(--white); padding: 1rem 2rem; border-bottom: 1px solid var(--primary-200); }
}
```

---

## 6. Footer

```css
.site-footer {
  background: var(--primary-950);
  color: var(--primary-300);
  padding: 3rem 2rem 1.5rem;
}
.footer-inner {
  max-width: 1200px; margin: 0 auto;
}
.footer-logo { color: var(--white); font-size: 18px; font-weight: 700; }
.footer-desc { font-size: 13px; color: var(--primary-400); margin-top: 6px; }
.footer-links a { color: var(--primary-400); font-size: 13px; }
.footer-links a:hover { color: var(--white); }
.footer-bottom {
  border-top: 0.5px solid rgba(255,255,255,0.1);
  margin-top: 2rem; padding-top: 1rem;
  font-size: 12px; color: var(--primary-400);
  display: flex; justify-content: space-between;
}
```

---

## 7. Cards

```css
/* Card cơ bản */
.card {
  background: var(--white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 1.25rem 1.5rem;
  transition: box-shadow 0.2s;
}
.card:hover { box-shadow: 0 4px 16px rgba(30,58,138,0.14); }

/* Card nổi bật (featured/dark) */
.card-featured {
  background: var(--primary-800);
  color: var(--white);
}
.card-featured h3 { color: var(--white); }
.card-featured p  { color: var(--primary-300); }

/* Card stat */
.card-stat {
  background: var(--primary-50);
  border-left: 3px solid var(--primary-800);
  border-radius: var(--radius-md);
  padding: 1rem 1.25rem;
}
.card-stat .stat-number { font-size: 28px; font-weight: 700; color: var(--primary-800); }
.card-stat .stat-label  { font-size: 12px; color: var(--neutral-500); }

/* Icon trong card */
.card-icon {
  width: 42px; height: 42px;
  border-radius: var(--radius-md);
  background: var(--primary-100);
  display: flex; align-items: center; justify-content: center;
  font-size: 20px;
  margin-bottom: 12px;
}
.card-featured .card-icon { background: rgba(255,255,255,0.15); }
```

---

## 8. Badges & Tags

```css
.badge {
  display: inline-block;
  font-size: 11px; font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--radius-full);
}
.badge-primary { background: var(--primary-100); color: var(--primary-800); }
.badge-accent   { background: var(--accent-100);  color: #c2410c; }
.badge-success  { background: var(--success-100); color: var(--success-600); }
.badge-danger   { background: var(--danger-100);  color: var(--danger-600); }
.badge-dark     { background: var(--primary-800); color: var(--white); }
.badge-outline  { border: 1px solid var(--primary-300); color: var(--primary-700); }
```

---

## 9. Form Inputs

```css
.form-group { display: flex; flex-direction: column; gap: 5px; }
.form-label { font-size: 13px; font-weight: 500; color: var(--neutral-700); }

.form-input,
.form-select,
.form-textarea {
  font-family: var(--font-sans);
  font-size: 14px;
  color: var(--neutral-900);
  background: var(--white);
  border: 1.5px solid var(--neutral-300);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  width: 100%;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  border-color: var(--primary-600);
  box-shadow: 0 0 0 3px var(--primary-100);
}
.form-input::placeholder { color: var(--neutral-500); }

.form-error { font-size: 12px; color: var(--danger-600); margin-top: 3px; }
```

---

## 10. Progress Bar

```css
.progress-label {
  display: flex; justify-content: space-between;
  font-size: 13px; margin-bottom: 6px;
}
.progress-label span:last-child { color: var(--primary-700); font-weight: 600; }

.progress-track {
  height: 8px;
  background: var(--primary-100);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--primary-800);
  transition: width 0.4s ease;
}
/* Urgency: đổi màu khi cần gấp */
.progress-fill.urgent { background: var(--accent-500); }
```

---

## 11. Hero Section

```css
.hero {
  background: linear-gradient(130deg, var(--primary-950) 0%, var(--primary-800) 100%);
  padding: 5rem 2rem;
  color: var(--white);
}
.hero-eyebrow { /* dùng class .eyebrow nhưng override màu */
  color: var(--primary-300);
}
.hero h1 { color: var(--white); font-size: 42px; }
.hero p  { color: var(--primary-300); font-size: 16px; max-width: 560px; }
.hero-actions { display: flex; gap: 12px; margin-top: 2rem; flex-wrap: wrap; }
```

---

## 12. Notifications / Toasts

```css
.toast {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px;
  border-radius: var(--radius-md);
  font-size: 14px;
}
.toast-success { background: var(--success-100); color: #166534; border-left: 3px solid var(--success-600); }
.toast-info    { background: var(--primary-100); color: var(--primary-800); border-left: 3px solid var(--primary-600); }
.toast-warning { background: var(--warning-100); color: #854d0e; border-left: 3px solid var(--warning-600); }
.toast-danger  { background: var(--danger-100);  color: #991b1b; border-left: 3px solid var(--danger-600); }
```

---

## 13. Spacing & Layout

```css
/* Max-width container */
.container { max-width: 1200px; margin: 0 auto; padding: 0 1.5rem; }
.container-narrow { max-width: 760px; margin: 0 auto; padding: 0 1.5rem; }

/* Section spacing */
.section { padding: 4rem 0; }
.section-sm { padding: 2.5rem 0; }

/* Grid helpers */
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.grid-3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.5rem; }
.grid-4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; }

/* Divider */
.divider { height: 0.5px; background: var(--primary-200); margin: 2rem 0; }

/* Nền section xen kẽ */
.bg-alt { background: var(--primary-50); }
.bg-dark { background: var(--primary-950); }
```

---

## 14. Quy tắc dành cho AI Agent

Khi sinh code cho bất kỳ trang nào của website, **bắt buộc** tuân theo:

1. **Luôn dùng CSS variables** thay vì hardcode hex. Ví dụ: `color: var(--primary-800)` thay vì `color: #1e3a8a`.
2. **Nền trang mặc định là trắng** (`var(--white)`). Dùng `var(--primary-50)` cho section xen kẽ.
3. **Button quyên góp/donate** luôn dùng `btn-accent` (màu cam `#f97316`) để tạo contrast nổi bật.
4. **Button hành động phụ** (tìm hiểu thêm, xem chi tiết) dùng `btn-outline` hoặc `btn-ghost`.
5. **Header** luôn sticky, nền trắng, border-bottom `var(--primary-200)`.
6. **Footer** luôn nền `var(--primary-950)` (xanh đậm gần đen).
7. **Cards** có `border-radius: var(--radius-lg)` và `box-shadow: var(--shadow-card)`.
8. **Progress bar** quyên góp gần deadline đổi fill sang `var(--accent-500)`.
9. **Badges trạng thái**: dùng đúng semantic (success/danger/warning) không dùng màu tùy ý.
10. **Font chính**: `Be Vietnam Pro` (Google Fonts) — phù hợp tiếng Việt, hiện đại, dễ đọc.

---

*Design System v1.0 — Charity Website · Màu gốc #1e3a8a*
