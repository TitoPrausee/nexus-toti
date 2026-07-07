"""
Unit tests for SessionManager — per-chat session isolation, timeout cleanup, and stats.

Run: python3 -m pytest tests/test_session_manager.py -v
"""

import time
import pytest
import threading

from nexus.core.session_manager import SessionManager, ChatSession


@pytest.fixture
def minimal_config(tmp_path):
    """Minimal config that NexusAgent can initialize with (no real LLM needed)."""
    return {
        "llm": {
            "base_url": "http://localhost:11434",
            "mode": "cloud",
            "default_model": "test-model",
            "default_temperature": 0.7,
            "default_max_tokens": 256,
            "max_retries": 0,
            "timeout": 5,
        },
        "memory": {
            "l1_max_tokens": 2000,
            "l2_max_entries": 10,
            "l3_max_entries": 50,
            "vector_search": {"enabled": False},
        },
        "conversations": {
            "data_dir": str(tmp_path / "sessions"),
            "max_sessions": 10,
        },
        "soul": {
            "enabled": True,
            "file": str(tmp_path / "soul" / "soul.yaml"),
        },
        "session_manager": {
            "timeout_seconds": 600,  # 10 minutes for tests
            "max_sessions": 5,
            "cleanup_interval": 60,
            "auto_save_on_cleanup": True,
        },
        "performance": {
            "max_tool_calls_per_turn": 5,
            "max_tokens_per_turn": 2000,
        },
        "tools": {"enabled": []},
    }


@pytest.fixture
def manager(minimal_config):
    """Create a fresh SessionManager with minimal config."""
    return SessionManager(minimal_config)


class TestSessionManagerInit:
    """Tests for SessionManager initialization."""

    def test_initial_state(self, manager):
        """New manager should have zero sessions."""
        stats = manager.stats()
        assert stats["active_sessions"] == 0
        assert stats["total_created"] == 0
        assert stats["total_cleaned"] == 0

    def test_config_defaults(self):
        """Default config values should be applied when not specified."""
        mgr = SessionManager({})
        assert mgr.session_timeout == 3600  # 1 hour default
        assert mgr.max_sessions == 50
        assert mgr.cleanup_interval == 300

    def test_custom_config(self, minimal_config):
        """Custom config values should override defaults."""
        mgr = SessionManager(minimal_config)
        assert mgr.session_timeout == 600
        assert mgr.max_sessions == 5


class TestSessionCreation:
    """Tests for session creation and retrieval."""

    def test_create_session(self, manager):
        """Creating a session should return a ChatSession with an agent."""
        session = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        assert session is not None
        assert session.chat_id == "chat_1"
        assert session.user_id == "user_1"
        assert session.agent is not None
        assert session.message_count == 1  # touch() called on creation

    def test_create_multiple_sessions(self, manager):
        """Multiple chat IDs should get separate sessions."""
        s1 = manager.get_or_create(chat_id="chat_A", user_id="user_1")
        s2 = manager.get_or_create(chat_id="chat_B", user_id="user_2")

        assert s1.chat_id != s2.chat_id
        assert s1.agent is not s2.agent  # Different agent instances
        assert manager.stats()["active_sessions"] == 2

    def test_get_existing_session(self, manager):
        """Getting the same chat_id should return the existing session."""
        s1 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        s2 = manager.get_or_create(chat_id="chat_1", user_id="user_1")

        assert s1 is s2  # Same object — no new session created
        assert manager.stats()["active_sessions"] == 1

    def test_session_touch_updates_activity(self, manager):
        """Each get_or_create should update last_active."""
        s1 = manager.get_or_create(chat_id="chat_1")
        first_active = s1.last_active

        time.sleep(0.01)  # Small delay to ensure different timestamp
        s2 = manager.get_or_create(chat_id="chat_1")

        # Same session object, but last_active was updated
        assert s2.last_active >= first_active

    def test_update_user_id_on_existing_session(self, manager):
        """If user_id changes for the same chat, it should be updated."""
        s1 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        assert s1.user_id == "user_1"

        s2 = manager.get_or_create(chat_id="chat_1", user_id="user_2")
        assert s2.user_id == "user_2"  # Updated


