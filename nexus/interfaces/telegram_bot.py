"""
NEXUS v9.2 — Telegram Bot Interface (python-telegram-bot)
Pair architecture: Router/Worker for efficient responses.
Personalization: learns about users through natural conversation.
DSGVO-compliant: per-user consent, data minimization, right to deletion.

v9.2: Live status display (frameless), per-agent displays, /background /show commands.
v9.1: /einstellungen command — view and change all settings from Telegram
v8.2.1: Live terminal block — asyncio.Queue + consumer task for real-time
        step updates. Sync callback puts events on queue, async consumer
        edits the Telegram message in real-time.
"""

import os
import re
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from nexus.core.agent import NexusAgent
from nexus.core.session_manager import SessionManager
from nexus.core.rate_limiter import RateLimiter
from nexus.core.feedback import FeedbackEmitter, FeedbackType, FeedbackEvent
from nexus.core.personalization import PersonalizationEngine
from nexus.core.dsgvo import DSGVOCompliance
from nexus.interfaces.markdown_utils import escape_markdown_v2, format_markdown_v2, split_markdown_v2

log = logging.getLogger("nexus.telegram")

# ─── Live Status Display ──────────────────────────────────

STEP_ICONS = {
    FeedbackType.THINKING: "💭",
    FeedbackType.LLM_CALL: "⚡",
    FeedbackType.TOOL_START: "🔧",
    FeedbackType.TOOL_RESULT: "✅",
    FeedbackType.PROGRESS: "📡",
    FeedbackType.DONE: "✨",
    FeedbackType.AGENT_START: "🤖",
    FeedbackType.AGENT_PROGRESS: "⏳",
    FeedbackType.AGENT_DONE: "✅",
}

DEPT_ICONS = {
    "ceo": "👔",
    "research": "🔍",
    "engineering": "💻",
    "creative": "🎨",
    "operations": "📋",
}

DEPT_NAMES = {
    "ceo": "CEO",
    "research": "Research",
    "engineering": "Engineering",
    "creative": "Creative",
    "operations": "Operations",
}


@dataclass
class AgentDisplayState:
    """Tracks per-agent Telegram message state for live displays."""
    department: str
    display_name: str
    model_name: str
    icon: str
    message_id: int = 0
    steps: list = field(default_factory=list)
    status: str = "running"  # running | completed | failed
    start_time: float = 0.0

# ─── Terminal-style step formatting ─────────────────────────

STEP_ICONS = {
    FeedbackType.THINKING: "💭",
    FeedbackType.LLM_CALL: "⚡",
    FeedbackType.TOOL_START: "🔧",
    FeedbackType.TOOL_RESULT: "✅",
    FeedbackType.PROGRESS: "📡",
    FeedbackType.DONE: "🎯",
}


