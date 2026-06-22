"""
NEXUS v8.1 — Pair Architecture Router
Two-tier LLM routing: fast/cheap for trivial, capable/expensive for complex.

Routing logic:
1. Router classifies intent: trivial, tool-based, complex, critical
2. Trivial -> Router answers directly (1 small model call)
3. Tool-based -> Router plans, Worker executes (1 small + 1 large call)
4. Complex -> Worker handles everything (1 large call with full context)
5. Critical -> Worker + optional Critic check (1-2 large + 1 small)

Efficiency rules:
- Max 1 Worker call per task unless retry is needed
- Context compressed before sending to Worker
- Tool calls don't go to Worker if Router can route them deterministically
- Token budgets: Router max 512, Worker max 4096, Critic max 1024
"""

import re
import logging
from typing import Optional, List
from dataclasses import dataclass

from nexus.core.llm_client import LLMClient, Message, LLMResponse

log = logging.getLogger("nexus.router")


class IntentType:
    TRIVIAL = "trivial"
    TOOL_BASED = "tool_based"
    COMPLEX = "complex"
    CRITICAL = "critical"
    DELEGATION = "delegation"


@dataclass
class RoutingDecision:
    intent: str
    confidence: float
    router_response: str = ""
    plan: str = ""
    model_key: str = "default"
    needs_worker: bool = False
    context_compression: str = "recent"
    max_worker_tokens: int = 4096
    complexity: str = "simple"  # simple, moderate, complex, critical


class PairRouter:
    """
    Two-tier Router/Worker architecture.

    Router (small, fast): gemini-3-flash-preview:cloud
    Worker (capable): kimi-k2.6:cloud or specialist models
    Critic (small, optional): gemma4:cloud

    Cost savings: Router calls are ~10x cheaper than Worker calls.
    Trivial tasks never hit the Worker.
    """

    TRIVIAL_PATTERNS = [
        (r"^(hi|hey|hallo|moin|servus|na|yo|sup|wasup|hello|hi there)[\s!.?]*$", 0.95),
        (r"^(danke|thanks|thx|cheers|merci|bitte|sorry|entschuldigung)[\s!.?]*$", 0.9),
        (r"^(ja|nein|nope|yep|n[oö]|ok|okay|done|fertig|klar)[\s!.?]*$", 0.85),
        (r"^(wie geht|how are|was machst|what'?s up)[\s?.!]*$", 0.85),
        (r"^(wer bist|was bist|who are|what are you)[\s?.!]*$", 0.85),
        (r"^(tschüss|bye|ciao|auf wiedersehen|see you|bis dann)[\s!.?]*$", 0.9),
        # Extended: common conversational openers (no LLM needed)
        (r"^(klingt gut|cool|geil|super|toll|nice|awesome|krass|perfekt)[\s!.?]*$", 0.85),
        (r"^(stimmt|genau|exakt|richtig|logisch|klar|na klar)[\s!.?]*$", 0.85),
        (r"^(verstehe|kapier|aha|oh|wirklich|echt|seriously)[\s!.?]*$", 0.80),
        (r"^(lol|haha|hehe|xd|😄|😂)[\s!.?]*$", 0.90),
    ]

    COMPLEX_KEYWORDS = {
        "programmier", "implementier", "refactor", "debug", "fix bug",
        "erstelle mir", "schreibe mir code", "analysier code", "recherchier und vergleiche",
        "architektur design", "deploy auf", "erkläre wie das funktioniert",
        "baue mir", "entwickle ein", "optimier den code", "migrat die datenbank",
        "gitlab pipeline", "github actions", "api endpoint erstellen",
        "skill erstellen", "feature implementieren", "funktion hinzufügen",
    }

    CRITICAL_KEYWORDS = {
        "löschen", "delete", "produktion", "production", "sicherheit", "security",
        "passwort", "password", "geheim", "secret", "entscheide", "decision",
        "bestätige", "confirm", "kritisch", "critical", "wichtig", "important",
    }

    DELEGATION_KEYWORDS = {
        "delegier", "spezialist", "expert", "delegation",
    }

    def __init__(self, llm, config=None):
        self.llm = llm
        self.config = config or {}
        self.router_max_tokens = self.config.get("router_max_tokens", 512)
        self.worker_max_tokens = self.config.get("worker_max_tokens", 4096)
        self.critic_max_tokens = self.config.get("critic_max_tokens", 1024)
        self.router_model = self.config.get("router_model", "fast")
        self.critic_model = self.config.get("critic_model", "creative")

    def classify_intent(self, user_message, conversation_context=""):
        msg_lower = user_message.lower().strip()

        # Pattern matching (deterministic, free)
        for pattern, confidence in self.TRIVIAL_PATTERNS:
            if re.match(pattern, msg_lower):
                return RoutingDecision(
                    intent=IntentType.TRIVIAL,
                    confidence=confidence,
                    router_response=self._trivial_response(msg_lower),
                    needs_worker=False,
                    context_compression="recent",
                    complexity="simple",
                )

        delegation_hits = sum(1 for kw in self.DELEGATION_KEYWORDS if kw in msg_lower)
        if delegation_hits >= 1:
            return RoutingDecision(
                intent=IntentType.DELEGATION,
                confidence=0.85,
                needs_worker=True,
                model_key="default",
                plan="Delegation task detected",
                context_compression="summary",
                max_worker_tokens=self.worker_max_tokens,
                complexity="complex",
            )

        critical_hits = sum(1 for kw in self.CRITICAL_KEYWORDS if kw in msg_lower)
        if critical_hits >= 1:
            return RoutingDecision(
                intent=IntentType.CRITICAL,
                confidence=0.8,
                needs_worker=True,
                model_key="default",
                context_compression="full",
                max_worker_tokens=self.worker_max_tokens,
                complexity="critical",
            )

        complex_hits = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in msg_lower)
        word_count = len(user_message.split())
        is_long = word_count > 25

        if complex_hits >= 1:
            # Determine complexity level based on message characteristics
            complexity = "moderate"
            if complex_hits >= 3 or is_long:
                complexity = "complex"
            if complex_hits >= 5 or word_count > 50:
                complexity = "critical"

            return RoutingDecision(
                intent=IntentType.COMPLEX,
                confidence=0.8,
                needs_worker=True,
                model_key="default",
                context_compression="summary",
                max_worker_tokens=self.worker_max_tokens,
                complexity=complexity,
            )

        question_words = {"wie", "warum", "wieso", "was", "wobei", "welche", "wer", "wo", "wann", "womit", "how", "why", "what", "which", "who", "where", "when"}
        question_count = sum(1 for w in question_words if w in msg_lower)
        has_question_mark = "?" in user_message
        # Check trivial patterns FIRST for known smalltalk (e.g. "was geht", "wie geht")
        trivial = self._trivial_response(msg_lower)
        # Questions are NOT automatically complex — simple questions get answered directly.
        # Only route to Worker if the question is clearly multi-step or technical.
        # Short questions (<=15 words) with a single question word → answer directly (no Worker)
        if (question_count >= 1 or has_question_mark) and not trivial:
            # Multi-question or long questions → Worker needed
            if question_count >= 2 or word_count > 30:
                return RoutingDecision(
                    intent=IntentType.COMPLEX,
                    confidence=0.75,
                    needs_worker=True,
                    model_key="default",
                    context_compression="summary",
                    max_worker_tokens=self.worker_max_tokens,
                    complexity="moderate",
                )
            # Simple single question → Router can answer directly (no delegation)
            # falls through to LLM classification below

        # ── FAST PATH: Short messages (<=15 words) without complex keywords ──
        # No LLM call needed — the main model can handle these directly.
        # This eliminates the _classify_and_route_via_llm overhead that was causing slow responses.
        has_multi_clauses = any(sep in user_message for sep in [". ", "! ", "? "]) and word_count > 5
        if word_count <= 15 and complex_hits == 0 and not has_multi_clauses:
            # Already checked trivial patterns above — if we're here, it's a short
            # question or statement the main model should answer directly (no Worker delegation)
            return RoutingDecision(
                intent=IntentType.TOOL_BASED,
                confidence=0.7,
                needs_worker=False,  # Main model handles directly — no Worker needed
                model_key="default",
                context_compression="recent",
                complexity="simple",
            )

        # ── MEDIUM PATH: Messages 16-40 words without complex keywords ──
        # Main model can handle these too — only delegate if multi-clause or complex.
        if word_count <= 40 and complex_hits == 0:
            if has_multi_clauses:
                # Multi-clause: needs Worker for coherent multi-step handling
                return RoutingDecision(
                    intent=IntentType.COMPLEX,
                    confidence=0.65,
                    needs_worker=True,
                    model_key="default",
                    context_compression="summary",
                    max_worker_tokens=min(self.worker_max_tokens, 2048),
                    complexity="moderate",
                )
            # Single-clause medium message — main model handles it
            return RoutingDecision(
                intent=IntentType.TOOL_BASED,
                confidence=0.7,
                needs_worker=False,  # Direct answer, no delegation
                model_key="default",
                context_compression="recent",
                complexity="simple",
            )

        # ── DEFAULT: Long or keyword-heavy messages need Worker ──
        return RoutingDecision(
            intent=IntentType.COMPLEX,
            confidence=0.7,
            needs_worker=True,
            model_key="default",
            context_compression="summary",
            max_worker_tokens=self.worker_max_tokens,
            complexity="moderate",
        )

    # NOTE: _classify_and_route_via_llm removed in v9.3 — it added 2-5s latency
    # for every short message. Classification is now fully deterministic via
    # keyword matching and message length heuristics. No LLM call for routing.

    # Patterns that match the ENTIRE message (exact or near-exact)
    # These must NOT match partial words in longer messages
    TRIVIAL_EXACT = {
        "hi", "hey", "hallo", "moin", "servus", "hello", "yo", "na", "sup",
        "tschüss", "bye", "ciao", "auf wiedersehen", "see you",
        "danke", "thanks", "thx", "cheers",
        "ja", "yep", "ok", "okay", "klar", "stimmt", "genau",
        "nein", "nope", "nö",
        "klingt gut", "cool", "geil", "super", "toll", "nice", "krass", "perfekt",
        "verstehe", "kapier", "aha", "echt", "wirklich",
        "lol", "haha", "hehe",
    }

    def _is_only_trivial(self, msg_lower):
        """Check if message is purely trivial (matches exact or is very short smalltalk)."""
        stripped = msg_lower.strip().rstrip("!.?")

        # Check known smalltalk phrases (multi-word)
        smalltalk = ["wie geht", "how are", "was machst", "was gibt", "was geht", "was laeuft",
                     "wer bist", "was bist", "who are"]
        for s in smalltalk:
            if s in stripped:
                return True

        # Check if the message IS an exact trivial word/phrase
        if stripped in self.TRIVIAL_EXACT:
            return True

        # Very short (1-2 words) that start with a trivial word
        words = stripped.split()
        if len(words) <= 2 and words[0] in self.TRIVIAL_EXACT:
            return True

        return False

    def _trivial_response(self, msg_lower):
        # Only match if the message is purely trivial
        if not self._is_only_trivial(msg_lower):
            return ""

        if any(g in msg_lower for g in ["hi", "hey", "hallo", "moin", "servus", "hello", "yo", "na", "sup"]):
            return "Hey! Was geht?"
        if any(g in msg_lower for g in ["tschüss", "bye", "ciao", "auf wiedersehen", "see you"]):
            return "Bis dann!"
        if any(t in msg_lower for t in ["danke", "thanks", "thx", "cheers"]):
            return "Gern!"
        if any(h in msg_lower for h in ["wie geht", "how are", "was machst", "was gibt", "was geht", "was laeuft"]):
            return "Laeuft! Und selbst?"
        if any(w in msg_lower for w in ["wer bist", "was bist", "who are"]):
            return "Nexus. Persoenlicher Assistent."
        if any(y in msg_lower for y in ["ja", "yep", "ok", "okay", "klar", "stimmt", "genau"]):
            return "Verstanden."
        if any(n in msg_lower for n in ["nein", "nope", "nö"]):
            return "Ok, kein Thema."
        if any(r in msg_lower for r in ["klingt gut", "cool", "geil", "super", "toll", "nice", "krass", "perfekt"]):
            return "Freut mich!"
        if any(r in msg_lower for r in ["verstehe", "kapier", "aha", "echt", "wirklich"]):
            return "Jep."
        if any(r in msg_lower for r in ["lol", "haha", "hehe"]):
            return "😄"
        return "Verstanden."

    def route(self, user_message, context=""):
        decision = self.classify_intent(user_message, context)
        log.info(
            "Router: intent=%s confidence=%.2f needs_worker=%s model=%s",
            decision.intent, decision.confidence, decision.needs_worker, decision.model_key,
        )
        return decision

    def critique_response(self, original_query, response):
        messages = [
            Message("system",
                "Du bist ein Kritiker. Pruefe die Antwort auf: "
                "1) Halluzinationen 2) Faktenfehler 3) Off-topic 4) Unvollstaendigkeit. "
                "Antworte nur 'OK' wenn die Antwort gut ist, oder eine kurze Korrektur maximal 2 Saetze."),
            Message("user", "Frage: " + original_query + " // Antwort: " + response[:1500]),
        ]

        critic = self.llm.chat(
            messages,
            model_key=self.critic_model,
            max_tokens=self.critic_max_tokens,
        )

        content = critic.content.strip()
        if content.upper() in ("OK", "OK."):
            return ""

        return content

    def compress_context(self, messages, strategy="recent"):
        if strategy == "full" or len(messages) <= 5:
            return messages

        if strategy == "recent":
            system_msgs = [m for m in messages if m.role == "system"]
            recent = [m for m in messages if m.role != "system"][-4:]
            return system_msgs + recent

        if strategy == "summary":
            system_msgs = [m for m in messages if m.role == "system"]
            non_system = [m for m in messages if m.role != "system"]

            if len(non_system) <= 5:
                return messages

            to_summarize = non_system[:-3]
            recent = non_system[-3:]

            summary_parts = []
            for m in to_summarize:
                summary_parts.append(m.role + ": " + m.content[:200])
            summary_text = " | ".join(summary_parts)

            summary_response = self.llm.chat(
                [
                    Message("system", "Fasse diesen Gespraechsverlauf in 2-3 Saetzen zusammen. Nur die wichtigsten Fakten."),
                    Message("user", summary_text),
                ],
                model_key=self.router_model,
                max_tokens=256,
            )

            summary_msg = Message("system", "Zusammenfassung frueherer Nachrichten: " + summary_response.content)
            return system_msgs + [summary_msg] + recent

        return messages