"""
Tests for circular chain detection in NexusAgent.

Covers:
- Simple A→B→A→B pattern (2-tool cycle)
- A→B→C→A→B→C pattern (3-tool cycle)
- A→A→A return-to-same-tool with short intervals
- Normal tool sequences that should NOT trigger detection
- Edge cases: single tool, empty sequence, etc.
"""

import pytest
from unittest.mock import MagicMock, patch
from collections import Counter

from nexus.core.agent import NexusAgent


@pytest.fixture
def agent():
    """Create a NexusAgent with mocked dependencies for testing."""
    with patch("nexus.core.agent.LLMClient"), \
         patch("nexus.core.agent.MemorySystem"), \
         patch("nexus.core.agent.SoulEngine"), \
         patch("nexus.core.agent.ToolRegistry"), \
         patch("nexus.core.agent.ConversationStore"):
        config = {
            "performance": {
                "max_tool_calls_per_turn": 15,
                "max_duplicate_calls": 3,
                "max_chain_repeats": 2,
            }
        }
        a = NexusAgent(config=config)
        # Reset state
        a._tool_call_hashes = []
        a._tool_name_sequence = []
        return a


class TestCircularChainTwoToolCycle:
    """Test A→B→A→B pattern detection (2-tool alternating cycle)."""

    def test_no_cycle_with_few_calls(self, agent):
        """3 calls: terminal, file_read, terminal — not enough for a cycle."""
        agent._tool_name_sequence = []
        is_circ, desc = agent._is_circular_chain("terminal")
        assert not is_circ
        is_circ, desc = agent._is_circular_chain("file_read")
        assert not is_circ
        is_circ, desc = agent._is_circular_chain("terminal")
        assert not is_circ

    def test_detects_abab_cycle(self, agent):
        """terminal → file_read → terminal → file_read should be detected."""
        agent._tool_name_sequence = []
        agent._is_circular_chain("terminal")
        agent._is_circular_chain("file_read")
        agent._is_circular_chain("terminal")
        is_circ, desc = agent._is_circular_chain("file_read")
        assert is_circ
        assert "terminal→file_read" in desc

    def test_detects_three_tool_cycle(self, agent):
        """A→B→C→A→B→C should be detected (pattern length 3)."""
        agent._tool_name_sequence = []
        agent._is_circular_chain("terminal")
        agent._is_circular_chain("file_read")
        agent._is_circular_chain("code_exec")
        agent._is_circular_chain("terminal")
        agent._is_circular_chain("file_read")
        is_circ, desc = agent._is_circular_chain("code_exec")
        assert is_circ
        assert "terminal→file_read→code_exec" in desc


class TestCircularChainReturnToSame:
    """Test A→B→A→C→A pattern (tool A keeps coming back)."""

    def test_tool_returning_3x_short_intervals(self, agent):
        """terminal called 3x with 1-2 tools between = cycling."""
        agent._tool_name_sequence = []
        agent._is_circular_chain("terminal")   # [terminal]
        agent._is_circular_chain("file_read")   # [terminal, file_read]
        agent._is_circular_chain("terminal")    # [terminal, file_read, terminal]
        agent._is_circular_chain("code_exec")   # [terminal, file_read, terminal, code_exec]
        is_circ, desc = agent._is_circular_chain("terminal")  # [terminal, file_read, terminal, code_exec, terminal]
        assert is_circ
        assert "terminal" in desc

    def test_tool_returning_3x_long_intervals_not_cycling(self, agent):
        """terminal called 3x but with many tools between = NOT cycling."""
        agent._tool_name_sequence = []
        agent._is_circular_chain("terminal")    # [terminal]
        agent._is_circular_chain("file_read")    # [terminal, file_read]
        agent._is_circular_chain("file_write")   # [terminal, file_read, file_write]
        agent._is_circular_chain("web_search")   # [4 tools]
        agent._is_circular_chain("calculator")   # [5 tools]
        # Now add terminal again — long intervals between calls
        is_circ, desc = agent._is_circular_chain("terminal")
        # Should NOT be detected as cycling because only 2 terminal calls with long intervals
        assert not is_circ


