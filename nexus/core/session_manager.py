"""
NEXUS v7 — Session Manager

Manages per-chat NexusAgent instances for the Telegram bot (and other interfaces).

Problem: Without session isolation, all users share a single agent with shared L1
working memory. This causes memory bleed, no conversation privacy, and no per-user
context persistence.

Solution: SessionManager creates, tracks, and cleans up individual agent sessions
per chat. Each chat gets its own agent instance with isolated L1 memory, but they
share L3 long-term memory and the soul system.

Features:
- Per-chat agent instances with isolated L1 working memory
- Timeout-based cleanup of idle sessions (configurable)
- Shared L3 memory and soul across sessions
- Conversation persistence via ConversationStore
- Thread-safe with locking
- Stats reporting for monitoring
"""

import time
import logging
import threading
from typing import Optional
from dataclasses import dataclass, field

from nexus.core.agent import NexusAgent
from nexus.core.memory import MemorySystem
from nexus.core.conversations import ConversationStore
from nexus.soul import SoulEngine

log = logging.getLogger("nexus.session_manager")


@dataclass
class ChatSession:
    """A single chat session with its own agent instance.

    Each Telegram chat (or other interface conversation) gets its own
    ChatSession with an isolated L1 working memory. The L3 long-term
    memory and soul are shared across all sessions.
    """
    chat_id: str
    user_id: str = ""
    agent: NexusAgent = None
    created_at: float = 0.0
    last_active: float = 0.0
    message_count: int = 0

    def touch(self):
        """Update last_active timestamp and increment message count."""
        self.last_active = time.time()
        self.message_count += 1


