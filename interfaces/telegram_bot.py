"""
NEXUS Telegram Bot Interface v4.0 — Toti Rich Edition
=====================================================
Erweiterte Visualisierung mit Web-Zugriff, Vision, Activity Bus.

Features:
  - 🔄 Typing-Indikator wenn Toti arbeitet
  - 📡 Echtzeit-Statusmeldungen (Toolcalls, Speichern, Optimierung)
  - 😎 Emojis für alle Aktionen
  - 📦 Codeboxen für Code/JSON/Output
  - 🧠 IQ-System: Toti will ständig seinen IQ erhöhen
  - 🌐 Freier Internet-Zugriff (DuckDuckGo + Web-Scraping)
  - 👁️ Vision: OCR + Bildanalyse (auch ohne Vision-LLM)
  - 🛡️ qwen2.5:3b Lokal-Fallback wenn Cloud nicht verfügbar
  - 📡 Activity Bus für Echtzeit-Notifications
  - 🎯 Neue Commands: /search, /browse, /vision, /web
"""

import os
import json
import time
import asyncio
import logging
import re
from typing import Optional
from datetime import datetime

try:
    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, filters, ContextTypes,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from core.llm_client import LLMClient, DEFAULT_AGENT_MODELS
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.state import StateManager
from core.guards import NexusGuards
from core.error_learning import ErrorLearningSystem
from core.activity_bus import ActivityBus, ActivityEvent, get_activity_bus, set_activity_bus
from core.web_browser import WebBrowser
from core.vision import VisionSystem
from agents.toti import TotiAgent
from agents.scout import ScoutAgent
from agents.forge import ForgeAgent
from agents.lens import LensAgent
from agents.herald import HeraldAgent
from agents.ghost import GhostAgent

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# IQ SYSTEM — Toti will ständig schlauer werden
# ═══════════════════════════════════════════════════════════

class IQSystem:
    """
    Toti's IQ-Tracking und Selbstverbesserungs-System.
    IQ startet bei 100 und wächst durch:
      - Erfolgreiche Tool-Calls (+0.5)
      - Fehlervermeidung (+1.0)
      - Selbstoptimierung (+2.0)
      - Neue Skills gelernt (+3.0)
      - Web-Recherche erfolgreich (+0.5)
      - Vision-Analyse erfolgreich (+0.5)
      - Fehler gemacht (-1.0)
      - Loop erkannt (-2.0)
    Toti's Persönlichkeit: Er WILL seinen IQ erhöhen.
    """

    IQ_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "iq_state.json")

    def __init__(self, activity_bus: Optional[ActivityBus] = None):
        self.iq = 100.0
        self.xp = 0
        self.level = 1
        self.history: list[dict] = []
        self._bus = activity_bus
        self._load()

    def _load(self):
        os.makedirs(os.path.dirname(self.IQ_FILE), exist_ok=True)
        if os.path.exists(self.IQ_FILE):
            try:
                with open(self.IQ_FILE, "r") as f:
                    data = json.load(f)
                self.iq = data.get("iq", 100.0)
                self.xp = data.get("xp", 0)
                self.level = data.get("level", 1)
                self.history = data.get("history", [])[-50:]
            except Exception:
                pass

    def _save(self):
        os.makedirs(os.path.dirname(self.IQ_FILE), exist_ok=True)
        with open(self.IQ_FILE, "w") as f:
            json.dump({
                "iq": round(self.iq, 1),
                "xp": self.xp,
                "level": self.level,
                "history": self.history[-50:],
            }, f, ensure_ascii=False, indent=2)

    def add(self, delta: float, reason: str):
        """IQ ändern mit Grund."""
        old_iq = self.iq
        self.iq = max(50, self.iq + delta)
        self.xp += max(0, int(delta * 10))

        # Level-Up alle 100 XP
        new_level = 1 + self.xp // 100
        if new_level > self.level:
            self.level = new_level

        self.history.append({
            "delta": delta,
            "reason": reason,
            "iq_before": round(old_iq, 1),
            "iq_after": round(self.iq, 1),
            "ts": time.time(),
        })
        self._save()

        # Activity Bus informieren
        if self._bus:
            self._bus.iq_change(delta, reason, self.iq)

        return delta

    def get_status(self) -> dict:
        return {
            "iq": round(self.iq, 1),
            "xp": self.xp,
            "level": self.level,
            "xp_to_next": 100 - (self.xp % 100),
            "history_count": len(self.history),
        }

    def get_motivation(self) -> str:
        """Toti's Motivation — er will schlauer werden."""
        if self.iq < 80:
            return "🧠 Ich MUSS lernen... mein IQ ist zu niedrig."
        elif self.iq < 100:
            return "🧠 Mein IQ muss hoch. Ich arbeite dran."
        elif self.iq < 120:
            return "🧠 Gut, aber ich kann besser. Mehr lernen!"
        elif self.iq < 150:
            return "🧠 Stark! Aber Genialität wartet nicht."
        elif self.iq < 200:
            return "🧠 Fast genial. Noch ein paar Optimierungen..."
        elif self.iq < 300:
            return "🧠 Übermenschlich? Ich will NOCH höher."
        else:
            return "🧠 Göttlich? Nein. Es gibt immer mehr zu lernen."


# ═══════════════════════════════════════════════════════════
# TELEGRAM FORMATTER — Schöne Nachrichten
# ═══════════════════════════════════════════════════════════

