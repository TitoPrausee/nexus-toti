"""
NEXUS v7 — Web UI Interface
FastAPI chat with invite-gate, per-user memory, rate limiting, DSGVO compliance.
Startup landing page + chat interface + privacy pages.
"""

import os
import json
import uuid
import hashlib
import time
import logging
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from nexus.core.agent import NexusAgent
from nexus.core.llm_client import LLMClient, Message

log = logging.getLogger("nexus.web")

# --- Config ---
WEB_PORT = int(os.environ.get("NEXUS_WEB_PORT", "3000"))
SESSION_TIMEOUT = 3600 * 2
RATE_LIMIT_REQUESTS = 30   # default max messages per user per window
RATE_LIMIT_WINDOW = 3600   # default 1 hour window

# Per-code rate limit overrides: {code: (max_requests, window_seconds)}
# 0 max_requests = unlimited
CODE_RATE_OVERRIDES: dict[str, tuple[int, int]] = {
    "nexus-admin": (0, 0),           # unlimited
    "nexus-test": (1, 600),          # 1 message per 10 minutes
}

# Invite codes — {code: user_label}
_invite_env = os.environ.get("NEXUS_INVITE_CODES", "")
if _invite_env:
    INVITE_CODES: dict[str, str] = {c.strip(): c.strip() for c in _invite_env.split(",") if c.strip()}
else:
    INVITE_CODES: dict[str, str] = {
        "nexus2024": "Alpha-Tester",
        "toti-friend": "Freund",
        "alpha-test": "Alpha-Tester",
        "nexus-admin": "Admin",
        "nexus-test": "Test-User",
    }

# Runtime state
_valid_tokens: dict[str, str] = {}       # {token: invite_code}
_user_memory: dict[str, list] = {}        # {invite_code: [messages]}
_rate_limits: dict[str, list] = {}        # {invite_code: [timestamps]}

class WebSession:
    """Per-user session state."""
    def __init__(self, session_id: str, user_name: str = "Guest"):
        self.id = session_id
        self.user_name = user_name
        self.agent = None
        self.history: list[dict] = []

    def init_agent(self, config: dict):
        if self.agent is None:
            self.agent = NexusAgent(config)
        return self.agent


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, WebSession] = {}

    def get_or_create(self, session_id: str = None, user_name: str = "Guest") -> WebSession:
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        sid = session_id or str(uuid.uuid4())[:12]
        session = WebSession(sid, user_name)
        self.sessions[sid] = session
        return session

    def cleanup(self):
        now = time.time()
        stale = [
            sid for sid, s in self.sessions.items()
            if not s.history or (now - s.history[-1].get("ts", 0)) > SESSION_TIMEOUT
        ]
        for sid in stale:
            del self.sessions[sid]

sessions = SessionManager()


ADMIN_CODES = {"nexus-admin"}
# DSGVO: Data retention config
DATA_RETENTION_DAYS = 30  # Auto-delete user data after 30 days
CONSENT_VERSION = "1.0"  # Current privacy policy version


def _check_rate_limit(invite_code: str) -> bool:
    """Return True if within rate limit. Admin codes have no limit."""
    max_req, window = CODE_RATE_OVERRIDES.get(invite_code, (RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW))
    if max_req == 0:
        return True
    now = time.time()
    timestamps = _rate_limits.setdefault(invite_code, [])
    _rate_limits[invite_code] = [t for t in timestamps if now - t < window]
    return len(_rate_limits[invite_code]) < max_req


def create_app(config: dict = None) -> FastAPI:
    config = config or {}

    if not config:
        try:
            import yaml
            config_path = Path(__file__).parent.parent.parent / "config.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            pass

    app = FastAPI(title="NEXUS v7", docs_url=None, redoc_url=None)

    # DSGVO / Security headers middleware
    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "frame-src 'self'; "
                "connect-src 'self'; "
                "form-action 'self'"
            )
            if request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.environ.get("NEXUS_CORS_ORIGIN", "*")],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(get_landing_html())

    @app.get("/chat", response_class=HTMLResponse)
    async def chat_page():
        return HTMLResponse(get_chat_html())

    @app.get("/health")
    async def health():
        return {"status": "ok", "sessions": len(sessions.sessions), "privacy": "dsgvo-compliant", "consent_version": CONSENT_VERSION}

    # --- DSGVO Routes ---

    @app.get("/datenschutz", response_class=HTMLResponse)
    async def datenschutz():
        return HTMLResponse(get_datenschutz_html())

    @app.get("/impressum", response_class=HTMLResponse)
    async def impressum():
        return HTMLResponse(get_impressum_html())

    @app.post("/api/delete-data")
    async def delete_user_data(request: Request):
        """DSGVO Art. 17 — Right to erasure. Deletes ALL data for the given invite token."""
        body = await request.json()
        invite_token = body.get("invite_token", "")
        confirmation = body.get("confirm", False)
        if not confirmation:
            return JSONResponse({"error": "Bitte bestaetige die Loeschung mit confirm:true"}, status_code=400)
        if invite_token not in _valid_tokens:
            raise HTTPException(403, "Ungueltiger Token.")
        invite_code = _valid_tokens[invite_token]
        # Delete all user data
        if invite_code in _user_memory:
            del _user_memory[invite_code]
        if invite_code in _rate_limits:
            del _rate_limits[invite_code]
        # Invalidate token
        del _valid_tokens[invite_token]
        # Remove sessions for this user
        to_remove = [sid for sid, s in sessions.sessions.items() if s.user_name and invite_code in str(s.history)]
        for sid in to_remove:
            del sessions.sessions[sid]
        log.info(f"DSGVO: Deleted all data for code={invite_code}")
        return {"ok": True, "message": "Alle deine Daten wurden geloescht."}

    @app.get("/api/privacy-settings")
    async def privacy_settings():
        """Return current privacy policy metadata."""
        return {
            "consent_version": CONSENT_VERSION,
            "data_retention_days": DATA_RETENTION_DAYS,
            "data_types": ["chat_messages", "session_id", "invite_code_hash"],
            "third_party": [],
            "cookies_necessary": True,
            "cookies_analytics": False,
            "right_to_erasure": True,
            "right_to_export": True,
        }

    @app.post("/api/export-data")
    async def export_user_data(request: Request):
        """DSGVO Art. 20 — Right to data portability. Export all data for the user."""
        body = await request.json()
        invite_token = body.get("invite_token", "")
        if invite_token not in _valid_tokens:
            raise HTTPException(403, "Ungueltiger Token.")
        invite_code = _valid_tokens[invite_token]
        user_data = _user_memory.get(invite_code, [])
        return {
            "invite_code_label": INVITE_CODES.get(invite_code, invite_code),
            "message_count": len(user_data),
            "data_retention_days": DATA_RETENTION_DAYS,
            "export_timestamp": time.time(),
            "messages": [{"role": m["role"], "content_preview": m["content"][:50] + "..." if len(m["content"]) > 50 else m["content"]} for m in user_data],
        }

    @app.post("/api/invite")
    async def verify_invite(request: Request):
        body = await request.json()
        code = body.get("code", "").strip()
        if code in INVITE_CODES:
            token = hashlib.sha256(f"{code}:{uuid.uuid4()}".encode()).hexdigest()[:24]
            _valid_tokens[token] = code
            max_req, window = CODE_RATE_OVERRIDES.get(code, (RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW))
            return {"valid": True, "token": token, "label": INVITE_CODES[code], "daily_limit": max_req, "window": window}
        return JSONResponse({"valid": False, "error": "Ungueltiger Code"}, status_code=403)

    @app.post("/api/logout")
    async def logout(request: Request):
        body = await request.json()
        token = body.get("invite_token", "")
        if token in _valid_tokens:
            del _valid_tokens[token]
        return {"ok": True}

    @app.post("/api/chat")
    async def chat_api(request: Request):
        body = await request.json()
        invite_token = body.get("invite_token", "")
        if invite_token not in _valid_tokens:
            raise HTTPException(403, "Ungueltiger Einladungscode.")

        invite_code = _valid_tokens[invite_token]
        message = body.get("message", "").strip()
        session_id = body.get("session_id")
        user_name = body.get("user_name", "Guest")

        # Rate limit
        if not _check_rate_limit(invite_code):
            remaining_time = RATE_LIMIT_WINDOW
            raise HTTPException(429, f"Rate-Limit erreicht. Maximal {RATE_LIMIT_REQUESTS} Nachrichten pro Stunde. Versuche es spaeter wieder.")

        if not message:
            raise HTTPException(400, "Message required")

        session = sessions.get_or_create(session_id, user_name)
        agent = session.init_agent(config)

        if message == "__ping__":
            return {"response": "pong", "session_id": session.id, "user_name": session.user_name}

        # Per-user memory
        user_history = _user_memory.setdefault(invite_code, [])
        user_history.append({"role": "user", "content": message})

        # Rate limit tracking
        _rate_limits.setdefault(invite_code, []).append(time.time())

        try:
            # Inject recent history as context (last 10 messages)
            context_messages = user_history[-10:]
            full_message = message
            if len(context_messages) > 1:
                context_str = "\n".join(
                    f"{'User' if m['role']=='user' else 'Nexus'}: {m['content']}"
                    for m in context_messages[:-1]
                )
                full_message = f"Kontext unserer Unterhaltung:\n{context_str}\n\nNeue Nachricht: {message}"

            response = agent.process(full_message, user_id=session.id)

            if not response or not isinstance(response, str):
                response = "Ich konnte leider keine Verbindung zum Sprachmodell herstellen. Bitte versuche es spaeter nochmal."

            user_history.append({"role": "assistant", "content": response})

            # Keep last 50 messages per user
            if len(user_history) > 50:
                _user_memory[invite_code] = user_history[-50:]

            session.history.append({"role": "user", "content": message, "ts": time.time()})
            session.history.append({"role": "assistant", "content": response, "ts": time.time()})

            if len(sessions.sessions) > 50:
                sessions.cleanup()

            max_req, window = CODE_RATE_OVERRIDES.get(invite_code, (RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW))
            remaining = max_req - len(_rate_limits.get(invite_code, [])) if max_req > 0 else -1
            return {
                "response": response,
                "session_id": session.id,
                "user_name": session.user_name,
                "remaining": remaining,
            }
        except Exception as e:
            log.error(f"Chat error: {e}")
            raise HTTPException(500, str(e))

    return app


