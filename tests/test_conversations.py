"""
Unit tests for ConversationStore — save/load/list/delete/cleanup.

Run: python3 -m pytest tests/test_conversations.py -v
"""

import json
import os
import time
import tempfile
import pytest

from nexus.core.conversations import ConversationStore, SessionMetadata


@pytest.fixture
def store(tmp_path):
    """Create a fresh ConversationStore in a temp directory."""
    return ConversationStore(data_dir=str(tmp_path / "sessions"), max_sessions=20)


class TestConversationStore:
    """Tests for ConversationStore CRUD and cleanup."""

    def test_initial_state(self, store):
        """New store should have empty stats."""
        stats = store.stats()
        assert stats["total_sessions"] == 0
        assert stats["total_messages"] == 0

    def test_save_and_load_session(self, store):
        """Save a session and load it back."""
        entries = [
            {"role": "user", "content": "Hallo!", "timestamp": time.time(), "tokens": 2, "importance": 0.5},
            {"role": "assistant", "content": "Hallo! Wie kann ich helfen?", "timestamp": time.time(), "tokens": 8, "importance": 0.5},
        ]

        result = store.save_session("sess_1", entries, user_id="user_1", summary="Begrüßung")
        assert result is True

        loaded = store.load_session("sess_1")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[0]["content"] == "Hallo!"
        assert loaded[1]["content"] == "Hallo! Wie kann ich helfen?"

    def test_load_nonexistent_session(self, store):
        """Loading a nonexistent session should return None."""
        result = store.load_session("does_not_exist")
        assert result is None

    def test_list_sessions_empty(self, store):
        """Listing sessions on empty store returns empty list."""
        sessions = store.list_sessions()
        assert sessions == []

    def test_list_sessions(self, store):
        """List sessions returns sorted metadata."""
        entries_base = [{"role": "user", "content": "test", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]

        store.save_session("sess_a", entries_base, user_id="alice", summary="Talk A")
        time.sleep(0.01)
        store.save_session("sess_b", entries_base * 3, user_id="bob", summary="Talk B")
        time.sleep(0.01)
        store.save_session("sess_c", entries_base, user_id="alice", summary="Talk C")

        # All sessions
        sessions = store.list_sessions()
        assert len(sessions) == 3
        # Sorted by last_active desc (most recent first)
        assert sessions[0]["session_id"] == "sess_c"

        # Filter by user
        alice_sessions = store.list_sessions(user_id="alice")
        assert len(alice_sessions) == 2
        assert all(s["user_id"] == "alice" for s in alice_sessions)

        bob_sessions = store.list_sessions(user_id="bob")
        assert len(bob_sessions) == 1
        assert bob_sessions[0]["session_id"] == "sess_b"

    def test_list_sessions_limit(self, store):
        """Limit parameter works."""
        entries = [{"role": "user", "content": "hi", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]
        for i in range(5):
            store.save_session(f"sess_{i}", entries)
            time.sleep(0.01)

        sessions = store.list_sessions(limit=3)
        assert len(sessions) == 3

    def test_delete_session(self, store):
        """Delete a session removes it from index and disk."""
        entries = [{"role": "user", "content": "bye", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]
        store.save_session("del_me", entries, user_id="user_1")

        # Confirm it exists
        loaded = store.load_session("del_me")
        assert loaded is not None

        # Delete it
        result = store.delete_session("del_me")
        assert result is True

        # Confirm it no longer exists
        loaded = store.load_session("del_me")
        assert loaded is None

        # Confirm removed from index
        sessions = store.list_sessions()
        assert len(sessions) == 0

    def test_delete_nonexistent_session(self, store):
        """Deleting nonexistent session still succeeds (idempotent)."""
        result = store.delete_session("ghost_session")
        assert result is True

    def test_get_session_metadata(self, store):
        """Get metadata without loading full entries."""
        entries = [{"role": "user", "content": "meta test", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]
        store.save_session("meta_test", entries, user_id="tester", summary="Test summary")

        meta = store.get_session_metadata("meta_test")
        assert meta is not None
        assert meta["session_id"] == "meta_test"
        assert meta["user_id"] == "tester"
        assert meta["message_count"] == 1
        assert "Test summary" in meta["summary"]

    def test_get_session_metadata_nonexistent(self, store):
        """Metadata for nonexistent session returns None."""
        meta = store.get_session_metadata("nonexistent")
        assert meta is None

    def test_save_overwrites_existing(self, store):
        """Saving same session_id twice overwrites."""
        entries1 = [{"role": "user", "content": "first", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]
        entries2 = [{"role": "user", "content": "second", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]

        store.save_session("overwrite_test", entries1, user_id="u1", summary="First")
        store.save_session("overwrite_test", entries2, user_id="u1", summary="Second")

        loaded = store.load_session("overwrite_test")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["content"] == "second"

        meta = store.get_session_metadata("overwrite_test")
        assert "Second" in meta["summary"]

    def test_cleanup_removes_old_sessions(self, store):
        """Cleanup removes sessions older than max_age_days."""
        entries = [{"role": "user", "content": "old", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]
        store.save_session("old_session", entries, user_id="old_user")

        # Manually backdate the session metadata
        store._index["old_session"].last_active = time.time() - (31 * 86400)  # 31 days ago
        store._index["old_session"].created_at = time.time() - (31 * 86400)
        store._save_index()

        # Also backdate the file on disk
        import json as _json
        session_file = store.data_dir / "session_old_session.json"
        if session_file.exists():
            data = _json.loads(session_file.read_text())
            data["metadata"]["last_active"] = time.time() - (31 * 86400)
            data["metadata"]["created_at"] = time.time() - (31 * 86400)
            session_file.write_text(_json.dumps(data, ensure_ascii=False))

        removed = store.cleanup(max_age_days=30)
        assert removed >= 1

        # Confirm session is gone
        assert store.load_session("old_session") is None
        assert len(store.list_sessions()) == 0

    def test_cleanup_enforces_max_sessions(self, store):
        """Cleanup removes oldest sessions when count exceeds max."""
        entries = [{"role": "user", "content": "hi", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]

        # Store has max_sessions=20, create 5 with lower limit
        for i in range(5):
            store.save_session(f"sess_{i}", entries)
            time.sleep(0.01)

        # Cleanup with max_sessions=3 should remove 2 oldest
        removed = store.cleanup(max_age_days=999, max_sessions=3)
        assert removed == 2

        sessions = store.list_sessions()
        assert len(sessions) == 3
        # Should keep the 3 most recent
        session_ids = {s["session_id"] for s in sessions}
        assert "sess_4" in session_ids
        assert "sess_3" in session_ids
        assert "sess_2" in session_ids

    def test_stats(self, store):
        """Stats reflect stored sessions."""
        entries = [{"role": "user", "content": "hello", "timestamp": time.time(), "tokens": 1, "importance": 0.5}]

        store.save_session("stats_1", entries, user_id="alice")
        store.save_session("stats_2", entries, user_id="bob")

        stats = store.stats()
        assert stats["total_sessions"] == 2
        assert stats["total_messages"] == 2  # 1 entry each
        assert stats["unique_users"] == 2
        assert str(store.data_dir) in stats["data_dir"]

    def test_rebuild_index_on_corrupt(self, tmp_path):
        """Store rebuilds index if the index file is corrupt."""
        store = ConversationStore(data_dir=str(tmp_path / "sessions2"))

        # Create a session file directly
        session_data = {
            "metadata": {
                "session_id": "manual_sess",
                "user_id": "manual_user",
                "created_at": time.time(),
                "last_active": time.time(),
                "message_count": 2,
                "summary": "Manually created",
            },
            "entries": [
                {"role": "user", "content": "manual test", "timestamp": time.time(), "tokens": 2, "importance": 0.5}
            ]
        }
        session_file = store.data_dir / "session_manual_sess.json"
        session_file.write_text(json.dumps(session_data))

        # Corrupt the index
        index_file = store.data_dir / "index.json"
        index_file.write_text("NOT VALID JSON {{{")

        # Re-initialize store — should rebuild from files
        store2 = ConversationStore(data_dir=str(tmp_path / "sessions2"))
        meta = store2.get_session_metadata("manual_sess")
        assert meta is not None
        assert meta["user_id"] == "manual_user"

    def test_unicode_content(self, store):
        """Sessions handle Unicode content correctly (German Umlauts etc.)."""
        entries = [
            {"role": "user", "content": "Wie geht's? Grüße aus München! 🎉", "timestamp": time.time(), "tokens": 6, "importance": 0.7},
            {"role": "assistant", "content": "Mir geht es gut! Ä Ö Ü ß", "timestamp": time.time(), "tokens": 8, "importance": 0.5},
        ]
        store.save_session("unicode_test", entries, summary="Umlaut-Test")

        loaded = store.load_session("unicode_test")
        assert loaded is not None
        assert "Grüße" in loaded[0]["content"]
        assert "Ä Ö Ü" in loaded[1]["content"]

    def test_empty_entries_save_and_load(self, store):
        """Saving and loading empty session works."""
        result = store.save_session("empty_sess", [], user_id="empty_user")
        assert result is True

        loaded = store.load_session("empty_sess")
        assert loaded is not None
        assert len(loaded) == 0

    def test_large_session(self, store):
        """Handles sessions with many entries."""
        entries = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"Message {i} with some content for testing",
             "timestamp": time.time(),
             "tokens": 10,
             "importance": 0.5}
            for i in range(100)
        ]
        result = store.save_session("large_sess", entries, user_id="heavy_user", summary="Large session test")
        assert result is True

        loaded = store.load_session("large_sess")
        assert len(loaded) == 100


class TestSessionMetadata:
    """Tests for SessionMetadata dataclass."""

    def test_to_dict(self):
        meta = SessionMetadata(
            session_id="test_1",
            user_id="alice",
            created_at=1000.0,
            last_active=2000.0,
            message_count=5,
            summary="Test summary",
        )
        d = meta.to_dict()
        assert d["session_id"] == "test_1"
        assert d["message_count"] == 5

    def test_from_dict(self):
        d = {
            "session_id": "test_2",
            "user_id": "bob",
            "created_at": 3000.0,
            "last_active": 4000.0,
            "message_count": 10,
            "summary": "Another test",
        }
        meta = SessionMetadata.from_dict(d)
        assert meta.session_id == "test_2"
        assert meta.message_count == 10

    def test_from_dict_ignores_extra_keys(self):
        d = {
            "session_id": "test_3",
            "extra_key": "should be ignored",
        }
        meta = SessionMetadata.from_dict(d)
        assert meta.session_id == "test_3"