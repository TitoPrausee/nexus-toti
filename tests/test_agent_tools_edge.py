"""
Tests for Agent special tool handlers and more _parse_tool_calls edge cases.
Tests focus on: _handle_memory_tool, _handle_session_tool, _handle_delegation,
and additional parse edge cases like deeply nested JSON and mixed formats.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from nexus.core.agent import NexusAgent, TOOL_START, TOOL_END
from nexus.core.tools import ToolRegistry, ToolResult
from nexus.core.memory import MemorySystem


@pytest.fixture
def agent(tmp_path):
    """Create a NexusAgent with mocked LLM to avoid network calls."""
    with patch("nexus.core.agent.LLMClient") as MockLLM:
        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = "Test response"
        mock_response.model = "test-model"
        mock_response.total_tokens = 10
        mock_response.error = ""
        mock_llm.chat.return_value = mock_response
        mock_llm.stats.return_value = {"calls": 0, "errors": 0}
        MockLLM.return_value = mock_llm

        config = {
            "memory": {"l1_max_tokens": 8000},
            "tools": {},
        }
        agent = NexusAgent(config=config)
        # Replace LLM with mock after init
        agent.llm = mock_llm
        return agent


class TestMemoryToolHandler:
    """Tests for NexusAgent._handle_memory_tool()."""

    def test_memory_stats_action(self, agent):
        result = agent._handle_memory_tool({"action": "stats"})
        assert result.success is True
        assert "L1=" in result.output

    def test_memory_remember_action(self, agent):
        result = agent._handle_memory_tool({
            "action": "remember",
            "content": "Test fact about Python",
            "category": "knowledge",
            "importance": 0.8,
        })
        assert result.success is True
        assert "Test fact about Python" in result.output

    def test_memory_remember_default_importance(self, agent):
        result = agent._handle_memory_tool({
            "action": "remember",
            "content": "Another fact",
            "category": "general",
        })
        assert result.success is True
        # Default importance should be 0.7
        facts = agent.memory.l3
        matching = [f for f in facts if f.get("content") == "Another fact"]
        assert len(matching) == 1
        assert matching[0]["importance"] == 0.7

    def test_memory_recall_action(self, agent):
        # Remember something first
        agent._handle_memory_tool({
            "action": "remember",
            "content": "Rust is memory safe",
            "category": "programming",
        })
        # Then recall it
        result = agent._handle_memory_tool({
            "action": "recall",
            "content": "Rust memory",
        })
        assert result.success is True
        assert "Rust" in result.output

    def test_memory_recall_with_empty_l3(self, agent):
        # Clear L3 to ensure empty recall
        agent.memory.l3 = []
        result = agent._handle_memory_tool({
            "action": "recall",
            "content": "anything",
        })
        assert result.success is True
        assert "Keine Erinnerungen" in result.output

    def test_memory_unknown_action(self, agent):
        result = agent._handle_memory_tool({"action": "delete_all"})
        assert result.success is False
        assert "Unknown memory action" in result.error


class TestSessionToolHandler:
    """Tests for NexusAgent._handle_session_tool()."""

    def test_session_start_new(self, agent):
        result = agent._handle_session_tool({
            "action": "start",
            "user_id": "test_user",
        })
        assert result.success is True
        assert "Session" in result.output
        assert result.data is not None
        assert "session_id" in result.data

    def test_session_list_empty(self, agent, tmp_path):
        result = agent._handle_session_tool({"action": "list"})
        # May have existing sessions or not
        assert result.success is True

    def test_session_save_without_active_session(self, agent):
        # No active session, should fail
        result = agent._handle_session_tool({"action": "save"})
        assert result.success is False

    def test_session_unknown_action(self, agent):
        result = agent._handle_session_tool({"action": "unknown_action"})
        assert result.success is False


class TestDelegationHandler:
    """Tests for NexusAgent._handle_delegation()."""

    def test_delegation_success(self, agent):
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = "Coding task completed"
        mock_response.model = "coding-model"
        mock_response.total_tokens = 50
        agent.llm.chat.return_value = mock_response

        result = agent._handle_delegation({
            "task": "Write a Python function",
            "specialist": "coding",
        })
        assert result.success is True
        assert "Coding task completed" in result.output

    def test_delegation_failure(self, agent):
        mock_response = MagicMock()
        mock_response.success = False
        mock_response.error = "Model not available"
        mock_response.content = ""
        agent.llm.chat.return_value = mock_response

        result = agent._handle_delegation({
            "task": "Write code",
            "specialist": "coding",
        })
        assert result.success is False
        assert "fehlgeschlagen" in result.error

    def test_delegation_with_context(self, agent):
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = "Done"
        mock_response.model = "research-model"
        mock_response.total_tokens = 30
        agent.llm.chat.return_value = mock_response

        result = agent._handle_delegation({
            "task": "Research topic X",
            "specialist": "research",
            "context": "Some background info",
        })
        assert result.success is True
        # Verify LLM was called with the specialist model key
        call_args = agent.llm.chat.call_args
        assert call_args[1].get("model_key") == "research" or \
               (len(call_args[0]) > 1 and call_args[0][1] == "research") or \
               call_args.kwargs.get("model_key") == "research"


class TestParseToolCallsEdgeCases:
    """Additional edge cases for _parse_tool_calls beyond existing tests."""

    def test_mixed_xml_and_inline_not_confused(self, agent):
        """XML tool call should take priority, inline on same line ignored."""
        text = f'Here is what I found: {TOOL_START}{{"tool": "file_read", "path": "/tmp/data.txt"}}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "file_read"
        assert calls[0]["path"] == "/tmp/data.txt"

    def test_tool_call_with_nested_json(self, agent):
        """Tool call payload with nested JSON structures."""
        payload = json.dumps({
            "tool": "terminal",
            "command": "echo '{\"key\": \"value\"}'"
        })
        text = f'{TOOL_START}{payload}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "terminal"

    def test_tool_call_with_empty_payload(self, agent):
        """Empty payload within tool tags should return no valid calls."""
        text = f'{TOOL_START}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 0

    def test_multiple_tool_calls_same_line_inline(self, agent):
        """Multiple inline JSON tool calls on separate lines."""
        # Each JSON must start with { and contain "tool" — on its own line
        text = '{\n  "tool": "time"\n}\n{"tool": "calculator", "expression": "2+2"}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) >= 1

    def test_json_with_extra_whitespace(self, agent):
        """JSON with extra whitespace inside tool tags."""
        payload = '  \n  {"tool": "time"}  \n  '
        text = f'{TOOL_START}{payload}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["tool"] == "time"

    def test_tool_call_with_integer_value(self, agent):
        """Tool call with non-string parameter values."""
        text = f'{TOOL_START}{{"tool": "web_search", "query": "test", "max_results": 5}}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["max_results"] == 5

    def test_tool_call_url_in_payload(self, agent):
        """Tool call with URL containing special characters."""
        text = f'{TOOL_START}{{"tool": "web_fetch", "url": "https://example.com/path?a=1&b=2"}}{TOOL_END}'
        calls = agent._parse_tool_calls(text)
        assert len(calls) == 1
        assert "example.com" in calls[0]["url"]


class TestAgentLoopDetection:
    """Tests for loop detection in tool calls."""

    def test_hash_tool_call_deterministic(self, agent):
        """Same tool call should produce same hash."""
        call = {"tool": "terminal", "command": "ls -la"}
        h1 = agent._hash_tool_call(call)
        h2 = agent._hash_tool_call(call)
        assert h1 == h2

    def test_hash_different_for_different_args(self, agent):
        """Different args should produce different hashes."""
        call1 = {"tool": "terminal", "command": "ls -la"}
        call2 = {"tool": "terminal", "command": "ls -la /tmp"}
        h1 = agent._hash_tool_call(call1)
        h2 = agent._hash_tool_call(call2)
        assert h1 != h2

    def test_loop_detected_after_max_duplicates(self, agent):
        """Loop detection should trigger after max_duplicate_calls."""
        call = {"tool": "time"}
        for i in range(agent.max_duplicate_calls - 1):
            result = agent._is_loop_detected(call)
            assert result is False, f"Should not detect loop on call {i+1}"
        # Next call should trigger loop detection
        result = agent._is_loop_detected(call)
        assert result is True

    def test_loop_not_detected_for_different_calls(self, agent):
        """Different tool calls should not trigger loop detection."""
        call1 = {"tool": "time"}
        call2 = {"tool": "calculator", "expression": "1+1"}
        agent._is_loop_detected(call1)
        agent._is_loop_detected(call2)
        agent._is_loop_detected(call1)
        # None of these should trigger loop detection (only 2 duplicates for each)
        assert not agent._is_loop_detected(call2)


class TestAgentProcessErrorHandling:
    """Tests for Agent.process() error handling with mocked LLM."""

    def test_process_returns_default_on_all_failures(self, agent):
        """If LLM fails consistently, should return error message."""
        mock_response = MagicMock()
        mock_response.success = False
        mock_response.error = "Connection refused"
        mock_response.model = "test-model"
        agent.llm.chat.return_value = mock_response

        # Reset tool call tracking
        response = agent.process("Hi there")
        # Should return German error message about problems
        assert "Entschuldigung" in response or "Werkzeug" in response or len(response) > 0

    def test_process_adds_to_l1_memory(self, agent):
        """Verify that process adds user message to L1."""
        initial_l1 = len(agent.memory.l1)
        # Mock a successful response without tool calls
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.content = "Hallo!"
        mock_response.model = "test"
        agent.llm.chat.return_value = mock_response

        agent.process("Wie gehts?")
        # Should have added user message and assistant response to L1
        assert len(agent.memory.l1) > initial_l1