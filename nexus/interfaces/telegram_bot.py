"""
NEXUS v8.2 — Telegram Bot Interface (python-telegram-bot)
Pair architecture: Router/Worker for efficient responses.
Personalization: learns about users through natural conversation.
DSGVO-compliant: per-user consent, data minimization, right to deletion.

v8.2: Rich Telegram formatting — terminal-style steps, thought bubbles,
      code blocks, message reactions, progressive feedback.
"""

import os
import re
import asyncio
import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

from nexus.core.agent import NexusAgent
from nexus.core.session_manager import SessionManager
from nexus.core.rate_limiter import RateLimiter
from nexus.core.feedback import FeedbackEmitter, FeedbackType
from nexus.core.personalization import PersonalizationEngine
from nexus.interfaces.markdown_utils import escape_markdown_v2

log = logging.getLogger("nexus.telegram")

# ─── Terminal-style step formatting ─────────────────────────

STEP_ICONS = {
    FeedbackType.THINKING: "💭",
    FeedbackType.LLM_CALL: "⚡",
    FeedbackType.TOOL_START: "🔧",
    FeedbackType.TOOL_RESULT: "✅",
    FeedbackType.PROGRESS: "📡",
    FeedbackType.DONE: "🎯",
}

# Map tool names to human-readable labels + emojis
TOOL_LABELS = {
    "terminal": ("💻 Terminal", "`"),
    "file_read": ("📖 Datei", ""),
    "file_write": ("✏️ Schreiben", ""),
    "file_search": ("🔍 Suche", ""),
    "web_search": ("🌐 Recherche", ""),
    "web_fetch": "🌐 Fetch",
    "code_exec": ("⚡ Code", "`"),
    "calculator": ("🔢 Rechner", ""),
    "delegation": ("🤝 Team", ""),
    "memory": ("🧠 Memory", ""),
    "session": ("💾 Session", ""),
    "time": ("🕐 Zeit", ""),
}


