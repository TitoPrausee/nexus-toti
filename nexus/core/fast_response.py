"""
NEXUS v9.2 — Fast Response Layer
Sofortige erste Antwort (< 4s) mit Hybrid-Approach:
- Template-Ack: < 100ms, garantiert sofort
- Hybrid-Ack: Template sofort + fast-Model-Call parallel
  Wenn fast-Model schneller als Worker → kontextsensitiver Ack ersetzt Template.

Integration:
- QuickResponder.generate_ack() → sofortige Zwischenantwort
- agent.py process() ruft quick_callback auf bevor Worker startet
- telegram_bot.py sendet Acknowledge-Nachricht, editiert mit Endergebnis
"""

import re
import time
import logging
import threading
from typing import Optional, Callable
from dataclasses import dataclass

from nexus.core.llm_client import LLMClient, Message
from nexus.core.pair_router import IntentType

log = logging.getLogger("nexus.fast_response")

# ─── Intent-basierte Template-Acks ──────────────────────────

INTENT_ACKS = {
    IntentType.TRIVIAL: {
        "default": "✅",
        "patterns": [
            (r"hallo|hi|hey|moin|servus", "Hey! 👋"),
            (r"danke|thanks|thx", "Gern geschehen! 💙"),
            (r"wie geht|was machst|was geht", "Läuft! Und selbst? 😊"),
            (r"tschüss|bye|ciao", "Bis dann! 👋"),
        ],
    },
    IntentType.TOOL_BASED: {
        "default": "🔧 Lass mich das nachschlagen...",
    },
    IntentType.COMPLEX: {
        "default": "🧠 Analysiere deine Anfrage...",
        "patterns": [
            (r"code|programmier|implementier|refactor|debug|fix", "💻 Arbeite an deinem Code..."),
            (r"recherchi|such|finde|analysier", "🔍 Recherchiere für dich..."),
            (r"erklär|wie funktioniert|warum", "📖 Erkläre dir das gleich..."),
            (r"schreib|erstelle|baue|mach", "✏️ Setze das um..."),
            (r"vergleich|unterschied|besser", "📊 Vergleiche das für dich..."),
        ],
    },
    IntentType.CRITICAL: {
        "default": "⚠️ Wichtige Entscheidung — prüfe sorgfältig...",
    },
    IntentType.DELEGATION: {
        "default": "🤝 Delegiere an Spezialisten...",
        "patterns": [
            (r"research|recherche", "🔍 Research-Team arbeitet..."),
            (r"engineer|code|programmier", "💻 Engineering-Team arbeitet..."),
            (r"creative|design|text", "🎨 Creative-Team arbeitet..."),
        ],
    },
}

# Context extraction patterns for smarter template acks
_TOPIC_PATTERNS = [
    (r"(?:über|von|zu|r|zum|zur)\s+['\"]?([A-ZÄÖÜ][\wäöüß-]+)", "topic"),
    (r"(?:wie|was|warum|wieso|wobei)\s+([A-ZÄÖÜ][\wäöüß-]+)", "topic"),
    (r"(?:kannst du|kannst)\s+([a-zäöüß]+)", "action"),
]


@dataclass
class AckResult:
    """Result of a quick acknowledgment generation."""
    text: str
    source: str  # "template" or "hybrid"
    elapsed_ms: float


class QuickResponder:
    """
    Generiert sofortige Kontext-Acknowledges.

    Hybrid-Approach:
    1. Template-Ack sofort (< 100ms) → Callback feuert
    2. Parallel: fast-Model generiert kontextsensitiveren Ack
    3. Wenn fast-Model vor Worker fertig → Ack wird upgedated
    4. Worker arbeitet weiter im Hintergrund
    """

    def __init__(self, llm: LLMClient = None, config: dict = None):
        self.llm = llm
        self.config = config or {}
        self._hybrid_timeout = self.config.get("hybrid_ack_timeout", 2.0)
        self._enabled = self.config.get("enabled", True)

    def generate_ack(self, user_message: str, routing_decision,
                     callback: Optional[Callable[[str], None]] = None) -> AckResult:
        """
        Generate an immediate acknowledgment.

        Args:
            user_message: The user's message
            routing_decision: RoutingDecision from PairRouter
            callback: Optional callback to update the ack with hybrid result

        Returns:
            AckResult with template ack (immediate)
        """
        if not self._enabled:
            return AckResult(text="", source="disabled", elapsed_ms=0)

        start = time.time()
        intent = getattr(routing_decision, 'intent', 'complex')

        # 1. Generate template ack immediately
        template_ack = self._template_ack(user_message, intent)
        elapsed = (time.time() - start) * 1000

        # 2. If LLM available and intent is complex/critical, try hybrid ack
        if self.llm and intent in (IntentType.COMPLEX, IntentType.CRITICAL, IntentType.DELEGATION):
            self._try_hybrid_ack(user_message, intent, template_ack, callback)

        return AckResult(
            text=template_ack,
            source="template",
            elapsed_ms=elapsed,
        )

    def _template_ack(self, user_message: str, intent: str) -> str:
        """Generate template-based ack — no LLM call, instant."""
        intent_config = INTENT_ACKS.get(intent, INTENT_ACKS.get(IntentType.COMPLEX))
        if not intent_config:
            intent_config = INTENT_ACKS[IntentType.COMPLEX]

        # Check patterns first
        patterns = intent_config.get("patterns", [])
        msg_lower = user_message.lower()
        for pattern, response in patterns:
            if re.search(pattern, msg_lower):
                return response

        # Extract topic for contextual template ack
        topic = self._extract_topic(user_message)
        default = intent_config.get("default", "🧠 Denke nach...")

        if topic and intent != IntentType.TRIVIAL:
            return f"{default.split('...')[0]} **{topic}**..."

        return default

    def _extract_topic(self, message: str) -> str:
        """Extract a topic from the user message for contextual acks."""
        for pattern, _ in _TOPIC_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                topic = match.group(1)
                if len(topic) > 30:
                    topic = topic[:30] + "..."
                return topic
        return ""

    def _try_hybrid_ack(self, user_message: str, intent: str,
                        template_ack: str,
                        callback: Optional[Callable[[str], None]] = None) -> None:
        """
        Try to generate a better ack using the fast model.
        Runs in a background thread — if it finishes before timeout,
        calls callback to update the ack message.
        """
        if not callback:
            return

        def _hybrid_worker():
            try:
                messages = [
                    Message("system",
                        "Du bist ein Acknowledgment-Generator. "
                        "Erzeuge EINEN kurzen Satz (< 15 Worte) der zeigt, dass du die Anfrage verstehst. "
                        "Keine Einleitung, keine Erklärung, nur der Ack-Satz. "
                        "Beispiele: 'Analysiere den Code für dich...', 'Recherchiere Kubernetes-Deployment...'"),
                    Message("user", user_message),
                ]

                response = self.llm.chat(
                    messages,
                    model_key="fast",
                    max_tokens=48,
                )

                if response.success and response.content.strip():
                    hybrid_ack = response.content.strip()
                    # Only use hybrid ack if it's reasonable length
                    if 5 <= len(hybrid_ack) <= 120:
                        log.debug(f"Hybrid ack generated in {response.elapsed:.2f}s: {hybrid_ack[:50]}")
                        callback(hybrid_ack)
            except Exception as e:
                log.debug(f"Hybrid ack failed (non-critical): {e}")

        thread = threading.Thread(target=_hybrid_worker, daemon=True)
        thread.start()

    def generate_progress_ack(self, completed_agents: int, total_agents: int,
                              agent_names: list = None) -> str:
        """Generate a progress update when agents complete."""
        names_str = ""
        if agent_names:
            names_str = f" ({', '.join(agent_names[:2])})"

        if completed_agents == 0:
            return f"🔄 {total_agents} Agenten arbeiten{names_str}..."
        elif completed_agents < total_agents:
            return f"⏳ {completed_agents}/{total_agents} Agenten fertig{names_str}..."
        else:
            return "✨ Synthetisiere Ergebnisse..."

    def generate_delegation_ack(self, department: str, task: str) -> str:
        """Generate ack for a delegation to a specific department."""
        dept_names = {
            "ceo": "CEO",
            "research": "Research",
            "engineering": "Engineering",
            "creative": "Creative",
            "operations": "Operations",
        }
        name = dept_names.get(department, department.capitalize())
        topic = self._extract_topic(task)
        if topic:
            return f"🔍 {name} arbeitet zu **{topic}**..."
        return f"🔍 {name} arbeitet daran..."