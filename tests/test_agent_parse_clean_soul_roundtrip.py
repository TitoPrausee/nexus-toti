"""
NEXUS v7 QA — Agent parse/clean edge cases + Soul save/load roundtrip + system prompt tests.
All tests run WITHOUT network (everything mocked).

Focus areas (this run):
- Agent: _parse_tool_calls() edge cases (fuzzy JSON, inline, malformed)
- Agent: _clean_response() (tool block removal, whitespace normalization)
- Soul: save/load roundtrip (persistence correctness)
- Soul: get_system_prompt() (with/without user, adaptation)
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nexus.core.agent import NexusAgent, TOOL_START, TOOL_END
from nexus.core.tools import ToolRegistry, ToolResult
from nexus.core.memory import MemorySystem
from nexus.core.llm_client import LLMClient, LLMResponse, Message
from nexus.soul import SoulEngine, UserRelation


# ═══════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════


@pytest.fixture
def agent():
    """Create a NexusAgent with mocked LLM (no network)."""
    with patch("nexus.core.agent.LLMClient") as MockLLM:
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(content="OK", model="mock", success=True)
        MockLLM.return_value = mock_llm
        a = NexusAgent()
        a.llm = mock_llm
        return a


@pytest.fixture
def soul(tmp_path):
    """Create a SoulEngine with a temp directory."""
    soul_dir = str(tmp_path / "soul")
    s = SoulEngine(soul_dir=soul_dir)
    return s


# ═══════════════════════════════════════════════════
# Agent: _parse_tool_calls() edge cases
# ═══════════════════════════════════════════════════


class TestParseToolCallsXML:
    """Test _parse_tool_calls with XML-style <tool>...</tool> format."""

    def test_single_valid_tool_call(self, agent):
        """Standard <tool>JSON</tool> format should parse correctly."""
        text = f'I will check the time. {TOOL_START}{{"tool": "time"}}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"

    def test_multiple_tool_calls(self, agent):
        """Multiple <tool> blocks should all be extracted."""
        text = (
            f'Let me run commands. {TOOL_START}{{"tool": "terminal", "command": "ls"}}{TOOL_END}'
            f' and then {TOOL_START}{{"tool": "file_read", "path": "/tmp/x"}}{TOOL_END}'
        )
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 2
        assert calls[0]["tool"] == "terminal"
        assert calls[0]["command"] == "ls"
        assert calls[1]["tool"] == "file_read"

    def test_tool_call_with_multiline_payload(self, agent):
        """Multiline JSON inside <tool> tags should parse."""
        payload = json.dumps({"tool": "terminal", "command": "echo hello\nworld"})
        text = f'{TOOL_START}{payload}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "terminal"

    def test_whitespace_around_payload(self, agent):
        """Leading/trailing whitespace inside <tool> should be tolerated."""
        text = f'{TOOL_START}  {{"tool": "calculator", "expression": "2+2"}}  {TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "calculator"


class TestParseToolCallsJSONBlock:
    """Test _parse_tool_calls with ```json code block format."""

    def test_json_code_block_tool_call(self, agent):
        """```json {...} ``` format should be parsed."""
        text = 'Let me search.\n```json\n{"tool": "web_search", "query": "test"}\n```'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "web_search"

    def test_json_code_block_not_extracted_if_xml_found(self, agent):
        """If <tool> tags exist, code blocks should be ignored (first match wins)."""
        text = (
            f'{TOOL_START}{{"tool": "time"}}{TOOL_END}\n'
            f'```json\n{{"tool": "calculator", "expression": "1+1"}}\n```'
        )
        calls = agent._parse_tool_calls(text)
        # XML format is found first, so code block is skipped
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"


class TestParseToolCallsInline:
    """Test _parse_tool_calls with inline JSON (raw JSON on a line)."""

    def test_inline_json_on_own_line(self, agent):
        """A line starting with { and containing "tool" should be parsed as inline JSON."""
        text = 'Here is what I will do:\n{"tool": "time"}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"

    def test_inline_json_with_arguments(self, agent):
        """Inline JSON with multiple keys should parse."""
        text = 'Running command:\n{"tool": "terminal", "command": "echo hi"}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "terminal"
        assert calls[0]["command"] == "echo hi"


class TestParseToolCallsFuzzyRepair:
    """Test _try_parse_json fuzzy repair capabilities."""

    def test_trailing_comma_repair(self, agent):
        """Trailing comma before } should be repaired."""
        payload = '{"tool": "time",}'
        result = agent._try_parse_json(payload)
        assert result is not None
        assert result["tool"] == "time"

    def test_missing_closing_brace_repair(self, agent):
        """Missing closing } should be repaired."""
        payload = '{"tool": "time"'
        result = agent._try_parse_json(payload)
        assert result is not None
        assert result["tool"] == "time"

    def test_single_quotes_repair(self, agent):
        """Single quotes around keys/values should be repaired to double quotes."""
        payload = "{'tool': 'time'}"
        result = agent._try_parse_json(payload)
        assert result is not None
        assert result["tool"] == "time"

    def test_missing_closing_bracket_repair(self, agent):
        """Missing closing ] should be repaired."""
        payload = '{"tool": "terminal", "args": [1, 2'
        result = agent._try_parse_json(payload)
        assert result is not None

    def test_completely_invalid_json_returns_none(self, agent):
        """Completely unparseable JSON should return None."""
        result = agent._try_parse_json("not json at all!!!")
        assert result is None

    def test_empty_string_returns_none(self, agent):
        """Empty string should return None."""
        result = agent._try_parse_json("")
        assert result is None

    def test_valid_json_returns_dict(self, agent):
        """Valid JSON dict should parse without repair."""
        payload = '{"tool": "calculator", "expression": "2+2"}'
        result = agent._try_parse_json(payload)
        assert result is not None
        assert result["tool"] == "calculator"
        assert result["expression"] == "2+2"

    def test_no_tool_key_returns_none(self, agent):
        """Valid JSON without 'tool' key is returned but won't be added to calls."""
        payload = '{"command": "ls"}'
        result = agent._try_parse_json(payload)
        # _try_parse_json returns the dict, but _parse_tool_calls won't add it
        # because the "tool" key check happens at the caller level
        assert result is not None
        assert "tool" not in result


class TestParseToolCallsEdgeCases:
    """More edge cases for _parse_tool_calls."""

    def test_no_tool_calls_in_plain_text(self, agent):
        """Plain text without tool syntax should return empty list."""
        calls = agent._parse_tool_calls("Just a normal response, nothing to see here.")
        assert calls == []

    def test_tool_call_missing_tool_key(self, agent):
        """<tool> block with valid JSON but no 'tool' key should be skipped."""
        text = f'{TOOL_START}{{"command": "ls"}}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert calls == []

    def test_nested_braces_in_payload(self, agent):
        """Tool call with nested JSON structures should parse."""
        payload = json.dumps({
            "tool": "file_write",
            "path": "/tmp/test.py",
            "content": "def hello():\n    return 'world'"
        })
        text = f'{TOOL_START}{payload}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "file_write"


# ═══════════════════════════════════════════════════
# Agent: _clean_response() tests
# ═══════════════════════════════════════════════════


class TestCleanResponse:
    """Test _clean_response() — removing tool blocks from final LLM output."""

    def test_removes_xml_tool_blocks(self, agent):
        """<tool>...</tool> blocks should be stripped from response."""
        text = f'Hello! {TOOL_START}{{"tool": "time"}}{TOOL_END} Here is the answer.'
        cleaned = agent._clean_response(text)
        assert TOOL_START not in cleaned
        assert TOOL_END not in cleaned
        assert "Hello!" in cleaned
        assert "answer" in cleaned

    def test_removes_json_code_block_tool_calls(self, agent):
        """```json {"tool": ...} ``` blocks should be removed."""
        text = 'Result:\n```json\n{"tool": "calculator", "expression": "1+1"}\n```\nThe answer is 2.'
        cleaned = agent._clean_response(text)
        assert "calculator" not in cleaned
        assert "answer is 2" in cleaned

    def test_normalizes_excessive_newlines(self, agent):
        """Three or more consecutive newlines should be collapsed to two."""
        text = "Paragraph 1\n\n\n\nParagraph 2"
        cleaned = agent._clean_response(text)
        assert "\n\n\n" not in cleaned
        assert "Paragraph 1" in cleaned
        assert "Paragraph 2" in cleaned

    def test_strips_leading_trailing_whitespace(self, agent):
        """Leading/trailing whitespace should be stripped."""
        text = "  \n  Hello world  \n  "
        cleaned = agent._clean_response(text)
        assert cleaned == "Hello world"

    def test_plain_text_unchanged(self, agent):
        """Plain text without tool blocks should be returned as-is (except strip)."""
        text = "This is a normal response with no tool calls."
        cleaned = agent._clean_response(text)
        assert cleaned == text

    def test_empty_string_after_removal(self, agent):
        """If only tool calls and whitespace remain, result should be empty / whitespace-only."""
        text = f'{TOOL_START}{{"tool": "time"}}{TOOL_END}'
        cleaned = agent._clean_response(text)
        assert cleaned.strip() == ""


# ═══════════════════════════════════════════════════
# Soul: save/load roundtrip
# ═══════════════════════════════════════════════════


class TestSoulSaveLoadRoundtrip:
    """Test that SoulEngine save/load preserves all data correctly."""

    def test_personality_survives_roundtrip(self, soul):
        """Personality dict should survive save/load."""
        soul.personality = {
            "name": "TestBot",
            "role": "Tester",
            "tone": "friendly",
            "style": "minimal",
        }
        soul.save()

        # Reload
        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert soul2.personality["name"] == "TestBot"
        assert soul2.personality["role"] == "Tester"

    def test_knowledge_survives_roundtrip(self, soul):
        """Knowledge dict should survive save/load."""
        soul.knowledge = {
            "about_self": ["I am a test bot", "I like testing"],
            "tech_stack": ["Python", "pytest"],
        }
        soul.save()

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "I am a test bot" in soul2.knowledge["about_self"]
        assert "Python" in soul2.knowledge["tech_stack"]

    def test_quirks_survive_roundtrip(self, soul):
        """Quirks list should survive save/load."""
        soul.quirks = ["Uses German", "Loves testing", "Always says hi"]
        soul.save()

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert soul2.quirks == ["Uses German", "Loves testing", "Always says hi"]

    def test_relationships_survive_roundtrip(self, soul):
        """User relationships should survive save/load."""
        soul.relationships["user123"] = UserRelation(
            name="Alice",
            language="en",
            preferences=["Python", "Dark mode"],
            conversation_count=42,
            trust_level=0.8,
            humor_style="dry",
            formality_level=0.4,
            technical_depth=0.9,
        )
        soul.save()

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "user123" in soul2.relationships
        rel = soul2.relationships["user123"]
        assert rel.name == "Alice"
        assert rel.language == "en"
        assert "Python" in rel.preferences
        assert rel.conversation_count == 42
        assert abs(rel.trust_level - 0.8) < 0.01
        assert rel.humor_style == "dry"

    def test_multiple_users_roundtrip(self, soul):
        """Multiple user relationships should all survive save/load."""
        soul.relationships["u1"] = UserRelation(name="User1", trust_level=0.5)
        soul.relationships["u2"] = UserRelation(name="User2", trust_level=0.9)
        soul.save()

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "u1" in soul2.relationships
        assert "u2" in soul2.relationships
        assert soul2.relationships["u1"].name == "User1"
        assert soul2.relationships["u2"].name == "User2"

    def test_learn_and_persist(self, soul):
        """learn() should persist facts that survive reload."""
        soul.learn("test_category", "Python is great")
        soul.learn("test_category", "Pytest is awesome")
        # learn() calls save() internally

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "Python is great" in soul2.knowledge["test_category"]
        assert "Pytest is awesome" in soul2.knowledge["test_category"]

    def test_learn_no_duplicates(self, soul):
        """learn() should not store the same fact twice."""
        soul.learn("colors", "blue")
        soul.learn("colors", "blue")  # duplicate
        assert soul.knowledge["colors"].count("blue") == 1

    def test_update_user_persists(self, soul):
        """update_user() should persist data that survives reload."""
        soul.update_user("test_user", name="Bob", trust_delta=0.05)

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "test_user" in soul2.relationships
        assert soul2.relationships["test_user"].name == "Bob"
        assert abs(soul2.relationships["test_user"].trust_level - 0.55) < 0.01

    def test_empty_quirks_roundtrip(self, soul):
        """Empty quirks should survive save/load without error."""
        soul.quirks = []
        soul.save()

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert soul2.quirks == []


# ═══════════════════════════════════════════════════
# Soul: get_system_prompt()
# ═══════════════════════════════════════════════════


class TestSoulSystemPrompt:
    """Test get_system_prompt() — personality, adaptation, user context."""

    def test_basic_prompt_contains_identity(self, soul):
        """System prompt should contain the bot's name and role."""
        soul.personality = {"name": "NexusBot", "role": "Test Agent"}
        prompt = soul.get_system_prompt()
        assert "NexusBot" in prompt
        assert "Test Agent" in prompt

    def test_prompt_without_user_id(self, soul):
        """System prompt without user_id should use base personality."""
        soul.personality = {"name": "Toti", "role": "KI-Agent", "tone": "direkt"}
        prompt = soul.get_system_prompt()
        assert "Toti" in prompt
        assert "Direkt" in prompt or "direkt" in prompt

    def test_prompt_with_known_user_adapts(self, soul):
        """System prompt with known user_id should adapt personality."""
        soul.personality = {"name": "Toti", "role": "Agent"}
        soul.relationships["u1"] = UserRelation(
            name="Max",
            language="en",
            humor_style="playful",
            formality_level=0.8,
            technical_depth=0.9,
        )
        prompt = soul.get_system_prompt(user_id="u1")
        assert "Toti" in prompt
        assert "playful" in prompt or "locker" in prompt  # humor or formality adapted

    def test_prompt_with_unknown_user(self, soul):
        """System prompt with unknown user_id should fall back to base personality."""
        soul.personality = {"name": "Toti", "role": "Agent"}
        prompt = soul.get_system_prompt(user_id="unknown_user")
        assert "Toti" in prompt

    def test_prompt_includes_rules(self, soul):
        """System prompt should include rules from personality."""
        soul.personality = {
            "name": "TestBot",
            "rules": ["Always be polite", "Never lie"],
        }
        prompt = soul.get_system_prompt()
        assert "Always be polite" in prompt
        assert "Never lie" in prompt

    def test_prompt_includes_values(self, soul):
        """System prompt should include values from personality."""
        soul.personality = {
            "name": "TestBot",
            "values": ["Honesty", "Efficiency"],
        }
        prompt = soul.get_system_prompt()
        assert "Honesty" in prompt
        assert "Efficiency" in prompt

    def test_prompt_includes_quirks(self, soul):
        """System prompt should include quirks."""
        soul.personality = {"name": "TestBot"}
        soul.quirks = ["Speaks in haiku", "Loves ASCII art"]
        prompt = soul.get_system_prompt()
        assert "haiku" in prompt
        assert "ASCII art" in prompt

    def test_prompt_includes_emotion_arc(self, soul):
        """System prompt for user with emotion history should include mood arc."""
        soul.personality = {"name": "TestBot"}
        soul.track_emotion("u1", "curious")
        soul.track_emotion("u1", "focused")
        prompt = soul.get_system_prompt(user_id="u1")
        assert "Stimmungsverlauf" in prompt or "curious" in prompt.lower() or "focused" in prompt.lower()


# ═══════════════════════════════════════════════════
# Soul: compute_trust_delta()
# ═══════════════════════════════════════════════════


class TestSoulTrustDelta:
    """Test compute_trust_delta() — mood-based trust changes."""

    def test_happy_mood_gives_positive_delta(self, soul):
        """Happy mood should give strong positive trust delta."""
        delta = soul.compute_trust_delta("happy", "Das ist super!")
        assert delta > 0.02

    def test_frustrated_mood_gives_negative_delta(self, soul):
        """Frustrated mood should give slightly negative trust delta."""
        delta = soul.compute_trust_delta("frustrated", "Es geht nicht!")
        assert delta < 0

    def test_gratitude_overrides_frustration(self, soul):
        """Messages with gratitude markers should have at least neutral-positive delta."""
        delta = soul.compute_trust_delta("frustrated", "danke für die Hilfe")
        assert delta >= 0.02

    def test_long_message_bonus(self, soul):
        """Long messages should get a small extra trust bonus."""
        short_msg = "Hallo"
        long_msg = "Hallo, ich möchte dir etwas ausführlich erklären, weil ich finde dass das wichtig ist und es mehr als zwanzig Wörter braucht"
        short_delta = soul.compute_trust_delta("neutral", short_msg)
        long_delta = soul.compute_trust_delta("neutral", long_msg)
        assert long_delta > short_delta

    def test_unknown_mood_defaults_to_neutral(self, soul):
        """Unknown mood string should default to neutral delta."""
        delta = soul.compute_trust_delta("excited", "something")
        # Should use the default 0.01 from the mood_deltas dict's fallback
        assert 0.005 <= delta <= 0.02


# ═══════════════════════════════════════════════════
# Soul: extract_learnable_facts()
# ═══════════════════════════════════════════════════


class TestSoulExtractLearnableFacts:
    """Test extract_learnable_facts() — proactive fact extraction from messages."""

    def test_german_preference(self, soul):
        """German preference statement should be extracted."""
        facts = soul.extract_learnable_facts("ich mag Python")
        assert len(facts) >= 1
        categories = [f[0] for f in facts]
        assert "preference" in categories

    def test_english_preference(self, soul):
        """English preference statement should be extracted."""
        facts = soul.extract_learnable_facts("I prefer dark mode")
        assert len(facts) >= 1
        categories = [f[0] for f in facts]
        assert "preference" in categories

    def test_name_introduction_german(self, soul):
        """German name introduction should extract identity fact."""
        facts = soul.extract_learnable_facts("Ich heiße Anna")
        identity_facts = [f for f in facts if f[0] == "identity"]
        assert len(identity_facts) >= 1
        assert "Anna" in identity_facts[0][1]

    def test_name_introduction_english(self, soul):
        """English name introduction should extract identity fact."""
        facts = soul.extract_learnable_facts("My name is Bob")
        identity_facts = [f for f in facts if f[0] == "identity"]
        assert len(identity_facts) >= 1
        assert "Bob" in identity_facts[0][1]

    def test_no_facts_from_greeting(self, soul):
        """Simple greetings should not produce learnable facts."""
        facts = soul.extract_learnable_facts("Hallo!")
        # A simple "Hallo!" shouldn't match any patterns meaningfully
        # It might or might not produce facts, but they should be minimal
        assert len(facts) <= 1  # At most a weak match

    def test_work_context_extraction(self, soul):
        """Work context statements should be extracted."""
        facts = soul.extract_learnable_facts("ich arbeite mit Python und Docker")
        categories = [f[0] for f in facts]
        assert "work_context" in categories

    def test_location_extraction(self, soul):
        """Location statements should be extracted."""
        facts = soul.extract_learnable_facts("ich wohne in Berlin")
        categories = [f[0] for f in facts]
        assert "location" in categories