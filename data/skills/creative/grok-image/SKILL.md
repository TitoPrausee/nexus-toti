---
name: grok-image
description: Generate images using xAI Grok/Aurora model. 7-pillar prompting system for high-quality results.
version: 1.0.0
---

# Grok Image Generation (xAI Aurora)

Generate images using xAI's Grok/Aurora model via the API.

## API Endpoint

```
POST https://api.x.ai/v1/images/generations
Authorization: Bearer <XAI_API_KEY>
Content-Type: application/json

{
  "model": "grok-imagine-image",
  "prompt": "...",
  "n": 1
}
```

**Model names:** `grok-imagine-image` (Aurora, standard), `grok-2-image` (Grok 2), `grok-imagine-image-pro` (higher quality). Do NOT pass `size` parameter — xAI returns 400. No separate negative prompt field.

## Available Models (as of 2026-05)

**Image Generation:**
- `grok-imagine-image` — Aurora model, standard image generation
- `grok-2-image` — Grok 2 image model
- `grok-imagine-image-pro` — higher quality
- `grok-imagine-video` — video generation

**Vision (Image Analysis):**
- `grok-4-fast-non-reasoning` — supports image input via `image_url` content type
- Send messages with `content: [{"type": "image_url", "image_url": {"url": "..."}}, {"type": "text", "text": "describe"}]`

**Do NOT include `size` parameter** — the API rejects it with "Argument not supported: size".

## Vision / Image Analysis

When you need to analyze an image (generated or external), use grok-4-fast-non-reasoning with multimodal input:

```bash
curl -s "https://api.x.ai/v1/chat/completions" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"grok-4-fast-non-reasoning","messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"IMAGE_URL"}},{"type":"text","text":"Describe this image in detail"}]}],"max_tokens":500}'
```

Note: The Hermes Agent's built-in `vision_analyze` tool uses the active LLM (GLM-5.1:cloud) which does NOT support vision. Use Grok-4 as a workaround for image analysis.

## xAI API Key

The API key was rotated in May 2026. Current key: `<XAI_API_KEY>`. If this key stops working, ask Tito for a new one — xAI keys rotate.

## Image Analysis (Vision) — CRITICAL: GLM-5.1 does NOT support vision

```python
import json, subprocess, base64

XAI_KEY = "<XAI_API_KEY>"

# For local images: encode as base64 and use data URI
with open("image.jpeg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

payload = {
    "model": "grok-4-fast-non-reasoning",
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": "Describe this image in detail"}
    ]}],
    "max_tokens": 800
}

# IMPORTANT: Write payload to file first — base64 images are too large for inline curl args
with open("/tmp/vision-payload.json", "w") as f:
    json.dump(payload, f)

result = subprocess.run(
    ["curl", "-s", "https://api.x.ai/v1/chat/completions",
     "-H", f"Authorization: Bearer {XAI_KEY}",
     "-H", "Content-Type: application/json",
     "-d", "@/tmp/vision-payload.json"],
    capture_output=True, text=True, timeout=60
)
```

For images with URLs: use `{"url": "https://..."}` instead of base64 data URI.
Available vision-capable model: `grok-4-fast-non-reasoning`. GLM-5.1 does NOT support vision.

## Response Format

## xAI Image URLs — CRITICAL: xAI returns .jpeg (NOT .png)

xAI's `grok-imagine-image` model returns `mime_type: image/jpeg` and URLs ending in `.jpeg`.
**Never hardcode `.png` as output extension.** Extract extension from URL or use MIME type:
```javascript
const urlExt = imgUrl.match(/\.(png|jpe?g|webp|gif)(\?|$)/i);
const mimeExt = json.data[0].mime_type === 'image/jpeg' ? '.jpg' : json.data[0].mime_type === 'image/webp' ? '.webp' : '.png';
const ext = urlExt ? `.${urlExt[1].toLowerCase()}` : mimeExt;
```

## Response Format (Image Gen)

Returns JSON with `data[0].url`

## Image Delivery in Telegram

To send generated images in Telegram chat, include `MEDIA:/absolute/path/to/file.jpeg` in your response text. Do NOT use `send_message` — it only sends text.

## Prompt Engineering — The 7 Pillars (ALWAYS address all)

1. **Subject** — Hyperspecific. Not "a woman" but "Model, 30s, slightly angled posture, gaze shifted left, loose shoulders, matte olive jacket". Include posture, expression, materials.

2. **Composition** — Which shot? Close-up / medium / full body? Camera angle? Where in frame? Rule of Thirds, never always centered.

3. **Light (MOST IMPORTANT)** — Never just "cinematic lighting". Specify: source, direction, hardness, temperature, shadow behavior. E.g.: "harsh direct frontal strobe, warm 5500K, no facial shadow, hard specular highlights on forehead"

4. **Color Palette** — 2-4 colors with saturation. "high-saturation royal blue backdrop, warm honey skin tones, matte black outfit"

5. **Environment/Backdrop** — Not "nature" or "city". Concrete textures: "hand-painted flat panel, cracked plaster wall, raw concrete"

