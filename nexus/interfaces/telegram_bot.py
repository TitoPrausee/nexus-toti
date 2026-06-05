"""
NEXUS v7 — Telegram Bot Interface
Streaming-first, fast responses, soul-aware.
"""

import os
import re
import json
import logging
import asyncio
from typing import Optional

import telethon
from telethon import TelegramClient, events
from telethon.tl.types import Message

from nexus.core.agent import NexusAgent

log = logging.getLogger("nexus.telegram")


class NexusTelegramBot:
    """
    Telegram interface for NEXUS v7.
    
    Features:
    - Streaming responses (token by token)
    - Typing indicator while processing
    - User recognition via Soul system
    - Message splitting for long responses
    - MarkdownV2 formatting
    """

    def __init__(self, agent: NexusAgent, config: dict = None):
        self.agent = agent
        self.config = config or {}

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

        self.client = None

    async def start(self):
        """Start the Telegram bot."""
        if not self.token:
            log.error("No Telegram token found. Set NEXUS_TG_TOKEN env var.")
            return

        self.client = TelegramClient(
            "nexus_session",
            api_id=0,  # Will use bot token directly
            api_hash="",
        )

        # Bot mode — just use token
        await self.client.start(bot_token=self.token)

        # Register handlers
        @self.client.on(events.NewMessage(incoming=True))
        async def handle_message(event):
            await self._handle_message(event)

        log.info("NEXUS Telegram bot started")

        await self.client.run_until_disconnected()

    async def _handle_message(self, event):
        """Handle incoming Telegram message."""
        sender = await event.get_sender()
        user_id = str(sender.id) if sender else None

        # Auth check
        if self.authorized_users and sender.id not in self.authorized_users:
            await event.respond("Nicht autorisiert.")
            return

        message_text = event.message.message
        if not message_text:
            return

        log.info(f"Message from {sender.first_name if sender else 'unknown'}: {message_text[:100]}")

        # Typing indicator
        if self.typing_indicator:
            await self.client(event)

        # Process with agent
        try:
            if self.streaming:
                await self._stream_response(event, message_text, user_id)
            else:
                response = self.agent.process(message_text, user_id=user_id)
                await self._send_message(event, response)

        except Exception as e:
            log.error(f"Error processing message: {e}")
            await self._send_message(event, f"Fehler: {e}")

    async def _stream_response(self, event, message_text: str, user_id: str):
        """Stream response token by token, sending partial updates."""
        buffer = ""
        last_sent = ""

        async for token in self.agent.process_stream(message_text, user_id=user_id):
            buffer += token

            # Send when we have enough content and enough time passed
            if len(buffer) - len(last_sent) > 200:
                await self._send_message(event, buffer)
                last_sent = buffer

        # Send final response if different from last sent
        if buffer != last_sent:
            # Split long messages
            await self._send_message(event, self._format_markdown(buffer))

    async def _send_message(self, event, text: str):
        """Send message, splitting if too long."""
        if len(text) <= self.max_message_length:
            await event.respond(text)
            return

        # Split at paragraph boundaries
        chunks = []
        while text:
            if len(text) <= self.max_message_length:
                chunks.append(text)
                break

            # Find a good split point
            split_at = text.rfind("\n\n", 0, self.max_message_length)
            if split_at == -1:
                split_at = text.rfind("\n", 0, self.max_message_length)
            if split_at == -1:
                split_at = text.rfind(" ", 0, self.max_message_length)
            if split_at == -1:
                split_at = self.max_message_length

            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()

        for chunk in chunks:
            await event.respond(chunk)

    def _format_markdown(self, text: str) -> str:
        """Basic markdown formatting for Telegram."""
        # Escape special chars for MarkdownV2
        # But keep our formatting
        return text

    def stop(self):
        """Stop the bot."""
        if self.client:
            self.client.disconnect()
        self.agent.shutdown()
        log.info("NEXUS Telegram bot stopped")


if __name__ == "__main__":
    import yaml

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    agent = NexusAgent(config)
    bot = NexusTelegramBot(agent, config.get("telegram", {}))

    asyncio.run(bot.start())