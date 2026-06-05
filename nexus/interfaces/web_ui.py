"""
NEXUS v7 — Web UI Interface
FastAPI + WebSocket chat for invited friends on Tailscale.
"""

import os
import json
import uuid
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
SESSION_TIMEOUT = 3600 * 2  # 2 hours idle session cleanup


class WebSession:
    """Per-user session state."""
    def __init__(self, session_id: str, user_name: str = "Guest"):
        self.id = session_id
        self.user_name = user_name
        self.agent = None
        self.history: list[dict] = []

    def init_agent(self, config: dict):
        """Lazy-init agent per session."""
        if self.agent is None:
            self.agent = NexusAgent(config)
        return self.agent


class SessionManager:
    """Manages all active web sessions."""
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
        """Remove stale sessions."""
        import time
        now = time.time()
        stale = [
            sid for sid, s in self.sessions.items()
            if not s.history or (now - s.history[-1].get("ts", 0)) > SESSION_TIMEOUT
        ]
        for sid in stale:
            del self.sessions[sid]


sessions = SessionManager()


def create_app(config: dict = None) -> FastAPI:
    """Create the FastAPI app with all routes."""
    config = config or {}

    # Try loading config.yaml
    if not config:
        try:
            import yaml
            config_path = Path(__file__).parent.parent.parent / "config.yaml"
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception:
            pass

    app = FastAPI(title="NEXUS v7", docs_url=None, redoc_url=None)

    # CORS for Tailscale access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(get_chat_html())

    @app.get("/health")
    async def health():
        return {"status": "ok", "sessions": len(sessions.sessions)}

    @app.post("/api/chat")
    async def chat_api(request: Request):
        """REST API for chat — returns full response."""
        body = await request.json()
        message = body.get("message", "").strip()
        session_id = body.get("session_id")
        user_name = body.get("user_name", "Guest")

        if not message:
            raise HTTPException(400, "Message required")

        session = sessions.get_or_create(session_id, user_name)
        agent = session.init_agent(config)

        try:
            response = agent.process(message, user_id=session.id)
            
            # If response is empty/error, give a friendly fallback
            if not response or not isinstance(response, str):
                response = "Ich konnte leider keine Verbindung zum Sprachmodell herstellen. Bitte versuche es spaeter nochmal."
            
            session.history.append({"role": "user", "content": message, "ts": __import__("time").time()})
            session.history.append({"role": "assistant", "content": response, "ts": __import__("time").time()})

            # Cleanup old sessions periodically
            if len(sessions.sessions) > 50:
                sessions.cleanup()

            return {
                "response": response,
                "session_id": session.id,
                "user_name": session.user_name,
            }
        except Exception as e:
            log.error(f"Chat error: {e}")
            raise HTTPException(500, str(e))

    @app.websocket("/ws/chat")
    async def websocket_chat(ws: WebSocket):
        """WebSocket for streaming chat experience."""
        await ws.accept()

        session_id = None
        agent = None

        try:
            while True:
                data = await ws.receive_text()
                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "content": "Invalid JSON"})
                    continue

                message = msg.get("message", "").strip()
                user_name = msg.get("user_name", "Guest")
                session_id = msg.get("session_id") or session_id

                if not message:
                    await ws.send_json({"type": "error", "content": "Empty message"})
                    continue

                session = sessions.get_or_create(session_id, user_name)
                session_id = session.id
                agent = session.init_agent(config)

                # Send typing indicator
                await ws.send_json({"type": "typing", "status": True})

                try:
                    response = agent.process(message, user_id=session.id)

                    session.history.append({"role": "user", "content": message, "ts": __import__("time").time()})
                    session.history.append({"role": "assistant", "content": response, "ts": __import__("time").time()})

                    # Stream in chunks for better UX
                    chunk_size = 80
                    for i in range(0, len(response), chunk_size):
                        chunk = response[i:i + chunk_size]
                        await ws.send_json({
                            "type": "chunk",
                            "content": chunk,
                            "done": i + chunk_size >= len(response),
                        })
                        await __import__("asyncio").sleep(0.01)

                    await ws.send_json({
                        "type": "done",
                        "session_id": session.id,
                        "full_response": response,
                    })
                except Exception as e:
                    log.error(f"WS chat error: {e}")
                    await ws.send_json({"type": "error", "content": f"Fehler: {str(e)}"})
                finally:
                    await ws.send_json({"type": "typing", "status": False})

        except WebSocketDisconnect:
            log.info(f"WebSocket disconnected: {session_id}")
        except Exception as e:
            log.error(f"WS error: {e}")

    @app.get("/api/sessions")
    async def list_sessions():
        return {
            "active": len(sessions.sessions),
            "sessions": [
                {"id": s.id, "user": s.user_name, "messages": len(s.history)}
                for s in sessions.sessions.values()
            ],
        }

    return app