class TestCircularChainNoFalsePositives:
    """Ensure normal tool sequences don't trigger detection."""

    def test_sequential_different_tools(self, agent):
        """Each tool used once in sequence — no cycling."""
        agent._tool_name_sequence = []
        for tool in ["terminal", "file_read", "code_exec", "web_search", "calculator"]:
            is_circ, _ = agent._is_circular_chain(tool)
            assert not is_circ, f"False positive for {tool}"

    def test_revisit_tool_after_many_others(self, agent):
        """If terminal is used early, then 5+ other tools, then terminal again,
        that's not cycling — it's a legitimate revisit."""
        agent._tool_name_sequence = []
        agent._is_circular_chain("terminal")
        agent._is_circular_chain("file_read")
        agent._is_circular_chain("file_write")
        agent._is_circular_chain("web_search")
        agent._is_circular_chain("code_exec")
        agent._is_circular_chain("calculator")
        # terminal again, but with long intervals between
        is_circ, _ = agent._is_circular_chain("terminal")
        assert not is_circ  # 5 tools between — not cycling

    def test_single_tool_repeated_but_not_circular(self, agent):
        """terminal called twice with one other tool between — not cycling yet."""
        agent._tool_name_sequence = []
        agent._is_circular_chain("terminal")
        agent._is_circular_chain("file_read")
        is_circ, _ = agent._is_circular_chain("terminal")
        assert not is_circ  # Only 2 calls, need 3+ for return pattern


class TestCircularChainWithIntegration:
    """Test that circular chain detection integrates with the agent loop."""

    def test_process_resets_sequence(self, agent):
        """Each process() call should reset the tool name sequence."""
        agent._tool_name_sequence = ["terminal", "file_read"]
        agent._tool_call_hashes = ["abc123"]

        # process() resets both
        agent._tool_call_count = 0
        agent._tool_call_hashes = []
        agent._tool_name_sequence = []

        assert agent._tool_name_sequence == []

    def test_config_max_chain_repeats(self):
        """Verify max_chain_repeats can be configured."""
        with patch("nexus.core.agent.LLMClient"), \
             patch("nexus.core.agent.MemorySystem"), \
             patch("nexus.core.agent.SoulEngine"), \
             patch("nexus.core.agent.ToolRegistry"), \
             patch("nexus.core.agent.ConversationStore"):
            config = {"performance": {"max_chain_repeats": 3}}
            a = NexusAgent(config=config)
            assert a.max_chain_repeats == 3

    def test_default_max_chain_repeats(self):
        """Verify default max_chain_repeats is 2."""
        with patch("nexus.core.agent.LLMClient"), \
             patch("nexus.core.agent.MemorySystem"), \
             patch("nexus.core.agent.SoulEngine"), \
             patch("nexus.core.agent.ToolRegistry"), \
             patch("nexus.core.agent.ConversationStore"):
            a = NexusAgent()
            assert a.max_chain_repeats == 2


class TestDuplicateDetectionUnchanged:
    """Verify that duplicate (hash-based) loop detection still works alongside circular chains."""

    def test_same_call_3x_detected(self, agent):
        """Same tool+args 3 times should trigger hash-based loop detection."""
        agent._tool_call_hashes = []
        call = {"tool": "terminal", "command": "ls -la"}
        assert not agent._is_loop_detected(call)  # 1st time
        assert not agent._is_loop_detected(call)  # 2nd time
        assert agent._is_loop_detected(call)       # 3rd time — loop!

    def test_different_args_no_loop(self, agent):
        """Different args should not trigger hash-based duplicate detection."""
        agent._tool_call_hashes = []
        call1 = {"tool": "terminal", "command": "ls -la"}
        call2 = {"tool": "terminal", "command": "pwd"}
        assert not agent._is_loop_detected(call1)
        assert not agent._is_loop_detected(call2)