class TestSessionIsolation:
    """Tests verifying L1 memory isolation between sessions."""

    def test_l1_memory_isolation(self, manager):
        """Each session should have its own L1 working memory."""
        s1 = manager.get_or_create(chat_id="chat_A", user_id="user_1")
        s2 = manager.get_or_create(chat_id="chat_B", user_id="user_2")

        # Add different messages to each session
        s1.agent.memory.add("user", "Hello from chat A", importance=0.5)
        s2.agent.memory.add("user", "Hello from chat B", importance=0.5)

        # Verify isolation: each L1 should only contain its own messages
        l1_a = [e.content for e in s1.agent.memory.l1]
        l1_b = [e.content for e in s2.agent.memory.l1]

        assert "Hello from chat A" in l1_a
        assert "Hello from chat A" not in l1_b
        assert "Hello from chat B" in l1_b
        assert "Hello from chat B" not in l1_a

    def test_l3_memory_sharing(self, manager):
        """L3 long-term memory should be shared across sessions."""
        s1 = manager.get_or_create(chat_id="chat_A", user_id="user_1")
        s2 = manager.get_or_create(chat_id="chat_B", user_id="user_2")

        # Remember something in session A
        s1.agent.memory.remember("Python ist toll", category="preferences", importance=0.9)

        # Session B should see it via shared L3
        # Note: L3 is shared through the reference, so both point to the same list
        assert len(s2.agent.memory.l3) > 0

    def test_soul_sharing(self, manager):
        """Soul system should be shared across all sessions."""
        s1 = manager.get_or_create(chat_id="chat_A", user_id="user_1")
        s2 = manager.get_or_create(chat_id="chat_B", user_id="user_2")

        # Both should reference the same soul instance
        assert s1.agent.soul is s2.agent.soul


class TestSessionTimeout:
    """Tests for timeout-based session cleanup."""

    def test_timeout_creates_new_session(self, manager):
        """A timed-out session should be replaced by a new one."""
        s1 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        assert manager.stats()["active_sessions"] == 1

        # Simulate timeout by setting last_active far in the past
        s1.last_active = time.time() - manager.session_timeout - 100

        # Getting the same chat_id should create a new session
        s2 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        assert s2 is not s1  # New session object
        assert manager.stats()["active_sessions"] == 1  # Still 1 (old one cleaned up)

    def test_cleanup_idle_removes_timed_out(self, manager):
        """cleanup_idle() should remove all timed-out sessions."""
        s1 = manager.get_or_create(chat_id="chat_A")
        s2 = manager.get_or_create(chat_id="chat_B")
        s3 = manager.get_or_create(chat_id="chat_C")

        # Make sessions A and B timed out, but C is still active
        s1.last_active = time.time() - manager.session_timeout - 100
        s2.last_active = time.time() - manager.session_timeout - 50
        # s3 is still active

        removed = manager.cleanup_idle()
        assert removed == 2
        assert manager.stats()["active_sessions"] == 1

    def test_cleanup_idle_nothing_to_remove(self, manager):
        """cleanup_idle() with all sessions active should remove nothing."""
        manager.get_or_create(chat_id="chat_A")
        manager.get_or_create(chat_id="chat_B")

        removed = manager.cleanup_idle()
        assert removed == 0
        assert manager.stats()["active_sessions"] == 2


class TestSessionRemoval:
    """Tests for manual session removal."""

    def test_remove_existing_session(self, manager):
        """Removing a session should clean it up."""
        manager.get_or_create(chat_id="chat_1")
        assert manager.stats()["active_sessions"] == 1

        result = manager.remove_session("chat_1")
        assert result is True
        assert manager.stats()["active_sessions"] == 0

    def test_remove_nonexistent_session(self, manager):
        """Removing a nonexistent session should return False."""
        result = manager.remove_session("nonexistent")
        assert result is False


