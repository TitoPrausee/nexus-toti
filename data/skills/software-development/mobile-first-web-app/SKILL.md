---
name: mobile-first-web-app
description: Build self-contained web apps optimized for iPhone 15 Pro (393x852) with bottom-tab navigation, iOS safe areas, and touch-first interactions. Includes desktop layout as progressive enhancement.
version: 2.0
---

# Mobile-First Web App Pattern

## When to Use
Any web app (not landing page) that needs to work great on iPhone, especially private tools accessed via Tailscale network.

## Architecture: Mobile-First with Desktop Enhancement

### Core Principle
Design mobile UI first (bottom tabs, full-screen panels), then add desktop side-by-side layout via `@media(min-width:769px)`.

### Mobile Layout Structure
```
┌─────────────────────┐
│   Content Area       │  ← scrollable, padding-bottom for tab bar
│   (switches by tab)  │
│                      │
├─────────────────────┤
│ ✏️Erstellen │ 🖼️Bild │ 📑Galerie │  ← fixed bottom tab bar
└─────────────────────┘
```

### Desktop Layout Structure
```
┌──────────────────────────┐
│      Top Bar            │
├────────┬────────────────┤
│ Input  │   Result        │
│ Panel  │   Panel         │
│ (400px)│   (flex)        │
└────────┴────────────────┘
```

## Required HTML Meta Tags
```html
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover, maximum-scale=1, user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0A0A0B">
```

## CSS Essentials

### iOS Safe Areas
```css
:root {
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --safe-left: env(safe-area-inset-left, 0px);
  --safe-right: env(safe-area-inset-right, 0px);
  --tab-bar-h: 56px;
}
```

### Bottom Tab Bar (mobile only)
```css
.mobile-tab-bar {
  display: none; /* hidden on desktop */
  position: fixed; bottom: 0; left: 0; right: 0;
  background: var(--bg-surface);
  border-top: 1px solid var(--border);
  padding-bottom: var(--safe-bottom);
  z-index: 100;
}
@media (max-width: 768px) {
  .mobile-tab-bar { display: flex; }
}
```

### Content Area (mobile)
```css
.mobile-content {
  flex: 1; overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: calc(var(--tab-bar-h) + var(--safe-bottom) + 16px);
}
```

### Touch Optimizations
```css
* { -webkit-tap-highlight-color: transparent; touch-action: manipulation; }
input, textarea, button { -webkit-appearance: none; appearance: none; }
/* Use :active for touch feedback, NOT :hover */
.btn:active { transform: scale(0.97); opacity: 0.9; }
```

### Prevent iOS Zoom on Input Focus
```css
input, textarea { font-size: 16px !important; } /* iOS won't zoom at 16px+ */
```

## JavaScript Patterns

### Tab Switching
```js
document.querySelectorAll('.mobile-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.tab;
    document.querySelectorAll('.mobile-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.querySelectorAll('.mobile-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('mobile' + capitalize(target)).classList.add('active');
  });
});
```

### Auto-Switch to Result Tab After Action
```js
function showResultTab() {
  if (window.innerWidth <= 768) {
    // Auto-switch mobile to "Image" tab after generation
    document.querySelectorAll('.mobile-tab').forEach(t => 
      t.classList.toggle('active', t.dataset.tab === 'result'));
    document.querySelectorAll('.mobile-panel').forEach(p => p.classList.remove('active'));
    document.getElementById('mobileResult').classList.add('active');
  }
}
```

### Fullscreen Image Overlay (mobile)
```html
<div class="fullscreen-overlay" id="fullscreenOverlay">
  <button class="fullscreen-close">✕</button>
  <img id="fsImage" src="" alt="">
  <div class="fullscreen-actions">
    <button class="action-btn">Download</button>
    <button class="action-btn primary">Fertig</button>
  </div>
</div>
```
```css
.fullscreen-overlay {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,.95); z-index: 300;
  padding: calc(var(--safe-top) + 16px) 16px calc(var(--safe-bottom) + 60px);
}
```

### Web Share API (native iOS share sheet)
```js
$('btnShare').onclick = () => {
  if (navigator.share) {
    navigator.share({ url: imageUrl }).catch(() => window.open(imageUrl, '_blank'));
  } else {
    window.open(imageUrl, '_blank');
  }
};
```

## Action Buttons: Desktop Hover vs Mobile Always-Visible
```css
/* Desktop: hover overlay on image */
.result-overlay-desktop { opacity: 0; transition: opacity .2s; }
.result-image-wrap:hover .result-overlay-desktop { opacity: 1; }
/* Mobile: always-visible action bar below image */
.result-actions-mobile { display: none; }
@media (max-width: 768px) {
  .result-actions-mobile { display: flex; }
  .result-overlay-desktop { display: none; }
}
```

## Apple Dark Mode Design System (Toti Style)

When the user says "more grey" or "like Apple" — use this monochrome palette:

