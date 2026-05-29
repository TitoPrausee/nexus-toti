"""
NEXUS Telegram Bot Interface — Toti Edition
Toti's personality, direct communication, state persistence per user.
"""

import os
import json
import time
import asyncio
import logging
from typing import Optional

try:
    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, filters, ContextTypes,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from core.llm_client import LLMClient
from core.memory import MemorySystem
from core.tools import ToolRegistry
from core.state import StateManager
from core.guards import NexusGuards
from agents.toti import TotiAgent
from agents.scout import ScoutAgent
from agents.forge import ForgeAgent
from agents.lens import LensAgent
from agents.herald import HeraldAgent
from agents.ghost import GhostAgent

logger = logging.getLogger(__name__)


class NexusTelegramBot:
    """Telegram Bot — Toti-powered."""

    def __init__(self, token: str, authorized_users: Optional[list[int]] = None):
        if not TELEGRAM_AVAILABLE:
            raise ImportError("python-telegram-bot not installed. pip install python-telegram-bot")

        self.token = token
        self.authorized_users = set(authorized_users) if authorized_users else None
        self.llm = LLMClient()
        self.tools = ToolRegistry()
        self._sessions: dict[int, MemorySystem] = {}
        self._states: dict[int, StateManager] = {}
        self._totis: dict[int, TotiAgent] = {}

    def _get_toti(self, user_id: int) -> TotiAgent:
        if user_id not in self._totis:
            memory = MemorySystem(session_id=f"tg_{user_id}")
            state = StateManager(state_path=f"data/state/toti_tg_{user_id}.json")
            guards = NexusGuards()
            toti = TotiAgent(self.llm, memory, self.tools, state, guards)

            agents = {
                "SCOUT": ScoutAgent(self.llm, memory, self.tools, state=state, guards=guards),
                "FORGE": ForgeAgent(self.llm, memory, self.tools, state=state, guards=guards),
                "LENS": LensAgent(self.llm, memory, self.tools, state=state, guards=guards),
                "HERALD": HeraldAgent(self.llm, memory, self.tools, state=state, guards=guards),
                "GHOST": GhostAgent(self.llm, memory, self.tools, state=state, guards=guards),
            }
            for aid, agent in agents.items():
                toti.register_agent(aid, agent)

            self._sessions[user_id] = memory
            self._states[user_id] = state
            self._totis[user_id] = toti

        return self._totis[user_id]

    def _is_authorized(self, user_id: int) -> bool:
        if self.authorized_users is None:
            return True
        return user_id in self.authorized_users

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self._is_authorized(user.id):
            await update.message.reply_text("Nicht autorisiert.")
            return

        await update.message.reply_text(
            f"**Toti — Nexus System**\n\n"
            f"Hallo {user.first_name}. Ich bin Toti — nicht dein Assistent, dein Kollege.\n\n"
            f"Schreib was du brauchst, ich kümmere mich drum.\n\n"
            f"/status /memory /state /reset /help",
            parse_mode="Markdown",
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "**Toti Befehle:**\n\n"
            "/start — Hallo\n"
            "/status — System-Status\n"
            "/memory — Memory\n"
            "/state — State-Objekt\n"
            "/reset — Session zurücksetzen\n"
            "/help — Diese Hilfe\n\n"
            "Oder einfach schreiben.",
            parse_mode="Markdown",
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        result = toti._handle_command("/status")
        await update.message.reply_text(f"```\n{result}\n```", parse_mode="Markdown")

    async def memory_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        result = toti._handle_command("/memory")
        await update.message.reply_text(f"```\n{result}\n```", parse_mode="Markdown")

    async def state_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        toti = self._get_toti(update.effective_user.id)
        result = toti._handle_command("/state")
        # State JSON can be long — truncate
        if len(result) > 4000:
            result = result[:4000] + "\n... (truncated)"
        await update.message.reply_text(result)

    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update.effective_user.id):
            return
        user_id = update.effective_user.id
        if user_id in self._totis:
            del self._totis[user_id]
        if user_id in self._sessions:
            del self._sessions[user_id]
        if user_id in self._states:
            del self._states[user_id]
        await update.message.reply_text("Session + State reset. Frischer Start.")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not self._is_authorized(user.id):
            await update.message.reply_text("Nicht autorisiert.")
            return

        message_text = update.message.text
        if not message_text:
            return

        processing_msg = await update.message.reply_text("Toti arbeitet...")

        try:
            toti = self._get_toti(user.id)
            response = toti.process(message_text)

            # Auto-save
            if user.id in self._states:
                self._states[user.id].save()
            if user.id in self._sessions:
                self._sessions[user.id].session_save()

            # Truncate for Telegram
            max_len = 4000
            if len(response) > max_len:
                chunks = [response[i:i+max_len] for i in range(0, len(response), max_len)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response)

            try:
                await processing_msg.delete()
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error: {e}")
            try:
                await processing_msg.edit_text(f"Fehler: {str(e)[:500]}")
            except Exception:
                pass

    def run(self):
        if not TELEGRAM_AVAILABLE:
            print("ERROR: pip install python-telegram-bot")
            return

        app = Application.builder().token(self.token).build()

        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(CommandHandler("memory", self.memory_command))
        app.add_handler(CommandHandler("state", self.state_command))
        app.add_handler(CommandHandler("reset", self.reset_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        print("Toti Telegram Bot starting...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