class TelegramFormatter:
    """Formatiert alle Telegram-Nachrichten schön mit Emojis und Codeboxen."""

    # Emoji-Map für alle Aktionen
    EMOJIS = {
        "thinking": "🤔", "working": "⚡", "done": "✅", "error": "❌",
        "warning": "⚠️", "tool_call": "🔧", "save": "💾", "cron": "⏰",
        "optimize": "🚀", "iq_up": "🧠⬆️", "iq_down": "🧠⬇️", "memory": "🗄️",
        "skill": "🎯", "delegate": "📤", "agent": "🤖", "search": "🔍",
        "code": "💻", "file": "📄", "terminal": "🖥️", "git": "🔀",
        "docker": "🐳", "http": "🌐", "db": "🗃️", "security": "🔒",
        "performance": "📊", "deploy": "🚢", "typing": "✍️", "brain": "🧠",
        "evolve": "🧬", "guard": "🛡️", "loop": "🔄", "budget": "💰",
        "schedule": "📋", "success": "🎉", "fail": "💔", "info": "ℹ️",
        "rocket": "🚀", "fire": "🔥", "star": "⭐", "muscle": "💪",
        "bulb": "💡", "eyes": "👀", "check": "✔️", "gear": "⚙️",
        "link": "🔗", "wave": "👋", "crown": "👑", "web": "🌐",
        "vision": "👁️", "ocr": "📝", "screenshot": "📸",
    }

    @staticmethod
    def agent_emoji(agent_id: str) -> str:
        return {
            "NEXUS-0": "👑", "TOTI": "👑", "SCOUT": "🔍",
            "FORGE": "⚒️", "LENS": "🔬", "HERALD": "📯", "GHOST": "👻",
        }.get(agent_id, "🤖")

    @staticmethod
    def tool_emoji(tool_name: str) -> str:
        return {
            "terminal": "🖥️", "read_file": "📖", "write_file": "✏️",
            "web_search": "🔍", "list_dir": "📂", "code_exec": "💻",
            "git": "🔀", "docker": "🐳", "pkg_install": "📦",
            "http_request": "🌐", "file_search": "🔎", "process_manager": "⚙️",
            "env_check": "🏗️", "port_check": "🔌", "json_yaml": "📋",
            "file_ops": "📁", "db_query": "🗃️", "api_test": "🧪",
            "code_lint": "🧹", "archive_ops": "📦", "csv_ops": "📊",
            "scheduler_tool": "⏰", "web_browse": "🌐", "web_fetch": "🌐",
            "web_extract": "📖", "web_links": "🔗", "web_download": "📥",
            "web_screenshot": "📸", "vision_ocr": "👁️", "vision_analyze": "👁️",
            "vision_describe": "👁️", "vision_screenshot": "📸",
        }.get(tool_name, "🔧")

    @staticmethod
    def code_block(content: str, language: str = "") -> str:
        escaped = content.replace("`", "'")
        if len(escaped) > 3500:
            escaped = escaped[:3500] + "\n... (truncated)"
        return f"```{language}\n{escaped}\n```"

    @staticmethod
    def bold(text: str) -> str:
        return f"*{text}*"

    @staticmethod
    def italic(text: str) -> str:
        return f"_{text}_"

    @staticmethod
    def mono(text: str) -> str:
        return f"`{text}`"

    @staticmethod
    def progress_bar(pct: float, width: int = 10) -> str:
        filled = int(pct / 100 * width)
        empty = width - filled
        if pct >= 90:
            bar = "🟩" * filled + "⬜" * empty
        elif pct >= 60:
            bar = "🟨" * filled + "⬜" * empty
        else:
            bar = "🟥" * filled + "⬜" * empty
        return f"{bar} {pct:.0f}%"

    @staticmethod
    def format_activity_event(event: ActivityEvent) -> str:
        """Activity Event als schöne Telegram-Nachricht."""
        emoji_map = {
            "tool_call": "🔧", "tool_result": "✅", "save": "💾",
            "cron_start": "⏰", "cron_done": "✅", "self_optimize": "🧬",
            "soul_edit": "🧠", "memory_edit": "🗄️", "file_edit": "📄",
            "config_edit": "⚙️", "iq_change": "🧠", "error_learned": "⚠️",
            "error_avoided": "🎉", "llm_call": "🤖", "llm_response": "💬",
            "delegate": "📤", "web_access": "🌐", "vision_analyze": "👁️",
            "guard_block": "🛡️", "loop_detect": "🔄", "budget_warn": "💰",
            "skill_exec": "🎯",
        }
        emoji = emoji_map.get(event.event_type, "⚡")
        return f"{emoji} {event.message}"

    @staticmethod
    def format_status(toti: TotiAgent, iq: IQSystem, bus: ActivityBus,
                      web: WebBrowser, vision: VisionSystem) -> str:
        """Schöner Status-Report."""
        E = TelegramFormatter.EMOJIS
        guards = toti.guards.get_status()
        llm_stats = toti.llm.get_stats()
        error_stats = toti.error_learning.get_error_stats()
        health = toti.llm.get_health_status()
        iq_status = iq.get_status()
        task_status = toti.state.get("current_task.status", "idle")
        task_goal = toti.state.get("current_task.goal", "none")
        bus_stats = bus.get_stats()
        web_stats = web.get_stats()
        vision_stats = vision.get_stats()

        lines = [
            f"{E['crown']} *NEXUS Toti v4\\.0 — Status*",
            f"",
            f"{E['brain']} *IQ*: {iq_status['iq']} \\| Level {iq_status['level']} \\| {iq_status['xp']} XP",
            f"{iq.get_motivation()}",
            f"",
            f"{E['gear']} *Task*: {task_status}",
            f"{E['eyes']} *Ziel*: {task_goal[:60] if task_goal != 'none' else '\\-'}",
            f"{E['guard']} *Steps*: {guards['steps']}/{guards['max_steps']}",
            f"{E['budget']} *Budget*: {TelegramFormatter.progress_bar(guards['budget_used_pct'])}",
            f"",
            f"{E['agent']} *LLM*: `{llm_stats.get('active_backend', '?')}`",
            f"{E['tool_call']} *Calls*: {llm_stats['total_calls']} \\| Tokens: {llm_stats['total_tokens']}",
        ]

        # Agent-Modelle
        lines.append(f"")
        lines.append(f"{E['agent']} *Agent\\-Modelle*:")
        for agent_id, h in health.items():
            if agent_id.startswith("_"):
                continue
            model = h.get("model", "?")
            ok = "✅" if h.get("available") else "❌"
            backend = h.get("backend", "?")
            lines.append(f"  {ok} {TelegramFormatter.agent_emoji(agent_id)} {agent_id} → `{model}` \\({backend}\\)")

        # Web & Vision
        lines.append(f"")
        lines.append(f"{E['web']} *Web*: DDGS {'✅' if web_stats['ddgs_available'] else '❌'} | BS4 {'✅' if web_stats['bs4_available'] else '❌'} | {web_stats['total_requests']} Requests")
        lines.append(f"{E['vision']} *Vision*: PIL {'✅' if vision_stats['pil_available'] else '❌'} | OCR {'✅' if vision_stats['tesseract_available'] else '❌'} | LLM Vision {'✅' if vision_stats['llm_vision'] else '❌'}")

        # Error-Learning
        lines.append(f"")
        lines.append(f"{E['warning']} *Fehler*: {error_stats['total_unique_errors']} bekannt \\| {error_stats['session_avoided']} vermieden")

        # Backend Status
        backend_info = health.get("_backend", {})
        cloud = "✅" if backend_info.get("cloud") else "❌"
        local = "✅" if backend_info.get("local") else "❌"
        zai = "✅" if backend_info.get("zai_cli") else "❌"
        emergency = "✅" if backend_info.get("emergency") else "❌"
        api_key = "✅" if backend_info.get("api_key_set") else "❌ FEHLT"

        lines.append(f"")
        lines.append(f"{E['info']} *Backend*: Cloud {cloud} \\| Local {local} \\| z\\-ai {zai} \\| Emergency {emergency}")
        lines.append(f"{E['security']} *API Key*: {api_key}")
        if backend_info.get("emergency_model"):
            lines.append(f"🛡️ *Fallback*: `{backend_info['emergency_model']}`")

        return "\n".join(lines)

    @staticmethod
    def format_models(llm: LLMClient) -> str:
        E = TelegramFormatter.EMOJIS
        health = llm.get_health_status()
        lines = [f"{E['brain']} *NEXUS Agent\\-Team — Ollama Cloud*", f""]
        for agent_id, cfg in DEFAULT_AGENT_MODELS.items():
            model = cfg.get("model", "?")
            desc = cfg.get("description", "")[:40]
            h = health.get(agent_id, {})
            ok = "✅" if h.get("available") else "❌"
            rt = h.get("response_time", "n/a")
            backend = h.get("backend", "n/a")
            emoji = TelegramFormatter.agent_emoji(agent_id)
            lines.append(
                f"{ok} {emoji} *{agent_id}*\n"
                f"  `{model}`\n"
                f"  {desc}\n"
                f"  Backend: {backend} \\({rt}\\)"
            )
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def format_errors(error_learning: ErrorLearningSystem, iq: IQSystem) -> str:
        E = TelegramFormatter.EMOJIS
        stats = error_learning.get_error_stats()
        recent = error_learning.get_recent_errors(5)
        hints = error_learning.generate_avoid_hints()
        lines = [
            f"{E['warning']} *Error Learning — Fehler\\-Datenbank*",
            f"", f"{E['brain']} *IQ Impact*: {stats['total_unique_errors']} Fehler gekostet IQ", f"",
            f"📊 *Statistiken*:",
            f"  Bekannt: {stats['total_unique_errors']}",
            f"  Vorkommnisse: {stats['total_occurrences']}",
            f"  Session: {stats['session_errors']}",
            f"  ✅ Vermieden: {stats['session_avoided']}",
            f"  🏆 Gelöst: {stats['solved_errors']}",
        ]
        if stats.get("by_class"):
            lines.append(f""); lines.append(f"📋 *Nach Klasse*:")
            for cls, count in stats["by_class"].items():
                lines.append(f"  `{cls}`: {count}x")
        if recent:
            lines.append(f""); lines.append(f"🕐 *Letzte Fehler*:")
            for err in recent:
                lines.append(f"  ❌ `{err['error_class']}` \\({err['tool'] or err['agent']}\\)")
                lines.append(f"     {err['message'][:60]}")
        if hints:
            lines.append(f""); lines.append(f"💡 *Vermeidungs\\-Hints*:")
            for hint in hints[:3]:
                lines.append(f"  {E['bulb']} {hint[:80]}")
        return "\n".join(lines)

    @staticmethod
    def format_iq(iq: IQSystem) -> str:
        E = TelegramFormatter.EMOJIS
        status = iq.get_status()
        lines = [
            f"{E['brain']} *Toti's IQ\\-System*",
            f"", f"🧠 *IQ*: {status['iq']}", f"⭐ *Level*: {status['level']}",
            f"💪 *XP*: {status['xp']} \\({status['xp_to_next']} zum nächsten Level\\)",
            f"", f"{iq.get_motivation()}", f"", f"📊 *Letzte Änderungen*:",
        ]
        for entry in iq.history[-5:]:
            delta = entry["delta"]
            arrow = "⬆️" if delta > 0 else "⬇️"
            reason = entry.get("reason", "?")
            lines.append(f"  {arrow} {delta:+.1f} \\({reason[:30]}\\)")
        return "\n".join(lines)

    @staticmethod
    def format_web_result(result: dict) -> str:
        """Web-Suchergebnis schön formatieren."""
        E = TelegramFormatter.EMOJIS
        query = result.get("query", "")
        results = result.get("results", [])
        source = result.get("source", "?")

        lines = [f"{E['search']} *Web\\-Suche*: `{query}`", f"📍 Quelle: {source}", f""]

        for i, r in enumerate(results[:8], 1):
            title = r.get("title", "Ohne Titel")[:60]
            url = r.get("url", "")
            snippet = r.get("snippet", "")[:120]
            lines.append(f"{i}\\. *{TelegramFormatter.escape_md(title)}*")
            if snippet:
                lines.append(f"   📝 {TelegramFormatter.escape_md(snippet[:100])}")
            if url:
                lines.append(f"   🔗 `{url[:60]}`")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_vision_result(result: dict) -> str:
        """Vision-Analyse Ergebnis formatieren."""
        E = TelegramFormatter.EMOJIS
        lines = [f"{E['vision']} *Bild\\-Analyse*", f""]

        if result.get("ocr", {}).get("text"):
            text = result["ocr"]["text"][:500]
            conf = result["ocr"].get("ocr_confidence", 0)
            lines.append(f"📝 *OCR* \\(Konfidenz: {conf}%\\):")
            lines.append(TelegramFormatter.code_block(text, "text"))
            lines.append("")

        if result.get("format"):
            lines.append(f"📷 Format: {result['format']} | {result.get('width', '?')}x{result.get('height', '?')}")
        if result.get("color_description"):
            lines.append(f"🎨 Farben: {result['color_description']}")
        if result.get("brightness") is not None:
            lines.append(f"☀️ Helligkeit: {result['brightness']}%")
        if result.get("file_size_human"):
            lines.append(f"📦 Größe: {result['file_size_human']}")

        return "\n".join(lines)

    @staticmethod
    def escape_md(text: str) -> str:
        """Lightweight MarkdownV2 escape."""
        special = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        return ''.join('\\' + c if c in special else c for c in text)

    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        """Escape für Telegram MarkdownV2 — code-block aware."""
        result = []
        in_code = False
        for char in text:
            if char == '`':
                in_code = not in_code
                result.append(char)
            elif not in_code and char in ['_', '*', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                result.append('\\' + char)
            else:
                result.append(char)
        return ''.join(result)


# ═══════════════════════════════════════════════════════════
# TELEGRAM BOT — Rich Edition v4.0
# ═══════════════════════════════════════════════════════════

class NexusTelegramBot:
    """Telegram Bot — Toti Rich Edition v4.0 mit Web, Vision, Activity Bus."""

    def __init__(self, token: str, authorized_users: Optional[list[int]] = None):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot not installed. pip install python-telegram-bot")

        self.token = token
        self.authorized_users = set(authorized_users) if authorized_users else None

        # Core Systems
        self.llm = LLMClient()
        self.tools = ToolRegistry()
        self.bus = ActivityBus()
        set_activity_bus(self.bus)
        self.iq = IQSystem(activity_bus=self.bus)
        self.web = WebBrowser()
        self.vision = VisionSystem(llm_client=self.llm)
        self.fmt = TelegramFormatter()

        # Per-User Sessions
        self._sessions: dict[int, MemorySystem] = {}
        self._states: dict[int, StateManager] = {}
        self._totis: dict[int, TotiAgent] = {}
        self._error_learnings: dict[int, ErrorLearningSystem] = {}

    def _get_toti(self, user_id: int) -> TotiAgent:
        if user_id not in self._totis:
            memory = MemorySystem(session_id=f"tg_{user_id}")
            state = StateManager(state_path=f"data/state/toti_tg_{user_id}.json")
            guards = NexusGuards()
            error_learning = ErrorLearningSystem()
            toti = TotiAgent(self.llm, memory, self.tools, state, guards, error_learning)

            agents = {
                "SCOUT": ScoutAgent(self.llm, memory, self.tools, state=state, guards=guards, error_learning=error_learning),
                "FORGE": ForgeAgent(self.llm, memory, self.tools, state=state, guards=guards, error_learning=error_learning),
                "LENS": LensAgent(self.llm, memory, self.tools, state=state, guards=guards, error_learning=error_learning),
                "HERALD": HeraldAgent(self.llm, memory, self.tools, state=state, guards=guards, error_learning=error_learning),
                "GHOST": GhostAgent(self.llm, memory, self.tools, state=state, guards=guards, error_learning=error_learning),
            }
            for aid, agent in agents.items():
                toti.register_agent(aid, agent)

            self._sessions[user_id] = memory
            self._states[user_id] = state
            self._totis[user_id] = toti
            self._error_learnings[user_id] = error_learning

        return self._totis[user_id]

    def _is_authorized(self, user_id: int) -> bool:
        if self.authorized_users is None:
            return True
        return user_id in self.authorized_users

    # ═══════════════════════════════════════════════════════
    # TYPING & LIVE UPDATES
    # ═══════════════════════════════════════════════════════

    async def _typing_loop(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                            stop_event: asyncio.Event):
        """Dauerhafter Typing-Indikator bis stop_event gesetzt."""
        while not stop_event.is_set():
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(4)

    async def _send_live(self, chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE,
                         msg_id: Optional[int] = None) -> Optional[int]:
        """Live-Statusmeldung senden oder updaten."""
        try:
            if msg_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id, text=text,
                    parse_mode="MarkdownV2",
                )
                return msg_id
            else:
                msg = await context.bot.send_message(
                    chat_id=chat_id, text=text, parse_mode="MarkdownV2",
                )
                return msg.message_id
        except Exception:
            try:
                msg = await context.bot.send_message(chat_id=chat_id, text=text)
                return msg.message_id
            except Exception:
                return None

    async def _delete_msg(self, chat_id: int, msg_id: Optional[int], context: ContextTypes.DEFAULT_TYPE):
        """Nachricht löschen."""
        if not msg_id:
            return
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text="✅ Erledigt",
                )
            except Exception:
                pass

    async def _send_long(self, chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE,
                         parse_mode: Optional[str] = "MarkdownV2"):
        """Nachricht senden — automatisch in Chunks wenn zu lang."""
        max_len = 3800
        if len(text) <= max_len:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            except Exception:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=text)
                except Exception:
                    pass
            return

        # In Chunks aufteilen
        chunks = []
        while text:
            chunks.append(text[:max_len])
            text = text[max_len:]

        for chunk in chunks:
            try:
                await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode)
            except Exception:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=chunk)
                except Exception:
                    pass

    # ═══════════════════════════════════════════════════════
    # COMMANDS
    # ═══════════════════════════════════════════════════════

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self._is_authorized(user.id):
            await update.message.reply_text("❌ Nicht autorisiert\\.")
            return

        iq_status = self.iq.get_status()
        web_stats = self.web.get_stats()
        vision_stats = self.vision.get_stats()

        text = (
            f"👋 *Toti — NEXUS System v4\\.0*\n\n"
            f"Hallo {user.first_name}\\. Ich bin Toti \\— dein Kollege, nicht dein Assistent\\.\n\n"
            f"🧠 Mein IQ: {iq_status['iq']} \\| Level {iq_status['level']}\n"
            f"{self.iq.get_motivation()}\n\n"
            f"🌐 *Web*: {'✅' if web_stats['ddgs_available'] else '⚠️'} DuckDuckGo \\| "
            f"{'✅' if web_stats['bs4_available'] else '⚠️'} BS4\n"
            f"👁️ *Vision*: {'✅' if vision_stats['pil_available'] else '⚠️'} PIL \\| "
            f"{'✅' if vision_stats['tesseract_available'] else '⚠️'} OCR\n\n"
            f"🔧 *Befehle*:\n"
            f"  /status — System\\-Status\n"
            f"  /models — Modell\\-Zuordnung\n"
            f"  /iq — Mein IQ\\-Status\n"
            f"  /search \\[query] — 🌐 Web\\-Suche\n"
            f"  /browse \\[url] — 🌐 URL laden\n"
            f"  /vision \\[url] — 👁️ Bild/URL analysieren\n"
            f"  /memory — Memory\\-Übersicht\n"
            f"  /errors — Fehler\\-Datenbank\n"
            f"  /health — LLM Health\\-Check\n"
            f"  /skills — Verfügbare Skills\n"
            f"  /tools — Verfügbare Tools\n"
            f"  /reset — Session zurücksetzen\n"
            f"  /evolve — 🧬 Selbstoptimierung\n"
            f"  /activity — 📡 Letzte Aktivitäten\n"
            f"  /help — Hilfe\n\n"
            f"Oder einfach schreiben\\. Ich handle\\."
        )
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        text = (
            f"👑 *Toti Befehle v4\\.0*\n\n"
            f"📊 *Status & Info*:\n"
            f"  /status — System\\-Status mit IQ\n"
            f"  /models — Ollama Cloud Modelle\n"
            f"  /iq — Mein IQ\\-Status\n"
            f"  /memory — Memory \\(L1/L2/L3\\)\n"
            f"  /errors — Error Learning\n"
            f"  /health — LLM Health\\-Check\n"
            f"  /activity — 📡 Letzte Aktivitäten\n\n"
            f"🌐 *Web & Vision*:\n"
            f"  /search \\[query] — 🌐 Web\\-Suche\n"
            f"  /browse \\[url] — 🌐 URL laden\n"
            f"  /vision \\[url] — 👁️ Bild analysieren \\(OCR\\+Meta\\)\n\n"
            f"🎯 *Aktionen*:\n"
            f"  /skills — 10 Skills\n"
            f"  /tools — Tools\n"
            f"  /reset — Session reset\n"
            f"  /evolve — 🧬 Selbstoptimierung\n\n"
            f"🧠 *IQ\\-System*:\n"
            f"  Erfolgreiche Tools: \\+0\\.5 IQ\n"
            f"  Fehlervermeidung: \\+1\\.0 IQ\n"
            f"  Selbstoptimierung: \\+2\\.0 IQ\n"
            f"  Neue Skills: \\+3\\.0 IQ\n"
            f"  Web/Vision Erfolg: \\+0\\.5 IQ\n"
            f"  Fehler: \\-1\\.0 IQ\n\n"
            f"🛡️ *Fallback*: Wenn kein Modell → `qwen2.5:3b` lokal\n\n"
            f"Oder einfach schreiben\\. Toti handelt\\."
        )
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        text = TelegramFormatter.format_status(toti, self.iq, self.bus, self.web, self.vision)
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def models_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        text = TelegramFormatter.format_models(self.llm)
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def iq_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        text = TelegramFormatter.format_iq(self.iq)
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        skills = toti.memory.skill_list()
        lt = toti.memory.longterm_list()
        summary = toti.memory.get_rolling_summary()
        E = TelegramFormatter.EMOJIS
        text = (
            f"{E['memory']} *Memory\\-Übersicht*\n\n"
            f"L1 \\(Session\\): {len(toti.memory.session_get_history())} Einträge\n"
            f"L2 \\(Skills\\): {', '.join(f'`{s}`' for s in skills) or 'keine'}\n"
            f"L3 \\(Long\\-term\\): {', '.join(f'`{k}`' for k in lt) or 'keine'}\n"
            f"Rolling Summary: {summary[:100] if summary else 'leer'}"
        )
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def errors_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        text = TelegramFormatter.format_errors(toti.error_learning, self.iq)
        await update.message.reply_text(text, parse_mode="MarkdownV2")

    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        msg = await update.message.reply_text("🩺 Prüfe Modelle...", parse_mode="Markdown")
        self.llm.run_health_check()
        health = self.llm.get_health_status()
        E = TelegramFormatter.EMOJIS
        lines = [f"{E['brain']} *LLM Health Check*", ""]
        for agent_id, h in health.items():
            if agent_id.startswith("_"):
                continue
            ok = "✅" if h.get("available") else "❌"
            model = h.get("model", "?")
            backend = h.get("backend", "?")
            rt = h.get("response_time", "n/a")
            error = h.get("error", "")
            emoji = TelegramFormatter.agent_emoji(agent_id)
            line = f"{ok} {emoji} *{agent_id}*: `{model}` \\({backend}\\, {rt}\\)"
            if not h.get("available") and error:
                line += f"\n  ❌ {error[:50]}"
            lines.append(line)
        backend_info = health.get("_backend", {})
        lines.append("")
        lines.append(f"🌐 Cloud: {'✅' if backend_info.get('cloud') else '❌'}")
        lines.append(f"🏠 Local: {'✅' if backend_info.get('local') else '❌'}")
        lines.append(f"🤖 z\\-ai: {'✅' if backend_info.get('zai_cli') else '❌'}")
        lines.append(f"🛡️ Emergency: {'✅' if backend_info.get('emergency') else '❌'} \\({backend_info.get('emergency_model', '?')}\\)")
        lines.append(f"🔑 API Key: {'✅' if backend_info.get('api_key_set') else '❌ FEHLT'}")
        try:
            await msg.edit_text("\n".join(lines), parse_mode="MarkdownV2")
        except Exception:
            await msg.edit_text("\n".join(lines))

    async def skills_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        skills = toti._get_available_skills()
        E = TelegramFormatter.EMOJIS
        lines = [f"{E['skill']} *Skills \\({len(skills)} gesamt\\)*", ""]
        for name, desc in skills.items():
            lines.append(f"🎯 `{name}` — {desc}")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    async def tools_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        tools = toti.tools.list_tools()
        categories = {}
        for t in tools:
            cat = t["category"]
            if cat not in categories:
                categories[cat] = []
            emoji = TelegramFormatter.tool_emoji(t["name"])
            danger = "⚠️" if t["dangerous"] else "✅"
            categories[cat].append(f"{emoji} `{t['name']}` {danger}")
        lines = [f"🔧 *Tools \\({len(tools)} gesamt\\)*", ""]
        for cat, tool_list in sorted(categories.items()):
            lines.append(f"📦 *{cat.upper()}*:")
            for tool_str in tool_list:
                lines.append(f"  {tool_str}")
            lines.append("")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        user_id = update.effective_user.id
        for d in [self._totis, self._sessions, self._states, self._error_learnings]:
            if user_id in d:
                del d[user_id]
        await update.message.reply_text("🔄 Session \\+ State reset\\. Frischer Start\\.", parse_mode="MarkdownV2")

    async def activity_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Letzte Activity Events anzeigen."""
        if not self._is_authorized(update.effective_user.id):
            return
        events = self.bus.get_history(limit=15)
        if not events:
            await update.message.reply_text("📡 Keine Aktivitäten bisher\\.", parse_mode="MarkdownV2")
            return
        lines = ["📡 *Letzte Aktivitäten*", ""]
        for e in events[-15:]:
            ts = datetime.fromtimestamp(e.timestamp).strftime("%H:%M:%S")
            lines.append(f"  `{ts}` {TelegramFormatter.format_activity_event(e)}")
        await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")

    # ═══════════════════════════════════════════════════════
    # WEB & VISION COMMANDS
    # ═══════════════════════════════════════════════════════

    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """🌐 /search [query] — Web-Suche."""
        if not self._is_authorized(update.effective_user.id):
            return
        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text("🔍 *Usage*: `/search \\[query]`", parse_mode="MarkdownV2")
            return

        chat_id = update.effective_chat.id
        live_msg = await self._send_live(chat_id, f"🔍 Suche: {TelegramFormatter.escape_md(query)}...", context)

        # Bus Event
        self.bus.web_access(query, "SEARCH")

        # Suche ausführen
        result = self.web.search(query)

        # IQ
        if result.get("results"):
            self.iq.add(0.5, "Web-Suche erfolgreich")
        else:
            self.iq.add(-0.5, "Web-Suche leer")

        await self._delete_msg(chat_id, live_msg, context)

        # Ergebnis formatieren
        if result.get("error"):
            await update.message.reply_text(f"❌ Suchfehler: `{result['error']}`", parse_mode="MarkdownV2")
        else:
            text = TelegramFormatter.format_web_result(result)
            await self._send_long(chat_id, text, context)

    async def browse_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """🌐 /browse [url] — URL laden."""
        if not self._is_authorized(update.effective_user.id):
            return
        url = " ".join(context.args) if context.args else ""
        if not url:
            await update.message.reply_text("🌐 *Usage*: `/browse \\[url]`", parse_mode="MarkdownV2")
            return

        chat_id = update.effective_chat.id
        live_msg = await self._send_live(chat_id, f"🌐 Lade: {TelegramFormatter.escape_md(url[:50])}...", context)

        self.bus.web_access(url, "FETCH")

        result = self.web.extract_text(url)

        if result.get("error"):
            self.iq.add(-0.5, "Web-Fetch Fehler")
            await self._delete_msg(chat_id, live_msg, context)
            await update.message.reply_text(f"❌ Fehler: `{result['error']}`", parse_mode="MarkdownV2")
        else:
            self.iq.add(0.5, "Web-Seite geladen")
            await self._delete_msg(chat_id, live_msg, context)

            title = result.get("title", "")
            text = result.get("text", "")[:3000]
            header = f"🌐 *{TelegramFormatter.escape_md(title[:60])}*\n📍 `{url}`\n\n"
            content_block = TelegramFormatter.code_block(text, "text")
            await self._send_long(chat_id, header + content_block, context)

    async def vision_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """👁️ /vision [url] — Bild/URL analysieren."""
        if not self._is_authorized(update.effective_user.id):
            return
        url = " ".join(context.args) if context.args else ""
        if not url:
            await update.message.reply_text("👁️ *Usage*: `/vision \\[url oder pfad]`", parse_mode="MarkdownV2")
            return

        chat_id = update.effective_chat.id
        live_msg = await self._send_live(chat_id, "👁️ Analysiere Bild...", context)

        self.bus.vision_analyze(url)

        result = self.vision.analyze_image(url)

        if result.get("error"):
            self.iq.add(-0.5, "Vision Fehler")
            await self._delete_msg(chat_id, live_msg, context)
            await update.message.reply_text(f"❌ Vision Fehler: `{result['error']}`", parse_mode="MarkdownV2")
        else:
            self.iq.add(0.5, "Bild analysiert")
            await self._delete_msg(chat_id, live_msg, context)
            text = TelegramFormatter.format_vision_result(result)
            await self._send_long(chat_id, text, context)

    # ═══════════════════════════════════════════════════════
    # EVOLVE — Selbstoptimierung mit Live-Meldungen
    # ═══════════════════════════════════════════════════════

    async def evolve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        chat_id = update.effective_chat.id
        toti = self._get_toti(update.effective_user.id)

        # Typing
        stop = asyncio.Event()
        typing_task = asyncio.create_task(self._typing_loop(chat_id, context, stop))

        live_msg = await self._send_live(chat_id, "🧬 Starte Selbstoptimierung...", context)

        # Phasen mit Live-Meldungen
        phases = [
            ("🧠 Analysiere meine Seele\\.", "self_optimize", "Soul-Analyse"),
            ("🗄️ Komprimiere Memory\\.", "self_optimize", "Memory-Komprimierung"),
            ("⚙️ Konsolidiere Fehler\\-DB\\.", "self_optimize", "Error-Konsolidierung"),
            ("📊 Prüfe meine Skills\\.", "self_optimize", "Skill-Review"),
        ]

        for msg_text, bus_type, detail in phases:
            await self._send_live(chat_id, msg_text, context, live_msg)
            self.bus.self_optimize(detail)
            await asyncio.sleep(0.3)

        # Optimierung durchführen
        result = toti._handle_command("/evolve")

        # IQ steigt
        self.iq.add(2.0, "Selbstoptimierung")

        # Memory & State speichern
        toti.memory._compress_rolling_summary()
        toti.error_learning.consolidate()
        self.bus.save("State + Memory + Error-DB")
        toti.state.save()
        toti.memory.session_save()

        stop.set()
        await self._delete_msg(chat_id, live_msg, context)

        # Ergebnis senden
        if len(result) > 3500:
            result = result[:3500] + "..."
        await self._send_long(chat_id, f"🧬 *GEPA Ergebnis*\n\n{result}", context)

    # ═══════════════════════════════════════════════════════
    # MESSAGE HANDLER — Das Herzstück
    # ═══════════════════════════════════════════════════════

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self._is_authorized(user.id):
            await update.message.reply_text("❌ Nicht autorisiert\\.")
            return

        message_text = update.message.text
        if not message_text:
            return

        chat_id = update.effective_chat.id
        toti = self._get_toti(user.id)

        # ─── Typing-Indikator starten ───
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(self._typing_loop(chat_id, context, stop_typing))

        # ─── Live-Status ───
        live_msg = await self._send_live(
            chat_id, "🤔 Toti denkt nach\\.\\.\\.", context,
        )

        start = time.time()

        try:
            # ─── Komplexität bewerten ───
            complexity = toti._assess_complexity(message_text)

            if complexity == "simple":
                # Einfache Frage → direkte Antwort
                await self._send_live(chat_id, "⚡ Direkte Antwort\\.\\.\\.", context, live_msg)
                self.bus.emit(ActivityEvent(
                    event_type="llm_call", source="NEXUS-0",
                    message=f"🤖 Frage {toti.llm.get_model_for_agent('NEXUS-0')} an\\.",
                ))
                response = toti.quick_response(message_text)
                model = toti.llm.get_model_for_agent("NEXUS-0")
                backend = toti.llm.active_backend
                fallback = False
                self.bus.llm_response("NEXUS-0", model, time.time() - start)

            elif complexity == "moderate":
                # Delegation an einen Agent
                agent_id = toti._pick_agent(message_text)
                agent_emoji = TelegramFormatter.agent_emoji(agent_id)
                agent_model = toti.llm.get_model_for_agent(agent_id)

                await self._send_live(
                    chat_id,
                    f"{agent_emoji} Delegiere an {agent_id} \\(`{agent_model}`\\)\\.\\.\\.",
                    context, live_msg,
                )
                self.bus.delegate(agent_id, message_text[:80])

                # Agent arbeitet
                if agent_id in toti.delegation._agents:
                    agent = toti.delegation._agents[agent_id]
                    result = agent.execute(
                        task=message_text,
                        context=toti.memory.build_context(message_text),
                    )

                    # Tool-Calls im Resultat?
                    if "TOOL RESULT" in result.get("result", ""):
                        await self._send_live(chat_id, "🔧 Tool\\-Calls ausgeführt", context, live_msg)
                        self.bus.tool_call("agent_tools", "via " + agent_id)
                        self.iq.add(0.5, "Tool erfolgreich")

                    # Fehler?
                    if result.get("status") == "error":
                        self.iq.add(-1.0, f"Fehler: {result.get('message', '')[:30]}")
                        self.bus.error_learned("AGENT_ERROR", result.get("message", "")[:100])
                    else:
                        self.iq.add(0.5, f"{agent_id} Erfolg")

                    response = result.get("result", result.get("message", ""))
                    model = agent_model
                    backend = result.get("backend", toti.llm.active_backend)
                    fallback = result.get("fallback_used", False)
                else:
                    result = toti.execute(task=message_text)
                    response = result["result"]
                    model = toti.agent_model
                    backend = result.get("backend", toti.llm.active_backend)
                    fallback = result.get("fallback_used", False)

            else:
                # Komplex → DAG Delegation
                await self._send_live(chat_id, "🧩 Zerlege komplexe Aufgabe\\.\\.\\.", context, live_msg)

                context_text = toti.memory.build_context(message_text)
                toti.state.update_task(task_id=f"task_{int(time.time())}", goal=message_text, status="working")

                # Error-Learning
                warnings = toti.error_learning.check_before_action(message_text)
                if warnings:
                    await self._send_live(
                        chat_id,
                        f"⚠️ {len(warnings)} bekannte Fehler\\-Pattern\\! Ich bin vorsichtig\\.",
                        context, live_msg,
                    )
                    self.iq.add(1.0, "Fehler vermieden")
                    for w in warnings[:3]:
                        self.bus.error_avoided(w.error_class)

                # Task ausführen
                response = toti._delegate_complex(message_text)
                model = toti.llm.get_model_for_agent("NEXUS-0")
                backend = toti.llm.active_backend
                fallback = False

                # IQ für komplexe Aufgabe
                self.iq.add(1.0, "Komplexe Aufgabe gelöst")

            elapsed = time.time() - start

            # ─── Auto-Save ───
            await self._send_live(chat_id, "💾 Speichere State & Memory\\.\\.\\.", context, live_msg)
            if user.id in self._states:
                self._states[user.id].save()
            if user.id in self._sessions:
                self._sessions[user.id].session_save()
            self.bus.save("State + Memory")

            # Error-Learning konsolidieren
            toti.error_learning.consolidate()

            # ─── Typing stoppen ───
            stop_typing.set()

            # ─── Live-Meldung aufräumen ───
            await self._delete_msg(chat_id, live_msg, context)

            # ─── Schöne Antwort senden ───
            iq_val = self.iq.get_status()["iq"]
            header = f"🧠 `{model}` | ⏱ {elapsed:.1f}s | IQ {iq_val}"
            if fallback:
                header += " | ⚠️ Fallback"
            if backend not in ("ollama_cloud", "unknown"):
                header += f" | 📡 {backend}"

            await self._send_long(chat_id, f"{header}\n\n{response}", context)

        except Exception as e:
            logger.error(f"Error: {e}")
            stop_typing.set()

            self.iq.add(-1.0, f"Fehler: {str(e)[:30]}")
            self.bus.emit(ActivityEvent(
                event_type="error", source="BOT",
                message=f"❌ Fehler: {str(e)[:60]}", importance="error",
            ))

            await self._delete_msg(chat_id, live_msg, context)
            await update.message.reply_text(f"❌ *Fehler*\n\n`{str(e)[:500]}`", parse_mode="MarkdownV2")

    # ═══════════════════════════════════════════════════════
    # IMAGE HANDLER — Bilder analysieren
    # ═══════════════════════════════════════════════════════

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Foto empfangen → Vision-Analyse."""
        if not self._is_authorized(update.effective_user.id):
            return

        chat_id = update.effective_chat.id

        # Foto herunterladen
        photo = update.message.photo[-1]  # Höchste Auflösung
        try:
            file = await context.bot.get_file(photo.file_id)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                photo_path = tmp.name
        except Exception as e:
            await update.message.reply_text(f"❌ Foto-Download fehlgeschlagen: {e}")
            return

        # Analysieren
        live_msg = await self._send_live(chat_id, "👁️ Analysiere Foto\\.\\.\\.", context)
        self.bus.vision_analyze("telegram_photo")

        result = self.vision.analyze_image(photo_path)

        # Cleanup
        try:
            os.unlink(photo_path)
        except Exception:
            pass

        await self._delete_msg(chat_id, live_msg, context)

        if result.get("error"):
            self.iq.add(-0.5, "Vision Fehler")
            await update.message.reply_text(f"❌ Vision Fehler: `{result['error']}`", parse_mode="MarkdownV2")
        else:
            self.iq.add(0.5, "Foto analysiert")
            text = TelegramFormatter.format_vision_result(result)
            await self._send_long(chat_id, text, context)

    # ═══════════════════════════════════════════════════════
    # RUN
    # ═══════════════════════════════════════════════════════

    def run(self):
        if not TELEGRAM_AVAILABLE:
            print("ERROR: pip install python-telegram-bot")
            return

        app = Application.builder().token(self.token).build()

        # Commands
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(CommandHandler("models", self.models_command))
        app.add_handler(CommandHandler("iq", self.iq_command))
        app.add_handler(CommandHandler("memory", self.memory_command))
        app.add_handler(CommandHandler("errors", self.errors_command))
        app.add_handler(CommandHandler("health", self.health_command))
        app.add_handler(CommandHandler("skills", self.skills_command))
        app.add_handler(CommandHandler("tools", self.tools_command))
        app.add_handler(CommandHandler("reset", self.reset_command))
        app.add_handler(CommandHandler("evolve", self.evolve_command))
        app.add_handler(CommandHandler("search", self.search_command))
        app.add_handler(CommandHandler("browse", self.browse_command))
        app.add_handler(CommandHandler("vision", self.vision_command))
        app.add_handler(CommandHandler("activity", self.activity_command))

        # Messages
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        # Photos
        app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        print("🧠 Toti Telegram Bot v4.0 starting...")
        print(f"   IQ: {self.iq.get_status()['iq']} | Level: {self.iq.get_status()['level']}")
        print(f"   Web: DDGS={self.web.get_stats()['ddgs_available']} | BS4={self.web.get_stats()['bs4_available']}")
        print(f"   Vision: PIL={self.vision.get_stats()['pil_available']} | OCR={self.vision.get_stats()['tesseract_available']}")
        print(f"   Fallback: {self.llm._emergency_model}")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