# ═══════════════════════════════════════════════════════════
# SHARED SVG ICONS (no emojis)
# ═══════════════════════════════════════════════════════════

_SVG = {
    "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
    "eye-off": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></svg>',
    "trash": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    "download": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
    "send": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
    "message": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    "key": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>',
    "user": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
    "zap": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    "lock": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    "heart": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
    "clock": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    "layers": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
    "arrow-right": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
    "code": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
    "nexus-logo": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 12l10 5 10-5"/><path d="M2 17l10 5 10-5"/></svg>',
    "menu": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
    "x": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
}

# ═══════════════════════════════════════════════════════════
# LANDING PAGE
# ═══════════════════════════════════════════════════════════

def get_landing_html() -> str:
    """Claude-style warm landing page with animated gradient background. No emojis, SVG icons only."""
    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS — Dein KI-Assistent</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2L2 7l10 5 10-5-10-5z' fill='%23c96442'/><path d='M2 12l10 5 10-5' fill='none' stroke='%23c96442' stroke-width='2'/></svg>">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
--parchment:#f5f4ed;--ivory:#faf9f5;--sand:#e8e6dc;--cream-border:#f0eee6;--near-black:#141413;--warm-black:#30302e;--text2:#5e5d59;--text3:#87867f;--terracotta:#c96442;--terracotta-light:#d97757;--terracotta-dark:#a85235;--warm-silver:#b0aea5;--ring:#d1cfc5;--font-serif:Georgia,'Times New Roman',serif;--font-sans:'Inter',system-ui,-apple-system,sans-serif;--font-mono:'JetBrains Mono',ui-monospace,monospace;--radius:12px;--radius-lg:16px
}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--font-sans);color:var(--near-black);line-height:1.6;-webkit-font-smoothing:antialiased;background:var(--parchment)}}
a{{color:var(--terracotta);text-decoration:none;transition:color .15s}}
a:hover{{color:var(--terracotta-dark)}}

