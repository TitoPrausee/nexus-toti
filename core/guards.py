"""
NEXUS Safety Guards — Loop Detection, Max Steps, Budget Tracking, Model Fallback
Runs locally (no model calls) — zero GPU cost.
"""

import hashlib
from collections import deque
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    suggested_level: int = 2
    loop_detected: bool = False


class NexusGuards:
    """
    Safety guards that run before every agent action.
    Level 0 — pure Python, no model calls, zero cost.
    """

    def __init__(self, max_steps: int = 10, budget_limit_pct: float = 90.0):
        self.max_steps = max_steps
        self.budget_limit_pct = budget_limit_pct
        self.steps = 0
        self.loop_history: deque[str] = deque(maxlen=3)
        self.cloud_fallback = False
        self._action_hashes: deque[str] = deque(maxlen=5)

    def tick(self) -> GuardResult:
        """Called at the start of every agent step."""
        self.steps += 1

        # Max steps check
        if self.steps >= self.max_steps:
            return GuardResult(
                allowed=False,
                reason=f"Max Steps erreicht ({self.max_steps}) — stoppe.",
                suggested_level=0,
            )

        # Budget warning at 80%, fallback at 90%
        budget_ratio = self.steps / self.max_steps
        if budget_ratio >= 0.9:
            self.cloud_fallback = True
            return GuardResult(
                allowed=True,
                reason="Budget knapp — wechsle zu leichterem Modell.",
                suggested_level=1,
            )
        elif budget_ratio >= 0.8:
            return GuardResult(
                allowed=True,
                reason="Budget bei 80% — Level-1 Modelle empfohlen.",
                suggested_level=1,
            )

        return GuardResult(allowed=True, suggested_level=2)

    def check_loop(self, output: str) -> bool:
        """Detect if the agent is producing the same output repeatedly."""
        h = hashlib.md5(output.encode()).hexdigest()
        if h in self.loop_history:
            return True
        self.loop_history.append(h)
        return False

    def check_action_loop(self, action: str) -> bool:
        """Detect if the agent is repeating the same action."""
        h = hashlib.md5(action.encode()).hexdigest()
        if h in self._action_hashes:
            return True
        self._action_hashes.append(h)
        return False

    def get_model_level(self, required_level: int) -> int:
        """
        Automatic model routing based on current budget state.
        Returns the actual level to use (may be lower than requested).
        """
        if self.cloud_fallback:
            return 1  # Fallback to fast model

        budget_ratio = self.steps / self.max_steps
        if budget_ratio > 0.8:
            return min(required_level, 1)  # Only allow level 1
        if budget_ratio > 0.6:
            return min(required_level, 2)  # Only allow up to level 2

        return required_level

    def pre_check(self, action: str, current_output: str = "") -> GuardResult:
        """
        Full pre-action check. Returns whether the action is allowed
        and at what model level.
        """
        # Step budget check
        step_result = self.tick()
        if not step_result.allowed:
            return step_result

        # Loop detection
        if current_output and self.check_loop(current_output):
            return GuardResult(
                allowed=True,
                reason="Loop erkannt — gleicher Output wie vorher. Versuche anderen Ansatz.",
                suggested_level=2,
                loop_detected=True,
            )

        # Action loop detection
        if self.check_action_loop(action):
            return GuardResult(
                allowed=True,
                reason="Gleiche Aktion erneut — möglicher Loop. Ändere Strategie.",
                suggested_level=2,
                loop_detected=True,
            )

        return step_result

    def reset(self):
        """Reset guard state for new task."""
        self.steps = 0
        self.loop_history.clear()
        self._action_hashes.clear()
        self.cloud_fallback = False

    def get_status(self) -> dict:
        return {
            "steps": self.steps,
            "max_steps": self.max_steps,
            "budget_used_pct": round(self.steps / self.max_steps * 100, 1),
            "cloud_fallback": self.cloud_fallback,
            "loops_detected": len(self.loop_history),
        }
