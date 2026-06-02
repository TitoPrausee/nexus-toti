"""
NEXUS Iteration Budget — Track and limit LLM calls per conversation turn.

Prevents runaway agent loops by enforcing per-turn and per-conversation
token/call budgets. Each agent gets a configurable budget that decreases
with each LLM call, and the system refuses calls when the budget is exhausted.

Inspired by Hermes Agent's iteration budget system, adapted for NEXUS.
"""

import time
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional, Tuple
from pathlib import Path
from enum import Enum


class BudgetType(Enum):
    """Type of budget limit."""
    CALLS = "calls"           # Number of LLM calls
    TOKENS = "tokens"         # Total tokens (prompt + completion)
    TURNS = "turns"           # Number of conversation turns


@dataclass
class BudgetLimit:
    """A single budget limit."""
    budget_type: BudgetType
    max_value: int            # Maximum allowed
    current_value: int = 0    # Current usage
    reset_on_turn: bool = True  # Reset at start of each turn

    @property
    def remaining(self) -> int:
        return max(0, self.max_value - self.current_value)

    @property
    def usage_pct(self) -> float:
        return (self.current_value / self.max_value * 100) if self.max_value > 0 else 0.0

    @property
    def is_exhausted(self) -> bool:
        return self.current_value >= self.max_value

    def consume(self, amount: int = 1) -> bool:
        """Try to consume budget. Returns True if successful, False if exhausted."""
        if self.is_exhausted:
            return False
        self.current_value += amount
        return True


@dataclass
class ConversationBudget:
    """Budget tracking for a single conversation."""
    conversation_id: str
    created_at: float = field(default_factory=time.time)

    # Per-turn limits (reset each turn)
    turn_calls: BudgetLimit = field(default_factory=lambda: BudgetLimit(BudgetType.CALLS, 25))
    turn_tokens: BudgetLimit = field(default_factory=lambda: BudgetLimit(BudgetType.TOKENS, 100_000))

    # Per-conversation limits (accumulate across turns)
    total_calls: BudgetLimit = field(default_factory=lambda: BudgetLimit(BudgetType.CALLS, 200, reset_on_turn=False))
    total_tokens: BudgetLimit = field(default_factory=lambda: BudgetLimit(BudgetType.TOKENS, 1_000_000, reset_on_turn=False))

    # Agent-specific overrides
    agent_overrides: Dict[str, Dict[str, int]] = field(default_factory=dict)

    current_turn: int = 0

    def reset_turn(self):
        """Reset per-turn budgets for a new turn."""
        self.current_turn += 1
        self.turn_calls.current_value = 0
        self.turn_tokens.current_value = 0

    def can_make_call(self, agent: str = "", estimated_tokens: int = 0) -> Tuple[bool, str]:
        """
        Check if a call can be made within budget.

        Returns (allowed, reason) tuple.
        """
        # Check per-turn call limit
        if self.turn_calls.is_exhausted:
            return False, f"Turn call limit reached ({self.turn_calls.max_value} calls/turn)"

        # Check per-turn token limit
        if self.turn_tokens.current_value + estimated_tokens > self.turn_tokens.max_value:
            return False, f"Turn token limit reached ({self.turn_tokens.max_value} tokens/turn)"

        # Check total conversation call limit
        if self.total_calls.is_exhausted:
            return False, f"Total call limit reached ({self.total_calls.max_value} calls)"

        # Check total conversation token limit
        if self.total_tokens.current_value + estimated_tokens > self.total_tokens.max_value:
            return False, f"Total token limit reached ({self.total_tokens.max_value} tokens)"

        # Check agent-specific overrides
        if agent and agent in self.agent_overrides:
            agent_limits = self.agent_overrides[agent]
            max_calls = agent_limits.get("max_calls", 0)
            if max_calls > 0:
                agent_calls = agent_limits.get("current_calls", 0)
                if agent_calls >= max_calls:
                    return False, f"Agent {agent} call limit reached ({max_calls} calls)"

        return True, "OK"

    def record_call(self, agent: str = "", tokens_used: int = 0):
        """Record an LLM call against the budget."""
        self.turn_calls.consume(1)
        self.turn_tokens.consume(tokens_used)
        self.total_calls.consume(1)
        self.total_tokens.consume(tokens_used)

        # Update agent-specific tracking
        if agent and agent in self.agent_overrides:
            self.agent_overrides[agent]["current_calls"] = \
                self.agent_overrides[agent].get("current_calls", 0) + 1

    def get_summary(self) -> dict:
        """Get a budget summary."""
        return {
            "conversation_id": self.conversation_id,
            "current_turn": self.current_turn,
            "turn_calls": f"{self.turn_calls.current_value}/{self.turn_calls.max_value}",
            "turn_tokens": f"{self.turn_tokens.current_value:,}/{self.turn_tokens.max_value:,}",
            "total_calls": f"{self.total_calls.current_value}/{self.total_calls.max_value}",
            "total_tokens": f"{self.total_tokens.current_value:,}/{self.total_tokens.max_value:,}",
        }