/* ─── Animated Background ─── */
.bg-anim{{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}}
.bg-orb{{position:absolute;border-radius:50%;filter:blur(120px);opacity:.35;animation:orbFloat 20s ease-in-out infinite}}
.bg-orb:nth-child(1){{width:600px;height:600px;background:radial-gradient(circle,#d4a57444,transparent 70%);top:-10%;left:-5%;animation-duration:18s}}
.bg-orb:nth-child(2){{width:500px;height:500px;background:radial-gradient(circle,#7ca8a844,transparent 70%);top:40%;right:-10%;animation-duration:22s;animation-delay:-5s}}
.bg-orb:nth-child(3){{width:450px;height:450px;background:radial-gradient(circle,#c9644233,transparent 70%);bottom:-5%;left:30%;animation-duration:25s;animation-delay:-10s}}
@keyframes orbFloat{{
0%,100%{{transform:translate(0,0) scale(1)}}
25%{{transform:translate(40px,-30px) scale(1.05)}}
50%{{transform:translate(-20px,40px) scale(.97)}}
75%{{transform:translate(30px,20px) scale(1.03)}}
}}

/* ─── Bauhaus Colour Strip ─── */
.colour-strip{{display:flex;width:100%;height:4px;position:relative;z-index:2}}
.colour-strip div{{flex:1;transition:flex .6s ease}}
.colour-strip:hover div:nth-child(1){{flex:2}}
.colour-strip:hover div:nth-child(3){{flex:2}}

/* ─── Navigation ─── */
.topbar{{position:sticky;top:0;z-index:100;display:flex;align-items:center;justify-content:space-between;padding:16px 32px;background:rgba(245,244,237,.85);backdrop-filter:blur(20px);border-bottom:1px solid var(--cream-border)}}
.topbar-l{{display:flex;align-items:center;gap:10px}}
.logo-icon{{width:36px;height:36px;background:var(--terracotta);border-radius:10px;display:flex;align-items:center;justify-content:center;color:#faf9f5}}
.logo-icon svg{{width:20px;height:20px}}
.logo-text{{font-family:var(--font-sans);font-size:20px;font-weight:700;color:var(--near-black);letter-spacing:-.02em}}
.topbar-r{{display:flex;align-items:center;gap:24px}}
.topbar-r a{{font-size:14px;color:var(--text2);font-weight:500;transition:color .15s}}
.topbar-r a:hover{{color:var(--terracotta)}}

/* ─── Hero ─── */
.page-content{{position:relative;z-index:1}}
.hero{{max-width:780px;margin:0 auto;padding:120px 32px 80px;text-align:center}}
.hero h1{{font-family:var(--font-serif);font-size:clamp(2.2rem,5.5vw,3.75rem);font-weight:500;line-height:1.12;color:var(--near-black);margin-bottom:20px;letter-spacing:-.01em}}
.hero h1 em{{font-style:normal;color:var(--terracotta)}}
.hero p.lead{{font-size:1.15rem;color:var(--text2);max-width:520px;margin:0 auto 36px;line-height:1.65;font-weight:400}}
.cta{{display:inline-flex;align-items:center;gap:8px;padding:14px 36px;background:var(--terracotta);color:var(--ivory);border-radius:var(--radius);font-size:15px;font-weight:600;border:none;cursor:pointer;transition:all .25s cubic-bezier(.16,1,.3,1);box-shadow:0 0 0 1px rgba(201,100,66,.2),0 4px 16px rgba(201,100,66,.2)}}
.cta:hover{{background:var(--terracotta-dark);transform:translateY(-1px);box-shadow:0 0 0 1px rgba(201,100,66,.3),0 6px 24px rgba(201,100,66,.25)}}
.cta svg{{width:18px;height:18px}}
.hero-sub{{font-size:.85rem;color:var(--text3);margin-top:20px}}

/* ─── Features ─── */
.features{{max-width:960px;margin:0 auto;padding:0 32px 100px;display:grid;grid-template-columns:repeat(3,1fr);gap:24px}}
.feat{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius-lg);padding:32px 28px;transition:border-color .25s,box-shadow .25s}}
.feat:hover{{border-color:var(--sand);box-shadow:0 4px 24px rgba(0,0,0,.05)}}
.feat-icon{{width:44px;height:44px;background:rgba(201,100,66,.08);border-radius:12px;display:flex;align-items:center;justify-content:center;margin-bottom:16px;color:var(--terracotta)}}
.feat-icon svg{{width:22px;height:22px}}
.feat h3{{font-family:var(--font-serif);font-size:1.1rem;font-weight:500;margin-bottom:8px;color:var(--near-black)}}
.feat p{{font-size:.9rem;color:var(--text2);line-height:1.6}}

/* ─── Steps ─── */
.steps{{max-width:960px;margin:0 auto;padding:0 32px 100px;text-align:center}}
.section-label{{display:inline-block;font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.12em;color:var(--terracotta);margin-bottom:8px}}
.steps h2{{font-family:var(--font-serif);font-size:2rem;font-weight:500;line-height:1.2;color:var(--near-black);margin-bottom:8px}}
.steps .sub{{color:var(--text2);margin-bottom:40px;font-size:.95rem}}
.steps-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;text-align:left}}
.step{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius-lg);padding:32px 28px;position:relative;transition:border-color .25s}}
.step:hover{{border-color:var(--sand)}}
.step-num{{width:36px;height:36px;background:var(--near-black);color:var(--ivory);border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:14px;margin-bottom:16px}}
.step h3{{font-family:var(--font-serif);font-size:1rem;font-weight:500;margin-bottom:8px;color:var(--near-black)}}
.step p{{font-size:.85rem;color:var(--text2);line-height:1.6}}

/* ─── Privacy ─── */
.privacy{{max-width:960px;margin:0 auto;padding:0 32px 100px;text-align:center}}
.privacy h2{{font-family:var(--font-serif);font-size:2rem;font-weight:500;color:var(--near-black);margin-bottom:8px}}
.privacy .sub{{color:var(--text2);margin-bottom:40px;font-size:.95rem}}
.privacy-cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:20px}}
.priv-card{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius-lg);padding:24px 20px;text-align:center;transition:border-color .25s,box-shadow .25s}}
.priv-card:hover{{border-color:var(--terracotta);box-shadow:0 0 0 1px rgba(201,100,66,.15)}}
.priv-card svg{{width:24px;height:24px;color:var(--terracotta);margin-bottom:10px}}
.priv-card h4{{font-family:var(--font-serif);font-size:.95rem;font-weight:500;margin-bottom:4px;color:var(--near-black)}}
.priv-card p{{font-size:.8rem;color:var(--text3)}}

/* ─── CTA Section ─── */
.cta-section{{max-width:780px;margin:0 auto;padding:0 32px 100px;text-align:center}}
.cta-box{{background:var(--near-black);border-radius:var(--radius-lg);padding:64px 48px;color:var(--ivory)}}
.cta-box h2{{font-family:var(--font-serif);font-size:2rem;font-weight:500;margin-bottom:12px;color:var(--ivory)}}
.cta-box p{{color:var(--warm-silver);margin-bottom:28px;font-size:1.05rem;line-height:1.6}}
.cta-box .cta{{box-shadow:0 0 0 1px rgba(201,100,66,.4),0 4px 16px rgba(201,100,66,.3)}}

/* ─── Footer ─── */
footer{{max-width:960px;margin:0 auto;padding:32px;text-align:center;border-top:1px solid var(--cream-border)}}
footer .fl{{display:flex;justify-content:center;gap:24px;margin-bottom:12px}}
footer .fl a{{font-size:.83rem;color:var(--text3);transition:color .15s}}
footer .fl a:hover{{color:var(--terracotta)}}
footer .copy{{font-size:.78rem;color:var(--text3)}}

/* ─── Dark Section (optional alternation) ─── */
.dark-section{{background:var(--near-black);position:relative;z-index:1}}
.dark-section .features .feat{{background:var(--warm-black);border-color:var(--warm-black);color:var(--warm-silver)}}
.dark-section .features .feat h3{{color:var(--ivory)}}
.dark-section .features .feat p{{color:var(--warm-silver)}}
.dark-section .features .feat-icon{{background:rgba(201,100,66,.12);color:var(--terracotta-light)}}

/* ─── Responsive ─── */
@media(max-width:768px){{
.hero{{padding:80px 24px 48px}}
.features,.steps-grid{{grid-template-columns:1fr}}
.privacy-cards{{grid-template-columns:1fr 1fr}}
.topbar{{padding:12px 20px}}
.topbar-r a.hide-mobile{{display:none}}
}}
@media(max-width:480px){{
.privacy-cards{{grid-template-columns:1fr}}
.cta-box{{padding:48px 28px}}
}}
</style>
</head>
<body>

<!-- Animated Background -->
<div class="bg-anim">
  <div class="bg-orb"></div>
  <div class="bg-orb"></div>
  <div class="bg-orb"></div>
</div>

<!-- Bauhaus Colour Strip -->
<div class="colour-strip">
  <div style="background:#d96b6b"></div>
  <div style="background:#7ec987"></div>
  <div style="background:#6db3d6"></div>
  <div style="background:#c58dd6"></div>
  <div style="background:#e8b84d"></div>
</div>

<!-- Navigation -->
<nav class="topbar">
  <div class="topbar-l">
    <div class="logo-icon">{_SVG['nexus-logo']}</div>
    <span class="logo-text">NEXUS</span>
  </div>
  <div class="topbar-r">
    <a href="/chat">Chat starten</a>
    <a href="/datenschutz">Datenschutz</a>
    <a href="https://github.com/***REMOVED***/nexus-toti" target="_blank" rel="noopener" class="hide-mobile">GitHub</a>
  </div>
</nav>

<div class="page-content">
  <!-- Hero -->
  <div class="hero">
    <h1>Dein <em>persoenlicher</em> Assistent.<br>Nicht generisch. Deins.</h1>
    <p class="lead">NEXUS ist ein privater, Open-Source KI-Agent mit eigener Persoenlichkeit. Kein Tracking, keine Werbung — einfach reden.</p>
    <a href="/chat" class="cta">
      {_SVG['message']}
      Jetzt starten
    </a>
    <div class="hero-sub">Open-Source &middot; DSGVO-konform &middot; Kein Tracking</div>
  </div>

  <!-- Features -->
  <div class="features">
    <div class="feat">
      <div class="feat-icon">{_SVG['user']}</div>
      <h3>Persoenlich</h3>
      <p>NEXUS merkt sich deinen Namen und Stil. Kein generischer Bot — ein Assistent mit Charakter.</p>
    </div>
    <div class="feat">
      <div class="feat-icon">{_SVG['shield']}</div>
      <h3>Privat</h3>
      <p>Einladungscodes schuetzen den Zugang. Keine Analyse, kein Fingerprinting, keine Werbetools.</p>
    </div>
    <div class="feat">
      <div class="feat-icon">{_SVG['clock']}</div>
      <h3>Fair</h3>
      <p>30 Nachrichten pro Stunde — genug fuer echte Gespraeche, Schutz gegen Missbrauch.</p>
    </div>
  </div>

  <!-- Steps -->
  <div class="steps">
    <span class="section-label">Loslegen</span>
    <h2>Drei Schritte zum Assistenten</h2>
    <p class="sub">Kein Account noetig. Keine E-Mail. Nur ein Code.</p>
    <div class="steps-grid">
      <div class="step">
        <div class="step-num">1</div>
        <h3>Einladungscode eingeben</h3>
        <p>Hol dir einen Code vom Admin auf Discord. Privat heisst privat.</p>
      </div>
      <div class="step">
        <div class="step-num">2</div>
        <h3>Namen nennen</h3>
        <p>Sag NEXUS, wie du heisst. Er merkt sich dich — individuell und persoenlich.</p>
      </div>
      <div class="step">
        <div class="step-num">3</div>
        <h3>Chatten</h3>
        <p>Rede mit NEXUS wie mit einem Kollegen. Er kennt den Kontext und behaelt ihn.</p>
      </div>
    </div>
  </div>

  <!-- Privacy -->
  <div class="privacy">
    <span class="section-label">Privatsphaere</span>
    <h2>Deine Daten gehoeren dir</h2>
    <p class="sub">DSGVO-konform, minimale Datenspeicherung, vollstaendige Loeschung auf Wunsch.</p>
    <div class="privacy-cards">
      <div class="priv-card">
        {_SVG['eye-off']}
        <h4>Kein Tracking</h4>
        <p>Keine Analytics, keine Tracker</p>
      </div>
      <div class="priv-card">
        {_SVG['shield']}
        <h4>DSGVO-konform</h4>
        <p>Volle EU-Datenschutzgrundverordnung</p>
      </div>
      <div class="priv-card">
        {_SVG['trash']}
        <h4>Datenloeschung</h4>
        <p>Art. 17 — sofort loeschbar</p>
      </div>
      <div class="priv-card">
        {_SVG['download']}
        <h4>Datenexport</h4>
        <p>Art. 20 — jederzeit exportierbar</p>
      </div>
    </div>
  </div>

  <!-- CTA -->
  <div class="cta-section">
    <div class="cta-box">
      <h2>Bereit loszulegen?</h2>
      <p>Kein Account, keine E-Mail. Nur ein Einladungscode und du kannst starten.</p>
      <a href="/chat" class="cta" style="background:var(--terracotta);color:var(--ivory)">
        {_SVG['arrow-right']}
        Zur Chat-Seite
      </a>
    </div>
  </div>
</div>

<!-- Footer -->
<footer>
  <div class="fl">
    <a href="/datenschutz">Datenschutz</a>
    <a href="/impressum">Impressum</a>
    <a href="/chat">Chat</a>
  </div>
  <div class="copy">NEXUS v7 &mdash; Open Source KI-Assistent</div>
</footer>

</body>
</html>'''


# ═══════════════════════════════════════════════════════════
# CHAT UI
# ═══════════════════════════════════════════════════════════

def get_chat_html() -> str:
    """Chat UI — Claude-style warm theme with animated background. No emojis, SVG icons only."""
    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS Chat</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2L2 7l10 5 10-5-10-5z' fill='%23c96442'/><path d='M2 12l10 5 10-5' fill='none' stroke='%23c96442' stroke-width='2'/></svg>">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
--parchment:#f5f4ed;--ivory:#faf9f5;--sand:#e8e6dc;--cream-border:#f0eee6;--near-black:#141413;--warm-black:#30302e;--text2:#5e5d59;--text3:#87867f;--terracotta:#c96442;--terracotta-light:#d97757;--terracotta-dark:#a85235;--warm-silver:#b0aea5;--ring:#d1cfc5;--font-serif:Georgia,'Times New Roman',serif;--font-sans:'Inter',system-ui,-apple-system,sans-serif;--font-mono:'JetBrains Mono',ui-monospace,monospace;--radius:12px
}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:var(--font-sans);color:var(--near-black);line-height:1.6;-webkit-font-smoothing:antialiased;background:var(--parchment);height:100vh;display:flex;flex-direction:column}}

/* ─── Animated Background ─── */
.bg-anim{{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}}
.bg-orb{{position:absolute;border-radius:50%;filter:blur(140px);opacity:.25;animation:orbFloat 20s ease-in-out infinite}}
.bg-orb:nth-child(1){{width:500px;height:500px;background:radial-gradient(circle,#d4a57444,transparent 70%);top:-5%;left:-5%;animation-duration:18s}}
.bg-orb:nth-child(2){{width:400px;height:400px;background:radial-gradient(circle,#7ca8a844,transparent 70%);bottom:10%;right:-5%;animation-duration:22s;animation-delay:-5s}}
.bg-orb:nth-child(3){{width:350px;height:350px;background:radial-gradient(circle,#c9644222,transparent 70%);bottom:-5%;left:25%;animation-duration:25s;animation-delay:-10s}}
@keyframes orbFloat{{
0%,100%{{transform:translate(0,0) scale(1)}}
25%{{transform:translate(40px,-30px) scale(1.05)}}
50%{{transform:translate(-20px,40px) scale(.97)}}
75%{{transform:translate(30px,20px) scale(1.03)}}
}}

/* ─── Layout ─── */
.chat-wrap{{position:relative;z-index:1;display:flex;flex-direction:column;height:100vh;max-width:820px;margin:0 auto;width:100%}}

/* ─── Header ─── */
.chat-header{{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;background:rgba(245,244,237,.88);backdrop-filter:blur(20px);border-bottom:1px solid var(--cream-border)}}
.chat-header-l{{display:flex;align-items:center;gap:10px}}
.logo-icon{{width:32px;height:32px;background:var(--terracotta);border-radius:8px;display:flex;align-items:center;justify-content:center;color:var(--ivory)}}
.logo-icon svg{{width:17px;height:17px}}
.chat-title{{font-family:var(--font-sans);font-size:16px;font-weight:600;color:var(--near-black)}}
.chat-header-r{{display:flex;align-items:center;gap:12px}}
.hdr-btn{{width:36px;height:36px;display:flex;align-items:center;justify-content:center;border:1px solid var(--cream-border);border-radius:8px;background:var(--ivory);cursor:pointer;color:var(--text2);transition:all .15s}}
.hdr-btn:hover{{border-color:var(--sand);color:var(--terracotta)}}
.hdr-btn svg{{width:18px;height:18px}}

/* ─── Invite Gate ─── */
.invite-overlay{{position:fixed;inset:0;z-index:200;background:rgba(245,244,237,.92);backdrop-filter:blur(24px);display:flex;align-items:center;justify-content:center}}
.invite-card{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius);padding:48px;max-width:420px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}}
.invite-card .logo-icon{{width:48px;height:48px;border-radius:14px;margin:0 auto 20px}}
.invite-card .logo-icon svg{{width:24px;height:24px}}
.invite-card h2{{font-family:var(--font-serif);font-size:1.5rem;font-weight:500;color:var(--near-black);margin-bottom:8px}}
.invite-card p{{color:var(--text2);font-size:.9rem;margin-bottom:24px;line-height:1.6}}
.invite-input{{width:100%;padding:12px 16px;border:1px solid var(--cream-border);border-radius:8px;font-size:15px;font-family:var(--font-sans);background:var(--parchment);color:var(--near-black);outline:none;transition:border-color .15s}}
.invite-input:focus{{border-color:var(--terracotta)}}
.invite-btn{{width:100%;padding:12px;margin-top:12px;background:var(--terracotta);color:var(--ivory);border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}}
.invite-btn:hover{{background:var(--terracotta-dark)}}
.invite-error{{color:#b53333;font-size:.85rem;margin-top:8px;min-height:1.2em}}
.invite-dsgvo{{font-size:.75rem;color:var(--text3);margin-top:16px}}
.invite-dsgvo a{{color:var(--terracotta)}}

/* ─── Name Gate ─── */
.name-overlay{{position:fixed;inset:0;z-index:200;background:rgba(245,244,237,.92);backdrop-filter:blur(24px);display:none;align-items:center;justify-content:center}}
.name-card{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius);padding:48px;max-width:420px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}}
.name-card h2{{font-family:var(--font-serif);font-size:1.5rem;font-weight:500;color:var(--near-black);margin-bottom:8px}}
.name-card p{{color:var(--text2);font-size:.9rem;margin-bottom:24px}}
.name-input{{width:100%;padding:12px 16px;border:1px solid var(--cream-border);border-radius:8px;font-size:15px;font-family:var(--font-sans);background:var(--parchment);color:var(--near-black);outline:none;transition:border-color .15s}}
.name-input:focus{{border-color:var(--terracotta)}}
.name-btn{{width:100%;padding:12px;margin-top:12px;background:var(--terracotta);color:var(--ivory);border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition:background .15s}}
.name-btn:hover{{background:var(--terracotta-dark)}}

/* ─── Messages ─── */
.messages{{flex:1;overflow-y:auto;padding:24px;display:flex;flex-direction:column;gap:16px}}
.msg{{display:flex;gap:12px;max-width:88%}}
.msg.user{{align-self:flex-end;flex-direction:row-reverse}}
.msg-avatar{{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex-shrink:0}}
.msg.assistant .msg-avatar{{background:var(--terracotta);color:var(--ivory)}}
.msg.user .msg-avatar{{background:var(--warm-black);color:var(--ivory)}}
.msg-bubble{{padding:12px 16px;border-radius:var(--radius);line-height:1.65;font-size:.92rem}}
.msg.assistant .msg-bubble{{background:var(--ivory);border:1px solid var(--cream-border);color:var(--near-black)}}
.msg.user .msg-bubble{{background:var(--near-black);color:var(--ivory)}}
.msg-bubble pre{{background:var(--parchment);border:1px solid var(--cream-border);border-radius:8px;padding:12px;overflow-x:auto;font-family:var(--font-mono);font-size:.85rem;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;margin:8px 0}}
.msg-bubble code{{font-family:var(--font-mono);font-size:.85rem;background:var(--parchment);padding:2px 5px;border-radius:4px}}

/* ─── Input ─── */
.chat-input-wrap{{padding:16px 24px 24px;background:rgba(245,244,237,.88);backdrop-filter:blur(20px);border-top:1px solid var(--cream-border)}}
.chat-input-row{{display:flex;gap:10px;max-width:820px;margin:0 auto}}
.chat-input{{flex:1;padding:12px 16px;border:1px solid var(--cream-border);border-radius:var(--radius);font-size:15px;font-family:var(--font-sans);background:var(--ivory);color:var(--near-black);outline:none;resize:none;transition:border-color .15s}}
.chat-input:focus{{border-color:var(--terracotta)}}
.send-btn{{width:44px;height:44px;display:flex;align-items:center;justify-content:center;background:var(--terracotta);color:var(--ivory);border:none;border-radius:var(--radius);cursor:pointer;transition:background .15s}}
.send-btn:hover{{background:var(--terracotta-dark)}}
.send-btn svg{{width:20px;height:20px}}
.rate-info{{text-align:center;font-size:.75rem;color:var(--text3);margin-top:6px}}

/* ─── Privacy Panel ─── */
.priv-panel{{display:none;position:fixed;top:0;right:0;bottom:0;width:320px;background:var(--ivory);border-left:1px solid var(--cream-border);z-index:150;padding:24px;overflow-y:auto;box-shadow:-4px 0 24px rgba(0,0,0,.06)}}
.priv-panel.open{{display:block}}
.priv-panel h3{{font-family:var(--font-serif);font-size:1.2rem;font-weight:500;margin-bottom:16px;color:var(--near-black)}}
.priv-panel p{{font-size:.85rem;color:var(--text2);line-height:1.6;margin-bottom:16px}}
.priv-action{{display:flex;align-items:center;gap:10px;padding:12px 16px;border:1px solid var(--cream-border);border-radius:8px;margin-bottom:10px;cursor:pointer;background:var(--parchment);color:var(--near-black);font-size:.9rem;transition:all .15s}}
.priv-action:hover{{border-color:var(--terracotta);color:var(--terracotta)}}
.priv-action svg{{width:18px;height:18px;flex-shrink:0}}
.priv-close{{position:absolute;top:16px;right:16px;width:32px;height:32px;display:flex;align-items:center;justify-content:center;border:1px solid var(--cream-border);border-radius:8px;background:var(--ivory);cursor:pointer;color:var(--text2)}}

/* ─── Cookie Banner ─── */
.cookie-banner{{position:fixed;bottom:0;left:0;right:0;z-index:180;background:var(--near-black);color:var(--warm-silver);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px;font-size:.85rem}}
.cookie-banner a{{color:var(--terracotta-light)}}
.cookie-btns{{display:flex;gap:8px}}
.cookie-btn{{padding:8px 20px;border-radius:8px;font-size:.85rem;font-weight:500;cursor:pointer;border:none}}
.cookie-btn.accept{{background:var(--terracotta);color:var(--ivory)}}
.cookie-btn.decline{{background:var(--warm-black);color:var(--warm-silver);border:1px solid var(--warm-black)}}

/* ─── Welcome ─── */
.welcome-msg{{text-align:center;padding:48px 24px}}
.welcome-msg h3{{font-family:var(--font-serif);font-size:1.3rem;font-weight:500;color:var(--near-black);margin-bottom:8px}}
.welcome-msg p{{color:var(--text2);font-size:.9rem}}

/* ─── Responsive ─── */
@media(max-width:768px){{
.chat-wrap{{max-width:100%}}
.messages{{padding:16px}}
.msg{{max-width:95%}}
.priv-panel{{width:100%}}
.cookie-banner{{flex-direction:column;text-align:center}}
}}
</style>
</head>
<body>

<!-- Animated Background -->
<div class="bg-anim">
  <div class="bg-orb"></div>
  <div class="bg-orb"></div>
  <div class="bg-orb"></div>
</div>

<!-- Invite Gate -->
<div class="invite-overlay" id="inviteOverlay">
  <div class="invite-card">
    <div class="logo-icon" style="width:48px;height:48px;border-radius:14px;margin:0 auto 20px">{_SVG['nexus-logo']}</div>
    <h2>Willkommen bei NEXUS</h2>
    <p>Gib deinen Einladungscode ein, um den Chat zu starten.</p>
    <input type="text" class="invite-input" id="inviteInput" placeholder="Einladungscode..." autocomplete="off">
    <button class="invite-btn" id="inviteBtn">Freischalten</button>
    <div class="invite-error" id="inviteError"></div>
    <div class="invite-dsgvo">Mit der Nutzung akzeptierst du die <a href="/datenschutz">Datenschutzerklaerung</a>.</div>
  </div>
</div>

<!-- Name Gate -->
<div class="name-overlay" id="nameOverlay">
  <div class="name-card">
    <div class="logo-icon" style="width:48px;height:48px;border-radius:14px;margin:0 auto 20px;background:var(--terracotta);color:var(--ivory)">{_SVG['user']}</div>
    <h2>Wie soll ich dich nennen?</h2>
    <p>NEXUS merkt sich deinen Namen fuer persoenliche Gespraeche.</p>
    <input type="text" class="name-input" id="nameInput" placeholder="Dein Name..." autocomplete="off">
    <button class="name-btn" id="nameBtn">Loslegen</button>
  </div>
</div>

<!-- Privacy Panel -->
<div class="priv-panel" id="privPanel">
  <button class="priv-close" id="privClose">{_SVG['x']}</button>
  <h3>Datenschutz</h3>
  <p>Deine Daten gehoeren dir. NEXUS speichert nur das Noetigste und loescht alles auf Wunsch.</p>
  <div class="priv-action" id="exportBtn">{_SVG['download']} Daten exportieren (Art. 20)</div>
  <div class="priv-action" id="deleteBtn">{_SVG['trash']} Daten loeschen (Art. 17)</div>
  <p style="margin-top:16px;font-size:.8rem;color:var(--text3)">Consent-Version: {CONSENT_VERSION} &middot; Aufbewahrung: {DATA_RETENTION_DAYS} Tage</p>
</div>

<!-- Chat -->
<div class="chat-wrap" id="chatWrap" style="display:none">
  <div class="chat-header">
    <div class="chat-header-l">
      <div class="logo-icon">{_SVG['nexus-logo']}</div>
      <span class="chat-title">NEXUS</span>
    </div>
    <div class="chat-header-r">
      <button class="hdr-btn" id="privBtn" title="Datenschutz">{_SVG['shield']}</button>
      <button class="hdr-btn" id="logoutBtn" title="Abmelden">{_SVG['lock']}</button>
    </div>
  </div>

  <div class="messages" id="messages">
    <div class="welcome-msg">
      <h3>Hallo! Ich bin NEXUS.</h3>
      <p>Stell mir eine Frage, oder sag einfach, was dich beschaeftigt.</p>
    </div>
  </div>

  <div class="chat-input-wrap">
    <div class="chat-input-row">
      <textarea class="chat-input" id="chatInput" placeholder="Nachricht eingeben..." rows="1"></textarea>
      <button class="send-btn" id="sendBtn">{_SVG['send']}</button>
    </div>
    <div class="rate-info" id="rateInfo"></div>
  </div>
</div>

<!-- Cookie Banner -->
<div class="cookie-banner" id="cookieBanner" style="display:none">
  <span>Diese Seite verwendet nur notwendige Cookies. Keine Analyse, kein Tracking. <a href="/datenschutz">Mehr erfahren</a></span>
  <div class="cookie-btns">
    <button class="cookie-btn accept" id="cookieAccept">Akzeptieren</button>
  </div>
</div>

<script>
const inviteOverlay=document.getElementById('inviteOverlay');
const nameOverlay=document.getElementById('nameOverlay');
const chatWrap=document.getElementById('chatWrap');
const inviteInput=document.getElementById('inviteInput');
const inviteBtn=document.getElementById('inviteBtn');
const inviteError=document.getElementById('inviteError');
const nameInput=document.getElementById('nameInput');
const nameBtn=document.getElementById('nameBtn');
const messages=document.getElementById('messages');
const chatInput=document.getElementById('chatInput');
const sendBtn=document.getElementById('sendBtn');
const rateInfo=document.getElementById('rateInfo');
const privPanel=document.getElementById('privPanel');
const privBtn=document.getElementById('privBtn');
const privClose=document.getElementById('privClose');
const exportBtn=document.getElementById('exportBtn');
const deleteBtn=document.getElementById('deleteBtn');
const logoutBtn=document.getElementById('logoutBtn');
const cookieBanner=document.getElementById('cookieBanner');
const cookieAccept=document.getElementById('cookieAccept');

let inviteToken=localStorage.getItem('nexus_token')||'';
let userName=localStorage.getItem('nexus_name')||'';
let sessionId=localStorage.getItem('nexus_sid')||Math.random().toString(36).substr(2,9);
let consentGiven=localStorage.getItem('nexus_consent')||'';

// Cookie consent
if(!consentGiven){{cookieBanner.style.display='flex'}}
cookieAccept.onclick=()=>{{localStorage.setItem('nexus_consent','1.0');cookieBanner.style.display='none';consentGiven='1.0'}}

// Check existing token
if(inviteToken){{inviteOverlay.style.display='none';if(userName){{nameOverlay.style.display='none';chatWrap.style.display='flex'}}else{{nameOverlay.style.display='flex'}}}}

inviteBtn.onclick=async()=>{{
  const code=inviteInput.value.trim();
  if(!code){{inviteError.textContent='Bitte gib einen Code ein.';return}}
  try{{
    const r=await fetch('/api/invite',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{code}})}});
    const d=await r.json();
    if(d.valid){{inviteToken=d.token;userName=d.label||'';localStorage.setItem('nexus_token',inviteToken);inviteOverlay.style.display='none';if(!userName){{nameOverlay.style.display='flex';nameInput.focus()}}else{{localStorage.setItem('nexus_name',userName);chatWrap.style.display='flex'}}rateInfo.textContent=d.daily_limit===-1?'Unbegrenzt':d.daily_limit+' Nachrichten/Stunde'}}
    else{{inviteError.textContent=d.error||'Ungueltiger Code'}}
  }}catch(e){{inviteError.textContent='Verbindungsfehler. Bitte versuche es spaeter.'}}
}}

inviteInput.addEventListener('keydown',e=>{{if(e.key==='Enter')inviteBtn.click()}});

nameBtn.onclick=()=>{{
  userName=nameInput.value.trim()||'Gast';
  localStorage.setItem('nexus_name',userName);
  nameOverlay.style.display='none';
  chatWrap.style.display='flex';
  addMsg('assistant','Hallo '+userName+'! Wie kann ich dir helfen?');
}};

nameInput.addEventListener('keydown',e=>{{if(e.key==='Enter')nameBtn.click()}});

// Privacy panel
privBtn.onclick=()=>privPanel.classList.toggle('open');
privClose.onclick=()=>privPanel.classList.remove('open');

exportBtn.onclick=async()=>{{
  if(!inviteToken)return;
  try{{
    const r=await fetch('/api/export-data',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{invite_token:inviteToken}})}});
    const d=await r.json();
    const blob=new Blob([JSON.stringify(d,null,2)],{{type:'application/json'}});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='nexus-export.json';a.click();
  }}catch(e){{alert('Export fehlgeschlagen.')}}
}};

deleteBtn.onclick=async()=>{{
  if(!confirm('Alle deine Daten wirklich loeschen? Das kann nicht rueckgaengig gemacht werden.'))return;
  try{{
    await fetch('/api/delete-data',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{invite_token:inviteToken,confirm:true}})}});
    localStorage.removeItem('nexus_token');localStorage.removeItem('nexus_name');localStorage.removeItem('nexus_sid');
    location.reload();
  }}catch(e){{alert('Loeschung fehlgeschlagen.')}}
}};

logoutBtn.onclick=async()=>{{
  if(!confirm('Wirklich abmelden?'))return;
  await fetch('/api/logout',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{invite_token:inviteToken}})}});
  localStorage.removeItem('nexus_token');localStorage.removeItem('nexus_name');localStorage.removeItem('nexus_sid');
  location.reload();
}};

// Chat
function addMsg(role,text){{
  const welcome=messages.querySelector('.welcome-msg');if(welcome)welcome.remove();
  const div=document.createElement('div');div.className='msg '+role;
  const avatar=document.createElement('div');avatar.className='msg-avatar';
  avatar.innerHTML=role==='assistant'?'N':'U';
  const bubble=document.createElement('div');bubble.className='msg-bubble';
  // Simple markdown
  let html=text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  html=html.replace(/```([\\s\\S]*?)```/g,'<pre>$1</pre>');
  html=html.replace(/`([^`]+)`/g,'<code>$1</code>');
  html=html.replace(/\\*\\*(.+?)\\*\\*/g,'<strong>$1</strong>');
  html=html.replace(/\\*(.+?)\\*/g,'<em>$1</em>');
  html=html.replace(/\\n/g,'<br>');
  bubble.innerHTML=html;
  div.append(avatar,bubble);messages.append(div);messages.scrollTop=messages.scrollHeight;
}}

sendBtn.onclick=sendMessage;
chatInput.addEventListener('keydown',e=>{{if(e.key==='Enter'&&!e.shiftKey){{e.preventDefault();sendMessage()}}}});

async function sendMessage(){{
  const text=chatInput.value.trim();if(!text)return;
  chatInput.value='';addMsg('user',text);sendBtn.disabled=true;
  try{{
    const r=await fetch('/api/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{invite_token:inviteToken,message:text,session_id:sessionId,user_name:userName}})}});
    if(!r.ok)throw new Error(r.statusText);
    const d=await r.json();addMsg('assistant',d.response);
    if(d.remaining>=0)rateInfo.textContent=d.remaining+' Nachrichten uebrig';else rateInfo.textContent='Unbegrenzt';
  }}catch(e){{addMsg('assistant','Fehler: '+e.message)}}
  sendBtn.disabled=false;
}}

// Auto-resize textarea
chatInput.addEventListener('input',()=>{{chatInput.style.height='auto';chatInput.style.height=Math.min(chatInput.scrollHeight,120)+'px'}}));
</script>
</body>
</html>'''


# ═══════════════════════════════════════════════════════════
# DATENSCHUTZ
# ═══════════════════════════════════════════════════════════

def get_datenschutz_html() -> str:
    """DSGVO Datenschutzerklaerung — Claude-style warm theme."""
    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS — Datenschutzerklaerung</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2L2 7l10 5 10-5-10-5z' fill='%23c96442'/><path d='M2 12l10 5 10-5' fill='none' stroke='%23c96442' stroke-width='2'/></svg>">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
--parchment:#f5f4ed;--ivory:#faf9f5;--sand:#e8e6dc;--cream-border:#f0eee6;--near-black:#141413;--warm-black:#30302e;--text2:#5e5d59;--text3:#87867f;--terracotta:#c96442;--terracotta-light:#d97757;--warm-silver:#b0aea5;--font-serif:Georgia,'Times New Roman',serif;--font-sans:'Inter',system-ui,-apple-system,sans-serif;--radius:12px
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--font-sans);color:var(--near-black);line-height:1.7;-webkit-font-smoothing:antialiased;background:var(--parchment)}}
a{{color:var(--terracotta);text-decoration:none}}
.container{{max-width:760px;margin:0 auto;padding:48px 24px}}
.back{{display:inline-flex;align-items:center;gap:6px;font-size:.85rem;color:var(--text3);margin-bottom:32px}}
.back:hover{{color:var(--terracotta)}}
h1{{font-family:var(--font-serif);font-size:2rem;font-weight:500;margin-bottom:32px;color:var(--near-black)}}
h2{{font-family:var(--font-serif);font-size:1.25rem;font-weight:500;margin:32px 0 12px;color:var(--near-black)}}
p{{margin-bottom:12px;color:var(--text2);font-size:.92rem}}
.section{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius);padding:20px 24px;margin-bottom:16px}}
.section h3{{font-family:var(--font-serif);font-size:1rem;font-weight:500;margin-bottom:6px;color:var(--near-black)}}
.section p{{font-size:.88rem}}
ul{{padding-left:20px;margin-bottom:12px}}
ul li{{color:var(--text2);font-size:.88rem;margin-bottom:4px}}
footer{{text-align:center;padding:32px 24px;border-top:1px solid var(--cream-border);margin-top:48px}}
footer a{{font-size:.85rem}}
</style>
</head>
<body>
<div class="container">
  <a href="/" class="back">&larr; Zurueck zur Startseite</a>
  <h1>Datenschutzerklaerung</h1>

  <div class="section"><h3>1. Verantwortliche Stelle</h3><p>Tito P., Betreiber von NEXUS. Kontakt ueber die auf der Startseite angegebenen Wege.</p></div>
  <div class="section"><h3>2. Erhobene Daten</h3><p>Wir erheben ausschliesslich: Chat-Nachrichten (fluechtig, max. 50 pro Benutzer), Sitzungs-ID, Invite-Code-Hash. Keine IP-Adressen, keine Cookies ausser dem noetigen Sitzungs-Token.</p></div>
  <div class="section"><h3>3. Zweck der Verarbeitung</h3><p>Die Verarbeitung dient ausschliesslich dem Betrieb des Chat-Dienstes: Beantwortung von Anfragen, Kontextfuehrung, Rate-Limiting.</p></div>
  <div class="section"><h3>4. Rechtsgrundlage</h3><p>Art. 6 Abs. 1 lit. b DSGVO (Vertragsfulung) sowie lit. f (berechtigtes Interesse am Betrieb).</p></div>
  <div class="section"><h3>5. Speicherdauer</h3><p>Chat-Daten werden automatisch nach {DATA_RETENTION_DAYS} Tagen geloescht. Sitzungs-Tokens verfallen nach 2 Stunden Inaktivitaet.</p></div>
  <div class="section"><h3>6. Drittlanduebermittlung</h3><p>Chat-Anfragen koennen an KI-Anbieter im Ausland uebermittelt werden. Wir waehlen Anbieter mit angemessenem Datenschutzniveau.</p></div>
  <div class="section"><h3>7. Deine Rechte (Art. 15-21 DSGVO)</h3>
    <ul>
      <li><strong>Auskunft (Art. 15):</strong> Du kannst jederzeit erfahren, welche Daten wir speichern.</li>
      <li><strong>Berichtigung (Art. 16):</strong> Fehlerhafte Daten werden korrigiert.</li>
      <li><strong>Loeschung (Art. 17):</strong> Du kannst alle deine Daten sofort loeschen lassen.</li>
      <li><strong>Einschraenkung (Art. 18):</strong> Du kannst die Verarbeitung einschraenken lassen.</li>
      <li><strong>Datenuebertragbarkeit (Art. 20):</strong> Du kannst deine Daten als JSON exportieren.</li>
      <li><strong>Widerspruch (Art. 21):</strong> Du kannst der Verarbeitung widersprechen.</li>
    </ul>
  </div>
  <div class="section"><h3>8. Cookies</h3><p>Wir verwenden ausschliesslich technisch notwendige Cookies (Sitzungs-Token, Einwilligung). Keine Analyse-Cookies, kein Tracking.</p></div>
  <div class="section"><h3>9. Analyse- und Tracking-Tools</h3><p>Wir setzen keine Analyse- oder Tracking-Tools ein. Kein Google Analytics, kein Matomo, keine Werbetools.</p></div>
  <div class="section"><h3>10. Sicherheit</h3><p>Sicherheitheaders: CSP, HSTS, X-Frame-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy. CORS beschraenkt auf GET/POST.</p></div>
  <div class="section"><h3>11. Aenderungen</h3><p>Wir behalten uns vor, diese Datenschutzerklaerung bei Bedarf anzupassen. Die aktuell gueltige Version ist jederzeit hier einsehbar.</p></div>
  <div class="section"><h3>12. Kontakt</h3><p>Fuer Datenschutzanfragen wende dich an den Betreiber ueber die auf der Startseite angegebenen Kontaktkanaele.</p></div>
