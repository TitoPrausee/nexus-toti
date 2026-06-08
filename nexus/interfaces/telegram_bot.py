"""
NEXUS v8.0 — Telegram Bot Interface (python-telegram-bot)
Streaming responses, typing indicators, step feedback, interrupt handling.
DSGVO-compliant: per-user consent, data minimization, right to deletion.
"""

import os
import re
import asyncio
import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)

from nexus.core.agent import NexusAgent
from nexus.core.session_manager import SessionManager
from nexus.core.rate_limiter import RateLimiter
from nexus.core.feedback import FeedbackEmitter
from nexus.interfaces.markdown_utils import escape_markdown_v2

log = logging.getLogger("nexus.telegram")


class NexusTelegramBot:
    """
    Telegram bot using python-telegram-bot.
    Only needs BOT_TOKEN — no api_id/api_hash required.
    Supports: typing indicators, step feedback, interrupt handling.
    """

    def __init__(self, agent: NexusAgent, config: dict = None):
        self.agent = agent
        self.config = config or {}
        self.token = os.environ.get(
            self.config.get("token_env", "NEXUS_TG_TOKEN"), ""
        )
        self.authorized_users = self._parse_authorized_users()
        self.session_manager = SessionManager(
            config.get("session_manager", {})
        )
        self.rate_limiter = RateLimiter(
            rate=self.config.get("rate_limiter", {}).get("rate", 0.33),
            burst=self.config.get("rate_limiter", {}).get("burst", 5),
        )
        self._processing = {}  # user_id -> bool (currently processing)
        self._interrupt_queue = {}  # user_id -> list[pending messages]
        self._feedback_emitters = {}  # user_id -> FeedbackEmitter

    def _parse_authorized_users(self):
        """Parse authorized user IDs from env var."""
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
        """Start the Telegram bot."""
        if not self.token:
            log.error("No Telegram token found. Set NEXUS_TG_TOKEN env var.")
            return

        app = ApplicationBuilder().token(self.token).build()

        # Register handlers
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("delete", self._cmd_delete))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_message
        ))

        log.info(f"NEXUS Telegram bot starting (authorized: {self.authorized_users or 'all'})")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("NEXUS Telegram bot running ✓")

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            log.info("Shutting down...")
            await app.updater.stop()
            await app.stop()
            await app.shutdown()

    # ─── Commands ──────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
        if self.authorized_users and user.id not in self.authorized_users:
            await update.message.reply_text("Nicht autorisiert.")
            return
        await update.message.reply_text(
            f"Hey {user.first_name}! 👋 Ich bin **Toti** — dein KI-Assistent.\n\n"
            "Einfach schreiben, was du brauchst. Ich zeige dir jeden Schritt live an.\n\n"
            "/status — Meine Info\n/help — Hilfe\n/delete — Deine Daten löschen (DSGVO)"
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "**Toti — KI-Assistent**\n\n"
            "Einfach schreiben, ich antworte mit Schritt-für-Schritt-Feedback.\n\n"
            "Besonderheiten:\n"
            "• Live-Feedback bei jedem Arbeitsschritt\n"
            "• Unterbrich mich jederzeit — ich antworte kurz und setze danach fort\n"
            "• Ich lerne automatisch aus unseren Gesprächen\n\n"
            "/status — Infos über mich\n/delete — Deine Daten löschen"
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        processing = self._processing.get(user.id, False)
        status = "arbeitet" if processing else "bereit"
        await update.message.reply_text(
            f"**Toti v8.0** — {status}\n\n"
            f"Session: {self.session_manager.stats()['active_sessions']} aktiv\n"
            f"Ollama Cloud: kimi-k2.6:cloud\n"
            f"DSGVO: konform"
        )

    async def _cmd_delete(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """DSGVO right to deletion."""
        user = update.effective_user
        self.agent.memory.clear_user(user.id)
        self.session_manager.remove(user.id)
        await update.message.reply_text(
            "✅ Alle deine Daten wurden gelöscht. DSGVO-konform."
        )

    # ─── Message Handler ───────────────────────────────

    async def _handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages with interrupt support."""
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
            # Currently processing — queue as interrupt
            if user.id not in self._interrupt_queue:
                self._interrupt_queue[user.id] = []
            self._interrupt_queue[user.id].append(text)

            # Send brief acknowledgment
            await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await update.message.reply_text(
                "⚡ Unterbrochen! Kurze Antwort kommt, dann setze ich fort."
            )
            return

        # ─── Normal processing ───────────────────────
        self._processing[user.id] = True

        # Create feedback emitter for this user
        emitter = FeedbackEmitter(
            callback=lambda msg, chat_id=chat_id, ctx=ctx: asyncio.ensure_future(
                self._send_step_feedback(chat_id, ctx, msg)
            )
        )
        self._feedback_emitters[user.id] = emitter

        try:
            # Show typing indicator continuously
            typing_task = asyncio.create_task(
                self._typing_loop(chat_id, ctx)
            )

            # Store original reply method for streaming
            response = await asyncio.to_thread(
                self.agent.process, text, str(user.id), feedback=emitter
            )

            # Stop typing
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass

            # Send final response (split if too long)
            await self._send_response(chat_id, ctx, response)

            # Check for queued interrupts
            pending = self._interrupt_queue.pop(user.id, [])
            if pending:
                # Brief acknowledgment of queued items
                queued_text = "\n".join(f"• {m[:80]}" for m in pending[:5])
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=f"📋 Eingereihte Nachrichten:\n{queued_text}\n\n_Spricht dein Anliegen? Sonst einfach neu schreiben._"
                )

        except Exception as e:
            log.error(f"Error processing message: {e}", exc_info=True)
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Fehler: {str(e)[:200]}"
            )
        finally:
            self._processing[user.id] = False
            self._feedback_emitters.pop(user.id, None)

    # ─── Helpers ────────────────────────────────────────

    async def _typing_loop(self, chat_id: int, ctx: ContextTypes.DEFAULT_TYPE):
        """Continuously send typing indicator while processing."""
        while True:
            try:
                await ctx.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING
                )
                await asyncio.sleep(4)  # Telegram typing lasts ~5s
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

    async def _send_step_feedback(self, chat_id: int, ctx, message: str):
        """Send a step feedback message (brief, overwritable)."""
        try:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=None,  # Step feedback is plain text
            )
        except Exception as e:
            log.debug(f"Step feedback send error (non-critical): {e}")

    async def _send_response(self, chat_id: int, ctx, text: str):
        """Send response, splitting into chunks if needed (Telegram 4096 char limit)."""
        MAX_LEN = 4096

        # Try MarkdownV2 first, fall back to plain
        try:
            escaped = escape_markdown_v2(text)
            chunks = self._split_text(escaped, MAX_LEN)
            for chunk in chunks:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="MarkdownV2",
                )
        except Exception:
            # Fallback to plain text
            chunks = self._split_text(text, MAX_LEN)
            for chunk in chunks:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                )

    @staticmethod
    def _split_text(text: str, max_len: int) -> list:
        """Split text into chunks respecting Telegram's length limit."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Find last newline within limit
            split_at = text.rfind("\n", 0, max_len)
            if split_at <= 0:
                split_at = text.rfind(" ", 0, max_len)
            if split_at <= 0:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n ")
        return chunks