class TestMaxSessions:
    """Tests for max_sessions limit enforcement."""

    def test_eviction_when_max_reached(self, minimal_config):
        """Creating more sessions than max_sessions should evict the most idle."""
        minimal_config["session_manager"]["max_sessions"] = 2
        mgr = SessionManager(minimal_config)

        s1 = mgr.get_or_create(chat_id="chat_A")
        time.sleep(0.01)
        s2 = mgr.get_or_create(chat_id="chat_B")
        time.sleep(0.01)

        # Both sessions active
        assert mgr.stats()["active_sessions"] == 2

        # Creating a 3rd should evict chat_A (most idle)
        s3 = mgr.get_or_create(chat_id="chat_C")
        assert mgr.stats()["active_sessions"] == 2

        # chat_A should have been evicted — getting it should create a new session
        s1_new = mgr.get_or_create(chat_id="chat_A")
        assert s1_new is not s1  # New instance


class TestGetSession:
    """Tests for get_session (non-creating lookup)."""

    def test_get_existing_active_session(self, manager):
        """get_session should return the session if it exists and is active."""
        s1 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        s2 = manager.get_session("chat_1")
        assert s2 is not None
        assert s2.chat_id == "chat_1"

    def test_get_nonexistent_session(self, manager):
        """get_session should return None if no session exists."""
        result = manager.get_session("nonexistent")
        assert result is None

    def test_get_timed_out_session(self, manager):
        """get_session should return None if session has timed out."""
        s1 = manager.get_or_create(chat_id="chat_1")
        s1.last_active = time.time() - manager.session_timeout - 100

        result = manager.get_session("chat_1")
        assert result is None


class TestSaveAll:
    """Tests for save_all (graceful shutdown)."""

    def test_save_all_persists_sessions(self, manager):
        """save_all should not crash even with active sessions."""
        manager.get_or_create(chat_id="chat_1")
        manager.get_or_create(chat_id="chat_2")

        # Should not raise
        manager.save_all()

        # Sessions should still be tracked
        assert manager.stats()["active_sessions"] == 2

    def test_save_all_empty_manager(self, manager):
        """save_all with no sessions should not crash."""
        manager.save_all()  # Should not raise


class TestStats:
    """Tests for statistics reporting."""

    def test_stats_with_active_sessions(self, manager):
        """Stats should reflect active sessions."""
        s1 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        stats = manager.stats()

        assert stats["active_sessions"] == 1
        assert stats["total_created"] == 1
        assert stats["total_cleaned"] == 0
        assert len(stats["sessions"]) == 1
        assert stats["sessions"][0]["chat_id"] == "chat_1"
        assert stats["sessions"][0]["user_id"] == "user_1"

    def test_stats_after_cleanup(self, manager):
        """Stats should reflect cleaned-up sessions."""
        s1 = manager.get_or_create(chat_id="chat_1")
        s1.last_active = time.time() - manager.session_timeout - 100

        manager.cleanup_idle()

        stats = manager.stats()
        assert stats["active_sessions"] == 0
        assert stats["total_cleaned"] == 1

    def test_stats_per_session_details(self, manager):
        """Per-session stats should include L1/L2 size, idle time, etc."""
        s1 = manager.get_or_create(chat_id="chat_1", user_id="user_1")
        s1.agent.memory.add("user", "Test message", importance=0.5)

        stats = manager.stats()
        session_info = stats["sessions"][0]

        assert "l1_entries" in session_info
        assert "l2_entries" in session_info
        assert "idle_seconds" in session_info
        assert "age_seconds" in session_info
        assert "messages" in session_info


class TestThreadSafety:
    """Tests for concurrent access thread safety."""

    def test_concurrent_session_creation(self, minimal_config):
        """Multiple threads creating sessions should not corrupt state."""
        # Increase max_sessions for this test to accommodate 10 sessions
        minimal_config["session_manager"]["max_sessions"] = 20
        mgr = SessionManager(minimal_config)

        results = []
        errors = []

        def create_session(chat_id):
            try:
                session = mgr.get_or_create(chat_id=chat_id, user_id=f"user_{chat_id}")
                results.append(session.chat_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=create_session, args=(f"chat_{i}",))
            for i in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors during concurrent creation: {errors}"
        assert len(results) == 10
        assert mgr.stats()["active_sessions"] == 10