class NexusTelegramBot:
    """
    Telegram bot using python-telegram-bot.

    v9.2: Live status display (frameless), per-agent displays, /background /show.
    v8.2.1: Live step feedback via asyncio.Queue + consumer task.
    """

    def __init__(self, agent: NexusAgent, config: dict = None):
        self.agent = agent
        self.config = config or {}
        self.token = os.environ.get(
            self.config.get("token_env", "TELEGRAM_BOT_TOKEN"), ""
        )
        self.authorized_users = self._parse_authorized_users()
        self.session_manager = SessionManager(
            self.config.get("session_manager", {})
        )
        self.rate_limiter = RateLimiter(
            rate=self.config.get("rate_limiter", {}).get("rate", 0.33),
            burst=self.config.get("rate_limiter", {}).get("burst", 5),
        )
        self._processing = {}  # user_id -> bool
        self._interrupt_queue = {}  # user_id -> list[pending messages]
        self._feedback_emitters = {}  # user_id -> FeedbackEmitter
        self._status_msg_ids = {}  # user_id -> message_id for live status
        self._agent_displays = {}  # user_id -> {department: AgentDisplayState}
        self._background_mode = {}  # user_id -> bool (True = hide agent details)
        self._last_edit_time = {}  # chat_id -> float (rate limit throttle)
        self._app = None  # Reference to the Application for bot API access
        self.dsgvo = DSGVOCompliance(
            data_dir=self.config.get("dsgvo", {}).get("data_dir", "data/dsgvo")
        )

    def _parse_authorized_users(self):
        env_var = self.config.get("authorized_users_env", "NEXUS_TG_USERS")
        raw = os.environ.get(env_var, "")
        if not raw:
            return set()
        users = set()
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                users.add(int(part))
        return users

    async def start(self):
        if not self.token:
            log.error("No Telegram token found. Set TELEGRAM_BOT_TOKEN env var.")
            return

        # Flush stale polling connections
        import requests as sync_requests
        base = "https://api.telegram.org/bot" + self.token
        try:
            sync_requests.post(base + "/setWebhook", json={"url": "https://example.com/fake"}, timeout=5)
            sync_requests.get(base + "/deleteWebhook?drop_pending_updates=true", timeout=5)
            import time; time.sleep(5)
            log.info("Flushed stale polling connections")
        except Exception as e:
            log.warning(f"Webhook flush failed (non-critical): {e}")

        app = ApplicationBuilder().token(self.token).build()
        app.updater._read_timeout = 30
        self._app = app

        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("delete", self._cmd_delete))
        app.add_handler(CommandHandler("data", self._cmd_data))
        app.add_handler(CommandHandler("consent", self._cmd_consent))
        app.add_handler(CommandHandler("team", self._cmd_team))
        app.add_handler(CommandHandler("agent", self._cmd_agent))
        app.add_handler(CommandHandler("background", self._cmd_background))
        app.add_handler(CommandHandler("show", self._cmd_show))
        app.add_handler(CommandHandler("einstellungen", self._cmd_settings))
        app.add_handler(CommandHandler("settings", self._cmd_settings))
        app.add_handler(CommandHandler("version", self._cmd_version))
        app.add_handler(CommandHandler("update", self._cmd_update))
        app.add_handler(CallbackQueryHandler(self._handle_update_callback, pattern=r"^update_"))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_message
        ))

        log.info(f"NEXUS Telegram bot starting (authorized: {self.authorized_users or 'all'})")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("NEXUS Telegram bot running")

        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            log.info("Shutting down...")
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    # ─── Commands ──────────────────────────────────────

    async def _cmd_start(self, update, ctx):
        user = update.effective_user
        uid = str(user.id)
        if self.authorized_users and user.id not in self.authorized_users:
            await update.message.reply_text("Nicht autorisiert.")
            return

        # DSGVO: Consent gate
        if self.dsgvo.needs_consent(uid):
            notice = self.dsgvo.get_privacy_notice()
            try:
                await update.message.reply_text(notice, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(notice)
            # Auto-give consent on /start (user explicitly started the bot)
            self.dsgvo.give_consent(uid)
            try:
                await update.message.reply_text(
                    "✅ Einwilligung erteilt\\. Schreib mir einfach\\!",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception:
                await update.message.reply_text("✅ Einwilligung erteilt. Schreib mir einfach!")
            return

        greeting = self.agent.personalization.generate_greeting(uid)
        await update.message.reply_text(greeting)

    async def _cmd_help(self, update, ctx):
        help_text = (
            "⚡ *Nexus* — KI\\-Agent mit Team\\-Architektur\n\n"
            "Schreib einfach, ich antworte mit Echtzeit\\-Feedback\\.\n\n"
            "🔧 `/status` — Infos ueber mich\n"
            "👥 `/team` — Team\\-Uebersicht\n"
            "🤖 `/agent` — Agenten\\-Management\\(create/assign/stats/evolve\\)\n"
            "👁 `/background` — Agenten\\-Details ausblenden\n"
            "📊 `/show` — Agenten\\-Details wieder einblenden\n"
            "📋 `/data` — Deine Daten einsehen \\(DSGVO Art\\. 15\\)\n"
            "🗑 `/delete` — Deine Daten löschen \\(DSGVO Art\\. 17\\)\n"
            "🔒 `/consent` — Einwilligung verwalten"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_status(self, update, ctx):
        from nexus import __version__
        user = update.effective_user
        processing = self._processing.get(user.id, False)
        status = "⚡ arbeitet" if processing else "✅ bereit"

        status_text = (
            f"⚡ *Nexus v{__version__}* — {status}\n\n"
            f"🏗 Architektur: Router \\+ Worker \\+ Team\n"
            f"📡 Sessions: {self.session_manager.stats()['active_sessions']} aktiv\n"
            f"🔒 DSGVO: konform"
        )

        if self.agent._iteration_budget:
            budget = self.agent._iteration_budget
            status_text += f"\n📊 Budget: {budget.calls_remaining} calls uebrig"

        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_data(self, update, ctx):
        """DSGVO Art. 15 — Right of access: show all stored user data."""
        user = update.effective_user
        uid = str(user.id)
        inventory = self.dsgvo.get_user_data_inventory(uid, self.session_manager)
        text = self.dsgvo.format_data_inventory(inventory)
        # Escape for MarkdownV2
        text = format_markdown_v2(text)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_delete(self, update, ctx):
        """DSGVO Art. 17 — Right to erasure: delete all user data."""
        user = update.effective_user
        uid = str(user.id)
        result = self.dsgvo.delete_all_user_data(uid, self.session_manager)
        cats = ", ".join(result.get("categories_deleted", []))
        count = result.get("total_entries_removed", 0)
        text = (
            f"🗑 Alle deine Daten wurden geloescht\\.\n\n"
            f"Geloeschte Kategorien: {escape_markdown_v2(cats)}\n"
            f"Eintraege entfernt: {count}\n\n"
            f"DSGVO\\-konform \\(Art\\. 17\\)\\."
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_consent(self, update, ctx):
        """DSGVO Art. 7 — Manage consent."""
        user = update.effective_user
        uid = str(user.id)
        info = self.dsgvo.get_consent_info(uid)

        if info.get("has_consent"):
            text = (
                f"✅ Einwilligung erteilt\n\n"
                f"Version: {escape_markdown_v2(str(info.get('version', '?')))}\n"
                f"Seit: {escape_markdown_v2(str(info.get('timestamp', '?'))[:10])}\n\n"
                f"/delete widerruft die Einwilligung automatisch\\."
            )
        else:
            text = (
                "❌ Keine Einwilligung vorhanden\\.\n\n"
                "/start — Einwilligung erteilen"
            )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_team(self, update, ctx):
        team_status = self.agent.team.get_team_status()
        lines = team_status.split("\n")
        formatted = []
        for line in lines:
            line = escape_markdown_v2(line)
            formatted.append(line)
        await update.message.reply_text("\n".join(formatted), parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_agent(self, update, ctx):
        """Agent management command.

        /agent — List available agents with stats
        /agent create <name> <role> — Create a new agent
        /agent assign <name> <skill> — Assign a skill to an agent
        /agent stats <name> — Show agent performance stats
        /agent evolve <name> — Trigger LLM-based evolution for an agent
        """
        from nexus.core.agent_profiles import (
            list_profiles, create_profile, assign_skill,
            get_stats, evolve_profile, load_profile,
        )
        from nexus.core.skill_autocreator import list_auto_skills

        user = update.effective_user
        uid = str(user.id)
        if self.authorized_users and user.id not in self.authorized_users:
            await update.message.reply_text("Nicht autorisiert.")
            return

        parts = (update.message.text or "").strip().split()
        subcommand = parts[1].lower() if len(parts) > 1 else ""

        # ─── /agent (no subcommand) — list agents ───
        if not subcommand:
            profiles = list_profiles()
            if not profiles:
                await update.message.reply_text("Keine Agenten-Profile gefunden.")
                return

            lines = ["🤖 *Nexus Agenten\\-Team*\n"]
            for p in profiles:
                name = escape_markdown_v2(p.get("name", "?"))
                role = escape_markdown_v2(p.get("role", "")[:50])
                model = escape_markdown_v2(p.get("model", "?"))
                tasks = p.get("tasks_completed", 0)
                rate = p.get("success_rate", 0)
                rate_str = f"{rate:.0%}" if rate > 0 else "neu"
                skills = p.get("skills_count", 0)
                lines.append(
                    f"👤 *{name}* — {role}\n"
                    f"   Modell: {model} | Tasks: {tasks} | Rate: {rate_str} | Skills: {skills}"
                )

            lines.append("\n📝 *Befehle:*")
            lines.append("/agent create \\<name\\> \\<rolle\\>")
            lines.append("/agent assign \\<name\\> \\<skill\\>")
            lines.append("/agent stats \\<name\\>")
            lines.append("/agent evolve \\<name\\>")

            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
            return

        # ─── /agent create <name> <role> ───
        if subcommand == "create":
            if len(parts) < 4:
                await update.message.reply_text(
                    "Verwendung: `/agent create <name> <rolle>`\n"
                    "Beispiel: `/agent create code-reviewer Code Reviews und Qualitätssicherung`"
                )
                return

            name = parts[2].lower().strip()
            role = " ".join(parts[3:])

            # Check if profile already exists
            existing = load_profile(name)
            if existing:
                await update.message.reply_text(
                    f"Agent *{escape_markdown_v2(name)}* existiert bereits\\!"
                )
                return

            profile = create_profile(name=name, role=role)
            await update.message.reply_text(
                f"✅ Agent *{escape_markdown_v2(profile.name)}* erstellt\\!\n"
                f"Rolle: {escape_markdown_v2(profile.role)}\n"
                f"Modell: {escape_markdown_v2(profile.model)}\n\n"
                f"Weiter: `/agent assign {escape_markdown_v2(name)} <skill>`"
            )
            return

        # ─── /agent assign <name> <skill> ───
        if subcommand == "assign":
            if len(parts) < 4:
                # Show available skills
                skills = list_auto_skills()
                if skills:
                    skill_names = [s.get("name", "?") for s in skills[:20]]
                    await update.message.reply_text(
                        "Verwendung: `/agent assign <name> <skill>`\n\n"
                        f"Verfügbare Skills: {', '.join(skill_names[:20])}"
                    )
                else:
                    await update.message.reply_text(
                        "Verwendung: `/agent assign <name> <skill>`"
                    )
                return

            agent_name = parts[2].lower().strip()
            skill = parts[3].lower().strip()

            success = assign_skill(agent_name, skill)
            if success:
                await update.message.reply_text(
                    f"✅ Skill *{escape_markdown_v2(skill)}* → Agent *{escape_markdown_v2(agent_name)}* zugewiesen"
                )
            else:
                await update.message.reply_text(
                    f"❌ Agent *{escape_markdown_v2(agent_name)}* nicht gefunden"
                )
            return

        # ─── /agent stats <name> ───
        if subcommand == "stats":
            if len(parts) < 3:
                await update.message.reply_text("Verwendung: `/agent stats <name>`")
                return

            agent_name = parts[2].lower().strip()
            stats = get_stats(agent_name)

            if not stats:
                await update.message.reply_text(
                    f"❌ Agent *{escape_markdown_v2(agent_name)}* nicht gefunden\n"
                    f"Verfügbar: {', '.join(p.get('name', '?') for p in list_profiles())}"
                )
                return

            perf = stats.get("performance", {})
            lines = [
                f"📊 *Agent: {escape_markdown_v2(stats['name'])}*\n",
                f"Rolle: {escape_markdown_v2(stats.get('role', ''))}",
                f"Modell: {escape_markdown_v2(stats.get('model', ''))}",
                f"Skills: {', '.join(stats.get('skills', [])[:10]) or 'keine'}",
                f"Tasks: {perf.get('tasks_completed', 0)} ✅ / {perf.get('tasks_failed', 0)} ❌",
                f"Erfolgsrate: {perf.get('success_rate', 0):.0%}",
                f"Ø Zeit: {perf.get('avg_time_s', 0):.1f}s",
                f"Evolutionen: {stats.get('evolution_count', 0)}",
            ]

            last_evo = stats.get("last_evolution")
            if last_evo:
                lines.append(f"Letzte Evolution: {escape_markdown_v2(last_evo.get('insight', '')[:80])}")

            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
            return

        # ─── /agent evolve <name> ───
        if subcommand == "evolve":
            if len(parts) < 3:
                await update.message.reply_text("Verwendung: `/agent evolve <name>`")
                return

            agent_name = parts[2].lower().strip()
            await update.message.reply_text(f"🔄 Starte Evolution für *{escape_markdown_v2(agent_name)}*\\.")

            # Run evolution (may use LLM)
            result = evolve_profile(agent_name, llm_client=self.agent.llm)

            if result:
                lines = [
                    f"✅ Evolution abgeschlossen für *{escape_markdown_v2(result.name)}*\n",
                    f"Rolle: {escape_markdown_v2(result.role)}",
                    f"Evolutionen: {len(result.evolution)}",
                ]
                if result.evolution:
                    latest = result.evolution[-1]
                    lines.append(f"Letzter Insight: {escape_markdown_v2(latest.get('insight', '')[:100])}")

                await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await update.message.reply_text(
                    f"❌ Agent *{escape_markdown_v2(agent_name)}* nicht gefunden"
                )
            return

        # Unknown subcommand
        await update.message.reply_text(
            "Unbekannter Befehl\\. Verfügbare Optionen:\n"
            "/agent — Agenten auflisten\n"
            "/agent create \\<name\\> \\<rolle\\>\n"
            "/agent assign \\<name\\> \\<skill\\>\n"
            "/agent stats \\<name\\>\n"
            "/agent evolve \\<name\\>",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    # ─── /background and /show ────────────────────────────

    async def _cmd_background(self, update, ctx):
        """Hide agent detail displays during processing."""
        user = update.effective_user
        self._background_mode[user.id] = True

        # Delete any existing agent display messages for this user
        displays = self._agent_displays.get(user.id, {})
        chat_id = update.effective_chat.id
        for dept, state in displays.items():
            if state.message_id:
                try:
                    await ctx.bot.delete_message(chat_id=chat_id, message_id=state.message_id)
                except Exception:
                    pass

        await update.message.reply_text(
            "👁 *Hintergrundmodus* aktiviert\\.\n\n"
            "Agenten\\-Details werden nicht mehr angezeigt\\.\n"
            "/show zum Wiederherstellen\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    async def _cmd_show(self, update, ctx):
        """Show agent detail displays during processing."""
        user = update.effective_user
        self._background_mode[user.id] = False

        await update.message.reply_text(
            "📊 *Agenten\\-Details* wieder sichtbar\\.\n\n"
            "Beim naechsten Auftrag werden Agenten\\-Displays eingeblendet\\.\n"
            "/background zum Ausblenden\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    async def _cmd_settings(self, update, ctx):
        """Show all configurable settings and allow changes via subcommands.

        /einstellungen — Show all settings
        /einstellungen model <name> — Change default model
        /einstellungen sprache <de|en> — Change language
        /einstellungen tone <0-1> — Change formality (0=casual, 1=formal)
        /einstellungen humor <0-1> — Change humor level
        /einstellungen verbose <0-1> — Change verbosity
        /einstellungen reset — Reset to defaults
        """
        from nexus import __version__
        user = update.effective_user
        uid = str(user.id)
        parts = (update.message.text or "").strip().split()

        # No subcommand — show all settings
        if len(parts) <= 1:
            soul = self.agent.soul
            user_ctx = soul.get_user_context(uid) or {}
            rel = soul.relationships.get(uid, {})

            model_name = self.config.get("llm", {}).get("default_model", "glm-5.1:cloud")
            language = soul.personality.get("language_default", "de")
            formality = soul.personality.get("formality_level", 0.3)
            humor = soul.personality.get("humor_style", "trocken-witzig")
            verbose = soul.personality.get("verbosity", 0.3)
            tech_depth = soul.personality.get("technical_depth", 0.8)

            text = (
                f"⚙ *Einstellungen* — Nexus v{escape_markdown_v2(__version__)}\n\n"
                f"📡 *Modell:* {escape_markdown_v2(model_name)}\n"
                f"🌍 *Sprache:* {escape_markdown_v2(language)}\n"
                f"👔 *Formalitaet:* {formality} \\(0\\=locker, 1\\=formell\\)\n"
                f"😄 *Humor:* {escape_markdown_v2(str(humor))}\n"
                f"📊 *Ausfuehrlichkeit:* {verbose} \\(0\\=kurz, 1\\=lang\\)\n"
                f"🔬 *Technische Tiefe:* {tech_depth} \\(0\\=einfach, 1\\=experte\\)\n\n"
                f"📝 *Aenderungen:*\n"
                f"/einstellungen model \\<name\\>\n"
                f"/einstellungen sprache de|en\n"
                f"/einstellungen tone 0\\.0 \\- 1\\.0\n"
                f"/einstellungen humor 0\\.0 \\- 1\\.0\n"
                f"/einstellungen verbose 0\\.0 \\- 1\\.0\n"
                f"/einstellungen reset\n\n"
                f"💡 *Beispiel:* /einstellungen tone 0\\.5"
            )
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(text.replace("\\", "").replace("*", "").replace("`", ""))
            return

        # Parse subcommand
        subcmd = parts[1].lower() if len(parts) > 1 else ""

        if subcmd == "model":
            if len(parts) < 3:
                await update.message.reply_text("📊 Verfuegbare Modelle:\n\n• glm-5.1:cloud\n• deepseek-v4-flash:cloud\n• kimi-k2.6:cloud\n• qwen3-coder-next:cloud\n\n/einstellungen model <name>")
                return
            new_model = parts[2]
            self.config.setdefault("llm", {})["default_model"] = new_model
            self.agent.llm.config["default_model"] = new_model
            text = f"✅ Modell geaendert: {escape_markdown_v2(new_model)}"
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(f"Modell geaendert: {new_model}")
            return

        elif subcmd in ("sprache", "language", "lang"):
            if len(parts) < 3 or parts[2].lower() not in ("de", "en", "es", "fr"):
                await update.message.reply_text("🌍 Verfuegbare Sprachen: de, en, es, fr\n\n/einstellungen sprache de")
                return
            new_lang = parts[2].lower()
            self.agent.soul.personality["language_default"] = new_lang
            self.agent.soul.save()
            text = f"✅ Sprache geaendert: {escape_markdown_v2(new_lang)}"
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(f"Sprache geaendert: {new_lang}")
            return

        elif subcmd in ("tone", "formality", "formalitaet"):
            if len(parts) < 3:
                await update.message.reply_text("👔 Formalitaet: 0.0 (locker) bis 1.0 (formell)\n\n/einstellungen tone 0.5")
                return
            try:
                val = float(parts[2])
                val = max(0.0, min(1.0, val))
            except ValueError:
                await update.message.reply_text("❌ Wert muss eine Zahl zwischen 0 und 1 sein.")
                return
            self.agent.soul.personality["formality_level"] = val
            self.agent.soul.save()
            text = f"✅ Formalitaet geaendert: {val}"
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(f"Formalitaet geaendert: {val}")
            return

        elif subcmd in ("humor",):
            if len(parts) < 3:
                await update.message.reply_text(
                    "😄 Humor-Stile:\n\n"
                    "• trocken-witzig\n• locker-witzig\n• trocken-sachlich\n• ironisch\n"
                    "Oder numerisch: 0.0 (kein Humor) bis 1.0 (viel Humor)\n\n"
                    "/einstellungen humor trocken-witzig"
                )
                return
            val_str = parts[2].lower()
            humor_styles = ["trocken-witzig", "locker-witzig", "trocken-sachlich", "ironisch"]
            if val_str in humor_styles:
                self.agent.soul.personality["humor_style"] = val_str
                self.agent.soul.save()
                text = f"✅ Humor-Stil geaendert: {escape_markdown_v2(val_str)}"
            else:
                try:
                    num = float(val_str)
                    num = max(0.0, min(1.0, num))
                    self.agent.soul.personality["humor_level"] = num
                    self.agent.soul.save()
                    text = f"✅ Humor-Level geaendert: {num}"
                except ValueError:
                    await update.message.reply_text("❌ Unbekannter Humor-Stil.")
                    return
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(text.replace("\\", "").replace("*", ""))
            return

        elif subcmd in ("verbose", "ausfuehrlichkeit"):
            if len(parts) < 3:
                await update.message.reply_text("📊 Ausfuehrlichkeit: 0.0 (kurz) bis 1.0 (lang)\n\n/einstellungen verbose 0.3")
                return
            try:
                val = float(parts[2])
                val = max(0.0, min(1.0, val))
            except ValueError:
                await update.message.reply_text("❌ Wert muss eine Zahl zwischen 0 und 1 sein.")
                return
            self.agent.soul.personality["verbosity"] = val
            self.agent.soul.save()
            text = f"✅ Ausfuehrlichkeit geaendert: {val}"
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(f"Ausfuehrlichkeit geaendert: {val}")
            return

        elif subcmd == "reset":
            # Reset personality to defaults from soul.yaml
            self.agent.soul.personality = {
                "language_default": "de",
                "formality_level": 0.3,
                "humor_style": "trocken-witzig",
                "technical_depth": 0.8,
                "verbosity": 0.3,
            }
            self.agent.soul.save()
            text = "✅ Einstellungen zurueckgesetzt auf Defaults."
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(text)
            return

        else:
            await update.message.reply_text(
                f"❓ Unbekannter Befehl: /einstellungen {subcmd}\n\n"
                f"Verfuegbar: model, sprache, tone, humor, verbose, reset"
            )

    # ─── Update & Version Commands ─────────────────────

    async def _cmd_version(self, update, ctx):
        """Show current Nexus version and check for updates."""
        from nexus import __version__

        user = update.effective_user
        uid = str(user.id)
        text = (
            f"📦 *Nexus v{__version__}*\n\n"
            f"Installierte Version: v{__version__}\n\n"
            f"Mit /update pruefst du auf neue Versionen\\."
        )
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception:
            await update.message.reply_text(f"Nexus v{__version__}")

    async def _cmd_update(self, update, ctx):
        """Check for updates and show changelog with inline keyboard."""
        from nexus import __version__
        from nexus.core.updater import VersionChecker

        user = update.effective_user

        # /update now — trigger immediate update
        parts = (update.message.text or "").strip().split()
        if len(parts) > 1 and parts[1].lower() == "now":
            await self._perform_update(update, ctx, user.id)
            return

        # Check GitHub for latest release
        await update.message.reply_text("🔍 Pruefe auf Updates...", parse_mode=None)

        checker = VersionChecker()
        version_info = checker.check_github_release()

        if not version_info.has_update:
            text = f"✅ Nexus ist auf dem neuesten Stand \\(v{__version__}\\)"
            try:
                await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await update.message.reply_text(f"✅ Nexus ist auf dem neuesten Stand (v{__version__})")
            return

        # New version available — show changelog with inline keyboard
        text = version_info.format_update_message()

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ja, updaten!", callback_data="update_yes"),
                InlineKeyboardButton("❌ Spaeter", callback_data="update_no"),
            ]
        ])

        try:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=keyboard,
            )
        except Exception as e:
            # Fallback without Markdown if formatting fails
            log.warning(f"Update message formatting failed: {e}")
            plain_text = (
                f"🆕 Nexus v{version_info.latest} verfügbar!\n\n"
                f"Aktuelle Version: v{version_info.current}\n"
                f"Neueste Version: v{version_info.latest}\n\n"
                f"/update now — Update durchführen"
            )
            await update.message.reply_text(plain_text)

    async def _handle_update_callback(self, update, ctx):
        """Handle inline keyboard callback for update confirmation."""
        query = update.callback_query
        await query.answer()

        user = query.from_user
        data = query.data

        if data == "update_yes":
            await query.edit_message_text("⏳ Update wird durchgefuehrt\\.\\.\\.", parse_mode=ParseMode.MARKDOWN_V2)
            await self._perform_update(query, ctx, user.id)
        elif data == "update_no":
            await query.edit_message_text("Okay, kein Update\\. Vielleicht spaeter\\!", parse_mode=ParseMode.MARKDOWN_V2)

    async def _perform_update(self, update_or_query, ctx, user_id: int):
        """Execute the auto-update: git pull + docker rebuild + restart."""
        from nexus.core.updater import AutoUpdater
        from nexus import __version__

        chat_id = None
        bot = ctx.bot

        # Get chat_id from update or callback query
        if hasattr(update_or_query, 'effective_chat'):
            chat_id = update_or_query.effective_chat.id
        elif hasattr(update_or_query, 'message') and update_or_query.message:
            chat_id = update_or_query.message.chat.id
        else:
            # Fallback: use authorized user
            if self.authorized_users:
                chat_id = list(self.authorized_users)[0]

        if not chat_id:
            log.error("Cannot determine chat_id for update notification")
            return

        # Notify: starting update
        try:
            await bot.send_message(
                chat_id=chat_id,
                text="⏳ *Update gestartet*\\.\\.\\.\n\n1️⃣ Git Pull\\.\\.\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        except Exception:
            pass

        # Run update in background thread
        updater = AutoUpdater()

        def run_update():
            import asyncio
            success, message = updater.update()

            # Schedule notification on the event loop
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = None

            async def notify():
                if success:
                    text = (
                        f"✅ *Update erfolgreich\\!*\n\n"
                        f"Nexus wurde auf die neueste Version aktualisiert\\.\n"
                        f"Der Container wird neu gestartet\\.\\.\\.\n\n"
                        f"💡 Nach dem Neustart: /version zeigt die neue Version\\."
                    )
                else:
                    text = f"❌ *Update fehlgeschlagen*\n\n{escape_markdown_v2(message)}"

                try:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
                except Exception:
                    await bot.send_message(chat_id=chat_id, text=text.replace("\\", ""))

            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(notify(), loop)
            # If loop not available, the notification will be lost — acceptable for edge cases

        import threading
        update_thread = threading.Thread(target=run_update, daemon=True, name="nexus-update")
        update_thread.start()

    # ─── Message Handler ───────────────────────────────

    async def _handle_message(self, update, ctx):
        user = update.effective_user
        chat_id = update.effective_chat.id
        text = update.message.text

        if not text or text.startswith("/"):
            return

        # Auth check
        if self.authorized_users and user.id not in self.authorized_users:
            await update.message.reply_text("Nicht autorisiert.")
            return

        # DSGVO: Consent gate — no processing without consent
        uid = str(user.id)
        if self.dsgvo.needs_consent(uid):
            await update.message.reply_text(
                "🔒 Bitte zuerst /start ausfuehren um die Datenschutzrichtlinie zu akzeptieren\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        # Track interaction for retention
        self.dsgvo.touch_interaction(uid)

        # Rate limiting
        if not self.rate_limiter.allow(user.id):
            await update.message.reply_text("⏳ Etwas zu schnell. Kurz warten...")
            return

        # ─── Interrupt handling ──────────────────────
        if self._processing.get(user.id, False):
            if user.id not in self._interrupt_queue:
                self._interrupt_queue[user.id] = []
            self._interrupt_queue[user.id].append(text)
            await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await update.message.reply_text("⏸ Unterbrochen. Kurze Antwort, dann setze ich fort.")
            return

        # ─── Normal processing ───────────────────────
        self._processing[user.id] = True
        self._status_msg_ids.pop(user.id, None)
        self._agent_displays.pop(user.id, None)

        # React to user message
        try:
            await update.message.set_reaction("👀")
        except Exception:
            pass

        # Live feedback: asyncio.Queue for cross-thread communication
        feedback_queue = asyncio.Queue()
        step_log = []

        # Quick callback — updates live status message from agent thread
        loop = asyncio.get_event_loop()

        def quick_callback(ack_text):
            """Called from agent thread to update the live status message."""
            msg_id = self._status_msg_ids.get(user.id)
            if msg_id:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        ctx.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=msg_id,
                            text=ack_text[:100]
                        ),
                        loop
                    )
                    future.result(timeout=3)
                except Exception:
                    pass

        # Sync callback — called from the agent thread
        def on_step(event):
            step_log.append(event)
            try:
                feedback_queue.put_nowait(event)
            except Exception:
                pass

        emitter = FeedbackEmitter(callback=on_step)
        self._feedback_emitters[user.id] = emitter

        # Start the live status consumer task
        consumer_task = asyncio.create_task(
            self._status_consumer(chat_id, ctx, user.id, feedback_queue, step_log)
        )

        try:
            typing_task = asyncio.create_task(
                self._typing_loop(chat_id, ctx)
            )

            # Process with Pair architecture + personalization (runs in thread)
            response = await asyncio.to_thread(
                self.agent.process, text, str(user.id),
                feedback=emitter, platform="telegram",
                quick_callback=quick_callback
            )

            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

            # Signal consumer to finish
            await feedback_queue.put(None)  # Sentinel
            await consumer_task

            # Finalize live status (mark as DONE)
            if step_log:
                await self._finalize_live_status(chat_id, ctx, user.id, step_log)

            # Change reaction from 👀 to ✅
            try:
                await update.message.set_reaction("✅")
            except Exception:
                pass

            # Clean up agent display messages
            await self._cleanup_agent_messages(chat_id, ctx, user.id)

            # Send the actual response
            await self._send_response(chat_id, ctx, response)

            # Check for queued interrupts
            pending = self._interrupt_queue.pop(user.id, [])
            if pending:
                queued_text = "\n".join(
                    "  " + m[:80] for m in pending[:5]
                )
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=f"📥 Eingereihte Nachrichten:\n{queued_text}\n\n_Spricht dein Anliegen? Sonst einfach neu schreiben._"
                )

        except Exception as e:
            log.error(f"Error processing message: {e}", exc_info=True)
            try:
                await update.message.set_reaction("❌")
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Fehler: {str(e)[:200]}"
            )
        finally:
            self._processing[user.id] = False
            self._feedback_emitters.pop(user.id, None)
            self._status_msg_ids.pop(user.id, None)
            self._agent_displays.pop(user.id, None)

    # ─── Live Status Consumer ─────────────────────────────

    async def _status_consumer(self, chat_id, ctx, user_id, queue, step_log):
        """Async consumer: reads events from queue and live-edits the status message.
        Also handles AGENT_START/AGENT_DONE events for per-agent displays."""
        last_edit_time = 0
        MIN_EDIT_INTERVAL = 2.0  # Throttle edits to avoid rate limits (2s = 30/min)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)

                if event is None:
                    break

                # Handle agent events — create/update per-agent messages
                if event.type in (FeedbackType.AGENT_START, FeedbackType.AGENT_DONE,
                                  FeedbackType.AGENT_PROGRESS):
                    await self._handle_agent_event(chat_id, ctx, user_id, event)

                # Throttle edits for the main status message
                now = asyncio.get_event_loop().time()
                if now - last_edit_time < MIN_EDIT_INTERVAL:
                    continue

                await self._update_live_status(chat_id, ctx, user_id, step_log)
                last_edit_time = now

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.debug(f"Status consumer error: {e}")
                continue

    # ─── Live Status Display ─────────────────────────────

    async def _format_live_status(self, steps):
        """Format step log as frameless live status with command header."""
        if not steps:
            return ""

        header = "⚡ /background · /show\n"
        lines = []
        for step in steps[-8:]:
            icon = STEP_ICONS.get(step.type, "·")
            msg = step.message[:40]
            if step.detail:
                detail = step.detail[:30]
                lines.append(f"{icon} {msg}: {detail}")
            else:
                lines.append(f"{icon} {msg}")

        if not lines:
            return ""

        return header + "\n".join(lines)

    async def _update_live_status(self, chat_id, ctx, user_id, steps):
        """Send or edit the live status message."""
        text = await self._format_live_status(steps)
        if not text:
            return

        msg_id = self._status_msg_ids.get(user_id)

        try:
            if msg_id:
                await ctx.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                )
            else:
                msg = await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )
                self._status_msg_ids[user_id] = msg.message_id
        except Exception:
            pass

    async def _finalize_live_status(self, chat_id, ctx, user_id, steps):
        """Final update to live status showing completion."""
        steps.append(FeedbackEvent(
            type=FeedbackType.DONE,
            message="Fertig",
            detail="",
            icon="✨",
            step=steps[-1].step + 1 if steps else 0,
        ))
        text = await self._format_live_status(steps)

        msg_id = self._status_msg_ids.get(user_id)
        try:
            if msg_id:
                await ctx.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                )
            else:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                )
        except Exception:
            pass

    # ─── Per-Agent Display ─────────────────────────────────

    async def _handle_agent_event(self, chat_id, ctx, user_id, event):
        """Handle AGENT_START/AGENT_PROGRESS/AGENT_DONE events for per-agent displays."""
        if self._background_mode.get(user_id, False):
            return

        department = event.department
        if not department:
            return

        displays = self._agent_displays.setdefault(user_id, {})
        icon = DEPT_ICONS.get(department, "🤖")
        name = DEPT_NAMES.get(department, department.capitalize())

        if event.type == FeedbackType.AGENT_START:
            state = AgentDisplayState(
                department=department,
                display_name=name,
                model_name=event.detail or event.model_name or "",
                icon=icon,
                status="running",
                start_time=time.time(),
            )
            state.steps.append("Gestartet...")
            displays[department] = state

            text = self._format_agent_display(state)
            try:
                msg = await ctx.bot.send_message(chat_id=chat_id, text=text)
                state.message_id = msg.message_id
            except Exception:
                pass

        elif event.type == FeedbackType.AGENT_PROGRESS:
            state = displays.get(department)
            if not state:
                return
            progress_text = event.message[:60]
            if event.detail:
                progress_text += f": {event.detail[:40]}"
            state.steps.append(progress_text)
            state.steps = state.steps[-5:]

            text = self._format_agent_display(state)
            if state.message_id:
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=chat_id, message_id=state.message_id, text=text)
                except Exception:
                    pass

        elif event.type == FeedbackType.AGENT_DONE:
            state = displays.get(department)
            if not state:
                return
            elapsed = event.elapsed if event.elapsed > 0 else (time.time() - state.start_time)
            success = "✅" in event.icon
            state.status = "completed" if success else "failed"
            status_text = f"✅ {elapsed:.1f}s" if success else "❌ Fehlgeschlagen"
            state.steps.append(status_text)

            text = self._format_agent_display(state)
            if state.message_id:
                try:
                    await ctx.bot.edit_message_text(
                        chat_id=chat_id, message_id=state.message_id, text=text)
                except Exception:
                    pass

    def _format_agent_display(self, state: AgentDisplayState) -> str:
        """Format a single agent's display as plain text with tree lines."""
        lines = [f"{state.icon} {state.display_name} ({state.model_name})"]
        for i, step in enumerate(state.steps):
            prefix = "├" if i < len(state.steps) - 1 else "└"
            lines.append(f"{prefix} {step}")
        return "\n".join(lines)

    async def _cleanup_agent_messages(self, chat_id, ctx, user_id):
        """Clean up agent display tracking after processing."""
        self._agent_displays.pop(user_id, None)

    # ─── Helpers ────────────────────────────────────────

    async def _typing_loop(self, chat_id, ctx):
        while True:
            try:
                await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

    def _format_response(self, text):
        """Format bot response for Telegram with rich structure.

        Transforms plain LLM output into well-structured Telegram messages:
        - Headers (lines ending with ':') → bold
        - Bullet lists → proper - with bold key terms
        - Numbered lists → bold numbers
        - Code blocks preserved
        - Dividers → unicode line
        - Short links → inline
        """
        lines = text.split("\n")
        formatted = []

        for line in lines:
            stripped = line.strip()

            # Preserve code blocks as-is
            if stripped.startswith("```") or (stripped.startswith("`") and not stripped.startswith("- ")):
                formatted.append(line)
                continue

            # Dividers
            if re.match(r'^[=\-]{3,}$', stripped):
                formatted.append("─" * 25)
                continue

            # Headers: lines like "Section:" or ending with ":" (not inside a sentence)
            if stripped.endswith(":") and len(stripped) < 80 and not stripped.startswith("-") and not stripped.startswith("•"):
                # Bold the header
                formatted.append(f"**{stripped.rstrip(':')}**")
                continue

            # Numbered lists: "1. Something" → bold number
            num_match = re.match(r'^(\d+\.)\s+(.*)', stripped)
            if num_match:
                num = num_match.group(1)
                rest = num_match.group(2)
                # Bold key term if present (before "–" or "—")
                formatted.append(f"**{num}** {rest}")
                continue

            # Bullet lists: "- item" or "• item"
            bullet_match = re.match(r'^[-•]\s+(.*)', stripped)
            if bullet_match:
                item = bullet_match.group(1)
                # Bold key term if "key – value" or "key: value" or "key — value"
                # Pattern: first phrase before separator
                bold_match = re.match(r'^(.+?)\s*[–—:]\s*(.*)', item)
                if bold_match:
                    key = bold_match.group(1)
                    value = bold_match.group(2)
                    formatted.append(f"  • **{key}** — {value}")
                else:
                    # Check if first word should be bolded (technical term, model name)
                    word_match = re.match(r'^([A-Z][\w\-.]+\s*[\w\-.]*)\s+(.*)', item)
                    if word_match and len(item) > 15:
                        formatted.append(f"  • **{word_match.group(1)}** {word_match.group(2)}")
                    else:
                        formatted.append(f"  • {item}")
                continue

            formatted.append(line)

        return "\n".join(formatted)

    async def _send_response(self, chat_id, ctx, text):
        """Send formatted response using MarkdownV2 with proper escaping."""
        MAX_LEN = 4096

        # First, apply structural formatting
        formatted = self._format_response(text)

        # Then convert to MarkdownV2 with proper escaping
        try:
            md2 = format_markdown_v2(formatted)
            chunks = split_markdown_v2(md2, MAX_LEN)
            for i, chunk in enumerate(chunks):
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)
        except Exception as e:
            log.warning(f"MarkdownV2 formatting failed, falling back to plain: {e}")
            # Fallback: plain text, no formatting
            chunks = self._split_text(text, MAX_LEN)
            for chunk in chunks:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                )

    @staticmethod
    def _split_text(text, max_len):
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, max_len)
            if split_at <= 0:
                split_at = text.rfind(" ", 0, max_len)
            if split_at <= 0:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n ")
        return chunks