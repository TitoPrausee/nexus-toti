"""
NEXUS v7 — Web UI Interface
FastAPI chat with invite-gate, per-user memory, rate limiting.
Startup landing page + chat interface.
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(get_landing_html())

    @app.get("/chat", response_class=HTMLResponse)
    async def chat_page():
        return HTMLResponse(get_chat_html())

    @app.get("/health")
    async def health():
        return {"status": "ok", "sessions": len(sessions.sessions)}

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
    """Startup-style landing page."""
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
footer{text-align:center;padding:40px 20px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--border)}
@media(max-width:640px){.hero h1{font-size:1.8rem}.features{grid-template-columns:1fr}}
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
  <g id="i-chevron-right"><polyline points="9 18 15 12 9 6"/></g>
</svg>

<div class="hero">
  <div class="logo-mark"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
  <h1>NEXUS</h1>
  <p>Autonomer KI-Agent mit Seele. Denkt, lernt, handelt — auf deine Art.</p>
  <div class="hero-sub">Open-Source - Privat - Kein Tracking</div>
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
    <h3>Privat &amp; Gesichert</h3>
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

<div class="section">
  <div class="limit-bar">
    <h4>Fair-Use Limit</h4>
    <span class="limit-num">30</span>
    <p>Nachrichten pro Stunde pro Nutzer.<br>Reichlich fuer Gespraeche, Schutz gegen Missbrauch.</p>
  </div>
</div>

<footer>NEXUS v7 - Open Source KI-Agent - <a href="https://github.com/TitoPrausee/nexus-toti">GitHub</a></footer>
</body></html>'''


def get_chat_html() -> str:
    """Chat UI — invite gate + name + chat. Dark theme, SVG icons."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS Chat</title>
