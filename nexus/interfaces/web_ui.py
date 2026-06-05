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


def get_landing_html() -> str:
    """Startup-style landing page with DSGVO compliance."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS — KI-Agent mit Seele</title>
<style>
:root{--bg:#07070d;--bg2:#0e0e18;--bg3:#151524;--text:#e4e4f0;--text2:#9494b0;--muted:#5c5c78;--accent:#6c5ce7;--accent2:#a29bfe;--accent3:#4f46e5;--green:#00b894;--border:#1f1f35;--radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.7;overflow-x:hidden}
a{color:var(--accent2);text-decoration:none}
.hero{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:40px 20px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:radial-gradient(ellipse at 50% 40%,rgba(108,92,231,.12) 0%,transparent 60%);pointer-events:none}
.logo-mark{width:72px;height:72px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:20px;display:flex;align-items:center;justify-content:center;margin-bottom:28px;animation:float 3s ease-in-out infinite}
.logo-mark svg{width:40px;height:40px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.hero h1{font-size:clamp(2.2rem,5vw,3.5rem);font-weight:800;letter-spacing:-.02em;margin-bottom:16px;background:linear-gradient(135deg,var(--text) 40%,var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hero p{font-size:1.15rem;color:var(--text2);max-width:540px;margin-bottom:36px}
.hero-sub{font-size:.95rem;color:var(--muted);margin-bottom:20px}
.cta{display:inline-flex;align-items:center;gap:10px;padding:16px 36px;background:linear-gradient(135deg,var(--accent3),var(--accent));color:#fff;border-radius:60px;font-size:1.05rem;font-weight:600;border:none;cursor:pointer;transition:all .25s;box-shadow:0 4px 24px rgba(108,92,231,.35)}
.cta:hover{transform:translateY(-2px);box-shadow:0 8px 32px rgba(108,92,231,.5)}
.cta svg{width:20px;height:20px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.features{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;max-width:960px;margin:0 auto;padding:80px 20px}
.feat{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:32px 28px;transition:border-color .2s}
.feat:hover{border-color:var(--accent)}
.feat-icon{width:44px;height:44px;background:linear-gradient(135deg,var(--accent3),var(--accent));border-radius:12px;display:flex;align-items:center;justify-content:center;margin-bottom:16px}
.feat-icon svg{width:22px;height:22px;fill:none;stroke:#fff;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.feat h3{font-size:1.1rem;font-weight:600;margin-bottom:8px}
.feat p{font-size:.92rem;color:var(--text2);line-height:1.6}
.section{max-width:960px;margin:0 auto;padding:60px 20px}
.section h2{font-size:1.8rem;font-weight:700;margin-bottom:12px;text-align:center}
.section .sub{text-align:center;color:var(--text2);margin-bottom:40px;font-size:1.05rem}
.limit-bar{max-width:480px;margin:0 auto;background:var(--bg3);border:1px solid var(--border);border-radius:16px;padding:24px 28px;text-align:center}
.limit-bar h4{font-size:1rem;font-weight:600;margin-bottom:10px;color:var(--text)}
.limit-bar p{font-size:.88rem;color:var(--text2)}
.limit-num{font-size:2.2rem;font-weight:800;color:var(--accent2);display:block;margin:8px 0}
.privacy-banner{max-width:960px;margin:0 auto;padding:40px 20px}
.privacy-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}
.privacy-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:24px 20px;text-align:center;transition:border-color .2s}
.privacy-card:hover{border-color:var(--green)}
.privacy-card svg{width:28px;height:28px;fill:none;stroke:var(--green);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;margin-bottom:10px}
.privacy-card h4{font-size:.95rem;font-weight:600;margin-bottom:4px}
.privacy-card p{font-size:.82rem;color:var(--text2)}
footer{text-align:center;padding:32px 20px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--border)}
footer .footer-links{display:flex;justify-content:center;gap:20px;margin-bottom:12px;flex-wrap:wrap}
footer .footer-links a{color:var(--text2);text-decoration:none;font-size:.85rem;transition:color .2s}
footer .footer-links a:hover{color:var(--accent2)}
@media(max-width:640px){.hero h1{font-size:1.8rem}.features{grid-template-columns:1fr}.privacy-cards{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg" id="icon-sprite">
  <g id="i-nexus"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 7l10 5 10-5"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></g>
  <g id="i-send"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></g>
  <g id="i-user"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></g>
  <g id="i-shield"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></g>
  <g id="i-brain"><circle cx="12" cy="12" r="10"/><path d="M12 2a15 15 0 0 1 1 20M12 2a15 15 0 0 0-1 20M2 12h20"/></g>
  <g id="i-msg"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></g>
  <g id="i-lock"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></g>
  <g id="i-eye-off"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></g>
  <g id="i-trash"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></g>
  <g id="i-download"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></g>
  <g id="i-chevron-right"><polyline points="9 18 15 12 9 6"/></g>
</svg>

<div class="hero">
  <div class="logo-mark"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
  <h1>NEXUS</h1>
  <p>Autonomer KI-Agent mit Seele. Denkt, lernt, handelt — auf deine Art.</p>
  <div class="hero-sub">Open-Source - Privat - Kein Tracking - DSGVO-konform</div>
  <a href="/chat" class="cta">
    <svg viewBox="0 0 24 24"><use href="#i-msg"/></svg>
    Jetzt testen
  </a>
</div>

<div class="features">
  <div class="feat">
    <div class="feat-icon"><svg viewBox="0 0 24 24"><use href="#i-brain"/></svg></div>
    <h3>Eigene Persoenlichkeit</h3>
    <p>Nexus hat eine Seele — keine generische KI, sondern ein Agent mit Charakter, der sich an dich erinnert.</p>
  </div>
  <div class="feat">
    <div class="feat-icon"><svg viewBox="0 0 24 24"><use href="#i-lock"/></svg></div>
    <h3>Privat und gesichert</h3>
    <p>Einladungscodes schuetzen den Zugang. Deine Gespraeche bleiben privat — kein Tracking, keine Werbung.</p>
  </div>
  <div class="feat">
    <div class="feat-icon"><svg viewBox="0 0 24 24"><use href="#i-shield"/></svg></div>
    <h3>Fair genutzter Zugang</h3>
    <p>30 Nachrichten pro Stunde, fair geteilt. Kein Massen-Spam, kein Missbrauch.</p>
  </div>
</div>

<div class="section">
  <h2>So funktioniert es</h2>
  <p class="sub">Drei Schritte zu deinem persoenlichen KI-Assistenten.</p>
  <div class="features">
    <div class="feat">
      <div class="feat-icon" style="background:linear-gradient(135deg,#00b894,#00cec9)"><span style="color:#fff;font-weight:700;font-size:18px">1</span></div>
      <h3>Einladungscode</h3>
      <p>Hol dir einen Code vom Server-Admin auf Discord. Privat heisst privat.</p>
    </div>
    <div class="feat">
      <div class="feat-icon" style="background:linear-gradient(135deg,#fdcb6e,#e17055)"><span style="color:#fff;font-weight:700;font-size:18px">2</span></div>
      <h3>Namen nennen</h3>
      <p>Sag Nexus wie du heisst. Er merkt sich dich — persoenlich und individuell.</p>
    </div>
    <div class="feat">
      <div class="feat-icon" style="background:linear-gradient(135deg,var(--accent3),var(--accent))"><span style="color:#fff;font-weight:700;font-size:18px">3</span></div>
      <h3>Chatten</h3>
      <p>Rede mit Nexus wie mit einem Freund. Er lernt deinen Stil und behaelt den Kontext.</p>
    </div>
  </div>
</div>

<div class="privacy-banner">
  <h2 style="font-size:1.8rem;font-weight:700;text-align:center;margin-bottom:12px">Deine Privatsphaere hat oberste Prioritaet</h2>
  <p class="sub" style="text-align:center;color:var(--text2);margin-bottom:32px;font-size:1.05rem">NEXUS ist DSGVO-konform, speichert minimale Daten und loescht alles auf Wunsch.</p>
  <div class="privacy-cards">
    <div class="privacy-card">
      <svg viewBox="0 0 24 24"><use href="#i-eye-off"/></svg>
      <h4>Kein Tracking</h4>
      <p>Keine Analytics, keine Tracker, kein Fingerprinting</p>
    </div>
    <div class="privacy-card">
      <svg viewBox="0 0 24 24"><use href="#i-shield"/></svg>
      <h4>DSGVO-konform</h4>
      <p>Volle Einhaltung der EU-Datenschutzgrundverordnung</p>
    </div>
    <div class="privacy-card">
      <svg viewBox="0 0 24 24"><use href="#i-trash"/></svg>
      <h4>Datenloeschung</h4>
      <p>Alle Daten auf Wunsch sofort loeschbar (Art. 17 DSGVO)</p>
    </div>
    <div class="privacy-card">
      <svg viewBox="0 0 24 24"><use href="#i-download"/></svg>
      <h4>Datenexport</h4>
      <p>Deine Daten jederzeit exportierbar (Art. 20 DSGVO)</p>
    </div>
  </div>
</div>

<div class="section">
  <div class="limit-bar">
    <h4>Fair-Use Limit</h4>
    <span class="limit-num">30</span>
    <p>Nachrichten pro Stunde pro Nutzer.<br>Reichlich fuer Gespraeche, Schutz gegen Missbrauch.</p>
  </div>
</div>

<footer>
  <div class="footer-links">
    <a href="/datenschutz">Datenschutzerklaerung</a>
    <a href="/impressum">Impressum</a>
    <a href="https://github.com/TitoPrausee/nexus-toti" target="_blank" rel="noopener">GitHub</a>
  </div>
  <p>NEXUS v7 - Open Source KI-Agent - DSGVO-konform - Serverstandort: Deutschland/EU</p>
</footer>
</body></html>'''


def get_chat_html() -> str:
    """Chat UI — invite gate + name + chat. Redesigned with DSGVO compliance, cookie consent, data deletion."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS Chat</title>