class SessionManager:
    """
    Manages per-chat agent instances with timeout-based cleanup.

    Each chat (identified by chat_id, typically a Telegram chat ID)
    gets its own NexusAgent instance. This provides:

    1. Isolated L1 working memory per conversation
    2. Per-user context and conversation history
    3. Independent LLM conversations without cross-bleed
    4. Timeout-based automatic session cleanup

    L3 long-term memory and the soul system are shared across all sessions,
    so learned facts and relationship data persist globally.

    Usage:
        config = yaml.safe_load(open("config.yaml"))
        manager = SessionManager(config)

        # Get or create session for a chat
        session = manager.get_or_create(chat_id="12345", user_id="67890")
        response = session.agent.process("Hello!", user_id="67890")

        # Cleanup idle sessions periodically
        manager.cleanup_idle()

    Thread Safety:
        All operations are protected by a threading.Lock to prevent
        race conditions when multiple Telegram messages arrive concurrently.
    """

    def __init__(self, config: dict = None):
        """
        Initialize the SessionManager.

        Args:
            config: Application config dict (same as NexusAgent config).
                    Session-specific settings are read from config.session_manager.
        """
        self.config = config or {}
        self._lock = threading.Lock()

        # Session config
        session_cfg = self.config.get("session_manager", {})
        self.session_timeout = session_cfg.get("timeout_seconds", 3600)  # 1 hour default
        self.max_sessions = session_cfg.get("max_sessions", 50)
        self.cleanup_interval = session_cfg.get("cleanup_interval", 300)  # 5 min
        self.auto_save_on_cleanup = session_cfg.get("auto_save_on_cleanup", True)

        # Store: chat_id -> ChatSession
        self._sessions: dict[str, ChatSession] = {}

        # Shared L3 memory — all sessions read/write to the same store
        # but each has its own L1 and L2
        self._shared_memory = None
        self._shared_soul = None
        self._shared_conversations = None

        # Stats
        self._total_created = 0
        self._total_cleaned = 0

        log.info(
            f"SessionManager initialized: timeout={self.session_timeout}s, "
            f"max_sessions={self.max_sessions}, cleanup_interval={self.cleanup_interval}s"
        )

    def _create_agent(self, chat_id: str, user_id: str = "") -> NexusAgent:
        """Create a new NexusAgent instance for a chat session.

        Each agent gets its own L1/L2 memory but shares L3 with all
        other sessions. This means:
        - Conversation context (L1) is isolated per chat
        - Session summaries (L2) are isolated per chat
        - Long-term facts (L3) are shared — what one user teaches the
          agent is remembered for all users
        - Soul/relationships are shared — same personality for everyone

        Args:
            chat_id: Unique identifier for the chat (e.g., Telegram chat ID).
            user_id: Optional user identifier for soul integration.

        Returns:
            A fresh NexusAgent instance with shared L3 and soul.
        """
        agent = NexusAgent(self.config)

        # Share L3 long-term memory across all sessions if we have a shared instance
        if self._shared_memory:
            agent.memory.l3 = self._shared_memory.l3
            agent.memory.vector_store = self._shared_memory.vector_store

        # Share soul across all sessions — relationship data is global
        if self._shared_soul:
            agent.soul = self._shared_soul

        # Share conversation store — each session uses its own ID within the shared store
        if self._shared_conversations:
            agent.conversations = self._shared_conversations

        log.info(f"Created new agent for chat_id={chat_id}, user_id={user_id or 'unknown'}")
        return agent

    def _ensure_shared_resources(self):
        """Lazily initialize shared resources (L3 memory, soul, conversations).

        Called on first session creation to set up the shared instances
        that all per-chat agents will reference.
        """
        if self._shared_memory is None:
            # Create a reference agent to get shared L3/soul
            reference = NexusAgent(self.config)
            self._shared_memory = reference.memory
            self._shared_soul = reference.soul
            self._shared_conversations = reference.conversations
            log.info("Initialized shared L3 memory, soul, and conversation store")

    def get_or_create(
        self,
        chat_id: str,
        user_id: str = "",
        resume_session: str = None,
    ) -> ChatSession:
        """
        Get an existing session or create a new one for the given chat.

        If a session exists for the chat_id and hasn't timed out, returns it
        with the L1 memory intact. If the session has timed out, it's cleaned
        up and a fresh one is created.

        If `resume_session` is provided, the new agent will attempt to load
        the specified conversation session from ConversationStore.

        Args:
            chat_id: Unique identifier for the chat (e.g., Telegram chat ID).
            user_id: User identifier for this chat.
            resume_session: Optional session ID to resume from ConversationStore.

        Returns:
            ChatSession with an active agent instance.
        """
        with self._lock:
            # Check if session exists and is still active
            if chat_id in self._sessions:
                session = self._sessions[chat_id]

                # Check if session has timed out
                idle_time = time.time() - session.last_active
                if idle_time > self.session_timeout:
                    log.info(
                        f"Session {chat_id} timed out (idle {idle_time:.0f}s > "
                        f"{self.session_timeout}s), creating new session"
                    )
                    self._cleanup_session(chat_id)
                else:
                    # Update user_id if provided and different
                    if user_id and user_id != session.user_id:
                        session.user_id = user_id
                    session.touch()
                    return session

            # Ensure shared resources are initialized
            self._ensure_shared_resources()

            # Create new session
            agent = self._create_agent(chat_id, user_id)

            # Resume a saved conversation if requested
            if resume_session:
                agent.start_session(user_id=user_id, session_id=resume_session)
            else:
                # Auto-start a session for tracking
                agent.start_session(user_id=user_id)

            session = ChatSession(
                chat_id=chat_id,
                user_id=user_id,
                agent=agent,
                created_at=time.time(),
                last_active=time.time(),
                message_count=0,
            )

            session.touch()  # Mark as active on creation
            self._sessions[chat_id] = session
            self._total_created += 1

            # Enforce max sessions — evict the most idle one
            if len(self._sessions) > self.max_sessions:
                self._evict_most_idle()

            log.info(
                f"New session for chat_id={chat_id}, "
                f"active_sessions={len(self._sessions)}"
            )
            return session

    def get_session(self, chat_id: str) -> Optional[ChatSession]:
        """
        Get an existing session without creating a new one.

        Returns None if the session doesn't exist or has timed out.

        Args:
            chat_id: The chat ID to look up.

        Returns:
            ChatSession if active, None otherwise.
        """
        with self._lock:
            if chat_id not in self._sessions:
                return None

            session = self._sessions[chat_id]
            idle_time = time.time() - session.last_active
            if idle_time > self.session_timeout:
                return None

            return session

    def remove_session(self, chat_id: str) -> bool:
        """
        Manually remove a session, saving its conversation first.

        Args:
            chat_id: The chat ID to remove.

        Returns:
            True if session was found and removed, False otherwise.
        """
        with self._lock:
            if chat_id not in self._sessions:
                return False
            self._cleanup_session(chat_id)
            return True

    def cleanup_idle(self) -> int:
        """
        Remove all sessions that have exceeded the idle timeout.

        Sessions are saved to ConversationStore before being removed,
        so their context is preserved if they resume later.

        Returns:
            Number of sessions cleaned up.
        """
        with self._lock:
            now = time.time()
            to_remove = []

            for chat_id, session in self._sessions.items():
                idle_time = now - session.last_active
                if idle_time > self.session_timeout:
                    to_remove.append(chat_id)

            for chat_id in to_remove:
                self._cleanup_session(chat_id)

            if to_remove:
                log.info(
                    f"Cleaned up {len(to_remove)} idle sessions "
                    f"(timeout={self.session_timeout}s), "
                    f"remaining={len(self._sessions)}"
                )

            return len(to_remove)

    def _cleanup_session(self, chat_id: str):
        """Clean up a single session: save conversation and remove from store.

        Must be called within _lock.
        """
        session = self._sessions.pop(chat_id, None)
        if session is None:
            return

        # Save conversation before removing
        if self.auto_save_on_cleanup and session.agent:
            try:
                session.agent.save_conversation()
                log.debug(f"Saved conversation for session {chat_id}")
            except Exception as e:
                log.warning(f"Failed to save conversation for session {chat_id}: {e}")

            # End the memory session (archives L1 to L2)
            try:
                session.agent.memory.end_session()
            except Exception as e:
                log.warning(f"Failed to end memory session for {chat_id}: {e}")

        self._total_cleaned += 1
        log.info(
            f"Removed session {chat_id}: "
            f"messages={session.message_count}, "
            f"duration={time.time() - session.created_at:.0f}s"
        )

    def _evict_most_idle(self):
        """Evict the most idle session to stay within max_sessions limit.

        Must be called within _lock.
        """
        if not self._sessions:
            return

        most_idle_id = min(
            self._sessions,
            key=lambda cid: self._sessions[cid].last_active,
        )
        log.info(f"Evicting most idle session {most_idle_id} (max_sessions reached)")
        self._cleanup_session(most_idle_id)

    def save_all(self):
        """
        Save all active sessions. Called during graceful shutdown.

        Each session's conversation and L3 memory is persisted.
        """
        with self._lock:
            for chat_id, session in self._sessions.items():
                if session.agent:
                    try:
                        session.agent.save_conversation()
                        session.agent.memory.save()
                    except Exception as e:
                        log.warning(f"Failed to save session {chat_id}: {e}")

            # Save shared L3 memory
            if self._shared_memory:
                try:
                    self._shared_memory.save()
                except Exception as e:
                    log.warning(f"Failed to save shared memory: {e}")

            # Save soul
            if self._shared_soul:
                try:
                    self._shared_soul.save()
                except Exception as e:
                    log.warning(f"Failed to save soul: {e}")

            log.info(f"Saved all {len(self._sessions)} active sessions")

    def stats(self) -> dict:
        """Get session manager statistics.

        Returns:
            Dict with active session count, total created/cleaned,
            per-session details, and timeout config.
        """
        with self._lock:
            sessions_info = []
            for chat_id, session in self._sessions.items():
                idle = time.time() - session.last_active
                sessions_info.append({
                    "chat_id": chat_id,
                    "user_id": session.user_id,
                    "messages": session.message_count,
                    "idle_seconds": round(idle, 1),
                    "age_seconds": round(time.time() - session.created_at, 1),
                    "l1_entries": len(session.agent.memory.l1) if session.agent else 0,
                    "l2_entries": len(session.agent.memory.l2) if session.agent else 0,
                })

            return {
                "active_sessions": len(self._sessions),
                "max_sessions": self.max_sessions,
                "session_timeout_seconds": self.session_timeout,
                "total_created": self._total_created,
                "total_cleaned": self._total_cleaned,
                "shared_l3_entries": len(self._shared_memory.l3) if self._shared_memory else 0,
                "shared_soul_relationships": (
                    len(self._shared_soul.relationships) if self._shared_soul else 0
                ),
                "sessions": sessions_info,
            }