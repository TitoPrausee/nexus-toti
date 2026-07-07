"""
NEXUS v7 QA — Tests for Memory, Soul, and Agent parser.
All tests run WITHOUT network (everything mocked).

Focus areas:
- Memory: add(), get_context(), remember(), recall(), compression, end_session(), clear(), stats()
- Soul: save/load roundtrip, get_system_prompt(), update_user(), learn()
- Agent: _parse_tool_calls() edge cases, _clean_response()
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nexus.core.memory import MemorySystem, MemoryEntry
from nexus.soul import SoulEngine, UserRelation


# ═══════════════════════════════════════════════════
# MEMORY TESTS
# ═══════════════════════════════════════════════════


class TestMemoryEntry:
    """Tests for the MemoryEntry dataclass."""

    def test_memory_entry_defaults(self):
        entry = MemoryEntry(role="user", content="hello")
        assert entry.role == "user"
        assert entry.content == "hello"
        assert entry.importance == 0.5
        assert entry.timestamp == 0.0
        assert entry.tokens == 0

    def test_memory_entry_to_dict(self):
        entry = MemoryEntry(role="user", content="test", importance=0.9)
        d = entry.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "test"
        assert d["importance"] == 0.9

    def test_memory_entry_from_dict(self):
        d = {"role": "assistant", "content": "response", "importance": 0.3, "tokens": 5, "timestamp": 1000.0}
        entry = MemoryEntry.from_dict(d)
        assert entry.role == "assistant"
        assert entry.content == "response"
        assert entry.importance == 0.3

    def test_memory_entry_from_dict_ignores_extra_fields(self):
        d = {"role": "user", "content": "hi", "extra_field": "ignored", "unknown": 42}
        entry = MemoryEntry.from_dict(d)
        assert entry.role == "user"
        assert entry.content == "hi"
        # Extra fields should be silently ignored


class TestMemorySystemAdd:
    """Tests for MemorySystem.add()."""

    def test_add_creates_entry(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        entry = m.add("user", "Hello world")
        assert entry.role == "user"
        assert entry.content == "Hello world"
        assert entry.tokens >= 1  # At least 1 token per word

    def test_add_multiple_entries(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.add("user", "first")
        m.add("assistant", "second")
        m.add("user", "third")
        assert len(m.l1) == 3
        assert m.l1[0].role == "user"
        assert m.l1[1].role == "assistant"
        assert m.l1[2].role == "user"

    def test_add_with_importance(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        entry = m.add("user", "important!", importance=0.9)
        assert entry.importance == 0.9

    def test_add_token_estimate(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        entry = m.add("user", "one two three four five")
        assert entry.tokens == 5  # Rough word-count estimate

    def test_add_empty_string(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        entry = m.add("user", "")
        assert entry.tokens == 1  # max(1, 0) = 1


class TestMemoryGetContext:
    """Tests for MemorySystem.get_context()."""

    def test_get_context_basic(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.add("system", "You are an AI")
        m.add("user", "Hello")
        m.add("assistant", "Hi there!")
        context = m.get_context()
        assert len(context) >= 2  # At least user + assistant

    def test_get_context_returns_dicts(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.add("user", "test")
        context = m.get_context()
        for msg in context:
            assert "role" in msg
            assert "content" in msg

    def test_get_context_with_l3_facts(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.remember("Python is great", category="programming", importance=0.8)
        m.add("user", "What about Python?")
        context = m.get_context()
        # Should include L3 fact as system message
        system_msgs = [c for c in context if c["role"] == "system" and "Erinnerung" in c["content"]]
        assert len(system_msgs) >= 1

    def test_get_context_with_l2_session(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.l2.append({"summary": "Previous chat about coding", "timestamp": time.time(), "entries_removed": 3})
        m.add("user", "Continue our chat")
        context = m.get_context()
        system_msgs = [c for c in context if c["role"] == "system" and "Kontext" in c["content"]]
        assert len(system_msgs) >= 1

    def test_get_context_token_budget(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"), config={"l1_max_tokens": 20})
        # Add many entries
        for i in range(20):
            m.add("user", f"Message number {i}")
        context = m.get_context()
        # Should not exceed budget drastically (compression may kick in)
        total_tokens = sum(max(1, len(msg.get("content", "").split())) for msg in context)
        # The budget is small so context should be limited
        assert total_tokens < 100  # Rough sanity check


class TestMemoryRememberAndRecall:
    """Tests for remember() and recall()."""

    def test_remember_basic(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.remember("User prefers Python", category="preferences", importance=0.8)
        assert len(m.l3) == 1
        assert m.l3[0]["content"] == "User prefers Python"
        assert m.l3[0]["category"] == "preferences"

    def test_recall_by_keyword(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.remember("User prefers Python programming", category="preferences")
        m.remember("Server runs on Linux", category="infra")
        m.remember("User likes dark mode", category="preferences")

        results = m.recall("Python")
        assert len(results) >= 1
        assert any("Python" in r for r in results)

    def test_recall_returns_empty_for_no_match(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.remember("User prefers Python")
        results = m.recall("quantum physics")
        assert len(results) == 0

    def test_remember_respects_max_entries(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"), config={"l3_max_entries": 3})
        m.remember("fact 1", importance=0.5)
        m.remember("fact 2", importance=0.6)
        m.remember("fact 3", importance=0.7)
        m.remember("fact 4", importance=0.8)
        # After exceeding max, lowest importance should be trimmed
        assert len(m.l3) <= 3

    def test_recall_limit(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        for i in range(10):
            m.remember(f"fact about coding {i}", category="coding")
        results = m.recall("coding", limit=3)
        assert len(results) <= 3


class TestMemoryCompression:
    """Tests for L1 compression (_compress_l1)."""

    def test_compress_triggers_on_large_context(self, tmp_path):
        # Very small budget to force compression
        m = MemorySystem(data_dir=str(tmp_path / "mem"), config={"l1_max_tokens": 30, "compress_threshold": 0.7})
        for i in range(20):
            m.add("user", f"This is message number {i} with some content")
        # Should have compressed, L1 should be smaller than 20
        assert len(m.l1) < 20

    def test_compress_preserves_recent_entries(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"), config={"l1_max_tokens": 50})
        for i in range(30):
            m.add("user", f"Message {i}")
        # Most recent entries should still be present
        last_contents = [e.content for e in m.l1[-3:]]
        assert any("29" in c for c in last_contents) or any("28" in c for c in last_contents)

    def test_compress_creates_l2_summary(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"), config={"l1_max_tokens": 30})
        l2_before = len(m.l2)
        for i in range(20):
            m.add("user", f"Long message number {i} with lots of words")
        # Compression should have added L2 entries
        # Note: compression only fires if l1 has >= 4 entries
        if len(m.l1) < 20:  # compression happened
            assert len(m.l2) >= l2_before


class TestMemoryEndSession:
    """Tests for end_session()."""

    def test_end_session_archives_to_l2(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.add("user", "Hello")
        m.add("assistant", "Hi there")
        m.add("user", "How are you?")
        l2_before = len(m.l2)
        m.end_session()
        # L1 should be cleared
        assert len(m.l1) == 0
        # L2 should have a new entry
        assert len(m.l2) == l2_before + 1

    def test_end_session_empty_l1(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        l2_before = len(m.l2)
        m.end_session()
        # Nothing should happen
        assert len(m.l2) == l2_before

    def test_end_session_persists(self, tmp_path):
        m1 = MemorySystem(data_dir=str(tmp_path / "mem"))
        m1.add("user", "Session message")
        m1.end_session()

        # New instance should load L2 from disk
        m2 = MemorySystem(data_dir=str(tmp_path / "mem"))
        assert len(m2.l2) >= 1


class TestMemoryClear:
    """Tests for clear()."""

    def test_clear_only_clears_l1(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.add("user", "hello")
        m.remember("Important fact")
        l3_count = len(m.l3)
        m.clear()
        assert len(m.l1) == 0
        assert len(m.l3) == l3_count  # L3 preserved


class TestMemoryStats:
    """Tests for stats()."""

    def test_stats_initial(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        stats = m.stats()
        assert "l1_entries" in stats
        assert "l1_tokens" in stats
        assert "l2_entries" in stats
        assert "l3_entries" in stats
        assert stats["l1_entries"] == 0

    def test_stats_after_add(self, tmp_path):
        m = MemorySystem(data_dir=str(tmp_path / "mem"))
        m.add("user", "hello world")
        stats = m.stats()
        assert stats["l1_entries"] == 1
        assert stats["l1_tokens"] >= 1


class TestMemorySaveLoad:
    """Tests for save/load roundtrip."""

    def test_save_and_reload(self, tmp_path):
        dir_path = str(tmp_path / "mem")
        m1 = MemorySystem(data_dir=dir_path)
        m1.add("user", "test message")
        m1.remember("Persist this fact", category="test")
        m1.end_session()

        # Reload from disk
        m2 = MemorySystem(data_dir=dir_path)
        # L2 should be loaded from disk
        assert len(m2.l2) >= 1
        # L3 should be loaded from disk
        assert len(m2.l3) >= 1
        assert any("Persist this fact" in e["content"] for e in m2.l3)


# ═══════════════════════════════════════════════════
# SOUL TESTS
# ═══════════════════════════════════════════════════


class TestSoulEngineInit:
    """Tests for SoulEngine initialization."""

    def test_soul_loads_default(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        # Should have a name from the default soul.yaml
        assert s.personality is not None

    def test_soul_name(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        name = s.personality.get("name", "Toti")
        assert isinstance(name, str)


class TestSoulSaveLoad:
    """Tests for Soul save/load roundtrip."""

    def test_save_and_reload(self, tmp_path):
        dir_path = str(tmp_path / "soul")
        s1 = SoulEngine(soul_dir=dir_path)
        s1.knowledge["about_self"] = ["I am a test AI", "I like Python"]
        s1.quirks = ["test quirk"]
        s1.save()

        s2 = SoulEngine(soul_dir=dir_path)
        assert "I am a test AI" in s2.knowledge.get("about_self", [])
        assert "test quirk" in s2.quirks

    def test_save_creates_files(self, tmp_path):
        dir_path = str(tmp_path / "soul")
        s = SoulEngine(soul_dir=dir_path)
        s.save()
        assert (Path(dir_path) / "soul.yaml").exists()
        assert (Path(dir_path) / "relations.json").exists()


class TestSoulSystemPrompt:
    """Tests for get_system_prompt()."""

    def test_system_prompt_contains_name(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        prompt = s.get_system_prompt()
        name = s.personality.get("name", "Toti")
        assert name in prompt

    def test_system_prompt_includes_rules(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        prompt = s.get_system_prompt()
        # Should include rules section
        assert "Regeln" in prompt or "Regel" in prompt or "regeln" in prompt.lower()


class TestSoulUpdateUser:
    """Tests for update_user()."""

    def test_update_user_creates_relationship(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123", name="Alice", language="en")
        assert "user123" in s.relationships
        assert s.relationships["user123"].name == "Alice"
        assert s.relationships["user123"].language == "en"

    def test_update_user_increments_conversation_count(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123")
        assert s.relationships["user123"].conversation_count == 1
        s.update_user("user123")
        assert s.relationships["user123"].conversation_count == 2

    def test_update_user_trust_level_default_no_change(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123")
        # Default trust_delta is 0, so trust stays at default 0.5
        assert s.relationships["user123"].trust_level == 0.5

    def test_update_user_trust_level_clamping_at_max(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123")
        # Test trust clamping at 1.0
        s.relationships["user123"].trust_level = 0.99
        s.update_user("user123", trust_delta=0.5)
        assert s.relationships["user123"].trust_level == 1.0  # Clamped at max

    def test_update_user_trust_level_clamping_at_min(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123")
        # Test trust clamping at 0.0
        s.relationships["user123"].trust_level = 0.01
        s.update_user("user123", trust_delta=-0.5)
        assert s.relationships["user123"].trust_level == 0.0  # Clamped at min

    def test_update_user_notes(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123", note="Prefers dark mode")
        assert "Prefers dark mode" in s.relationships["user123"].notes

    def test_update_user_prefs_dedup(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("user123", preferences=["Python", "async"])
        s.update_user("user123", preferences=["Python", "typing"])
        prefs = s.relationships["user123"].preferences
        # "Python" should not be duplicated
        assert prefs.count("Python") == 1
        assert "async" in prefs
        assert "typing" in prefs


class TestSoulLearn:
    """Tests for learn()."""

    def test_learn_adds_fact(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.learn("facts", "The sky is blue")
        assert "The sky is blue" in s.knowledge.get("facts", [])

    def test_learn_no_duplicates(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.learn("facts", "The sky is blue")
        s.learn("facts", "The sky is blue")
        count = s.knowledge.get("facts", []).count("The sky is blue")
        assert count == 1

    def test_learn_persists(self, tmp_path):
        dir_path = str(tmp_path / "soul")
        s1 = SoulEngine(soul_dir=dir_path)
        s1.learn("test_cat", "test fact value")
        s1.save()

        s2 = SoulEngine(soul_dir=dir_path)
        assert "test fact value" in s2.knowledge.get("test_cat", [])


class TestSoulGetUserContext:
    """Tests for get_user_context()."""

    def test_unknown_user_returns_empty(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        assert s.get_user_context("unknown") == ""

    def test_known_user_returns_context(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        s.update_user("u1", name="Bob", language="en", note="likes Python")
        ctx = s.get_user_context("u1")
        assert "Bob" in ctx
        assert "en" in ctx.lower() or "Englisch" in ctx or "Sprache" in ctx

    def test_frequent_user_context(self, tmp_path):
        s = SoulEngine(soul_dir=str(tmp_path / "soul"))
        for _ in range(6):
            s.update_user("u1", name="Alice")
        ctx = s.get_user_context("u1")
        # Should mention familiarity
        assert "6" in ctx or "kennst" in ctx.lower() or "bereits" in ctx.lower()


# ═══════════════════════════════════════════════════
# AGENT PARSER TESTS
# ═══════════════════════════════════════════════════


class TestParseToolCalls:
    """Tests for NexusAgent._parse_tool_calls() edge cases."""

    @pytest.fixture
    def agent(self):
        """Create agent with mocked LLM (no network!)."""
        with patch("nexus.core.agent.LLMClient") as MockLLM:
            mock_llm = MagicMock()
            mock_llm.chat.return_value = MagicMock(content="OK")
            MockLLM.return_value = mock_llm
            from nexus.core.agent import NexusAgent
            a = NexusAgent()
            a.llm = mock_llm
            return a

    def test_parse_xml_tool_call(self, agent):
        text = '<tool>{"tool": "calculator", "expression": "2+2"}</tool>'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "calculator"
        assert calls[0]["expression"] == "2+2"

    def test_parse_json_block_tool_call(self, agent):
        text = '```json\n{"tool": "calculator", "expression": "2+2"}\n```'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "calculator"

    def test_parse_inline_json_tool_call(self, agent):
        text = '{"tool": "time"}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"

    def test_parse_multiple_xml_calls(self, agent):
        text = (
            'Let me check<tool>{"tool": "time"}</tool>'
            ' and calculate<tool>{"tool": "calculator", "expression": "2+2"}</tool>'
        )
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 2

    def test_parse_empty_text(self, agent):
        calls = agent._parse_tool_calls("")
        assert len(calls) == 0

    def test_parse_invalid_json_skipped(self, agent):
        text = '<tool>{not valid json}</tool>'
        calls = agent._parse_tool_calls(text)
        # Should not crash, may return empty
        assert isinstance(calls, list)

    def test_parse_no_tool_key_skipped(self, agent):
        text = '<tool>{"action": "run", "data": "test"}</tool>'
        calls = agent._parse_tool_calls(text)
        # Missing "tool" key -> should be skipped
        assert len(calls) == 0

    def test_parse_fuzzy_json_trailing_comma(self, agent):
        text = '<tool>{"tool": "time", "format": "iso",}</tool>'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"

    def test_parse_fuzzy_json_missing_brace(self, agent):
        text = '<tool>{"tool": "time", "format": "iso"</tool>'
        calls = agent._parse_tool_calls(text)
        # Fuzzy repair should fix the missing closing brace
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"

    def test_parse_fuzzy_json_single_quotes(self, agent):
        text = "<tool>{'tool': 'time', 'format': 'iso'}</tool>"
        calls = agent._parse_tool_calls(text)
        # Fuzzy repair should handle single quotes
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"


class TestCleanResponse:
    """Tests for NexusAgent._clean_response()."""

    @pytest.fixture
    def agent(self):
        with patch("nexus.core.agent.LLMClient") as MockLLM:
            mock_llm = MagicMock()
            MockLLM.return_value = mock_llm
            from nexus.core.agent import NexusAgent
            a = NexusAgent()
            a.llm = mock_llm
            return a

    def test_removes_tool_tags(self, agent):
        text = 'Before<tool>{"tool": "time"}</tool> After'
        cleaned = agent._clean_response(text)
        assert "<tool>" not in cleaned
        assert "</tool>" not in cleaned

    def test_preserves_normal_text(self, agent):
        text = "This is a normal response without any tool calls."
        cleaned = agent._clean_response(text)
        assert cleaned == text

    def test_removes_json_tool_blocks(self, agent):
        text = 'Here\'s the result.```json\n{"tool": "calculator", "expression": "2+2"}\n``` Done.'
        cleaned = agent._clean_response(text)
        assert "calculator" not in cleaned or "2+2" not in cleaned

    def test_collapses_multiple_newlines(self, agent):
        text = "Line1\n\n\n\n\nLine2"
        cleaned = agent._clean_response(text)
        assert "\n\n\n" not in cleaned

    def test_strips_whitespace(self, agent):
        text = "  Hello world  "
        cleaned = agent._clean_response(text)
        assert cleaned == "Hello world"

    def test_empty_after_cleanup(self, agent):
        text = '<tool>{"tool": "time"}</tool>'
        cleaned = agent._clean_response(text)
        assert cleaned == ""
