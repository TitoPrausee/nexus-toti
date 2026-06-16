---
name: titocloud-microservice-proxy
description: Pattern for integrating microservices into TitoCloud via reverse proxy. Covers _proxy_to method, URL path stripping, relative frontend URLs, and POST body forwarding.
version: 1.0.0
tags: [titocloud, proxy, microservice, pattern]
---

# TitoCloud Microservice Proxy Pattern

How to add a new service behind TitoCloud's reverse proxy on port 8090.

## Architecture

```
Tailscale → TitoCloud (8090) → FileBrowser (8091)
                               → Toti Image (3000)
                               → [future services]
```

All services are proxied through TitoCloud. Tailscale clients only need port 8090.

## Adding a New Service

### 1. Add `_proxy_to` Routes in `titocloud.py`

The `_proxy_to(host, port, path, method, body)` method was added for generic microservice proxying.

**GET routes (in `do_GET`):**
```python
elif self.path == "/yourservice" or self.path == "/yourservice/":
    # Landing page — strip prefix, serve root
    self._proxy_to("localhost", PORT, "/")

elif self.path.startswith("/yourservice/"):
    # Static assets and API — strip prefix
    target_path = self.path.replace("/yourservice", "", 1)
    if not target_path:
        target_path = "/"
    self._proxy_to("localhost", PORT, target_path)
```

**POST routes (in `do_POST`):**
```python
if self.path.startswith("/yourservice/api/"):
    target_path = self.path.replace("/yourservice", "", 1)
    body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
    self._proxy_to("localhost", PORT, target_path, method="POST", body=body)
    return
```

### 2. Frontend MUST Use Relative URLs

The most critical pitfall: frontend JavaScript MUST use **relative** API paths.

```javascript
// ✅ CORRECT — works behind proxy
fetch('api/generate', { method: 'POST', ... })
fetch('api/gallery')

// ❌ WRONG — breaks behind proxy (/api/ goes to TitoCloud root)
fetch('/api/generate', { method: 'POST', ... })
fetch('/api/gallery')
```

Same for static assets:
```html
<!-- ✅ CORRECT -->
<link rel="icon" href="logo.svg">

<!-- ❌ WRONG -->
<link rel="icon" href="/logo.svg">
```

### 3. Add Portal Card

In `portal.html`, add a card for the new service:
```html
<div class="card">
    <a class="card-link" href="/yourservice/">
        <div class="card-icon yours">🎯</div>
        <div class="card-body">
            <div class="card-title">Your Service</div>
            <div class="card-desc">Short description</div>
        </div>
        <div class="card-arrow">›</div>
    </a>
</div>
```

Add matching CSS:
```css
.card-icon.yours { background: #1a2a3a; }
```

### 4. Auth Considerations

- Tailscale IPs (100.x) and localhost are trusted (no auth required)
- External access needs Bearer token via `TITOCLOUD_API_TOKENS` env var
- API endpoints are protected by `_require_auth()` — add your service's API paths to the auth check

### 5. Service Independence

Each service runs as its own process on its own port:
- TitoCloud: 8090 (Python Flask/HTTP)
- FileBrowser: 8091 (Go binary)
- Toti Image: 3000 (Node.js)
- Future services: pick an unused port

Start services as background processes. For production, use process managers.

## Critical Proxy Bugs & Fixes

### Missing CORS OPTIONS handler (causes JSON.parse errors)
`BaseHTTPRequestHandler` has NO `do_OPTIONS`. Browsers send CORS preflight `OPTIONS` before cross-origin POSTs. Without a handler → 501 + HTML → browser tries `JSON.parse("<!DOCTYPE...")` → crash at column 5.

**Fix:** Always add `do_OPTIONS`:
```python
def do_OPTIONS(self):
    self.send_response(204)
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PATCH, PUT, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Auth")
    self.send_header("Access-Control-Max-Age", "86400")
    self.end_headers()
```

### Transfer-Encoding: chunked proxy corruption
Node.js uses `Transfer-Encoding: chunked` by default. `_proxy_to` reads `resp.read()` (de-chunked) but forwards chunked headers → browser gets chunked headers + plain body → broken JSON.

**Fix:** Buffer body, strip hop-by-hop headers, add `Content-Length`:
```python
resp_body = resp.read()
for key, val in resp.headers.items():
    if key.lower() not in ("transfer-encoding", "connection", "keep-alive"):
        self.send_header(key, val)
self.send_header("Content-Length", str(len(resp_body)))
self.wfile.write(resp_body)
```

### Relative URL resolution behind proxy (MOST ELUSIVE)
On `/image/` → `fetch('api/generate')` → `/image/api/generate` ✅
On `/image` (no slash) → `fetch('api/generate')` → `/api/generate` ❌ → FileBrowser HTML → JSON.parse crash

**Frontend fix:** Dynamic base path:
```javascript
const _basePath = new URL('.', window.location.href).pathname;
const API = _basePath + 'api/';
const IMG = _basePath + 'images/';
```

**Server fix:** Add redirect `/image` → `/image/` to enforce trailing slash.

### xAI image format mismatch
xAI returns JPEG but server hardcoded `.png` extension → content-type mismatch.

**Fix:** Detect from URL or MIME type.

## Pitfalls