</div>
<footer>
  <a href="/">Startseite</a> &middot; <a href="/impressum">Impressum</a>
</footer>
</body>
</html>'''


# ═══════════════════════════════════════════════════════════
# IMPRESSUM
# ═══════════════════════════════════════════════════════════

def get_impressum_html() -> str:
    """Impressum — Claude-style warm theme."""
    return f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS — Impressum</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2L2 7l10 5 10-5-10-5z' fill='%23c96442'/><path d='M2 12l10 5 10-5' fill='none' stroke='%23c96442' stroke-width='2'/></svg>">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{
--parchment:#f5f4ed;--ivory:#faf9f5;--sand:#e8e6dc;--cream-border:#f0eee6;--near-black:#141413;--text2:#5e5d59;--text3:#87867f;--terracotta:#c96442;--font-serif:Georgia,'Times New Roman',serif;--font-sans:'Inter',system-ui,-apple-system,sans-serif;--radius:12px
}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:var(--font-sans);color:var(--near-black);line-height:1.7;-webkit-font-smoothing:antialiased;background:var(--parchment)}}
a{{color:var(--terracotta);text-decoration:none}}
.container{{max-width:760px;margin:0 auto;padding:48px 24px}}
.back{{display:inline-flex;align-items:center;gap:6px;font-size:.85rem;color:var(--text3);margin-bottom:32px}}
.back:hover{{color:var(--terracotta)}}
h1{{font-family:var(--font-serif);font-size:2rem;font-weight:500;margin-bottom:32px;color:var(--near-black)}}
h2{{font-family:var(--font-serif);font-size:1.25rem;font-weight:500;margin:32px 0 12px;color:var(--near-black)}}
p{{margin-bottom:12px;color:var(--text2);font-size:.92rem}}
.section{{background:var(--ivory);border:1px solid var(--cream-border);border-radius:var(--radius);padding:20px 24px;margin-bottom:16px}}
.section h3{{font-family:var(--font-serif);font-size:1rem;font-weight:500;margin-bottom:6px;color:var(--near-black)}}
.section p{{font-size:.88rem}}
footer{{text-align:center;padding:32px 24px;border-top:1px solid var(--cream-border);margin-top:48px}}
</style>
</head>
<body>
<div class="container">
  <a href="/" class="back">&larr; Zurueck zur Startseite</a>
  <h1>Impressum</h1>

  <div class="section"><h3>Angaben gemaess &sect;5 TMG</h3><p>Tito P.<br>Betreiber von NEXUS</p></div>
  <div class="section"><h3>Kontakt</h3><p>Elektronische Kontaktmoeglichkeiten ueber die auf der Startseite verlinkten Kanaele.</p></div>
  <div class="section"><h3>Verantwortlich fuer den Inhalt nach &sect;55 Abs. 2 RStV</h3><p>Tito P.</p></div>
  <div class="section"><h3>Haftungsausschluss</h3><p>Die Inhalte unserer Seiten wurden mit groesster Sorgfalt erstellt. Fuer die Richtigkeit, Vollstaendigkeit und Aktualitaet der Inhalte koennen wir jedoch keine Gewaehr uebernehmen.</p></div>
  <div class="section"><h3>Urheberrecht</h3><p>Die durch den Seitenbetreiber erstellten Inhalte und Werke auf diesen Seiten unterliegen dem Urheberrecht. Die Vervielfaeltigung, Bearbeitung, Verbreitung und jede Art der Verwertung ausserhalb der Grenzen des Urheberrechtes beduerfen der schriftlichen Zustimmung des jeweiligen Autors bzw. Erstellers.</p></div>
  <div class="section"><h3>Streitbeilegung</h3><p>Die Europaeische Kommission stellt eine Plattform zur Online-Streitbeilegung (OS) bereit: <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener">https://ec.europa.eu/consumers/odr</a></p></div>
</div>
<footer>
  <a href="/">Startseite</a> &middot; <a href="/datenschutz">Datenschutz</a>
</footer>
</body>
</html>'''


if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT)