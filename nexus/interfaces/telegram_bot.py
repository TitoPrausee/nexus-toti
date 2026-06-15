"""
NEXUS v8.2 — Telegram Bot Interface (python-telegram-bot)
Pair architecture: Router/Worker for efficient responses.
Personalization: learns about users through natural conversation.
DSGVO-compliant: per-user consent, data minimization, right to deletion.

v8.2.1: Live terminal block — asyncio.Queue + consumer task for real-time
        step updates. Sync callback puts events on queue, async consumer
        edits the Telegram message in real-time.
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
from nexus.core.feedback import FeedbackEmitter, FeedbackType, FeedbackEvent
from nexus.core.personalization import PersonalizationEngine
from nexus.core.dsgvo import DSGVOCompliance
from nexus.interfaces.markdown_utils import escape_markdown_v2, format_markdown_v2, split_markdown_v2

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


class NexusTelegramBot:
    """
    Telegram bot using python-telegram-bot.

    v8.2.1: Live step feedback via asyncio.Queue + consumer task.
            Terminal block edits the Telegram message in real-time
            as each step arrives.
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
            "📋 `/data` — Deine Daten einsehen \\(DSGVO Art\\. 15\\)\n"
            "🗑 `/delete` — Deine Daten löschen \\(DSGVO Art\\. 17\\)\n"
            "🔒 `/consent` — Einwilligung verwalten"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

    async def _cmd_status(self, update, ctx):
        user = update.effective_user
        processing = self._processing.get(user.id, False)
        status = "⚡ arbeitet" if processing else "✅ bereit"

        status_text = (
            f"⚡ *Nexus v8\\.2* — {status}\n\n"
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
        self._step_msg_ids.pop(user.id, None)

        # React to user message
        try:
            await update.message.set_reaction("👀")
        except Exception:
            pass

        # Live feedback: asyncio.Queue for cross-thread communication
        feedback_queue = asyncio.Queue()
        step_log = []  # Shared list, populated by sync callback, read by async consumer

        # Sync callback — called from the agent thread
        def on_step(event):
            step_log.append(event)
            try:
                feedback_queue.put_nowait(event)
            except Exception:
                pass

        emitter = FeedbackEmitter(callback=on_step)
        self._feedback_emitters[user.id] = emitter

        # Start the live terminal consumer task
        consumer_task = asyncio.create_task(
            self._terminal_consumer(chat_id, ctx, user.id, feedback_queue, step_log)
        )

        try:
            typing_task = asyncio.create_task(
                self._typing_loop(chat_id, ctx)
            )

            # Process with Pair architecture + personalization (runs in thread)
            response = await asyncio.to_thread(
                self.agent.process, text, str(user.id),
                feedback=emitter, platform="telegram"
            )

            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

            # Signal consumer to finish
            await feedback_queue.put(None)  # Sentinel
            await consumer_task

            # Finalize terminal block (mark as DONE)
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

    # ─── Live Terminal Consumer ──────────────────────

    async def _terminal_consumer(self, chat_id, ctx, user_id, queue, step_log):
        """Async consumer: reads events from queue and live-edits the terminal message."""
        last_edit_time = 0
        MIN_EDIT_INTERVAL = 0.8  # Throttle edits to avoid rate limits

        while True:
            try:
                # Wait for next event with timeout
                event = await asyncio.wait_for(queue.get(), timeout=30.0)

                # Sentinel = done
                if event is None:
                    break

                # Throttle edits
                now = asyncio.get_event_loop().time()
                if now - last_edit_time < MIN_EDIT_INTERVAL:
                    # Still update the step_log via queue, but skip Telegram edit
                    continue

                # Live-update the terminal block
                await self._update_terminal_block(chat_id, ctx, user_id, step_log)
                last_edit_time = now

            except asyncio.TimeoutError:
                # No new events for 30s — just keep waiting
                continue
            except Exception as e:
                log.debug(f"Terminal consumer error: {e}")
                continue

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
                lines.append("│ {} {}: {}".format(icon, msg, detail))
            else:
                lines.append("│ {} {}".format(icon, msg))
        lines.append("└──────────────────────────────┘```")
        return "\n".join(lines)

    async def _update_terminal_block(self, chat_id, ctx, user_id, steps):
        """Send or edit the terminal block message."""
        text = await self._format_terminal_block(steps)
        if not text:
            return

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
                msg = await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                self._step_msg_ids[user_id] = msg.message_id
        except Exception:
            pass

    async def _finalize_terminal_block(self, chat_id, ctx, user_id, steps):
        """Final update to terminal block showing completion."""
        steps.append(FeedbackEvent(
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