class NexusTelegramBot:
    """
    Telegram bot using python-telegram-bot.

    v8.2: Rich formatting — step feedback as terminal blocks,
          thought bubbles, reactions, code formatting.
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
        self._step_msg_ids = {}  # user_id -> message_id for terminal block

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

        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("delete", self._cmd_delete))
        app.add_handler(CommandHandler("team", self._cmd_team))
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
        if self.authorized_users and user.id not in self.authorized_users:
            await update.message.reply_text("Nicht autorisiert.")
            return

        # Personalization: first-contact greeting
        greeting = self.agent.personalization.generate_greeting(str(user.id))
        await update.message.reply_text(greeting)

    async def _cmd_help(self, update, ctx):
        help_text = (
            "⚡ **Nexus** — KI-Agent mit Team-Architektur\n\n"
            "Schreib einfach, ich antworte mit Echtzeit-Feedback.\n\n"
            "🔧 `/status` — Infos ueber mich\n"
            "👥 `/team` — Team-Uebersicht\n"
            "🗑 `/delete` — Deine Daten loeschen (DSGVO)"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_status(self, update, ctx):
        user = update.effective_user
        processing = self._processing.get(user.id, False)
        status = "⚡ arbeitet" if processing else "✅ bereit"

        status_text = (
            f"⚡ **Nexus v8.2** — {status}\n\n"
            f"🏗 Architektur: Router + Worker + Team\n"
            f"📡 Sessions: {self.session_manager.stats()['active_sessions']} aktiv\n"
            f"🔒 DSGVO: konform"
        )

        if self.agent._iteration_budget:
            budget = self.agent._iteration_budget
            status_text += f"\n📊 Budget: {budget.calls_remaining} calls uebrig"

        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_delete(self, update, ctx):
        user = update.effective_user
        self.agent.memory.clear_user(user.id)
        self.session_manager.remove(user.id)
        uid = str(user.id)
        if uid in self.agent.personalization._onboardings:
            del self.agent.personalization._onboardings[uid]
        if uid in self.agent.soul.relationships:
            del self.agent.soul.relationships[uid]
            self.agent.soul.save()
        await update.message.reply_text("🗑 Alle deine Daten wurden geloescht. DSGVO-konform.")

    async def _cmd_team(self, update, ctx):
        team_status = self.agent.team.get_team_status()
        # Format with markdown
        lines = team_status.split("\n")
        formatted = []
        for line in lines:
            line = escape_markdown_v2(line)
            formatted.append(line)
        await update.message.reply_text("\n".join(formatted), parse_mode=ParseMode.MARKDOWN_V2)

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
        self._step_msg_ids.pop(user.id, None)  # reset step message

        # React to user message
        try:
            await update.message.set_reaction("👀")
        except Exception:
            pass  # reactions not supported in all chats

        # Feedback emitter — collects steps, sends as terminal block
        step_log = []  # collect all steps for progressive update

        def on_step(event):
            """Sync callback — collects steps and schedules async send."""
            step_log.append(event)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._update_terminal_block(chat_id, ctx, user.id, step_log),
                        loop
                    )
            except Exception:
                pass

        emitter = FeedbackEmitter(callback=on_step)
        self._feedback_emitters[user.id] = emitter

        try:
            typing_task = asyncio.create_task(
                self._typing_loop(chat_id, ctx)
            )

            # Process with Pair architecture + personalization
            response = await asyncio.to_thread(
                self.agent.process, text, str(user.id),
                feedback=emitter, platform="telegram"
            )

            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

            # Mark done in terminal
            if step_log:
                await self._finalize_terminal_block(chat_id, ctx, user.id, step_log)

            # Change reaction from 👀 to ✅
            try:
                await update.message.set_reaction("✅")
            except Exception:
                pass

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
            self._step_msg_ids.pop(user.id, None)

    # ─── Terminal-style Step Display ──────────────────

    async def _format_terminal_block(self, steps):
        """Format step log as a terminal-style code block."""
        if not steps:
            return ""

        lines = ["```\n┌─ Nexus Terminal ─────────────┐"]
        for step in steps[-8:]:  # show last 8 steps max
            icon = STEP_ICONS.get(step.type, "·")
            msg = step.message[:35]
            if step.detail:
                detail = step.detail[:25]
                lines.append(f"│ {icon} {msg}: {detail}")
            else:
                lines.append(f"│ {icon} {msg}")
        lines.append("└──────────────────────────────┘```")
        return "\n".join(lines)

    async def _update_terminal_block(self, chat_id, ctx, user_id, steps):
        """Send or update the terminal block message."""
        text = await self._format_terminal_block(steps)
        if not text:
            return

        msg_id = self._step_msg_ids.get(user_id)

        try:
            if msg_id:
                # Edit existing message
                await ctx.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            else:
                # Send new message
                msg = await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                self._step_msg_ids[user_id] = msg.message_id
        except Exception:
            # If edit fails (content unchanged etc), just skip
            pass

    async def _finalize_terminal_block(self, chat_id, ctx, user_id, steps):
        """Final update to terminal block showing completion."""
        # Add a "done" marker
        from nexus.core.feedback import FeedbackEvent as FE
        steps.append(FE(
            type=FeedbackType.DONE,
            message="Fertig",
            detail="",
            icon="🎯",
            step=steps[-1].step + 1 if steps else 0,
        ))
        text = await self._format_terminal_block(steps)

        msg_id = self._step_msg_ids.get(user_id)
        try:
            if msg_id:
                await ctx.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            else:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
        except Exception:
            pass

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
        """Format bot response with rich Telegram formatting.

        Rules:
        - Code/commands: monospace code blocks
        - Step markers (numbered lists): bold
        - Key terms: bold
        - Thoughts/descriptions: italic
        - Lines starting with special chars get styled
        """
        lines = text.split("\n")
        formatted = []

        for line in lines:
            stripped = line.strip()

            # Code block or inline code — leave as-is
            if stripped.startswith("```") or stripped.startswith("`"):
                formatted.append(line)
                continue

            # Numbered steps like "1. " -> bold the number
            if re.match(r'^(\d+\.)\s', stripped):
                formatted.append(re.sub(r'^(\d+\.)\s', r'*\1* ', stripped))
                continue

            # Bullet points with bold headers like "- **Key**: value"
            if stripped.startswith("- **"):
                formatted.append(line)
                continue

            # Section headers (line of === or ---)
            if re.match(r'^[=\-]{3,}$', stripped):
                formatted.append(f"{'─' * 20}")
                continue

            formatted.append(line)

        return "\n".join(formatted)

    async def _send_response(self, chat_id, ctx, text):
        """Send formatted response, splitting into chunks if needed."""
        MAX_LEN = 4096

        # Try MarkdownV2 formatting first
        formatted = self._format_response(text)

        try:
            escaped = escape_markdown_v2(formatted)
            chunks = self._split_text(escaped, MAX_LEN)
            for i, chunk in enumerate(chunks):
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                if i < len(chunks) - 1:
                    await asyncio.sleep(0.5)  # delay between chunks
        except Exception:
            # Fallback: plain text
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