```css
:root {
  --bg: #000;           /* Pure black (iPhone OLED) */
  --surface: #1c1c1e;   /* iOS dark card background */
  --surface2: #2c2c2e;  /* iOS dark secondary */
  --surface3: #3a3a3c;  /* iOS separator/tertiary */
  --text: #fff;
  --text2: rgba(255,255,255,.55);   /* iOS secondary label */
  --text3: rgba(255,255,255,.3);     /* iOS tertiary label */
  --blue: #0a84ff;      /* iOS system blue — ONLY accent color */
  --blue2: #409cff;     /* iOS link blue */
  --red: #ff453a;       /* iOS destructive red */
  --green: #30d158;     /* iOS system green */
  --border: rgba(255,255,255,.12);  /* iOS separator */
}
```

**Rules:**
- NO colorful gradients, NO purple/blue gradients on buttons
- Buttons: white text on black (`background: white; color: black`) or system blue (`#0a84ff`)
- Cards: `#1c1c1e` with `1px solid rgba(255,255,255,.12)` border
- Sliders: `#3a3a3c` track, `#fff` thumb with shadow
- Active states: `background: rgba(255,255,255,.1)` — NOT colored backgrounds
- Selected states: `border-color: #0a84ff; background: rgba(10,132,255,.12); color: #409cff`
- Font: `-apple-system, Inter, system-ui, sans-serif`
- Round buttons: `border-radius: 50%` for icon buttons (Apple HIG)
- Pill buttons: `border-radius: 18px` for primary actions
- Bottom sheets: `border-radius: 20px 20px 0 0` with drag handle

## Canvas-Based Image Editor Architecture

For image editing apps, use a screen-based approach with shared canvas state:

### Screen System
```
Home → Generate → Editor (full screen canvas + bottom toolbar)
         ↗           ↑
    Pick Image ───────┘
    Camera    ────────┘
```

Each screen is `position: absolute; inset: 0` with `.scr.on` to toggle visibility.

### Editor Layout (Mobile-First)
```
┌─────────────────────────┐
│ ✕  ↶  ↷         Fertig │  ← top bar, gradient fade
│                         │
│                         │
│      Canvas Area        │  ← centered, scaled to fit
│    (checkerboard bg)    │
│                         │
│                         │
├─────────────────────────┤
│ ☀ 🎨 ✂️ 🔄 🖌️ A       │  ← bottom toolbar
└─────────────────────────┘
│   safe-area-bottom      │
```

### Key Canvas Patterns
```js
// Scale canvas to fit mobile viewport
function fitCanvas() {
  const wrap = document.getElementById('cWrap');
  const mw = wrap.clientWidth - 16;
  const mh = wrap.clientHeight - 80; // toolbar space
  const s = Math.min(mw / cv.width, mh / cv.height, 1);
  cv.style.width = (cv.width * s) + 'px';
  cv.style.height = (cv.height * s) + 'px';
}

// Touch-accurate canvas coordinates
function getCanvasPos(e) {
  const r = cv.getBoundingClientRect();
  const t = e.touches ? e.touches[0] : e;
  return {
    x: (t.clientX - r.left) * (cv.width / r.width),
    y: (t.clientY - r.top) * (cv.height / r.height)
  };
}

// Use pointer events (works for both touch AND mouse)
cv.addEventListener('pointerdown', onPointerDown);
cv.addEventListener('pointermove', onPointerMove);
cv.addEventListener('pointerup', onPointerUp);
```

### Undo/Redo with ImageData
```js
let history = [], histIdx = -1;
function pushHistory() {
  history = history.slice(0, histIdx + 1);
  history.push(ctx.getImageData(0, 0, cv.width, cv.height));
  histIdx = history.length - 1;
  if (history.length > 30) { history.shift(); histIdx--; }
}
// Undo: histIdx--; ctx.putImageData(history[histIdx], 0, 0);
// Redo: histIdx++; ctx.putImageData(history[histIdx], 0, 0);
```

### Slide-Up Tool Panels (iOS Action Sheet Style)
```css
.e-panel {
  position: absolute; bottom: 0; left: 0; right: 0; z-index: 60;
  background: rgba(28,28,30,.95); backdrop-filter: blur(20px);
  border-radius: 20px 20px 0 0;
  transform: translateY(100%);
  transition: transform .3s cubic-bezier(.32,.72,.24,1);
  padding: 0 20px var(--sab);
  max-height: 55dvh; overflow-y: auto;
}
.e-panel.open { transform: translateY(0); }
```

### Pixel Manipulation Filters (no WebGL needed)
```js
// All filters operate on ImageData.data (Uint8ClampedArray)
const FILTERS = [
  { n: 'Grau', f: (d) => { for(let i=0;i<d.length;i+=4){ const v=d[i]*.299+d[i+1]*.587+d[i+2]*.114; d[i]=d[i+1]=d[i+2]=v }},
  { n: 'Sepia', f: (d) => { for(let i=0;i<d.length;i+=4){ const r=d[i],g=d[i+1],b=d[i+2]; d[i]=Math.min(255,r*.393+g*.769+b*.189); d[i+1]=Math.min(255,r*.349+g*.686+b*.168); d[i+2]=Math.min(255,r*.272+g*.534+b*.131) }},
  // ... cold, warm, contrast, invert, dark, etc.
];
// Apply: ctx.drawImage(origImg, 0, 0); const imgData = ctx.getImageData(0,0,cv.width,cv.height); FILTER[i].f(imgData.data); ctx.putImageData(imgData, 0, 0);
```

