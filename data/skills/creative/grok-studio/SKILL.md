---
name: grok-studio
description: Self-hosted web UI for xAI Grok image generation and vision analysis. Quantic Design Language — deep-dark glass-morphism with purple-cyan-pink triad accents. Multi-file architecture (HTML+CSS+JS), proxied through TitoCloud.
version: 3.0.0
---

# Toti Image (Grok Studio v3)

Self-hosted web interface for xAI Grok/Aurora image generation and vision analysis.

## Architecture

- **Backend**: Node.js HTTP server (no Express) — proxies to `api.x.ai`
- **Frontend**: Multi-file — `index.html` + `style.css` + `app.js` — zero build step
- **Images**: Stored locally in `images/` directory, metadata in `data.json`
- **API Key**: Via `XAI_API_KEY` env var (default fallback hardcoded)
- **Proxy**: Integrated into TitoCloud on `/image/` path (port 8090)

## Quick Setup

```bash
# Server files at /opt/data/toti-image/
# - server.js          (Node.js backend)
# - public/index.html  (frontend structure)
# - public/style.css    (Quantic Design Language)
# - public/app.js       (frontend logic)
# - public/logo.svg     (logo)
# - images/            (generated images)
# - data.json          (image metadata + prompt history)

cd /opt/data/toti-image && node server.js
# Listens on port 3000 (direct) or 8090/image/ (via TitoCloud proxy)
```

### Access URLs

| Method | URL |
|--------|-----|
| Direct | `http://localhost:3000` |
| Tailscale | `http://<PRIVATE_IP>:3000` |
| TitoCloud | `http://<PRIVATE_IP>:8090/image/` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/generate` | Generate image. Body: `{prompt, model}`. Models: `grok-imagine-image` (Aurora), `grok-2-image` |
| POST | `/api/analyze` | Vision analysis. Body: `{image, prompt}`. image = base64 string or URL. Uses `grok-4-fast-non-reasoning` |
| GET | `/api/gallery` | List all generated images |
| POST | `/api/delete` | Delete image. Body: `{filename}` |
| GET | `/api/prompts` | Get prompt history |

## Design Language — Quantic

Mercury's Quantic Design Language, NOT Apple. Key differences from v2:

### Design Tokens
```css
:root {
  --bg-deep: #06060a;    /* NOT #000 — less harsh */
  --bg: #0a0a0f;
  --surface: #12121a;
  --surface-2: #1a1a25;
  --glass: rgba(255,255,255,0.04);
  --glass-border: rgba(255,255,255,0.08);
  --accent: #7c5cfc;     /* Purple, NOT Apple Blue */
  --accent-light: #a78bfa;
  --cyan: #22d3ee;
  --pink: #f472b6;
  --gradient: linear-gradient(135deg, #7c5cfc 0%, #22d3ee 50%, #f472b6 100%);
}
```

### Key Patterns
- **Ambient orbs**: Purple + cyan blurred gradients in body::before/::after (NOT CSS animation, pure CSS)
- **Glass-morphism cards**: `background: var(--glass); border: 1px solid var(--glass-border)` — hover adds glow
- **Shine-sweep button**: Gradient CTA with `::before` pseudo-element white sweep on hover
- **Staggered card entrance**: `animation: cardIn .4s ease-out both; animation-delay: index*30ms`
- **Spring easing**: `cubic-bezier(0.34,1.56,0.64,1)` for interactive elements
- **Navigation glass**: backdrop-filter blur(20px) saturate(180%) on rgba(6,6,10,0.7)
- **Tab bar glow**: Active tab icon gets `filter: drop-shadow(0 0 6px rgba(124,92,252,0.4))`
- **No borders on cards** — glass borders at 8% white, never solid borders

### Typography
- Font: Inter (Google Fonts CDN)
- Hero: clamp(32px, 8vw, 42px), weight 800, -1.5px tracking
- Body: 16-17px, weight 400, -0.2px tracking
- Labels: 12px, weight 600, uppercase, 0.06em tracking
- Gradient text for hero only: `background: var(--gradient); -webkit-background-clip: text`

## TitoCloud Proxy Integration

The app is proxied through TitoCloud (Python HTTP server on port 8090):

```python
# In titocloud.py — _proxy_to() method strips /image prefix
elif self.path == "/image" or self.path == "/image/":
    self._proxy_to("localhost", 3000, "/")
elif self.path.startswith("/image/"):
    target_path = self.path.replace("/image", "", 1)
    # ...proxies to port 3000 with path stripped
```

**Critical**: Frontend uses RELATIVE paths (`api/generate`, not `/api/generate`) so URLs work through both direct access and proxy.

## Pitfalls

- **xAI image URLs expire quickly** — server downloads them immediately and serves locally
- **Size parameter** — do NOT pass `size` to xAI API, returns 400
- **Vision analysis** — frontend sends base64 image data, server converts to data URI for xAI API
- **Delete API** — uses `{filename}` not `{id}` to match frontend
- **Model names** — `grok-imagine-image` (Aurora) works. `grok-2-image` may return 404.
- **Static file serving** — server must explicitly route `/style.css` and `/app.js` (not automatic directory serving)
- **TitoCloud proxy** — strips `/image` prefix before forwarding to port 3000. Frontend must use relative URLs.
- **Auth** — TitoCloud requires auth for external access; Tailscale IPs + localhost are trusted