class IterationBudgetManager:
    """
    Manages iteration budgets across conversations.

    Creates budgets per conversation, enforces limits, and
    provides budget summaries for monitoring.
    """

    def __init__(self, storage_path: str = "data/budgets"):
        self.storage_path = Path(storage_path)
        self._conversations: Dict[str, ConversationBudget] = {}
        self._default_limits = {
            "turn_calls": 25,
            "turn_tokens": 100_000,
            "total_calls": 200,
            "total_tokens": 1_000_000,
        }

    def create_budget(self, conversation_id: str,
                      agent_overrides: Dict[str, Dict[str, int]] = None) -> ConversationBudget:
        """Create a new conversation budget."""
        budget = ConversationBudget(
            conversation_id=conversation_id,
            turn_calls=BudgetLimit(BudgetType.CALLS, self._default_limits["turn_calls"]),
            turn_tokens=BudgetLimit(BudgetType.TOKENS, self._default_limits["turn_tokens"]),
            total_calls=BudgetLimit(BudgetType.CALLS, self._default_limits["total_calls"], reset_on_turn=False),
            total_tokens=BudgetLimit(BudgetType.TOKENS, self._default_limits["total_tokens"], reset_on_turn=False),
            agent_overrides=agent_overrides or {},
        )
        self._conversations[conversation_id] = budget
        return budget

    def get_budget(self, conversation_id: str) -> Optional[ConversationBudget]:
        """Get an existing conversation budget."""
        return self._conversations.get(conversation_id)

    def get_or_create(self, conversation_id: str) -> ConversationBudget:
        """Get or create a conversation budget."""
        return self._conversations.get(conversation_id) or self.create_budget(conversation_id)

    def can_call(self, conversation_id: str, agent: str = "",
                 estimated_tokens: int = 0) -> Tuple[bool, str]:
        """Check if an LLM call is within budget."""
        budget = self.get_or_create(conversation_id)
        return budget.can_make_call(agent, estimated_tokens)

    def record_call(self, conversation_id: str, agent: str = "",
                    tokens_used: int = 0):
        """Record an LLM call against the budget."""
        budget = self.get_or_create(conversation_id)
        budget.record_call(agent, tokens_used)

    def advance_turn(self, conversation_id: str):
        """Advance to the next turn in a conversation."""
        budget = self.get_or_create(conversation_id)
        budget.reset_turn()

    def get_all_summaries(self) -> Dict[str, dict]:
        """Get budget summaries for all conversations."""
        return {
            conv_id: budget.get_summary()
            for conv_id, budget in self._conversations.items()
        }

    def set_default_limits(self, turn_calls: int = None, turn_tokens: int = None,
                           total_calls: int = None, total_tokens: int = None):
        """Override default budget limits."""
        if turn_calls is not None:
            self._default_limits["turn_calls"] = turn_calls
        if turn_tokens is not None:
            self._default_limits["turn_tokens"] = turn_tokens
        if total_calls is not None:
            self._default_limits["total_calls"] = total_calls
        if total_tokens is not None:
            self._default_limits["total_tokens"] = total_tokens