### Image Loading (supports both URLs and Data URLs)
```js
function loadImageToEditor(src) {
  showScreen('edScr');
  origImg = new Image();
  origImg.crossOrigin = 'anonymous'; // needed for xAI URLs
  origImg.onload = () => {
    cv.width = origImg.width; cv.height = origImg.height;
    fitCanvas(); ctx.drawImage(origImg, 0, 0); pushHistory();
  };
  origImg.src = src;
}
```

### Camera + File Picker (iOS-native)
```html
<!-- Camera capture -->
<input type="file" accept="image/*" capture="environment" onchange="handlePick(event)">
<!-- Gallery picker -->
<input type="file" accept="image/*" onchange="handlePick(event)">
```
```js
function handlePick(e) {
  const f = e.target.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = ev => loadImageToEditor(ev.target.result);
  r.readAsDataURL(f);
}
```

## Design System Selection (Mercury's Templates)

Before writing ANY CSS, load the relevant design template from Mercury's `popular-web-designs` skill:
```
skill_view(name="popular-web-designs")          # list all 54 templates
skill_view(name="popular-web-designs", file_path="templates/notion.md")  # specific template
```

**Available templates**: Apple, Notion, Linear, Vercel, Stripe, Airbnb, Figma, GitHub, Raycast, and 46 more. Each template has exact color tokens, typography scales, shadow stacks, border radius rules, and component specs.

**Process:**
1. User mentions a design style → load matching template BEFORE writing CSS
2. If user says "helles Design", "Paper", "clean", "Notion-Style" → load `templates/notion.md`
3. If user says "Apple", "iOS-like" → load `templates/apple.md`
4. Apply the template's tokens wholesale — don't mix styles or invent values
5. Only deviate when user explicitly asks for changes

**Common mistake**: Writing CSS with invented values first, then having to redo it 2-3 times. Always load the template FIRST.

## TitoCloud Proxy Integration

When building a web app that runs behind TitoCloud's reverse proxy on port 8090:

### Adding a new service route
1. Add `_proxy_to` method to TitoCloud (if not present):
```python
def _proxy_to(self, host, port, path, method="GET", body=None, headers=None):
    url = f"http://{host}:{port}{path}"
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, data=body.encode() if body else None, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=30) as resp:
            self._send_response(resp.status, resp.read(), resp.headers.get_content_type())
    except Exception as e:
        self._send_response(502, str(e).encode())
```

2. Add route in `do_GET` (strip service prefix!):
```python
elif self.path == "/myservice" or self.path == "/myservice/":
    self._proxy_to("localhost", 3000, "/")
elif self.path.startswith("/myservice/"):
    target_path = self.path.replace("/myservice", "", 1)
    self._proxy_to("localhost", 3000, target_path)
```

3. Add route in `do_POST` for API calls:
```python
if self.path.startswith("/myservice/api/"):
    target_path = self.path.replace("/myservice", "", 1)
    self._proxy_to("localhost", 3000, target_path, method="POST", body=body_str)
```

4. Frontend must use **relative API paths** (`api/generate` not `/api/generate`) so they work both directly and through proxy

5. Add card to `portal.html` for the new service

### Pitfalls
- Absolute paths in frontend JS (`/api/...`) break behind `/myservice/` proxy → always use relative
- Static assets (CSS/JS) must be servable from the Node server — add routes for each file type
- `logo.svg` symlink may be needed if server looks in `__dirname` but file is in `public/`

## Key Pitfalls
1. **Never rely on :hover for mobile** — Use `:active` or always-visible buttons
2. **16px minimum font on inputs** — Prevents iOS auto-zoom on focus
3. **Bottom tab bar needs `padding-bottom: var(--safe-bottom)`** — Otherwise hidden behind home indicator
4. **`100dvh` instead of `100vh`** — Dynamic viewport height accounts for mobile browser chrome
5. **Touch targets minimum 44px** — Apple's HIG recommendation for tap targets
6. **`-webkit-overflow-scrolling: touch`** — Smooth scrolling on iOS
7. **`user-scalable=no`** — Prevents pinch-zoom on form elements (use judiciously)
8. **Separate DOM trees for mobile/desktop** — Easier than complex responsive CSS, keeps both clean
9. **Canvas crossOrigin must be set BEFORE src** — Otherwise CORS taints the canvas, blocking toDataURL()
10. **Pointer events (pointerdown/move/up) over touch/mouse** — Works on both iOS and desktop with one handler
11. **`touch-action: none` on canvas** — Prevents scroll interference while drawing
12. **File size limits** — Self-contained HTML with inline JS/CSS can hit write limits. Use `execute_code` with Python to build large files in chunks, or use `patch` to append sections
13. **Image loading race condition** — Always set `onload` handler BEFORE setting `img.src`
14. **iOS share sheet** — Use `navigator.share({url})` for native iOS sharing, fallback to `window.open()`