<style>
:root{--bg:#07070d;--bg2:#0e0e18;--bg3:#151524;--bg4:#1c1c32;--text:#e4e4f0;--text2:#9494b0;--muted:#5c5c78;--accent:#6c5ce7;--accent2:#a29bfe;--accent3:#4f46e5;--border:#1f1f35;--user:#1e1e3a;--nexus:#12122a;--green:#00b894;--red:#ff6b6b;--radius:12px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);height:100vh;overflow:hidden}
.app{display:flex;flex-direction:column;height:100vh;max-width:820px;margin:0 auto}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border);background:var(--bg2)}
.hdr-l{display:flex;align-items:center;gap:10px}
.logo{width:34px;height:34px;background:linear-gradient(135deg,var(--accent),var(--accent2));border-radius:10px;display:flex;align-items:center;justify-content:center}
.logo svg{width:20px;height:20px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.hdr-t{font-size:17px;font-weight:700;letter-spacing:.4px}
.hdr-s{font-size:11px;color:var(--muted);margin-top:1px}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.badge{font-size:11px;padding:3px 10px;border-radius:20px;background:var(--bg3);border:1px solid var(--border);color:var(--text2)}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.85);display:flex;align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(12px)}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:18px;padding:36px 32px;max-width:380px;width:92%;text-align:center}
.card .logo{width:52px;height:52px;margin:0 auto 18px}
.card h2{font-size:20px;margin-bottom:6px}
.card p{color:var(--text2);font-size:14px;margin-bottom:20px;line-height:1.55}
.inp{width:100%;padding:12px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-size:15px;outline:none;transition:border .2s}
.inp:focus{border-color:var(--accent)}
.btn{width:100%;padding:12px;margin-top:14px;background:linear-gradient(135deg,var(--accent3),var(--accent));color:#fff;border:none;border-radius:var(--radius);font-size:15px;font-weight:600;cursor:pointer;transition:all .2s}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 16px rgba(108,92,231,.4)}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.err{color:var(--red);font-size:13px;margin-top:8px;display:none}
.msgs{flex:1;overflow-y:auto;padding:18px;scroll-behavior:smooth}
.msgs::-webkit-scrollbar{width:5px}.msgs::-webkit-scrollbar-track{background:transparent}.msgs::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.welcome{text-align:center;padding:36px 16px;color:var(--muted)}
.welcome h3{font-size:18px;color:var(--text2);margin-bottom:6px}
.welcome p{font-size:14px;line-height:1.6}
.chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:14px}
.chip{padding:7px 14px;background:var(--bg3);border:1px solid var(--border);border-radius:20px;color:var(--text2);font-size:13px;cursor:pointer;transition:all .2s}
.chip:hover{border-color:var(--accent);color:var(--text)}
.msg{display:flex;gap:10px;margin-bottom:14px;animation:fadeUp .3s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.msg.user{flex-direction:row-reverse}
.av{width:30px;height:30px;border-radius:10px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.msg.user .av{background:linear-gradient(135deg,#00b894,#00cec9)}
.msg.nexus .av{background:linear-gradient(135deg,var(--accent),var(--accent2))}
.av svg{width:16px;height:16px;fill:none;stroke:#fff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.bub{max-width:72%;padding:11px 15px;border-radius:var(--radius);line-height:1.65;font-size:14px}
.msg.user .bub{background:var(--user);border-bottom-right-radius:4px}
.msg.nexus .bub{background:var(--nexus);border:1px solid var(--border);border-bottom-left-radius:4px}
.bub code{background:rgba(108,92,231,.15);padding:1px 5px;border-radius:4px;font-family:'SF Mono','Fira Code',monospace;font-size:13px}
.bub pre{background:var(--bg);padding:10px;border-radius:8px;overflow-x:auto;margin:6px 0;font-size:13px}
.mtime{font-size:10px;color:var(--muted);margin-top:3px}
.typing{display:none;padding:4px 18px;align-items:center;gap:10px}
.typing.on{display:flex}
.typ-bub{display:inline-flex;align-items:center;gap:5px;padding:11px 16px;background:var(--nexus);border:1px solid var(--border);border-radius:var(--radius);border-bottom-left-radius:4px}
.typ-bub .d{width:7px;height:7px;border-radius:50%;background:var(--accent);animation:bounce 1.4s infinite ease-in-out}
.typ-bub .d:nth-child(2){animation-delay:.16s}.typ-bub .d:nth-child(3){animation-delay:.32s}
@keyframes bounce{0%,60%,100%{transform:translateY(0);opacity:.35}30%{transform:translateY(-7px);opacity:1}}
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
.preview-btn{display:inline-block;padding:4px 12px;margin:4px 0 2px;background:linear-gradient(135deg,var(--accent3),var(--accent));color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;transition:all .2s}
.preview-btn:hover{opacity:.85;transform:translateY(-1px)}
.preview-container{margin:0 0 8px}
@media(max-width:600px){.bub{max-width:86%}.hdr{padding:10px 14px}.msgs{padding:10px}.bar{padding:10px 12px}}
.msgs{scrollbar-width:thin;scrollbar-color:var(--border) transparent}
</style>
</head>
<body>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg" id="icon-sprite">
  <g id="i-nexus"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 7l10 5 10-5"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></g>
  <g id="i-send"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></g>
  <g id="i-user"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></g>
  <g id="i-lock"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></g>
  <g id="i-shield"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></g>
</svg>

<div class="app">
  <div class="hdr">
    <div class="hdr-l">
      <div class="logo"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
      <div><div class="hdr-t">NEXUS</div><div class="hdr-s"><span class="dot"></span>Online</div></div>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <span class="badge" id="rate-badge">30 / 30</span>
      <span style="font-size:12px;color:var(--muted)" id="uname"></span>
      <button onclick="logoutUser()" style="background:none;border:1px solid var(--muted);color:var(--muted);padding:4px 10px;border-radius:6px;cursor:pointer;font-size:12px;" title="Abmelden">
        <svg style="vertical-align:middle;width:14px;height:14px" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        Logout
      </button>
    </div>
  </div>

  <div class="msgs" id="msgs">
    <div class="welcome" id="welcome">
      <h3>Willkommen bei NEXUS</h3>
      <p>Dein KI-Agent mit Seele. Alles, was du mir sagst, bleibt zwischen uns.</p>
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
</div>

<div class="overlay" id="invite-overlay">
  <div class="card">
    <div class="logo" style="width:52px;height:52px;margin:0 auto 18px;"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
    <h2>NEXUS Zugang</h2>
    <p>Dieser KI-Agent ist privat und per Einladung geschuetzt.<br>Frag einen Admin auf Discord fuer einen Code.</p>
    <input type="text" class="inp" id="invite-input" placeholder="Einladungscode..." onkeydown="if(event.key==='Enter')document.getElementById('invite-btn').click()" autofocus>
    <div class="err" id="invite-error">Ungueltiger Code. Frag einen Admin auf Discord.</div>
    <button class="btn" id="invite-btn" onclick="verifyInvite()">Freischalten</button>
  </div>
</div>

<div class="overlay" id="name-overlay" style="display:none">
  <div class="card">
    <div class="logo" style="width:52px;height:52px;margin:0 auto 18px;"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
    <h2>Willkommen bei NEXUS</h2>
    <p>Open-Source KI-Agent mit Seele.<br>Wie moechtest du heissen?</p>
    <input type="text" class="inp" id="name-input" placeholder="Dein Name..." onkeydown="if(event.key==='Enter')document.getElementById('name-btn').click()">
    <button class="btn" id="name-btn" onclick="setName()">Los gehts</button>
  </div>
</div>

<script>
const API = window.location.origin.replace(/\/$/, '');
let sessionId = null;
let userName = localStorage.getItem('nexus_user') || '';
let inviteToken = localStorage.getItem('nexus_invite') || '';
let rateLimit = 30;
let rateWindow = 3600;
let isAdmin = false;

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
  // Code blocks with preview button for HTML/React
  h = h.replace(/```(\w*)\n?([\s\S]*?)```/g, function(match, lang, code) {
    const isPreviewable = /^(html|xml|svg|jsx|tsx|react)$/i.test(lang) || (lang === '' && /<!DOCTYPE|<html|<div|<body|<svg|<style|react/i.test(code));
    const previewBtn = isPreviewable ? '<button class="preview-btn" onclick="togglePreview(this)">Vorschau</button>' : '';
    return previewBtn + '<pre><code>' + code + '</code></pre>';
  });
  h = h.replace(/`([^`]+)`/g,'<code>$1</code>');
  h = h.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  h = h.replace(/\*([^*]+)\*/g,'<em>$1</em>');
  h = h.replace(/\n/g,'<br>');
  return h;
}

function togglePreview(btn) {
  const pre = btn.nextElementSibling;
  if (!pre) return;
  const code = pre.querySelector('code') ? pre.querySelector('code').textContent : pre.textContent;
  // Check if preview container already exists
  let container = btn.parentElement.querySelector('.preview-container');
  if (container) {
    container.remove();
    btn.textContent = 'Vorschau';
    return;
  }
  btn.textContent = 'Vorschau schliessen';
  container = document.createElement('div');
  container.className = 'preview-container';
  // Wrap code in full HTML if it's a fragment
  let html = code.trim();
  if (!/<html/i.test(html)) {
    html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,sans-serif;padding:16px}</style></head><body>' + html + '</body></html>';
  }
  const iframe = document.createElement('iframe');
  iframe.sandbox = 'allow-scripts allow-same-origin';
  iframe.style.cssText = 'width:100%;height:350px;border:1px solid var(--border);border-radius:8px;background:#fff;margin-top:8px';
  container.appendChild(iframe);
  btn.parentElement.insertBefore(container, btn.nextSibling);
  iframe.srcdoc = html;
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
  if (isAdmin) return '\u221e';
  if (rateLimit === Infinity) return '\u221e';
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
    document.getElementById('rate-badge').textContent = '\u221e';
    document.getElementById('rate-info').textContent = 'Unbeschraenkt';
  } else {
    document.getElementById('rate-badge').textContent = rem + ' / ' + fmtLimit();
    document.getElementById('rate-info').textContent = rem + ' Nachrichten verbleibend (Fenster: ' + fmtWindow() + ')';
  }
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