6. **Texture & Detail** — Grok over-smooths. Always: "visible natural pores, minor skin imperfections, no retouching". Material-specific: "sequins catch light individually, visible stitching on jacket"

7. **Aesthetic Reference** — One era, one medium, one mood. "1990s Helmut Newton, 35mm grain, fashion editorial"

## Grok-Specific Tips

- ALWAYS append: `photo-realistic, candid, natural skin texture, no retouching` — prevents plastic skin
- Negative keywords IN the prompt (no separate field): `not airbrushed, not symmetrical, not stock photo`
- Grok is strong at lighting and background composition, weak at hands and specific facial features. Hide hands or write "hands behind back" if possible
- Model names: `grok-imagine-image` (Aurora), `grok-2-image` (Grok 2), `grok-imagine-image-pro` (pro), `grok-imagine-video` (video).
- Available models via `GET https://api.x.ai/v1/models`: grok-3, grok-4-*, grok-imagine-image, grok-imagine-image-pro, grok-imagine-video

## What NOT to Write

- Do NOT use: beautiful, stunning, ultra-realistic, 8K, masterpiece, highly detailed (generic AI slop)
- Instead use: physically meaningful adjectives — "weathered, angular, lacquered, sun-bleached, high-contrast"

## Response Format

Returns JSON with `data[0].url` containing the image URL. Download and save to file.

## UI Mockup Generation Workflow

For generating UI/app mockups iteratively:

1. **First prompt** — Generate broad layout (shelf+player, overall structure)
2. **Vision-analyze** — Use `grok-4-fast-non-reasoning` to evaluate: what works, what's missing, what to improve
3. **Refined prompt** — Generate focused mockup addressing gaps (e.g., interaction animations, specific panels)
4. **Repeat** — One more round for user-requested changes (new feature, different angle)

**Mockup prompt tips specific to UI:**
- Always specify "UI design mockup" and "not a real photo — clearly a UI design" to prevent photorealistic confusion
- Specify layout percentages: "LEFT (60%)... RIGHT (40%)..."
- Describe interaction states: "mid-animation being pulled out", "lid open waiting to receive"
- Reference design quality: "Dribbble quality", "Figma-quality design"
- For multi-view mockups, generate separate images per view rather than cramming everything into one

**Pitfall:** Downloaded images <50KB are usually broken/error images. Re-generate with a slightly adjusted prompt if this happens.
**Pitfall:** `urllib` may get 403 on image downloads — use `curl -sL` instead.
**Pitfall:** GLM-5.1 does NOT support vision input. For vision analysis, route through a vision-capable model.

## Toti Image v2 App

Self-hosted web UI at `/opt/data/toti-image/` with zero dependencies (pure Node.js HTTP server, no Express).

**Architecture:**
- `server.js` — Pure Node HTTP server on port 3000
- `public/index.html` — Centered app layout (max-width 480px)
- `public/style.css` — Light Paper Design (warm white `#f8f7f4`, ink `#1a1a1a`, purple accent)
- `public/app.js` — Frontend logic
- `public/logo.svg` — App icon
- `images/` — Local image storage
- `data.json` — Prompt history and image metadata

**Features:** Image generation (Grok Aurora + Grok 2), 8 style presets, Vision analysis (grok-4-fast-non-reasoning with base64 support), Gallery, Prompt history, Download/Share, Detail view with delete

**Design:** Light Paper — warm white backgrounds, subtle shadows, ink text, single purple accent (`#7c5cfc`). NOT dark/Glass/Apple.

**Integration:** Proxied through TitoCloud at `http://<PRIVATE_IP>:8090/image/` — all frontend URLs use relative paths (`api/generate` not `/api/generate`) so proxy path stripping works. TitoCloud strips `/image` prefix and forwards to `localhost:3000` via `_proxy_to()` method.

**Start:**
```bash
cd /opt/data/toti-image && node server.js
# Access: http://localhost:3000/ (direct) or http://<PRIVATE_IP>:8090/image/ (via TitoCloud)
```

**Key Pitfalls:**
- Frontend MUST use relative API URLs (`api/generate`) not absolute (`/api/generate`) — otherwise proxy breaks
- When adding new static files, add explicit routes in `server.js` router (e.g. `style.css`, `app.js`)
- When adding new API routes, update both server.js AND the `_proxy_to` routes in TitoCloud's `titocloud.py`
- Server `delete` API expects `{filename: "..."}` not `{id: "..."}`
- Server `analyze` API expects `{image: "base64_or_url", prompt: "..."}` and returns `{response: "..."}`
- Analyze endpoint auto-detects: if image starts with `http` → URL, else → `data:image/png;base64,{image}`
- ALWAYS clarify design direction with user BEFORE building frontend — preferences vary widely (dark vs light, glass vs paper, centered vs full-width)

## CLI Usage

```bash
# IMPORTANT: Write payload to file to avoid arg length limits with complex prompts
echo '{"model":"grok-imagine-image","prompt":"YOUR_PROMPT","n":1}' > /tmp/grok-payload.json
curl -s "https://api.x.ai/v1/images/generations" \
  -H "Authorization: Bearer $XAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d @/tmp/grok-payload.json | jq -r '.data[0].url'
```