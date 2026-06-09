"""
NEXUS v8.1 — Telegram Bot Interface (python-telegram-bot)
Pair architecture: Router/Worker for efficient responses.
Personalization: learns about users through natural conversation.
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
from nexus.core.personalization import PersonalizationEngine
from nexus.interfaces.markdown_utils import escape_markdown_v2

log = logging.getLogger("nexus.telegram")


class NexusTelegramBot:
    """
    Telegram bot using python-telegram-bot.
    Only needs BOT_TOKEN — no api_id/api_hash required.

    v8.1: Pair architecture for efficient routing.
    v8.0: Typing indicators, step feedback, interrupt handling.
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
        help_lines = [
            "**Nexus** — KI-Agent mit Pair-Architektur",
            "",
            "Schreib einfach, ich antworte mit Schritt-fuer-Schritt-Feedback.",
            "",
            "/status - Infos ueber mich",
            "/team - Team-Uebersicht",
            "/status - Infos ueber mich",
            "/team - Team-Uebersicht",
            "/delete — Deine Daten loeschen (DSGVO)",
        ]
        await update.message.reply_text(chr(10).join(help_lines))

    async def _cmd_status(self, update, ctx):
        user = update.effective_user
        processing = self._processing.get(user.id, False)
        status = "arbeitet" if processing else "bereit"

        status_lines = [
            "**Nexus v8.2** — " + status,
            "",
            "Architektur: Router (fast) + Worker (capable)",
            "Sessions: " + str(self.session_manager.stats()["active_sessions"]) + " aktiv",
            "DSGVO: konform",
        ]

        if self.agent._iteration_budget:
            status_lines.append(
                "Budget: " + self.agent._iteration_budget.summary()
            )

        await update.message.reply_text(chr(10).join(status_lines))

    async def _cmd_delete(self, update, ctx):
        user = update.effective_user
        self.agent.memory.clear_user(user.id)
        self.session_manager.remove(user.id)
        # Also clear personalization state
        uid = str(user.id)
        if uid in self.agent.personalization._onboardings:
            del self.agent.personalization._onboardings[uid]
        # Clear soul relationship
        if uid in self.agent.soul.relationships:
            del self.agent.soul.relationships[uid]
            self.agent.soul.save()
        await update.message.reply_text("Alle deine Daten wurden geloescht. DSGVO-konform.")


    async def _cmd_team(self, update, ctx):
        team_status = self.agent.team.get_team_status()
        await update.message.reply_text(team_status)

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
            await update.message.reply_text("Etwas zu schnell. Kurz warten...")
            return

        # ─── Interrupt handling ──────────────────────
        if self._processing.get(user.id, False):
            if user.id not in self._interrupt_queue:
                self._interrupt_queue[user.id] = []
            self._interrupt_queue[user.id].append(text)
            await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await update.message.reply_text(
                "Unterbrochen. Kurze Antwort kommt, dann setze ich fort."
            )
            return

        # ─── Normal processing ───────────────────────
        self._processing[user.id] = True

        emitter = FeedbackEmitter(
            callback=lambda msg, chat_id=chat_id, ctx=ctx: asyncio.ensure_future(
                self._send_step_feedback(chat_id, ctx, msg)
            )
        )
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

            await self._send_response(chat_id, ctx, response)

            # Check for queued interrupts
            pending = self._interrupt_queue.pop(user.id, [])
            if pending:
                queued_text = chr(10).join(
                    "  " + m[:80] for m in pending[:5]
                )
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text="Eingereihte Nachrichten:\n" + queued_text +
                         "\n\n_Spricht dein Anliegen? Sonst einfach neu schreiben._"
                )

        except Exception as e:
            log.error(f"Error processing message: {e}", exc_info=True)
            await ctx.bot.send_message(
                chat_id=chat_id,
                text="Fehler: " + str(e)[:200]
            )
        finally:
            self._processing[user.id] = False
            self._feedback_emitters.pop(user.id, None)

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

    async def _send_step_feedback(self, chat_id, ctx, message):
        try:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode=None,
            )
        except Exception as e:
            log.debug(f"Step feedback send error (non-critical): {e}")

    async def _send_response(self, chat_id, ctx, text):
        MAX_LEN = 4096
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