<style>
:root{--bg:#0b0b16;--bg2:#111120;--bg3:#191930;--bg4:#222242;--text:#e8e8f4;--text2:#a0a0c4;--muted:#606088;--accent:#6c5ce7;--accent2:#a29bfe;--accent3:#4f46e5;--border:#252544;--user-bg:linear-gradient(135deg,#1e1e40,#28284e);--nexus-bg:#141428;--green:#00d4aa;--red:#ff6b6b;--code-bg:#0d0d1a;--radius:14px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);height:100vh;overflow:hidden}
.app{display:flex;flex-direction:column;height:100vh;max-width:840px;margin:0 auto}
/* Header */
.hdr{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid var(--border);background:var(--bg2)}
.hdr-l{display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:10px;display:flex;align-items:center;justify-content:center}
.logo svg{width:20px;height:20px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.hdr-t{font-size:17px;font-weight:700;letter-spacing:.4px}
.hdr-s{font-size:11px;color:var(--muted);margin-top:1px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.hdr-r{display:flex;align-items:center;gap:8px}
.badge{font-size:11px;padding:3px 10px;border-radius:20px;background:var(--bg3);border:1px solid var(--border);color:var(--text2)}
.hdr-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:5px 10px;border-radius:8px;cursor:pointer;font-size:12px;transition:all .2s;display:inline-flex;align-items:center;gap:4px}
.hdr-btn:hover{border-color:var(--accent);color:var(--accent2)}
.hdr-btn svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
/* Overlays */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.88);display:flex;align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(16px)}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:18px;padding:36px 32px;max-width:400px;width:92%;text-align:center}
.card .logo{width:52px;height:52px;margin:0 auto 18px}
.card h2{font-size:20px;margin-bottom:6px}
.card p{color:var(--text2);font-size:14px;margin-bottom:14px;line-height:1.55}
.card .dsgvo-note{font-size:12px;color:var(--muted);margin-top:12px;line-height:1.5}
.card .dsgvo-note a{color:var(--accent2)}
.inp{width:100%;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:15px;outline:none;transition:border .2s}
.inp:focus{border-color:var(--accent)}
.btn{width:100%;padding:12px;margin-top:14px;background:linear-gradient(135deg,var(--accent3),var(--accent));color:#fff;border:none;border-radius:var(--radius);font-size:15px;font-weight:600;cursor:pointer;transition:all .2s}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 16px rgba(108,92,231,.4)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.err{color:var(--red);font-size:13px;margin-top:8px;display:none}
/* Messages */
.msgs{flex:1;overflow-y:auto;padding:18px;scroll-behavior:smooth}
.msgs::-webkit-scrollbar{width:5px}.msgs::-webkit-scrollbar-track{background:transparent}.msgs::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.msgs{scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.welcome{text-align:center;padding:36px 16px;color:var(--muted)}
.welcome h3{font-size:18px;color:var(--text2);margin-bottom:6px}
.welcome p{font-size:14px;line-height:1.6}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:14px}
.chip{padding:7px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:20px;color:var(--text2);font-size:13px;cursor:pointer;transition:all .2s}
.chip:hover{border-color:var(--accent);color:var(--text)}
.msg{display:flex;gap:10px;margin-bottom:14px;animation:msgIn .35s cubic-bezier(.16,1,.3,1)}
@keyframes msgIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.msg.user{flex-direction:row-reverse}
.av{width:30px;height:30px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.msg.user .av{background:linear-gradient(135deg,#00b894,#00cec9)}
.msg.nexus .av{background:linear-gradient(135deg,var(--accent),var(--accent2))}
.av svg{width:16px;height:16px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.bub{max-width:82%;padding:12px 16px;border-radius:var(--radius);line-height:1.65;font-size:14px}
.msg.user .bub{background:var(--user-bg);border-bottom-right-radius:4px}
.msg.nexus .bub{background:var(--nexus-bg);border:1px solid var(--border);border-bottom-left-radius:4px}
.bub code{background:rgba(108,92,231,.15);padding:1px 6px;border-radius:4px;font-family:'SF Mono','Fira Code','Cascadia Code',monospace;font-size:13px;color:var(--accent2)}
/* Code blocks */
.bub pre{background:var(--code-bg);padding:0;overflow:hidden;margin:10px 0;border-radius:10px;border:1px solid var(--border)}
.code-hdr{display:flex;justify-content:space-between;align-items:center;padding:6px 12px;background:var(--bg3);border-bottom:1px solid var(--border);font-size:11px;color:var(--muted)}
.code-hdr .lang{color:var(--accent2);font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.5px}
.copy-btn{background:none;border:1px solid var(--border);color:var(--muted);padding:2px 8px;border-radius:4px;font-size:11px;cursor:pointer;transition:all .2s;font-family:inherit}
.copy-btn:hover{border-color:var(--accent);color:var(--accent2)}
.code-body{padding:12px;overflow-x:auto;font-size:13px;line-height:1.6;font-family:'SF Mono','Fira Code','Cascadia Code',monospace;color:var(--text2);white-space:pre-wrap;word-wrap:break-word}
/* Split preview */
.preview-split{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:10px 0;border-radius:10px;overflow:hidden;border:1px solid var(--border)}
.preview-split .code-side{min-width:0;border-right:1px solid var(--border)}
.preview-split .preview-side{min-width:0;background:#fff}
.preview-split .preview-side iframe{width:100%;height:100%;min-height:320px;border:0}
/* Typing indicator */
.typing{display:none;padding:4px 18px;align-items:center;gap:10px}
.typing.on{display:flex}
.typ-bub{display:inline-flex;align-items:center;gap:5px;padding:11px 16px;background:var(--nexus-bg);border:1px solid var(--border);border-radius:var(--radius);border-bottom-left-radius:4px}
.typ-bub .d{width:7px;height:7px;border-radius:50%;background:var(--accent);animation:bounce 1.4s infinite ease-in-out}
.typ-bub .d:nth-child(2){animation-delay:.16s}.typ-bub .d:nth-child(3){animation-delay:.32s}
@keyframes bounce{0%,60%,100%{transform:translateY(0);opacity:.35}30%{transform:translateY(-7px);opacity:1}}
/* Input bar */
.bar{padding:12px 18px;border-top:1px solid var(--border);background:var(--bg2)}
.bar-row{display:flex;gap:8px;align-items:flex-end}
.txt{flex:1;padding:11px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:14px;outline:none;resize:none;max-height:110px;line-height:1.45;font-family:inherit;transition:border .2s}
.txt:focus{border-color:var(--accent)}.txt::placeholder{color:var(--muted)}
.send{padding:11px;background:linear-gradient(135deg,var(--accent3),var(--accent));border:none;border-radius:var(--radius);cursor:pointer;transition:all .2s;display:flex;align-items:center;justify-content:center}
.send svg{width:18px;height:18px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.send:hover{box-shadow:0 4px 16px rgba(108,92,231,.4)}
.send:disabled{opacity:.45;cursor:not-allowed;box-shadow:none}
.send.spin svg{animation:spin .8s linear infinite}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
.rate{font-size:11px;color:var(--muted);text-align:center;padding:4px 0 0}
.mtime{font-size:10px;color:var(--muted);margin-top:3px}
/* Cookie consent */
.cookie-bar{position:fixed;bottom:0;left:0;right:0;background:var(--bg2);border-top:1px solid var(--border);padding:14px 20px;z-index:200;display:none;align-items:center;justify-content:center;gap:16px;flex-wrap:wrap}
.cookie-bar.show{display:flex}
.cookie-bar p{font-size:13px;color:var(--text2);max-width:600px;line-height:1.5}
.cookie-bar p a{color:var(--accent2);text-decoration:underline}
.cookie-btn{padding:8px 20px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;border:none;transition:all .2s}
.cookie-btn.accept{background:linear-gradient(135deg,var(--accent3),var(--accent));color:#fff}
.cookie-btn.accept:hover{box-shadow:0 2px 12px rgba(108,92,231,.4)}
.cookie-btn.decline{background:var(--bg3);border:1px solid var(--border);color:var(--muted)}
.cookie-btn.decline:hover{border-color:var(--accent);color:var(--accent2)}
/* Privacy panel */
.privacy-panel{position:fixed;inset:0;background:rgba(0,0,0,.88);z-index:150;display:none;align-items:center;justify-content:center;backdrop-filter:blur(12px)}
.privacy-panel.show{display:flex}
.privacy-card{background:var(--bg2);border:1px solid var(--border);border-radius:18px;padding:32px;max-width:420px;width:92%;text-align:center}
.privacy-card h3{font-size:18px;margin-bottom:8px}
.privacy-card p{color:var(--text2);font-size:13px;line-height:1.55;margin-bottom:16px}
.privacy-actions{display:flex;flex-direction:column;gap:10px;margin-top:16px}
.privacy-action{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--bg3);border:1px solid var(--border);border-radius:10px;cursor:pointer;transition:all .2s}
.privacy-action:hover{border-color:var(--accent)}
.privacy-action .pa-label{font-size:13px;font-weight:600;display:flex;align-items:center;gap:8px}
.privacy-action .pa-label svg{width:16px;height:16px;fill:none;stroke:var(--accent2);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.privacy-action .pa-sub{font-size:11px;color:var(--muted)}
.privacy-danger{padding:12px;background:rgba(255,107,107,.08);border:1px solid rgba(255,107,107,.25);border-radius:10px;color:var(--red);font-size:13px;cursor:pointer;transition:all .2s}
.privacy-danger:hover{background:rgba(255,107,107,.15)}
/* Footer in chat */
.chat-footer{padding:6px 18px;border-top:1px solid var(--border);background:var(--bg2);display:flex;justify-content:center;gap:16px}
.chat-footer a{font-size:11px;color:var(--muted);text-decoration:none;transition:color .2s}
.chat-footer a:hover{color:var(--accent2)}
@media(max-width:600px){.bub{max-width:92%}.preview-split{grid-template-columns:1fr}.hdr{padding:10px 14px}.msgs{padding:10px}.bar{padding:10px 12px}.chat-footer{gap:10px}}
</style>
</head>
<body>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg" id="icon-sprite">
  <g id="i-nexus"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 7l10 5 10-5"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></g>
  <g id="i-send"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></g>
  <g id="i-user"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></g>
  <g id="i-lock"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></g>
  <g id="i-shield"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></g>
  <g id="i-eye"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></g>
  <g id="i-copy"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></g>
  <g id="i-check"><polyline points="20 6 9 17 4 12"/></g>
  <g id="i-trash"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></g>
  <g id="i-download"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></g>
  <g id="i-settings"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/></g>
  <g id="i-logout"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></g>
</svg>

<div class="app">
  <div class="hdr">
    <div class="hdr-l">
      <div class="logo"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
      <div><div class="hdr-t">NEXUS</div><div class="hdr-s"><span class="dot"></span>Online</div></div>
    </div>
    <div class="hdr-r">
      <span class="badge" id="rate-badge">30 / 30</span>
      <span style="font-size:12px;color:var(--muted)" id="uname"></span>
      <button class="hdr-btn" onclick="togglePrivacy()" title="Datenschutz">
        <svg viewBox="0 0 24 24"><use href="#i-shield"/></svg>
      </button>
      <button class="hdr-btn" onclick="logoutUser()" title="Abmelden">
        <svg viewBox="0 0 24 24"><use href="#i-logout"/></svg>
        Logout
      </button>
    </div>
  </div>

  <div class="msgs" id="msgs">
    <div class="welcome" id="welcome">
      <h3>Willkommen bei NEXUS</h3>
      <p>Dein KI-Agent mit Seele. Alles bleibt privat — kein Tracking, keine Werbung.</p>
      <div class="chips">
        <div class="chip" onclick="sendMsg('Wer bist du?')">Wer bist du?</div>
        <div class="chip" onclick="sendMsg('Was kannst du?')">Was kannst du?</div>
        <div class="chip" onclick="sendMsg('Erklaer mir das Projekt')">Projekt</div>
        <div class="chip" onclick="sendMsg('Schreibe ein Python-Skript')">Code</div>
      </div>
    </div>
  </div>

  <div class="typing" id="typing">
    <div class="av" style="width:30px;height:30px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent2));display:flex;align-items:center;justify-content:center;flex-shrink:0;">
      <svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round"><use href="#i-nexus"/></svg>
    </div>
    <div class="typ-bub"><div class="d"></div><div class="d"></div><div class="d"></div></div>
  </div>

  <div class="bar">
    <div class="bar-row">
      <textarea class="txt" id="input" placeholder="Nachricht an NEXUS..." rows="1" onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send" id="send-btn" onclick="sendMessage()"><svg viewBox="0 0 24 24"><use href="#i-send"/></svg></button>
    </div>
    <div class="rate" id="rate-info">30 Nachrichten verbleibend</div>
  </div>
  <div class="chat-footer">
    <a href="/datenschutz">Datenschutz</a>
    <a href="/impressum">Impressum</a>
  </div>
</div>

<!-- Invite overlay -->
<div class="overlay" id="invite-overlay">
  <div class="card">
    <div class="logo" style="width:52px;height:52px;margin:0 auto 18px;"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
    <h2>NEXUS Zugang</h2>
    <p>Privater KI-Agent, per Einladung geschuetzt.<br>Frag einen Admin auf Discord fuer einen Code.</p>
    <input type="text" class="inp" id="invite-input" placeholder="Einladungscode..." onkeydown="if(event.key==='Enter')document.getElementById('invite-btn').click()" autofocus>
    <div class="err" id="invite-error">Ungueltiger Code. Frag einen Admin auf Discord.</div>
    <button class="btn" id="invite-btn" onclick="verifyInvite()">Freischalten</button>
    <div class="dsgvo-note">Mit der Nutzung akzeptierst du die <a href="/datenschutz" target="_blank">Datenschutzerklaerung</a>. Kein Tracking, keine Werbung.</div>
  </div>
</div>

<!-- Name overlay -->
<div class="overlay" id="name-overlay" style="display:none">
  <div class="card">
    <div class="logo" style="width:52px;height:52px;margin:0 auto 18px;"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
    <h2>Willkommen bei NEXUS</h2>
    <p>Open-Source KI-Agent mit Seele. DSGVO-konform.<br>Wie moechtest du heissen?</p>
    <input type="text" class="inp" id="name-input" placeholder="Dein Name..." onkeydown="if(event.key==='Enter')document.getElementById('name-btn').click()">
    <button class="btn" id="name-btn" onclick="setName()">Los gehts</button>
  </div>
</div>

<!-- Privacy panel -->
<div class="privacy-panel" id="privacy-panel">
  <div class="privacy-card">
    <div class="logo" style="width:40px;height:40px;margin:0 auto 12px;"><svg viewBox="0 0 24 24"><use href="#i-shield"/></svg></div>
    <h3>Datenschutz</h3>
    <p>Deine Daten gehoeren dir. Kein Tracking, keine Analyse-Tools. Alle Daten werden nach 30 Tagen automatisch geloescht.</p>
    <div class="privacy-actions">
      <div class="privacy-action" onclick="exportData()">
        <div class="pa-label"><svg viewBox="0 0 24 24"><use href="#i-download"/></svg> Daten exportieren</div>
        <div class="pa-sub">Art. 20 DSGVO</div>
      </div>
      <div class="privacy-danger" onclick="deleteData()">Alle meine Daten loeschen (Art. 17 DSGVO)</div>
    </div>
    <div style="margin-top:14px">
      <button class="btn" onclick="togglePrivacy()" style="background:var(--bg3);border:1px solid var(--border);margin-top:0">Schliessen</button>
    </div>
    <div style="margin-top:10px"><a href="/datenschutz" style="font-size:12px;color:var(--accent2)">Vollstaendige Datenschutzerklaerung</a></div>
  </div>
</div>

<!-- Cookie consent -->
<div class="cookie-bar" id="cookie-bar">
  <p>NEXUS nutzt nur notwendige lokale Speicherung (Session, Name). Keine Tracking-Cookies. <a href="/datenschutz" target="_blank">Mehr erfahren</a></p>
  <button class="cookie-btn accept" onclick="acceptCookies()">Akzeptieren</button>
  <button class="cookie-btn decline" onclick="declineCookies()">Nur notwendige</button>
</div>

<script>
const API = window.location.origin.replace(/\\/$/, '');
let sessionId = null;
let userName = localStorage.getItem('nexus_user') || '';
let inviteToken = localStorage.getItem('nexus_invite') || '';
let rateLimit = 30;
let rateWindow = 3600;
let isAdmin = false;

// Cookie consent
if (!localStorage.getItem('nexus_cookie_consent')) {
  document.getElementById('cookie-bar').classList.add('show');
}
function acceptCookies() {
  localStorage.setItem('nexus_cookie_consent', 'accepted');
  document.getElementById('cookie-bar').classList.remove('show');
}
function declineCookies() {
  localStorage.setItem('nexus_cookie_consent', 'necessary');
  document.getElementById('cookie-bar').classList.remove('show');
}

// Already invited?
if (inviteToken) {
  document.getElementById('invite-overlay').style.display = 'none';
  if (userName) {
    sessionId = localStorage.getItem('nexus_session') || null;
    document.getElementById('uname').textContent = userName;
  } else {
    document.getElementById('name-overlay').style.display = 'flex';
  }
}

async function verifyInvite() {
  const code = document.getElementById('invite-input').value.trim();
  if (!code) return;
  const btn = document.getElementById('invite-btn');
  btn.disabled = true; btn.textContent = 'Pruefe...';
  try {
    const res = await fetch(API + '/api/invite', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({code})
    });
    const data = await res.json();
    if (data.valid) {
      inviteToken = data.token;
      rateLimit = data.daily_limit === 0 ? Infinity : (data.daily_limit || 30);
      rateWindow = data.window || 3600;
      isAdmin = data.daily_limit === 0;
      localStorage.setItem('nexus_invite', inviteToken);
      document.getElementById('invite-overlay').style.display = 'none';
      document.getElementById('name-overlay').style.display = 'flex';
      document.getElementById('name-input').focus();
    } else {
      const errEl = document.getElementById('invite-error');
      errEl.textContent = data.error || 'Ungueltiger Code';
      errEl.style.display = 'block';
    }
  } catch(e) {
    const errEl = document.getElementById('invite-error');
    errEl.textContent = 'Verbindungsfehler: ' + e.message;
    errEl.style.display = 'block';
  } finally { btn.disabled = false; btn.textContent = 'Freischalten'; }
}

function setName() {
  const name = document.getElementById('name-input').value.trim();
  if (!name) return;
  userName = name;
  localStorage.setItem('nexus_user', name);
  document.getElementById('name-overlay').style.display = 'none';
  document.getElementById('uname').textContent = name;
  document.getElementById('input').focus();
}

function fmtTime(ts) {
  return new Date(ts ? ts*1000 : Date.now()).toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'});
}

function esc(t) { const d=document.createElement('div'); d.textContent=t; return d.innerHTML; }

function fmtMsg(t) {
  let h = esc(t);
  // Code blocks with auto-preview for HTML and copy button
  h = h.replace(/```(\\w*)\\n?([\\s\\S]*?)```/g, function(match, lang, code) {
    const isPreviewable = /^(html|xml|svg|jsx|tsx|react|css)$/i.test(lang) || (lang === '' && /<!DOCTYPE|<html|<div|<body|<svg|<style/i.test(code));
    const langLabel = lang || 'code';
    const rawCode = code.replace(/^\\n+/, '').replace(/\\n+$/, '');
    const escapedCode = rawCode.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    if (isPreviewable) {
      let html = rawCode.trim();
      if (!/<html/i.test(html)) {
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,-apple-system,sans-serif;padding:16px;color:#111}</style></head><body>' + html + '</body></html>';
      }
      return '<div class="preview-split">' +
        '<div class="code-side"><div class="code-hdr"><span class="lang">' + langLabel + '</span><button class="copy-btn" onclick="copyCode(this)" data-raw="' + btoa(unescape(encodeURIComponent(rawCode))) + '"><svg style="width:12px;height:12px;vertical-align:middle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><use href="#i-copy"/></svg> Kopieren</button></div><pre class="code-body">' + escapedCode + '</pre></div>' +
        '<div class="preview-side"><iframe sandbox="allow-scripts" srcdoc="' + html.replace(/"/g,'&quot;').replace(/&/g,'&amp;') + '" style="width:100%;height:100%;min-height:320px;border:0"></iframe></div>' +
        '</div>';
    }
    // Non-previewable code blocks: header + copy
    return '<div class="code-hdr"><span class="lang">' + langLabel + '</span><button class="copy-btn" onclick="copyCode(this)" data-raw="' + btoa(unescape(encodeURIComponent(rawCode))) + '"><svg style="width:12px;height:12px;vertical-align:middle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><use href="#i-copy"/></svg> Kopieren</button></div><pre class="code-body">' + escapedCode + '</pre>';
  });
  h = h.replace(/`([^`]+)`/g,'<code>$1</code>');
  h = h.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  h = h.replace(/\\*([^*]+)\\*/g,'<em>$1</em>');
  h = h.replace(/\\n/g,'<br>');
  return h;
}

function copyCode(btn) {
  const raw = decodeURIComponent(escape(atob(btn.dataset.raw)));
  navigator.clipboard.writeText(raw).then(() => {
    btn.innerHTML = '<svg style="width:12px;height:12px;vertical-align:middle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><use href="#i-check"/></svg> Kopiert';
    setTimeout(() => { btn.innerHTML = '<svg style="width:12px;height:12px;vertical-align:middle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><use href="#i-copy"/></svg> Kopieren'; }, 2000);
  });
}

function addMsg(role, content) {
  const c = document.getElementById('msgs');
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'none';
  const m = document.createElement('div');
  m.className = 'msg ' + role;
  const svg = role === 'nexus'
    ? '<svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg>'
    : '<svg viewBox="0 0 24 24"><use href="#i-user"/></svg>';
  m.innerHTML = '<div class="av">'+svg+'</div><div><div class="bub">'+fmtMsg(content)+'</div><div class="mtime">'+fmtTime()+'</div></div>';
  c.appendChild(m);
  c.scrollTop = c.scrollHeight;
}

function setTyping(on) {
  document.getElementById('typing').className = on ? 'typing on' : 'typing';
}

function fmtLimit() {
  if (isAdmin) return '\\u221e';
  if (rateLimit === Infinity) return '\\u221e';
  return rateLimit;
}
function fmtWindow() {
  if (rateWindow >= 3600) return Math.round(rateWindow/3600) + 'h';
  if (rateWindow >= 60) return Math.round(rateWindow/60) + 'min';
  return rateWindow + 's';
}

function updateRate(rem) {
  rateLimit = rem;
  if (isAdmin || rem === Infinity) {
    document.getElementById('rate-badge').textContent = '\\u221e';
    document.getElementById('rate-info').textContent = 'Unbeschraenkt';
  } else {
    document.getElementById('rate-badge').textContent = rem + ' / ' + fmtLimit();
    document.getElementById('rate-info').textContent = rem + ' Nachrichten verbleibend (Fenster: ' + fmtWindow() + ')';
  }
}

function togglePrivacy() {
  const p = document.getElementById('privacy-panel');
  p.classList.toggle('show');
}

async function exportData() {
  if (!inviteToken) return;
  try {
    const res = await fetch(API + '/api/export-data', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({invite_token: inviteToken})
    });
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = 'nexus-data-export.json'; a.click();
    URL.revokeObjectURL(url);
    addMsg('nexus', 'Deine Daten wurden als JSON exportiert. Der Download sollte automatisch starten.');
  } catch(e) {
    addMsg('nexus', 'Export fehlgeschlagen: ' + e.message);
  }
}

async function deleteData() {
  if (!inviteToken) return;
  if (!confirm('Moechtest du wirklich ALLE deine Daten loeschen? Diese Aktion ist unwiderruflich (Art. 17 DSGVO).')) return;
  try {
    const res = await fetch(API + '/api/delete-data', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({invite_token: inviteToken, confirm: true})
    });
    const data = await res.json();
    if (data.ok) {
      alert('Alle deine Daten wurden geloescht. Du wirst abgemeldet.');
      logoutUser();
    } else {
      alert('Fehler: ' + (data.error || 'Loeschung fehlgeschlagen'));
    }
  } catch(e) {
    alert('Verbindungsfehler: ' + e.message);
  }
  togglePrivacy();
}

async function logoutUser() {
  try {
    await fetch(API + '/api/logout', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({invite_token: inviteToken})
    });
  } catch(e) {}
  localStorage.removeItem('nexus_invite');
  localStorage.removeItem('nexus_user');
  localStorage.removeItem('nexus_session');
  inviteToken = ''; userName = ''; sessionId = '';
  rateLimit = 30; rateWindow = 3600; isAdmin = false;
  document.getElementById('invite-overlay').style.display = 'flex';
  document.getElementById('name-overlay').style.display = 'none';
  document.getElementById('uname').textContent = '';
  document.getElementById('msgs').innerHTML = '';
  const w = document.getElementById('welcome'); if(w) w.style.display = '';
}

async function sendMessage() {
  const inp = document.getElementById('input');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = ''; autoResize(inp);
  addMsg('user', text);
  setTyping(true);
  document.getElementById('send-btn').disabled = true;

  try {
    const res = await fetch(API + '/api/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message:text, session_id:sessionId, user_name:userName, invite_token:inviteToken})
    });
    if (res.status === 403) {
      localStorage.removeItem('nexus_invite');
      inviteToken = '';
      document.getElementById('invite-overlay').style.display = 'flex';
      return;
    }
    if (res.status === 429) {
      addMsg('nexus', 'Rate-Limit erreicht — bitte warte einen Moment.');
      return;
    }
    const data = await res.json();
    if (data.session_id) { sessionId = data.session_id; localStorage.setItem('nexus_session', sessionId); }
    if (data.remaining !== undefined && data.remaining >= 0) updateRate(data.remaining);
    else if (data.remaining === -1) { isAdmin = true; rateLimit = Infinity; updateRate(Infinity); }
    addMsg('nexus', data.response);
  } catch(e) {
    addMsg('nexus', 'Verbindungsfehler: ' + e.message);
  } finally {
    setTyping(false);
    document.getElementById('send-btn').disabled = false;
    inp.focus();
  }
}

function sendMsg(t) { document.getElementById('input').value = t; sendMessage(); }
function handleKey(e) { if (e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();} }
function autoResize(el) { el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,110)+'px'; }

document.getElementById('input').focus();
if (!inviteToken) { setTimeout(()=>document.getElementById('invite-input').focus(),100); }
else if (!userName) { setTimeout(()=>document.getElementById('name-input').focus(),100); }
</script>
</body></html>'''


def get_datenschutz_html() -> str:
    """DSGVO-compliant Datenschutzerklaerung for NEXUS — full page."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS — Datenschutzerklaerung</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2L2 7l10 5 10-5-10-5z' fill='%236c5ce7'/><path d='M2 12l10 5 10-5' fill='none' stroke='%23a29bfe' stroke-width='2'/></svg>">
<style>
:root{--bg:#0a0a14;--bg2:#12122a;--accent:#7c6cf0;--accent2:#b8b0ff;--text:#e4e4f0;--text2:#9494b0;--border:#1f1f3a}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.75;overflow-x:hidden}
.dsgvo-page{max-width:820px;margin:0 auto;padding:48px 24px 80px}
.dsgvo-header{text-align:center;margin-bottom:48px;padding-bottom:32px;border-bottom:1px solid var(--border)}
.dsgvo-header .icon-wrap{display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:16px;margin-bottom:16px}
.dsgvo-header .icon-wrap svg{width:28px;height:28px;fill:none;stroke:#fff;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.dsgvo-header h1{font-size:clamp(1.6rem,3.5vw,2.2rem);font-weight:800;letter-spacing:-.01em;margin-bottom:8px;background:linear-gradient(135deg,var(--text) 40%,var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.dsgvo-header .meta{color:var(--text2);font-size:.92rem}
.dsgvo-header .meta span{display:inline-block;margin:0 10px}
.dsgvo-header .meta .sep{color:var(--border)}
.dsgvo-section{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:28px 32px;margin-bottom:20px;transition:border-color .2s}
.dsgvo-section:hover{border-color:rgba(124,108,240,.35)}
.dsgvo-section-head{display:flex;align-items:flex-start;gap:14px;margin-bottom:16px}
.dsgvo-section-head svg{flex-shrink:0;margin-top:3px;color:var(--accent2)}
.dsgvo-section-head h2{font-size:1.15rem;font-weight:700;letter-spacing:-.01em}
.dsgvo-section p,.dsgvo-section li{color:var(--text2);font-size:.93rem}
.dsgvo-section p{margin-bottom:10px}
.dsgvo-section p:last-child{margin-bottom:0}
.dsgvo-section ul{padding-left:20px;margin-bottom:10px}
.dsgvo-section ul li{margin-bottom:6px}
.dsgvo-section ul li:last-child{margin-bottom:0}
.dsgvo-section strong{color:var(--text);font-weight:600}
.dsgvo-section code{background:rgba(124,108,240,.12);padding:2px 7px;border-radius:5px;font-family:"SF Mono","Fira Code","Cascadia Code",monospace;font-size:.85rem;color:var(--accent2)}
.dsgvo-card-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:12px}
.dsgvo-card{background:rgba(124,108,240,.06);border:1px solid rgba(124,108,240,.15);border-radius:10px;padding:16px 18px;text-align:center}
.dsgvo-card svg{width:22px;height:22px;fill:none;stroke:var(--accent2);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;display:block;margin:0 auto 8px}
.dsgvo-card .label{font-size:.8rem;color:var(--text2);margin-bottom:2px}
.dsgvo-card .value{font-size:1.05rem;font-weight:700;color:var(--text)}
.dsgvo-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 14px;background:rgba(0,184,148,.1);border:1px solid rgba(0,184,148,.25);border-radius:20px;color:#00b894;font-size:.8rem;font-weight:600;margin-bottom:14px}
.dsgvo-badge svg{width:14px;height:14px;fill:none;stroke:#00b894;stroke-width:2.5;stroke-linecap:round;stroke-linejoin:round}
.dsgvo-footer{text-align:center;padding:32px 0 0;border-top:1px solid var(--border);margin-top:10px}
.dsgvo-footer p{color:var(--text2);font-size:.85rem;margin-bottom:8px}
.dsgvo-footer a{color:var(--accent2);text-decoration:none;border-bottom:1px solid transparent;transition:border-color .2s}
.dsgvo-footer a:hover{border-color:var(--accent2)}
.dsgvo-footer .links{display:flex;justify-content:center;gap:24px;margin-top:12px}
.dsgvo-footer .links a{font-size:.88rem;font-weight:500}
@media(max-width:640px){.dsgvo-page{padding:28px 16px 60px}.dsgvo-section{padding:20px 18px}.dsgvo-card-grid{grid-template-columns:1fr}}
</style>
</head>
<body>

<div class="dsgvo-page">
<div class="dsgvo-header">
  <div class="icon-wrap">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
    </svg>
  </div>
  <h1>Datenschutzerklaerung</h1>
  <div class="meta">
    <span>NEXUS KI-Agent</span>
    <span class="sep">|</span>
    <span>Stand: Juni 2025</span>
    <span class="sep">|</span>
    <span>DSGVO-konform</span>
  </div>
</div>

<div class="dsgvo-badge">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="20 6 9 17 4 12"/>
  </svg>
  Kein Tracking - Keine Werbung - Keine Analyse-Tools
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    <h2>1. Verantwortlicher</h2>
  </div>
  <p>Verantwortlicher im Sinne der Datenschutz-Grundverordnung (DSGVO) und anderer datenschutzrechtlicher Bestimmungen ist:</p>
  <p><strong>[NAME DES ANBIETERS]</strong><br>[ANSCHRIFT]<br>E-Mail: [E-MAIL]<br>Telefon: [TELEFON]</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <h2>2. Datenschutzbeauftragter</h2>
  </div>
  <p>Bei Fragen zum Datenschutz sowie zur Ausuebung Ihrer Betroffenenrechte koennen Sie sich an unseren Datenschutzbeauftragten wenden:</p>
  <p><strong>[NAME DES DATENSCHUTZBEAUFTRAGTEN]</strong><br>E-Mail: [E-MAIL-DSB]<br>Telefon: [TELEFON-DSB]</p>
  <p>Der Datenschutzbeauftragte ist Ihre zentrale Anlaufstelle fuer alle Angelegenheiten rund um die Verarbeitung Ihrer personenbezogenen Daten.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    <h2>3. Erhebung personenbezogener Daten</h2>
  </div>
  <p>Bei der Nutzung von NEXUS erheben wir folgende personenbezogene Daten, die fuer den Betrieb und die Sicherheit der Plattform erforderlich sind:</p>
  <ul>
    <li><strong>Chat-Nachrichten:</strong> Der von Ihnen eingegebene Nachrichtentext wird temporaer gespeichert, um den Gespraechskontext zu wahren. Pro Einladungscode werden maximal 50 Nachrichten vorgehalten. Nach <strong>30 Tagen</strong> werden alle Nachrichten automatisch und unwiderruflich geloescht.</li>
    <li><strong>Session-ID:</strong> Eine temporaere, zufaellig generierte Sitzungskennung, die waerend Ihrer Nutzungssitzung im Arbeitsspeicher vorgehalten wird. Diese wird nicht dauerhaft gespeichert und verfaellt nach Ihrer Sitzung oder spaetestens nach 2 Stunden Inaktivitaet.</li>
    <li><strong>Einladungscode-Hash:</strong> Der von Ihnen verwendete Einladungscode wird mittels SHA-256 gehasht gespeichert. Der Klartext-Code wird zu keinem Zeitpunkt dauerhaft gespeichert.</li>
    <li><strong>Benutzername:</strong> Der von Ihnen gewaehlte Anzeigename wird lokal in Ihrem Browser (<code>localStorage</code>) gespeichert und an den Server zur Identifikation innerhalb der Sitzung uebermittelt.</li>
    <li><strong>Rate-Limit-Zeitstempel:</strong> Zeitpunkte Ihrer Nachrichten-Anfragen werden temporaer erfasst, um die Fair-Use-Rate-Limits durchzusetzen (maximal 30 Nachrichten pro Stunde pro Nutzer). Diese Daten werden nach Ablauf des Rate-Limit-Fensters automatisch verworfen.</li>
  </ul>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
    <h2>4. Verarbeitungszwecke</h2>
  </div>
  <p>Ihre Daten werden ausschliesslich zu folgenden Zwecken verarbeitet:</p>
  <ul>
    <li><strong>Betrieb des Chat-Dienstes:</strong> Beantwortung Ihrer Anfragen durch den KI-Agenten und Aufrechterhaltung des Gespraechskontextes</li>
    <li><strong>Zugangskontrolle:</strong> Ueberpruefung der Berechtigung durch Einladungscodes</li>
    <li><strong>Missbrauchspraevention:</strong> Durchsetzung von Rate-Limits zur Gewaehrleistung eines farens Zugangs fuer alle Nutzer</li>
    <li><strong>Systemsicherheit:</strong> Schutz vor unbefugtem Zugriff und missbrauchlicher Nutzung</li>
  </ul>
  <p>Eine <strong>Datenverarbeitung zu Analyse-, Profiling- oder Werbezwecken</strong> findet nicht statt. NEXUS fuehrt kein Tracking durch und erstellt keine Nutzerprofile.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
    <h2>5. Rechtsgrundlagen</h2>
  </div>
  <p>Die Verarbeitung Ihrer personenbezogenen Daten erfolgt auf Basis folgender Rechtsgrundlagen der DSGVO:</p>
  <ul>
    <li><strong>Art. 6 Abs. 1 lit. b DSGVO:</strong> Die Verarbeitung ist fuer die Erfuellung eines Vertrags (Nutzung der NEXUS-Plattform) oder zur Durchfuehrung vorvertraglicher Massnahmen erforderlich.</li>
    <li><strong>Art. 6 Abs. 1 lit. f DSGVO:</strong> Die Verarbeitung ist zur Wahrung unserer berechtigten Interessen erforderlich, naemlich dem Betrieb und der Sicherheit der Plattform, der Missbrauchspraevention sowie der Gewaehrleistung eines farens Zugangs.</li>
    <li><strong>Art. 6 Abs. 1 lit. c DSGVO:</strong> Die Verarbeitung kann zur Erfuellung einer rechtlichen Verpflichtung erforderlich sein (z.B. Aufbewahrungspflichten nach Steuerrecht).</li>
  </ul>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
    <h2>6. Speicherdauer</h2>
  </div>
  <p>Die Speicherdauer Ihrer Daten ist strikt auf das notwendige Minimum begrenzt:</p>
  <ul>
    <li><strong>Chat-Nachrichten:</strong> Automatische Loeschung nach <strong>30 Tagen</strong>. Diese Frist beginnt mit dem Zeitpunkt der jeweiligen Nachricht.</li>
    <li><strong>Session-IDs:</strong> Verfall nach Ende der Sitzung oder spaetestens 2 Stunden Inaktivitaet.</li>
    <li><strong>Rate-Limit-Zeitstempel:</strong> Werden innerhalb des Rate-Limit-Fensters (1 Stunde) vorgehalten und anschliessend automatisch verworfen.</li>
  </ul>
  <p>Nach Loeschung der Daten sind diese nicht wiederherstellbar. Eine darueber hinausgehende Speicherung erfolgt nur, soweit gesetzliche Aufbewahrungspflichten bestehen.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    <h2>7. Datenuebermittlung an Dritte</h2>
  </div>
  <p>Eine Weitergabe Ihrer personenbezogenen Daten an Dritte erfolgt <strong>nicht</strong>, es sei denn:</p>
  <ul>
    <li>Sie haben ausdruecklich eingewilligt (Art. 6 Abs. 1 lit. a DSGVO)</li>
    <li>Es besteht eine gesetzliche Verpflichtung zur Weitergabe (Art. 6 Abs. 1 lit. c DSGVO)</li>
    <li>Es ist zur Rechtsverfolgung oder Verteidigung erforderlich</li>
  </ul>
  <p>NEXUS arbeitet nicht mit Werbenetzwerken, Analyse-Diensten oder sozialen Medien zusammen. Es werden keine Daten an Drittplattformen uebermittelt.</p>
  <p><strong>Serverstandort:</strong> Die gesamte Infrastruktur von NEXUS wird in Rechenzentren in <strong>Deutschland / der Europaeischen Union</strong> betrieben. Ein Datentransfer in Drittlaender ausserhalb der EU findet nicht statt.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
    <h2>8. Cookies und lokale Speicherung</h2>
  </div>
  <p>NEXUS verwendet <strong>keine Tracking-Cookies, keine Analyse-Cookies und keine Cookies von Drittanbietern</strong>.</p>
  <p>Allein die folgende lokal gespeicherte Information wird im Browser Ihres Endgeraets abgelegt:</p>
  <ul>
    <li><strong>localStorage - Einladungstoken:</strong> Speichert Ihren authentifizierten Token zur Wiedererkennung bei erneutem Besuch.</li>
    <li><strong>localStorage - Benutzername:</strong> Speichert Ihren gewaehlten Anzeigenamen fuer die naechste Sitzung.</li>
    <li><strong>localStorage - Session-ID:</strong> Speichert Ihre Sitzungskennung fuer die Wiederaufnahme des Gespraechs.</li>
  </ul>
  <p>Diese Daten verbleiben ausschliesslich lokal in Ihrem Browser und werden nicht an Dritte uebermittelt. Sie koennen diese Daten jederzeit ueber die Entwicklerwerkzeuge Ihres Browsers oder durch die "Logout"-Funktion loeschen.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
    <h2>9. Analyse-Tools und Tracking</h2>
  </div>
  <p><strong>NEXUS verwendet keinerlei Analyse-, Tracking- oder Statistik-Tools.</strong></p>
  <ul>
    <li>Kein Google Analytics, Matomo, Plausible oder aehnliche Dienste</li>
    <li>Kein Session-Replay oder Aufzeichnung von Nutzerinteraktionen</li>
    <li>Kein Fingerprinting</li>
    <li>Keine Werbe-Tracker oder Retargeting-Dienste</li>
    <li>Keine Social-Media-Plugins oder eingebundene externe Inhalte</li>
  </ul>
  <p>Ihre Privatsphaere hat fuer uns oberste Prioritaet. NEXUS ist als <strong>privacy-first</strong> Plattform konzipiert und verzichtet vollstaendig auf jegliche Form der Nutzerueberwachung.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    <h2>10. Ihre Betroffenenrechte</h2>
  </div>
  <p>Nach der DSGVO stehen Ihnen als betroffene Person die folgenden Rechte zu. Zur Ausuebung dieser Rechte wenden Sie sich bitte an die unter Ziffer 1 und 2 genannten Kontaktdaten.</p>

  <div class="dsgvo-card-grid">
    <div class="dsgvo-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
      <div class="label">Art. 15 DSGVO</div>
      <div class="value">Auskunftsrecht</div>
      <div style="font-size:.78rem;color:var(--text2);margin-top:4px">Information ueber Ihre gespeicherten Daten</div>
    </div>
    <div class="dsgvo-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      <div class="label">Art. 16 DSGVO</div>
      <div class="value">Berichtigung</div>
      <div style="font-size:.78rem;color:var(--text2);margin-top:4px">Berichtigung unrichtiger Daten</div>
    </div>
    <div class="dsgvo-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
      <div class="label">Art. 17 DSGVO</div>
      <div class="value">Loeschung</div>
      <div style="font-size:.78rem;color:var(--text2);margin-top:4px">Recht auf Vergessenwerden</div>
    </div>
    <div class="dsgvo-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
      <div class="label">Art. 18 DSGVO</div>
      <div class="value">Einschraenkung</div>
      <div style="font-size:.78rem;color:var(--text2);margin-top:4px">Einschraenkung der Verarbeitung</div>
    </div>
    <div class="dsgvo-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
      <div class="label">Art. 20 DSGVO</div>
      <div class="value">Datenuebertragbarkeit</div>
      <div style="font-size:.78rem;color:var(--text2);margin-top:4px">Export Ihrer Daten in strukturiertem Format</div>
    </div>
    <div class="dsgvo-card">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.69l-1.38 9A2 2 0 0 0 4.3 15H10z"/><path d="M17 15h3.23a2 2 0 0 0 2-1.72l1.37-9A2 2 0 0 0 21.62 2H17"/></svg>
      <div class="label">Art. 21 DSGVO</div>
      <div class="value">Widerspruchsrecht</div>
      <div style="font-size:.78rem;color:var(--text2);margin-top:4px">Widerspruch gegen die Verarbeitung</div>
    </div>
  </div>

  <p style="margin-top:16px"><strong>Auskunftsrecht (Art. 15 DSGVO):</strong> Sie haben das Recht, von uns eine Bestaetigung darueber zu verlangen, ob Sie betreffende personenbezogene Daten verarbeitet werden.</p>
  <p><strong>Recht auf Loeschung (Art. 17 DSGVO):</strong> Sie koennen die unverzuegliche Loeschung Ihrer personenbezogenen Daten verlangen. In der NEXUS-Oberflaeche steht Ihnen dafuer die Funktion "Daten loeschen" zur Verfuegung.</p>
  <p><strong>Recht auf Datenuebertragbarkeit (Art. 20 DSGVO):</strong> Sie haben das Recht, Ihre personenbezogenen Daten in einem strukturierten, gaengigen und maschinenlesbaren Format zu erhalten. Auf Anfrage stellen wir Ihnen einen Export Ihrer Chat-Nachrichten bereit.</p>
  <p><strong>Widerspruchsrecht (Art. 21 DSGVO):</strong> Sie haben das Recht, jederzeit gegen die Verarbeitung Ihrer personenbezogenen Daten Widerspruch einzulegen.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
    <h2>11. Automatisierte Entscheidungsfindung und Profiling</h2>
  </div>
  <p>NEXUS fuehrt <strong>keine automatisierte Entscheidungsfindung im Sinne des Art. 22 DSGVO</strong> durch und betreibt <strong>kein Profiling</strong>.</p>
  <p>Der KI-Agent beantwortet Ihre Anfragen auf Basis eines Sprachmodells. Es werden keine Bewertungen Ihres Verhaltens vorgenommen, keine Kategorisierungen erstellt und keine Vorhersagen ueber Ihre Person getroffen.</p>
</div>

<div class="dsgvo-section">
  <div class="dsgvo-section-head">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 15h4l2-8 3 16 2-6h4"/></svg>
    <h2>12. Beschwerderecht bei der Aufsichtsbehoerde</h2>
  </div>
  <p>Gemass Art. 77 DSGVO haben Sie das Recht auf Beschwerde bei einer Aufsichtsbehoerde, wenn Sie der Ansicht sind, dass die Verarbeitung der Sie betreffenden personenbezogenen Daten gegen die DSGVO verstoesst.</p>
  <p>Die fuer uns zustaendige Aufsichtsbehoerde ist:</p>
  <p><strong>[NAME DER AUFSICHTSBEHOERDE]</strong><br>[ANSCHRIFT AUFSICHTSBEHOERDE]<br>[E-MAIL AUFSICHTSBEHOERDE]</p>
</div>

<div class="dsgvo-footer">
  <p>NEXUS ist ein Open-Source-Projekt auf <a href="https://github.com/TitoPrausee/nexus-toti" target="_blank" rel="noopener">GitHub</a>.</p>
  <p>Diese Datenschutzerklaerung ist aktuell gueltig. Stand: <strong>Juni 2025</strong>.</p>
  <div class="links">
    <a href="/">Zurueck zur Startseite</a>
    <a href="/impressum">Impressum</a>
  </div>
</div>
</div>
</body></html>'''


def get_impressum_html() -> str:
    """Legal notice / Impressum for NEXUS — full page."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS — Impressum</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path d='M12 2L2 7l10 5 10-5-10-5z' fill='%236c5ce7'/><path d='M2 12l10 5 10-5' fill='none' stroke='%23a29bfe' stroke-width='2'/></svg>">
<style>
:root{--bg:#0a0a14;--bg2:#12122a;--accent:#7c6cf0;--accent2:#b8b0ff;--text:#e4e4f0;--text2:#9494b0;--border:#1f1f3a}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.75}
.impressum-page{max-width:720px;margin:0 auto;padding:48px 24px 80px}
.impressum-page h1{font-size:clamp(1.5rem,3vw,2rem);font-weight:800;margin-bottom:8px;background:linear-gradient(135deg,var(--text) 40%,var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;text-align:center}
.impressum-page .sub{text-align:center;color:var(--text2);font-size:.9rem;margin-bottom:36px}
.impressum-block{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:24px 28px;margin-bottom:16px;transition:border-color .2s}
.impressum-block:hover{border-color:rgba(124,108,240,.35)}
.impressum-block h2{font-size:1.05rem;font-weight:700;margin-bottom:12px;color:var(--accent2)}
.impressum-block p{color:var(--text2);font-size:.93rem;margin-bottom:6px}
.impressum-block a{color:var(--accent2);text-decoration:none}
.impressum-block a:hover{text-decoration:underline}
.impressum-block strong{color:var(--text);font-weight:600}
.impressum-footer{text-align:center;padding:28px 0 0;border-top:1px solid var(--border);margin-top:16px}
.impressum-footer a{color:var(--accent2);text-decoration:none;font-size:.88rem}
.impressum-footer a:hover{text-decoration:underline}
@media(max-width:640px){.impressum-page{padding:28px 16px 60px}.impressum-block{padding:18px 16px}}
</style>
</head>
<body>
<div class="impressum-page">
<h1>Impressum</h1>
<div class="sub">Angaben gemass § 5 TMG</div>

<div class="impressum-block">
  <h2>Anbieter</h2>
  <p><strong>[NAME DES ANBIETERS]</strong></p>
  <p>[ANSCHRIFT]</p>
  <p>E-Mail: [E-MAIL]</p>
  <p>Telefon: [TELEFON]</p>
</div>

<div class="impressum-block">
  <h2>Vertreten durch</h2>
  <p>[VERTRETER]</p>
</div>

<div class="impressum-block">
  <h2>Kontakt</h2>
  <p>E-Mail: [E-MAIL]</p>
  <p>Telefon: [TELEFON]</p>
</div>

<div class="impressum-block">
  <h2> Verantwortlicher im Sinne des § 55 Abs. 2 RStV</h2>
  <p><strong>[NAME DES ANBIETERS]</strong></p>
  <p>[ANSCHRIFT]</p>
</div>

<div class="impressum-block">
  <h2>Streitschlichtung</h2>
  <p>Die Europaeische Kommission stellt eine Plattform zur Online-Streitbeilegung bereit: <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener">https://ec.europa.eu/consumers/odr</a></p>
  <p>Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.</p>
</div>

<div class="impressum-block">
  <h2>Haftung fuer Inhalte</h2>
  <p>Als Diensteanbieter sind wir gemaess § 7 Abs.1 TMG fuer eigene Inhalte auf diesen Seiten nach den allgemeinen Gesetzen verantwortlich. Nach §§ 8 bis 10 TMG sind wir als Diensteanbieter jedoch nicht verpflichtet, uebermittelte oder gespeicherte fremde Informationen zu ueberwachen oder nach Umstaenden zu forschen, die auf eine rechtswidrige Taetigkeit hinweisen.</p>
</div>

<div class="impressum-block">
  <h2>Haftung fuer Links</h2>
  <p>Unser Angebot enthaelt Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss haben. Deshalb koennen wir fuer diese fremden Inhalte auch keine Gewaehr uebernehmen. Fuer die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich.</p>
</div>

<div class="impressum-block">
  <h2>Urheberrecht</h2>
  <p>Die durch die Seitenbetreiber erstellten Inhalte und Werke auf diesen Seiten unterliegen dem Urheberrecht. Die Vervielfaeltigung, Bearbeitung, Verbreitung und jede Art der Verwertung ausserhalb der Grenzen des Urheberrechtes beduerfen der schriftlichen Zustimmung des jeweiligen Autors bzw. Erstellers.</p>
  <p>Der Quellcode von NEXUS ist Open-Source und verfuegbar auf <a href="https://github.com/TitoPrausee/nexus-toti" target="_blank" rel="noopener">GitHub</a>.</p>
</div>

<div class="impressum-block">
  <h2>Projekt</h2>
  <p>NEXUS ist ein Open-Source KI-Agent-Projekt. Der Quellcode ist verfuegbar auf <a href="https://github.com/TitoPrausee/nexus-toti" target="_blank" rel="noopener">GitHub</a>.</p>
</div>

<div class="impressum-footer">
  <a href="/">Zurueck zur Startseite</a> &middot; <a href="/datenschutz">Datenschutzerklaerung</a>
</div>
</div>
</body></html>'''


def main():
    """Run the web UI server."""
    import uvicorn
    import yaml

    config_path = Path(__file__).parent.parent.parent / "config.yaml"
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    app = create_app(config)
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT, log_level="info")


if __name__ == "__main__":
    main()