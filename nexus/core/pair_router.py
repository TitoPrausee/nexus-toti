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
        "code", "programmier", "implementier", "refactor", "debug", "fix",
        "erstelle", "schreibe", "analysier", "recherchier", "vergleiche",
        "architektur", "design", "deploy", "erkläre wie", "warum funktioniert",
        "baue", "entwickle", "optimier", "migrat",
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
            )

        complex_hits = sum(1 for kw in self.COMPLEX_KEYWORDS if kw in msg_lower)
        word_count = len(user_message.split())
        is_long = word_count > 25

        if complex_hits >= 2 or (complex_hits >= 1 and is_long):
            return RoutingDecision(
                intent=IntentType.COMPLEX,
                confidence=0.8,
                needs_worker=True,
                model_key="default",
                context_compression="summary",
                max_worker_tokens=self.worker_max_tokens,
            )

        question_words = {"wie", "warum", "wieso", "was", "wobei", "welche", "how", "why", "what", "which"}
        question_count = sum(1 for w in question_words if w in msg_lower)
        if question_count >= 2:
            return RoutingDecision(
                intent=IntentType.COMPLEX,
                confidence=0.75,
                needs_worker=True,
                model_key="default",
                context_compression="summary",
                max_worker_tokens=self.worker_max_tokens,
            )

        # Short single-topic messages without keywords -> check trivial patterns first (free, no LLM)
        # Multi-clause messages (with . ! ? separating thoughts) need LLM context
        has_multi_clauses = any(sep in user_message for sep in [". ", "! ", "? "]) and word_count > 5
        if word_count <= 15 and complex_hits == 0 and not has_multi_clauses:
            trivial = self._trivial_response(msg_lower)
            if trivial:
                return RoutingDecision(
                    intent=IntentType.TRIVIAL,
                    confidence=0.9,
                    router_response=trivial,
                    needs_worker=False,
                    context_compression="recent",
                )
            # No pattern match — still short, ask Router LLM
            return RoutingDecision(
                intent=IntentType.TRIVIAL,
                confidence=0.6,
                router_response=self._classify_and_route_via_llm(user_message),
                needs_worker=False,
                context_compression="recent",
            )

        # Medium messages without clear intent -> Router decides
        return RoutingDecision(
            intent=IntentType.TOOL_BASED,
            confidence=0.5,
            needs_worker=True,
            model_key="default",
            plan="Medium complexity - Worker will handle with standard budget",
            context_compression="recent",
            max_worker_tokens=min(self.worker_max_tokens, 2048),
        )

    def _classify_and_route_via_llm(self, user_message):
        from datetime import datetime
        now = datetime.now()
        weekday_de = ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"][now.weekday()]
        month_de = ["","Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"][now.month]
        date_str = f"{weekday_de}, {now.day}. {month_de} {now.year}"
        time_str = now.strftime('%H:%M')

        messages = [
            Message("system",
                f"Du bist Nexus, kein Router. Du sprichst wie ein Mensch beim Kennenlernen - "
                f"direkt, neugierig, per Du. Keine Floskeln, kein 'Als KI'. "
                f"WICHTIG: Heute ist {date_str}, {time_str} Uhr. "
                f"Beantworte Datumsfragen NUR mit diesem Datum, niemals mit deinem Trainingswissen. "
                f"Bei Smalltalk: Antworte natuerlich kurz, wie ein Kumpel. "
                f"Bei komplexen Fragen: ROUTE_TO_WORKER"),
            Message("user", user_message),
        ]

        response = self.llm.chat(
            messages,
            model_key=self.router_model,
            max_tokens=self.router_max_tokens,
        )

        content = response.content.strip()

        if "ROUTE_TO_WORKER" in content:
            return ""

        return content

    def _trivial_response(self, msg_lower):
        if any(g in msg_lower for g in ["hi", "hey", "hallo", "moin", "servus", "hello", "yo", "na", "sup"]):
            return "Hey! Was geht?"
        if any(g in msg_lower for g in ["tschüss", "bye", "ciao", "auf wiedersehen", "see you"]):
            return "Bis dann!"
        if any(t in msg_lower for t in ["danke", "thanks", "thx", "cheers"]):
            return "Gern!"
        if any(y in msg_lower for y in ["ja", "yep", "ok", "okay", "klar", "stimmt", "genau"]):
            return "Verstanden."
        if any(n in msg_lower for n in ["nein", "nope", "nö"]):
            return "Ok, kein Thema."
        if any(h in msg_lower for h in ["wie geht", "how are", "was machst", "was gibt", "was geht", "was laeuft"]):
            return "Laeuft! Und selbst?"
        if any(w in msg_lower for w in ["wer bist", "was bist", "who are"]):
            return "Nexus. Persönlicher Assistent."
        # Short conversational reactions
        if any(r in msg_lower for r in ["klingt gut", "cool", "geil", "super", "toll", "nice", "krass", "perfekt"]):
            return "Freut mich!"
        if any(r in msg_lower for r in ["verstehe", "kapier", "aha", "echt", "wirklich"]):
            return "Jep."
        if any(r in msg_lower for r in ["lol", "haha", "hehe"]):
            return "😄"
        return ""

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