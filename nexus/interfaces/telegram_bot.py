"""
NEXUS v7 — Telegram Bot Interface
Streaming-first, fast responses, soul-aware.
Real-time step feedback (💻 terminal, 📖 read_file, etc.) — like Mercury.
Typing indicator while processing.
Interrupt handling — respond to new messages while busy.

v8.0: Active feedback, typing indicator, interrupt queue.
"""

import os
import re
import json
import logging
import asyncio
from typing import Optional, List

import telethon
from telethon import TelegramClient, events
from telethon.tl.types import Message

from nexus.core.agent import NexusAgent
from nexus.core.rate_limiter import RateLimiter
from nexus.core.session_manager import SessionManager
from nexus.core.feedback import FeedbackEmitter, FeedbackType
from nexus.interfaces.markdown_utils import (
    escape_markdown_v2,
    format_markdown_v2,
    split_markdown_v2,
)

log = logging.getLogger("nexus.telegram")

# Mercury-style step icons
_TOOL_ICONS = {
    "terminal": "💻",
    "file_read": "📖",
    "file_write": "✏️",
    "file_search": "🔍",
    "web_search": "🌐",
    "web_fetch": "🌐",
    "code_exec": "⚡",
    "calculator": "🔢",
    "time": "🕐",
    "delegation": "🤝",
    "memory": "🧠",
    "session": "💾",
    "skill": "📚",
    "thinking": "🧠",
    "llm_call": "💭",
}