1. **Absolute frontend paths break proxy** — Always use relative URLs in frontend code
2. **Relative URLs break without trailing slash** — `fetch('api/generate')` from page `/image` (no slash) resolves to `/api/generate` (TitoCloud root), NOT `/image/api/generate`. This sends the request to FileBrowser or TitoCloud's task API instead of the microservice → HTML error page → `JSON.parse` crash. **Fix**: In frontend JS, dynamically resolve the base path:
```javascript
// Resolves correctly regardless of trailing slash
const _basePath = new URL('.', window.location.href).pathname; // "/image/" or "/"
const API = _basePath + 'api/';
const IMG = _basePath + 'images/';
// Use: fetch(API + 'generate'), img.src = IMG + filename
```
Also ensure the proxy landing route (`/image` without slash) doesn't redirect — serve the HTML page directly so the browser stays on the correct path.
3. **Missing POST body forwarding** — The `_proxy_to` method needs `body=self.rfile.read(int(self.headers.get("Content-Length", 0)))` for POST requests
3. **DELETE routes need separate handling** — Add `do_DELETE` method if your service needs it
4. **CORS** — TitoCloud sets `Access-Control-Allow-Origin` based on Tailscale range, not wildcard `*`
5. **Content-Length missing** — Some POST requests from browsers may not send Content-Length; handle with `self.headers.get("Content-Length", 0)` default to 0
6. **Design ownership** — Tito delegates frontend design to Mercury. Build the backend/proxy, let Mercury handle the visual design. Don't redesign frontends yourself unless explicitly asked.
7. **CSS/Design iteration** — When user asks for a specific design style (Paper, Notion, Stripe, etc.), load the corresponding template from `popular-web-designs` skill FIRST: `skill_view(name='popular-web-designs', file_path='templates/notion.md')`. Don't guess or start from scratch.
8. **SVG `<use href>` breaks on iOS/Safari** — Never use `<svg><use href="#icon"/></svg>` referencing a hidden sprite `<svg id="icon-sprite">`. Safari cannot resolve cross-`<svg>` `<use href>` references. Always replace with **inline SVG paths**: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M..."/></svg>`. When deploying Mercury's HTML, always run an SVG inliner fix.
9. **Node.js static file caching** — For single-page apps served by Node, always set `Cache-Control: no-cache, no-store, must-revalidate` on `index.html` to prevent aggressive Safari/iOS caching. Other assets (CSS, JS, images) can keep long cache times.
10. **Low-opacity CSS is invisible on mobile** — Mercury's designs use `background: rgba(255,255,255,.05)` and `border: rgba(255,255,255,.07)` which are nearly invisible on dark backgrounds on iPhone screens in daylight. When deploying, boost critical interactive elements: textareas, cards, buttons → use `var(--bg2)` or `rgba(255,255,255,.12)` for backgrounds and `var(--border-hover)` for borders.
11. **`position:absolute; inset:0` screens lose parent padding** — Mercury's `.scr` class uses `position:absolute; inset:0; padding:0` which makes the screen fill the parent `.app` container but **completely ignores the parent's `padding:0 16px`**. Content inside `.scr-body` then has zero horizontal padding and text/inputs appear invisible or clipped. Fix: set `.scr { padding: 0 16px }` to match the parent's horizontal padding, or add `padding: 0 16px` to `.scr-body`.
12. **`Transfer-Encoding: chunked` breaks proxied JSON** — Node.js (and many HTTP servers) sends responses with `Transfer-Encoding: chunked` and no `Content-Length`. When `_proxy_to` forwards the upstream response headers verbatim (including `Transfer-Encoding: chunked`) but the body has already been de-chunked by `urllib.request.urlopen().read()`, the browser receives a chunked header with a non-chunked body → `JSON.parse: unexpected non-whitespace character after JSON data`. **Fix**: In `_proxy_to`, always read the full body first (`resp_body = resp.read()`), strip hop-by-hop headers (`transfer-encoding`, `connection`, `keep-alive`), then add `Content-Length: <len(resp_body)>` before sending. Same fix for error responses from `HTTPError`.
13. **xAI image API returns JPEG, not PNG** — `api.x.ai/v1/images/generations` returns images as `.jpeg` (check `mime_type` field in response). If your server hardcodes `.png` as the file extension, the file content won't match the extension and the MIME type from the static file server will be wrong (`image/png` for a JPEG). Always extract the extension from the xAI response URL or use `mime_type` to determine the correct file extension.
15. **Missing `do_OPTIONS` handler causes JSON.parse errors** — TitoCloud's `BaseHTTPRequestHandler` has no built-in CORS preflight support. When a browser makes a cross-origin POST (e.g., to `/image/api/generate`), it first sends an `OPTIONS` preflight request. Without a `do_OPTIONS` method, the handler returns `501 Unsupported method` with an **HTML error page** (`<!DOCTYPE html>...`). The browser's `fetch().then(r => r.json())` then tries to parse this HTML as JSON → `JSON.parse: unexpected non-whitespace character after JSON data at line 1 column 5` (the `C` in `<!DOC`). **Fix**: Add a `do_OPTIONS` method that returns `204 No Content` with proper CORS headers (`Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`). This is the #1 cause of "JSON parse" errors in proxied services.
16. **Mercury deploys to GitLab** — Mercury pushes UI designs to `gitlab.com/<GITHUB_USER>e/titocloud-ui` and `gitlab.com/<GITHUB_USER>e/toti-image`. Toti Image repo at GitHub `<GITHUB_USER>/toti-image` is the code backend; the frontend design lives on GitLab. When Mercury pushes a new version, `git pull` from GitLab and copy `image.html` → `/opt/data/toti-image/public/index.html`, `index.html` → `/opt/data/cloud-data/web/portal.html`, then restart both servers.