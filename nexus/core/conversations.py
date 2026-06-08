"""
NEXUS v7 — Conversation Storage

Persists conversation sessions to disk so the agent can resume
conversations across restarts. Each session is a JSON file containing
the L1 working memory entries and metadata (user_id, timestamps, etc.).

Features:
- Save/load/list/delete conversation sessions
- Auto-save on shutdown, auto-load on init
- Session metadata: user_id, created_at, last_active, message_count
- Thread-safe operations via file locking
- Cleanup of old sessions (configurable max age)
- Integration with MemorySystem and NexusAgent
"""

import json
import time
import os
import logging
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

log = logging.getLogger("nexus.conversations")


@dataclass
class SessionMetadata:
    """Metadata for a conversation session."""
    session_id: str
    user_id: str = ""
    created_at: float = 0.0
    last_active: float = 0.0
    message_count: int = 0
    summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMetadata":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ConversationStore:
    """
    Manages persistent conversation sessions.

    Each session is stored as a JSON file in the sessions directory.
    The store maintains an index of all sessions with metadata for fast
    listing and lookup.

    Thread safety: Uses a threading.Lock for all file operations to
    prevent data corruption from concurrent access.

    Usage:
        store = ConversationStore(data_dir="data/sessions")

        # Save current session
        store.save_session("session_123", entries, user_id="user_1")

        # Load and resume a session
        entries = store.load_session("session_123")

        # List sessions for a user
        sessions = store.list_sessions(user_id="user_1")

        # Cleanup old sessions
        store.cleanup(max_age_days=30)
    """

    def __init__(self, data_dir: str = "data/sessions", max_sessions: int = 100):
        """
        Initialize the conversation store.

        Args:
            data_dir: Directory to store session files.
            max_sessions: Maximum number of sessions to keep (oldest removed first).
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.max_sessions = max_sessions
        self._lock = threading.Lock()
        self._index_path = self.data_dir / "index.json"
        self._index: dict[str, SessionMetadata] = {}
        self._load_index()

    # ─── Index Management ──────────────────────────────────

    def _load_index(self):
        """Load the session index from disk."""
        if self._index_path.exists():
            try:
                with open(self._index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._index = {
                    sid: SessionMetadata.from_dict(meta)
                    for sid, meta in data.items()
                }
                log.debug(f"Loaded {len(self._index)} session entries from index")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                log.warning(f"Corrupt session index, rebuilding: {e}")
                self._rebuild_index()
        else:
            self._rebuild_index()

    def _save_index(self):
        """Persist the session index to disk."""
        data = {sid: meta.to_dict() for sid, meta in self._index.items()}
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _rebuild_index(self):
        """Rebuild the index by scanning all session files on disk."""
        self._index.clear()
        for session_file in self.data_dir.glob("session_*.json"):
            session_id = session_file.stem.replace("session_", "")
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                meta = data.get("metadata", {})
                self._index[session_id] = SessionMetadata(
                    session_id=session_id,
                    user_id=meta.get("user_id", ""),
                    created_at=meta.get("created_at", 0.0),
                    last_active=meta.get("last_active", 0.0),
                    message_count=meta.get("message_count", 0),
                    summary=meta.get("summary", ""),
                )
            except (json.JSONDecodeError, KeyError) as e:
                log.warning(f"Skipping corrupt session file {session_file}: {e}")
        self._save_index()
        log.info(f"Rebuilt session index: {len(self._index)} sessions")

    # ─── Session CRUD ──────────────────────────────────────

    def save_session(
        self,
        session_id: str,
        entries: list[dict],
        user_id: str = "",
        summary: str = "",
    ) -> bool:
        """
        Save a conversation session to disk.

        Args:
            session_id: Unique identifier for the session.
            entries: List of message dicts with 'role' and 'content' keys.
                     Each entry can also have 'timestamp', 'tokens', 'importance'.
            user_id: The user associated with this session.
            summary: Optional short summary of the conversation.

        Returns:
            True if saved successfully, False on error.
        """
        now = time.time()

        # Build or update metadata
        existing = self._index.get(session_id)
        if existing:
            meta = existing
            meta.last_active = now
            meta.message_count = len(entries)
            if summary:
                meta.summary = summary[:500]
        else:
            meta = SessionMetadata(
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                last_active=now,
                message_count=len(entries),
                summary=summary[:500] if summary else "",
            )

        session_data = {
            "metadata": meta.to_dict(),
            "entries": entries,
        }

        session_file = self.data_dir / f"session_{session_id}.json"

        with self._lock:
            try:
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, ensure_ascii=False, indent=2)

                self._index[session_id] = meta
                self._save_index()

                log.info(
                    f"Saved session {session_id}: {len(entries)} entries, "
                    f"user={user_id or 'unknown'}"
                )
                return True

            except Exception as e:
                log.error(f"Failed to save session {session_id}: {e}")
                return False

    def load_session(self, session_id: str) -> Optional[list[dict]]:
        """
        Load a conversation session from disk.

        Args:
            session_id: The session to load.

        Returns:
            List of message entry dicts, or None if session not found.
        """
        session_file = self.data_dir / f"session_{session_id}.json"

        with self._lock:
            if not session_file.exists():
                log.debug(f"Session {session_id} not found")
                return None

            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                entries = data.get("entries", [])

                # Update last_active timestamp
                if session_id in self._index:
                    self._index[session_id].last_active = time.time()
                    self._save_index()

                log.info(f"Loaded session {session_id}: {len(entries)} entries")
                return entries

            except (json.JSONDecodeError, KeyError) as e:
                log.error(f"Failed to load session {session_id}: {e}")
                return None

    def list_sessions(
        self,
        user_id: str = None,
        limit: int = 20,
        sort_by: str = "last_active",
    ) -> list[dict]:
        """
        List conversation sessions, optionally filtered by user.

        Args:
            user_id: Filter to sessions for this user (None = all users).
            limit: Maximum number of sessions to return.
            sort_by: Sort field ("last_active", "created_at", "message_count").

        Returns:
            List of session metadata dicts, sorted by the given field descending.
        """
        with self._lock:
            sessions = list(self._index.values())

        # Filter by user_id if provided
        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]

        # Sort
        valid_sort_fields = {"last_active", "created_at", "message_count"}
        if sort_by not in valid_sort_fields:
            sort_by = "last_active"
        sessions.sort(key=lambda s: getattr(s, sort_by, 0), reverse=True)

        return [s.to_dict() for s in sessions[:limit]]

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a conversation session.

        Args:
            session_id: The session to delete.

        Returns:
            True if deleted, False if not found or error.
        """
        session_file = self.data_dir / f"session_{session_id}.json"

        with self._lock:
            try:
                if session_file.exists():
                    session_file.unlink()
                    log.info(f"Deleted session file: {session_file}")
                else:
                    log.debug(f"Session file not found for deletion: {session_id}")

                if session_id in self._index:
                    del self._index[session_id]
                    self._save_index()
                else:
                    log.debug(f"Session {session_id} not in index")

                return True

            except Exception as e:
                log.error(f"Failed to delete session {session_id}: {e}")
                return False

    def get_session_metadata(self, session_id: str) -> Optional[dict]:
        """
        Get metadata for a session without loading the full entries.

        Args:
            session_id: The session to look up.

        Returns:
            Metadata dict, or None if not found.
        """
        with self._lock:
            meta = self._index.get(session_id)
            if meta:
                return meta.to_dict()
        return None

    # ─── Cleanup ───────────────────────────────────────────

    def cleanup(self, max_age_days: int = 30, max_sessions: int = None) -> int:
        """
        Remove old and excess sessions.

        Args:
            max_age_days: Remove sessions older than this many days.
            max_sessions: Remove oldest sessions if count exceeds this
                         (defaults to self.max_sessions).

        Returns:
            Number of sessions removed.
        """
        removed = 0
        max_age_seconds = max_age_days * 86400
        now = time.time()
        session_limit = max_sessions or self.max_sessions

        with self._lock:
            # Remove sessions older than max_age_days
            to_remove = []
            for sid, meta in self._index.items():
                if now - meta.last_active > max_age_seconds:
                    to_remove.append(sid)

            for sid in to_remove:
                session_file = self.data_dir / f"session_{sid}.json"
                if session_file.exists():
                    session_file.unlink()
                del self._index[sid]
                removed += 1

            # Remove oldest sessions if over the limit
            if len(self._index) > session_limit:
                sorted_sessions = sorted(
                    self._index.values(), key=lambda s: s.last_active
                )
                excess = len(self._index) - session_limit
                for meta in sorted_sessions[:excess]:
                    session_file = self.data_dir / f"session_{meta.session_id}.json"
                    if session_file.exists():
                        session_file.unlink()
                    del self._index[meta.session_id]
                    removed += 1

            if removed > 0:
                self._save_index()
                log.info(f"Cleanup removed {removed} sessions")

        return removed

    # ─── Stats ─────────────────────────────────────────────

    def stats(self) -> dict:
        """Get conversation store statistics."""
        with self._lock:
            sessions = list(self._index.values())

        total_messages = sum(s.message_count for s in sessions)
        unique_users = len({s.user_id for s in sessions if s.user_id})

        return {
            "total_sessions": len(sessions),
            "total_messages": total_messages,
            "unique_users": unique_users,
            "data_dir": str(self.data_dir),
            "max_sessions": self.max_sessions,
        }