def get_chat_html() -> str:
    """Inline HTML for Nexus chat UI — dark theme, SVG icons, typing animation."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS v7</title>
<style>
:root {
  --bg-primary: #0a0a0f;
  --bg-secondary: #12121a;
  --bg-tertiary: #1a1a26;
  --bg-input: #16162a;
  --text-primary: #e8e8f0;
  --text-secondary: #9999b0;
  --text-muted: #666680;
  --accent: #6c5ce7;
  --accent-glow: rgba(108, 92, 231, 0.3);
  --accent-hover: #7d6ff0;
  --border: #2a2a3a;
  --user-bubble: #1e1e3a;
  --nexus-bubble: #16162a;
  --success: #00b894;
  --error: #ff6b6b;
  --radius: 12px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  height: 100vh;
  overflow: hidden;
}

.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 860px;
  margin: 0 auto;
}

/* Header */
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo {
  width: 36px;
  height: 36px;
  background: linear-gradient(135deg, var(--accent), #a29bfe);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: white;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.header-sub {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
  display: inline-block;
  margin-right: 6px;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Name input overlay */
.name-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  backdrop-filter: blur(10px);
}

.name-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 40px;
  max-width: 400px;
  width: 90%;
  text-align: center;
}

.name-card h2 {
  font-size: 22px;
  margin-bottom: 8px;
}

.name-card p {
  color: var(--text-secondary);
  font-size: 14px;
  margin-bottom: 24px;
  line-height: 1.5;
}

.name-input {
  width: 100%;
  padding: 12px 16px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: 16px;
  outline: none;
  transition: border 0.2s;
}

.name-input:focus {
  border-color: var(--accent);
}

.name-btn {
  width: 100%;
  padding: 12px;
  margin-top: 16px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius);
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.name-btn:hover {
  background: var(--accent-hover);
}

/* Messages */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  scroll-behavior: smooth;
}

.messages::-webkit-scrollbar { width: 6px; }
.messages::-webkit-scrollbar-track { background: transparent; }
.messages::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.welcome {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-muted);
}

.welcome h3 {
  font-size: 20px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.welcome p {
  font-size: 14px;
  line-height: 1.6;
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
}

.suggestion {
  padding: 8px 16px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 20px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.suggestion:hover {
  border-color: var(--accent);
  color: var(--text-primary);
}

.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg.user { flex-direction: row-reverse; }

.msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.msg.user .msg-avatar {
  background: linear-gradient(135deg, #00b894, #00cec9);
  color: white;
}

.msg.nexus .msg-avatar {
  background: linear-gradient(135deg, var(--accent), #a29bfe);
  color: white;
}

.msg-bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: var(--radius);
  line-height: 1.6;
  font-size: 14px;
}

.msg.user .msg-bubble {
  background: var(--user-bubble);
  border-bottom-right-radius: 4px;
}

.msg.nexus .msg-bubble {
  background: var(--nexus-bubble);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
}

.msg-bubble code {
  background: rgba(108, 92, 231, 0.15);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 13px;
}

.msg-bubble pre {
  background: var(--bg-primary);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
  font-size: 13px;
}

.msg-time {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

.typing-indicator {
  display: none;
  padding: 4px 20px;
}

.typing-indicator.active { display: flex; align-items: center; gap: 10px; }

.typing-bubble {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 12px 18px;
  background: var(--nexus-bubble);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  border-bottom-left-radius: 4px;
}

.typing-bubble .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-bubble .dot:nth-child(2) { animation-delay: 0.16s; }
.typing-bubble .dot:nth-child(3) { animation-delay: 0.32s; }

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-8px); opacity: 1; }
}

/* Input */
.input-area {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
}

.input-wrapper {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.msg-input {
  flex: 1;
  padding: 12px 16px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: 15px;
  outline: none;
  resize: none;
  max-height: 120px;
  line-height: 1.4;
  font-family: inherit;
  transition: border 0.2s;
}

.msg-input:focus { border-color: var(--accent); }
.msg-input::placeholder { color: var(--text-muted); }

.send-btn {
  padding: 12px;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.send-btn svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: white;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.send-btn:hover { background: var(--accent-hover); }
.send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.send-btn.loading svg { animation: spin 1s linear infinite; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Responsive */
@media (max-width: 600px) {
  .msg-bubble { max-width: 85%; }
  .header { padding: 12px 16px; }
  .messages { padding: 12px; }
  .input-area { padding: 12px; }
}

/* Dark scrollbar for Firefox */
.messages {
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
</style>
</head>
<body>
<!-- SVG Icon Sprite -->
<svg style="display:none" xmlns="http://www.w3.org/2000/svg" id="icon-sprite">
  <g id="i-nexus"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 7l10 5 10-5"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></g>
  <g id="i-send"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></g>
  <g id="i-sparkle"><path d="M12 3l1.5 5L18 9l-4.5 1L12 15l-1.5-5L6 9l4.5-1z"/><path d="M4 18l2-2 2 2-2 2z"/><path d="M18 15l2-1 2 1-2 2z"/></g>
  <g id="i-user"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></g>
  <g id="i-chevron-right"><polyline points="9 18 15 12 9 6"/></g>
</svg>

<div class="app">
  <div class="header">
    <div class="header-left">
      <div class="logo"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
      <div>
        <div class="header-title">NEXUS v7</div>
        <div class="header-sub"><span class="status-dot"></span>Online</div>
      </div>
    </div>
    <div style="font-size:12px;color:var(--text-muted);" id="session-info"></div>
  </div>

  <div class="messages" id="messages">
    <div class="welcome" id="welcome">
      <h3>Willkommen bei NEXUS</h3>
      <p>Dein KI-Agent mit Seele. Frag mich alles.</p>
      <div class="suggestions">
        <div class="suggestion" onclick="sendMsg('Wer bist du?')">Wer bist du?</div>
        <div class="suggestion" onclick="sendMsg('Was kannst du machen?')">Was kannst du?</div>
        <div class="suggestion" onclick="sendMsg('Erklaer mir das Projekt')">Das Projekt</div>
        <div class="suggestion" onclick="sendMsg('Schreibe ein Python-Skript')">Code schreiben</div>
      </div>
    </div>
  </div>

  <div class="typing-indicator" id="typing">
    <div style="width:32px;height:32px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#a29bfe);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
      <svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:none;stroke:white;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;"><use href="#i-nexus"/></svg>
    </div>
    <div class="typing-bubble">
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
    </div>
  </div>

  <div class="input-area">
    <div class="input-wrapper">
      <textarea class="msg-input" id="input" placeholder="Nachricht an NEXUS..." rows="1"
                onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send-btn" id="send-btn" onclick="sendMessage()"><svg viewBox="0 0 24 24"><use href="#i-send"/></svg></button>
    </div>
  </div>
</div>

<div class="name-overlay" id="name-overlay">
  <div class="name-card">
    <div class="logo" style="width:56px;height:56px;margin:0 auto 16px;"><svg viewBox="0 0 24 24"><use href="#i-nexus"/></svg></div>
    <h2>Willkommen bei NEXUS</h2>
    <p>Open-Source KI-Agent mit Seele.<br>Wie moechtest du heissen?</p>
    <input type="text" class="name-input" id="name-input" placeholder="Dein Name..."
           onkeydown="if(event.key==='Enter')document.getElementById('name-btn').click()" autofocus>
    <button class="name-btn" id="name-btn" onclick="setName()">Los gehts</button>
  </div>
</div>

<script>
const API = window.location.origin;
let sessionId = null;
let userName = localStorage.getItem('nexus_user') || '';
let ws = null;
let useWS = true;

// Restore session
if (userName) {
  sessionId = localStorage.getItem('nexus_session') || null;
  document.getElementById('name-overlay').style.display = 'none';
  document.getElementById('session-info').textContent = userName;
}

function setName() {
  const input = document.getElementById('name-input');
  const name = input.value.trim();
  if (!name) return;
  userName = name;
  localStorage.setItem('nexus_user', name);
  document.getElementById('name-overlay').style.display = 'none';
  document.getElementById('session-info').textContent = name;
}

function formatTime(ts) {
  const d = new Date(ts ? ts * 1000 : Date.now());
  return d.toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'});
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function formatMessage(text) {
  // Basic markdown: code blocks, inline code, bold, italic
  let html = escapeHtml(text);
  // Code blocks
  html = html.replace(/```(\\w*)\\n?([\\s\\S]*?)```/g, '<pre><code>$2</code></pre>');
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
  // Italic
  html = html.replace(/\\*([^*]+)\\*/g, '<em>$1</em>');
  // Line breaks
  html = html.replace(/\\n/g, '<br>');
  return html;
}

function addMessage(role, content) {
  const container = document.getElementById('messages');
  const welcome = document.getElementById('welcome');
  if (welcome) welcome.style.display = 'none';

  const msg = document.createElement('div');
  msg.className = `msg ${role}`;

  const avatarSvg = role === 'nexus'
    ? '<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:none;stroke:white;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;"><use href="#i-nexus"/></svg>'
    : '<svg viewBox="0 0 24 24" style="width:18px;height:18px;fill:none;stroke:white;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;"><use href="#i-user"/></svg>';

  msg.innerHTML = `
    <div class="msg-avatar">${avatarSvg}</div>
    <div>
      <div class="msg-bubble">${formatMessage(content)}</div>
      <div class="msg-time">${formatTime()}</div>
    </div>
  `;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

function setTyping(show) {
  document.getElementById('typing').className = show ? 'typing-indicator active' : 'typing-indicator';
}

async function sendMessage() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  autoResize(input);
  addMessage('user', text);
  setTyping(true);
  document.getElementById('send-btn').disabled = true;

  try {
    const res = await fetch(API + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
        user_name: userName,
      }),
    });
    const data = await res.json();

    if (data.session_id) {
      sessionId = data.session_id;
      localStorage.setItem('nexus_session', sessionId);
    }

    addMessage('nexus', data.response);
  } catch (e) {
    addMessage('nexus', 'Verbindungsfehler: ' + e.message);
  } finally {
    setTyping(false);
    document.getElementById('send-btn').disabled = false;
    input.focus();
  }
}

function sendMsg(text) {
  document.getElementById('input').value = text;
  sendMessage();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

// Focus input
document.getElementById('input').focus();
if (!userName) {
  setTimeout(() => document.getElementById('name-input').focus(), 100);
}
</script>
</body>
</html>'''


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