class NexusTelegramBot:
    """
    Telegram interface for NEXUS v7.

    Features:
    - Step-by-step progress feedback (💻 terminal, 📖 read_file, etc.)
    - Typing indicator while processing
    - Interrupt handling — queue messages while busy
    - Per-chat session management with isolated L1 memory
    - Per-user rate limiting
    - Timeout-based session cleanup
    - MarkdownV2 formatting
    """

    def __init__(self, agent: NexusAgent, config: dict = None):
        """
        Initialize the Telegram bot.

        Args:
            agent: A NexusAgent instance (used for shared L3/soul initialization).
            config: Bot-specific configuration dict.
        """
        self.config = config or {}

        # Session manager for per-chat agent instances
        app_config = self.config.get("app_config", {})
        if not app_config:
            app_config = agent.config if hasattr(agent, 'config') else {}

        self.session_manager = SessionManager(app_config)
        log.info("SessionManager initialized for per-chat isolation")

        # Telegram config
        self.token = os.environ.get(
            self.config.get("token_env", "NEXUS_TG_TOKEN"),
            ""
        )
        authorized_env = self.config.get("authorized_users_env", "NEXUS_TG_USERS")
        authorized_raw = os.environ.get(authorized_env, "")
        self.authorized_users = set()
        if authorized_raw:
            self.authorized_users = {
                int(uid.strip())
                for uid in authorized_raw.split(",")
                if uid.strip().isdigit()
            }

        self.streaming = self.config.get("streaming", True)
        self.typing_indicator = self.config.get("typing_indicator", True)
        self.max_message_length = self.config.get("max_message_length", 4096)
        self.min_stream_interval = self.config.get("min_stream_interval", 0.3)

        # Per-user rate limiter: 1 message per 3 seconds, burst of 5
        rate_limiter_config = self.config.get("rate_limiter", {})
        self.rate_limiter = RateLimiter(
            rate=rate_limiter_config.get("rate", 1.0 / 3.0),
            burst=rate_limiter_config.get("burst", 5),
            config=rate_limiter_config,
        )

        # Session cleanup task
        self._cleanup_task = None
        self.client = None

        # v8.0: Track which chat_id maps to which agent (for interrupts)
        self._chat_agents = {}  # chat_id -> NexusAgent

    async def start(self):
        """Start the Telegram bot and session cleanup background task."""
        if not self.token:
            log.error("No Telegram token found. Set NEXUS_TG_TOKEN env var.")
            return

        # Telegram API credentials from https://my.telegram.org
        # Required by Telethon even for bot mode
        api_id = int(os.environ.get("TELEGRAM_API_ID", "0"))
        api_hash = os.environ.get("TELEGRAM_API_HASH", "")

        self.client = TelegramClient(
            "nexus_session",
            api_id=api_id,
            api_hash=api_hash,
        )

        # Bot mode — just use token
        await self.client.start(bot_token=self.token)

        # Register handlers
        @self.client.on(events.NewMessage(incoming=True))
        async def handle_message(event):
            await self._handle_message(event)

        # Start periodic session cleanup
        cleanup_interval = self.config.get(
            "session_manager", {}
        ).get("cleanup_interval", 300)

        async def session_cleanup_loop():
            """Periodically clean up idle sessions."""
            while True:
                await asyncio.sleep(cleanup_interval)
                try:
                    removed = self.session_manager.cleanup_idle()
                    if removed > 0:
                        log.info(f"Session cleanup: removed {removed} idle sessions")
                except Exception as e:
                    log.error(f"Session cleanup error: {e}")

        self._cleanup_task = asyncio.create_task(session_cleanup_loop())

        log.info("NEXUS Telegram bot started with per-chat session management")
        await self.client.run_until_disconnected()

    async def _handle_message(self, event):
        """Handle incoming Telegram message with interrupt support and step feedback."""
        sender = await event.get_sender()
        user_id = str(sender.id) if sender else None
        chat_id = str(event.chat_id) if hasattr(event, 'chat_id') else user_id

        # Auth check
        if self.authorized_users and sender.id not in self.authorized_users:
            await event.respond(escape_markdown_v2("Nicht autorisiert."), parse_mode="MarkdownV2")
            return

        message_text = event.message.message
        if not message_text:
            return

        # Rate limiting — per-user token bucket
        if user_id and not self.rate_limiter.allow(user_id):
            wait = self.rate_limiter.wait_time(user_id)
            log.info(f"Rate limited user {user_id}, wait {wait:.1f}s")
            rate_msg = escape_markdown_v2(
                f"Zu viele Nachrichten. Bitte warte {wait:.0f} Sekunden."
            )
            await self._send_message(event, rate_msg)
            return

        log.info(f"Message from {sender.first_name if sender else 'unknown'}: {message_text[:100]}")

        # Get or create a per-chat session
        chat_session = self.session_manager.get_or_create(
            chat_id=chat_id,
            user_id=user_id or "",
        )
        agent = chat_session.agent
        self._chat_agents[chat_id] = agent

        # v8.0: If agent is busy, queue as interrupt instead of waiting
        if agent.is_busy:
            agent.queue_interrupt(message_text, user_id)
            # Send immediate acknowledgment
            ack_msg = "⚡ Unterbrochen! Kurze Antwort kommt, dann setze ich fort."
            await event.respond(ack_msg, parse_mode="MarkdownV2")
            # Keep typing indicator
            await self._send_typing(event)
            return

        # Create feedback emitter for this request
        feedback_queue = asyncio.Queue()
        feedback = FeedbackEmitter(async_queue=feedback_queue)

        # v8.0: Process with feedback in background task
        # Send initial "thinking" indicator
        await self._send_typing(event)

        # Start progress updater task — reads from feedback queue and sends updates
        progress_task = asyncio.create_task(
            self._progress_updater(event, feedback_queue, chat_id)
        )

        try:
            # Run the synchronous agent.process in a thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: agent.process(
                    message_text, user_id=user_id, feedback=feedback
                )
            )

            # Wait for progress updater to finish
            await progress_task

            # Send final response
            formatted = self._format_markdown(response)
            await self._send_message(event, formatted)

        except Exception as e:
            log.error(f"Error processing message: {e}", exc_info=True)
            # Cancel progress task on error
            progress_task.cancel()
            error_msg = escape_markdown_v2(f"Fehler: {e}")
            await self._send_message(event, error_msg)

    async def _progress_updater(self, event, queue: asyncio.Queue, chat_id: str):
        """Send step-by-step progress messages from feedback events.

        Instead of one message per step, we batch events and send
        periodic updates to avoid Telegram rate limiting.
        """
        collected_steps = []
        last_update = asyncio.get_event_loop().time()
        update_interval = 2.0  # Send batched update every 2 seconds
        status_message = None

        while True:
            try:
                # Wait for next event with timeout
                event_obj = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No new event — check if we should send a batched update
                now = asyncio.get_event_loop().time()
                if collected_steps and (now - last_update) >= update_interval:
                    # Send batched progress update
                    progress_text = self._format_steps(collected_steps)
                    try:
                        if status_message:
                            await status_message.edit(progress_text)
                        else:
                            status_message = await event.respond(progress_text)
                    except Exception:
                        pass  # Silently ignore edit failures
                    collected_steps = []
                    last_update = now

                # Keep typing indicator alive
                await self._send_typing(event)
                continue

            # None is the sentinel for "done"
            if event_obj is None:
                # Send any remaining steps
                if collected_steps:
                    progress_text = self._format_steps(collected_steps)
                    try:
                        if status_message:
                            await status_message.edit(progress_text)
                        else:
                            await event.respond(progress_text)
                    except Exception:
                        pass
                # Delete the temporary status message
                if status_message:
                    try:
                        await status_message.delete()
                    except Exception:
                        pass
                return

            # Collect the step
            collected_steps.append(event_obj)
            last_step_time = asyncio.get_event_loop().time()

            # If it's a DONE event, flush immediately
            if event_obj.type == FeedbackType.DONE:
                if collected_steps:
                    progress_text = self._format_steps(collected_steps)
                    try:
                        if status_message:
                            await status_message.edit(progress_text)
                        else:
                            await event.respond(progress_text)
                    except Exception:
                        pass
                if status_message:
                    try:
                        await status_message.delete()
                    except Exception:
                        pass
                return

    def _format_steps(self, steps: list) -> str:
        """Format feedback steps as Telegram message."""
        lines = []
        seen = set()
        for step in steps[-8:]:  # Show last 8 steps max
            icon = _TOOL_ICONS.get(step.type.value, "⏳")
            # Deduplicate consecutive identical steps
            step_key = f"{icon}{step.message}"
            if step_key in seen:
                continue
            seen.add(step_key)

            if step.detail:
                # Truncate detail for display
                detail = step.detail[:50]
                lines.append(f"{icon} {step.message}: _{detail}_")
            else:
                lines.append(f"{icon} {step.message}")

        if not lines:
            return "🧠 Arbeite..."

        return "\n".join(lines)

    async def _send_typing(self, event):
        """Send typing indicator to the chat."""
        if not self.typing_indicator or not self.client:
            return
        try:
            await asyncio.sleep(0.05)
            from telethon.tl.functions.messages import SetTypingRequest
            from telethon.tl.types import SendMessageTypingAction
            peer = await event.get_input_chat()
            await self.client(SetTypingRequest(peer=peer, action=SendMessageTypingAction()))
        except Exception:
            pass  # Typing indicator is best-effort

    async def _stream_response(self, event, message_text: str, user_id: str, agent: NexusAgent):
        """Stream response token by token, sending partial updates.

        During streaming, we send raw text chunks for responsiveness.
        The final message is formatted with MarkdownV2.
        """
        buffer = ""
        last_sent_len = 0

        async for token in agent.process_stream(message_text, user_id=user_id):
            buffer += token

            # Send raw text updates during streaming for speed
            if len(buffer) - last_sent_len > 200:
                await self._send_message(event, buffer, parse_mode=None)
                last_sent_len = len(buffer)

        # Send final response with full MarkdownV2 formatting
        final_text = self._format_markdown(buffer)
        await self._send_message(event, final_text)

    async def _send_message(self, event, text: str, parse_mode: str = None):
        """Send message, splitting if too long. Respects MarkdownV2 formatting."""
        if parse_mode is None:
            parse_mode = self.config.get("parse_mode", "MarkdownV2")

        # Split long messages respecting formatting boundaries
        chunks = split_markdown_v2(text, max_length=self.max_message_length)

        for i, chunk in enumerate(chunks):
            try:
                if parse_mode:
                    await event.respond(chunk, parse_mode=parse_mode)
                else:
                    await event.respond(chunk)
            except Exception as e:
                # If MarkdownV2 parsing fails, fall back to plain text
                log.warning(f"MarkdownV2 parse failed, sending as plain text: {e}")
                try:
                    await event.respond(chunk)
                except Exception as e2:
                    log.error(f"Failed to send message chunk {i+1}/{len(chunks)}: {e2}")

            # Small delay between chunks to avoid rate limiting
            if len(chunks) > 1 and i < len(chunks) - 1:
                await asyncio.sleep(0.05)

    def _format_markdown(self, text: str) -> str:
        """Convert standard Markdown to Telegram MarkdownV2 format."""
        return format_markdown_v2(text)

    def stop(self):
        """Stop the bot, save all sessions, and clean up."""
        try:
            self.session_manager.save_all()
            log.info("All sessions saved on shutdown")
        except Exception as e:
            log.error(f"Failed to save sessions on shutdown: {e}")

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

        if self.client:
            self.client.disconnect()
        log.info("NEXUS Telegram bot stopped")

    def stats(self) -> dict:
        """Get bot + rate limiter + session manager statistics."""
        rate_stats = self.rate_limiter.stats()
        session_stats = self.session_manager.stats()
        return {
            "rate_limiter": rate_stats,
            "session_manager": session_stats,
        }


if __name__ == "__main__":
    import yaml

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    agent = NexusAgent(config)
    bot_config = config.get("telegram", {})
    bot_config["app_config"] = config

    bot = NexusTelegramBot(agent, bot_config)

    asyncio.run(bot.start())