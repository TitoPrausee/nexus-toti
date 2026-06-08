"""
NEXUS v8.1 — Personalization Engine
First-contact personalization: builds a user profile through natural conversation.
Turns the default "Hi, what can I do?" into a genuine getting-to-know-you exchange.
"""

import logging
from typing import Optional
from dataclasses import dataclass, field

log = logging.getLogger("nexus.personalization")


@dataclass
class UserOnboarding:
    """Tracks what we know about a new user and what we still want to learn."""
    user_id: str = ""
    name: Optional[str] = None
    language: str = "de"
    onboarding_phase: int = 0  # 0=just started, 1=got name, 2=got context, 3=completed
    interests: list = field(default_factory=list)
    work_context: Optional[str] = None
    communication_style: str = "normal"  # terse, normal, verbose
    questions_asked: list = field(default_factory=list)  # Track what onboarding questions we asked
    onboarding_complete: bool = False


class PersonalizationEngine:
    """
    Drives first-contact personalization.
    
    Instead of generic greetings, Nexus tries to learn about the user:
    Phase 0: Greet + ask name
    Phase 1: Ask what they work on / are interested in
    Phase 2: Ask communication preference (short/normal/detailed)
    Phase 3: Onboarding complete — normal interaction
    
    This only runs for the first few messages. After that, the soul's
    relationship system takes over for ongoing adaptation.
    """

    ONBOARDING_QUESTIONS = {
        "de": [
            "Wie heißt du?",                          # Phase 0→1
            "Was beschäftigt dich gerade? Arbeit, Projekt, Hobby?",  # Phase 1→2
            "Kurz und knapp oder lieber ausführlich?",  # Phase 2→3
        ],
        "en": [
            "What's your name?",                        # Phase 0→1
            "What are you working on? Work, projects, hobbies?",  # Phase 1→2
            "Brief and concise, or more detailed?",     # Phase 2→3
        ],
    }

    def __init__(self, soul=None):
        self.soul = soul
        self._onboardings: dict[str, UserOnboarding] = {}

    def get_or_create_onboarding(self, user_id: str) -> UserOnboarding:
        """Get existing onboarding state or create a new one."""
        if user_id not in self._onboardings:
            # Check if soul already knows this user
            if self.soul and user_id in self.soul.relationships:
                rel = self.soul.relationships[user_id]
                if rel.conversation_count > 3 and rel.name:
                    # Already onboarded — skip
                    onboard = UserOnboarding(
                        user_id=user_id,
                        name=rel.name,
                        language=rel.language or "de",
                        onboarding_phase=3,
                        work_context=rel.preferences[0] if rel.preferences else None,
                        onboarding_complete=True,
                    )
                    self._onboardings[user_id] = onboard
                    return onboard
            
            self._onboardings[user_id] = UserOnboarding(user_id=user_id)
        
        return self._onboardings[user_id]

    def generate_greeting(self, user_id: str) -> str:
        """Generate a personalized greeting based on onboarding phase.
        
        Returns a greeting message that either:
        - Welcomes a new user and starts personalization
        - Continues an ongoing onboarding conversation
        - Gives a brief greeting for returning users
        """
        onboard = self.get_or_create_onboarding(user_id)
        
        # Already familiar — brief greeting
        if onboard.onboarding_complete:
            return self._returning_greeting(onboard)
        
        # New user or in-progress onboarding
        return self._onboarding_greeting(onboard)

    def process_response(self, user_id: str, user_message: str) -> dict:
        """Process a user response during onboarding.
        
        Returns dict with:
        - learned: what we learned from this response
        - phase_advanced: whether we moved to the next phase
        - personalization_hints: suggestions for adapting the conversation
        """
        onboard = self.get_or_create_onboarding(user_id)
        result = {
            "learned": {},
            "phase_advanced": False,
            "personalization_hints": [],
        }

        if onboard.onboarding_complete:
            return result

        msg_lower = user_message.lower().strip()

        # ── Phase 0→1: Extract name ──
        if onboard.onboarding_phase == 0:
            name = self._extract_name(user_message)
            if name:
                onboard.name = name
                onboard.onboarding_phase = 1
                result["learned"]["name"] = name
                result["phase_advanced"] = True
            else:
                # User didn't give a name, that's fine — advance anyway
                onboard.onboarding_phase = 1
                result["phase_advanced"] = True

        # ── Phase 1→2: Extract interests/context ──
        elif onboard.onboarding_phase == 1:
            interests = self._extract_interests(user_message)
            work_ctx = self._extract_work_context(user_message)
            if interests:
                onboard.interests.extend(interests)
                result["learned"]["interests"] = interests
            if work_ctx:
                onboard.work_context = work_ctx
                result["learned"]["work_context"] = work_ctx
            
            # Always advance — even short answers give us something
            onboard.onboarding_phase = 2
            result["phase_advanced"] = True

        # ── Phase 2→3: Extract communication preference ──
        elif onboard.onboarding_phase == 2:
            style = self._detect_comm_style(user_message)
            onboard.communication_style = style
            result["learned"]["communication_style"] = style
            onboard.onboarding_phase = 3
            onboard.onboarding_complete = True
            result["phase_advanced"] = True

        # ── Update soul relationship ──
        if self.soul and result["learned"]:
            self._update_soul(user_id, onboard, result["learned"])

        return result

    def should_personalize(self, user_id: str) -> bool:
        """Whether we should add personalization context to the system prompt."""
        onboard = self.get_or_create_onboarding(user_id)
        return onboard.onboarding_phase < 3

    def get_system_prompt_addition(self, user_id: str) -> str:
        """Get personalization hints to add to the system prompt."""
        onboard = self.get_or_create_onboarding(user_id)
        
        if onboard.onboarding_complete:
            return ""
        
        parts = []
        
        if onboard.onboarding_phase == 0:
            parts.append(
                "WICHTIG: Der Nutzer ist neu. Begrüße ihn natürlich und frag nach seinem Namen. "
                "Kein generisches 'Wie kann ich helfen?' — mach es persönlich."
            )
        elif onboard.onboarding_phase == 1:
            name = onboard.name or "der Nutzer"
            parts.append(
                f"Du kennst den Nutzer als {name}. Frag nach was ihn beschäftigt — "
                f"Arbeit, Projekte, Interessen. Mach es kurz und natürlich, kein Interview."
            )
        elif onboard.onboarding_phase == 2:
            parts.append(
                "Fast am Ziel. Frag den Nutzer ob er lieber kurz & knackig oder "
                "ausführlich antworten möchte. Dann kennst du ihn genug."
            )
        
        # Communication style hint
        if onboard.communication_style == "terse":
            parts.append("Der Nutzer bevorzugt kurze Antworten — 1-2 Sätze maximal.")
        elif onboard.communication_style == "verbose":
            parts.append("Der Nutzer bevorzugt ausführliche Antworten mit Erklärungen.")
        
        return chr(10).join(parts) if parts else ""

    # ─── Internal Methods ──────────────────────────────

    def _returning_greeting(self, onboard: UserOnboarding) -> str:
        """Brief greeting for a returning user we already know."""
        name = onboard.name or ""
        time_greeting = self._time_greeting()
        
        if name:
            return f"{time_greeting}{name}! Was steht an?"
        return f"{time_greeting}Was kann ich für dich tun?"

    def _onboarding_greeting(self, onboard: UserOnboarding) -> str:
        """Greeting tailored to onboarding phase."""
        lang = onboard.language or "de"
        questions = self.ONBOARDING_QUESTIONS.get(lang, self.ONBOARDING_QUESTIONS["de"])
        
        if onboard.onboarding_phase == 0:
            # First contact
            return (
                "Hey! Ich bin Nexus, dein KI-Agent. "
                f"{questions[0]}"
            )
        elif onboard.onboarding_phase == 1:
            name = onboard.name or "Du"
            return f"Hey {name}! {questions[1]}"
        elif onboard.onboarding_phase == 2:
            return questions[2]
        
        return "Was kann ich für dich tun?"

    def _time_greeting(self) -> str:
        """Time-aware greeting."""
        from datetime import datetime
        hour = datetime.now().hour
        if 6 <= hour < 10:
            return "Morgen! "
        elif 10 <= hour < 18:
            return "Hey! "
        elif 18 <= hour < 22:
            return "Nabend! "
        else:
            return "Hey! "

    def _extract_name(self, text: str) -> Optional[str]:
        """Extract a name from user text."""
        patterns = [
            r"(?:ich bin|ich heiße|mein name ist|ich heiße)\s+(\w+)",
            r"(?:i'm|i am|my name is|call me)\s+(\w+)",
        ]
        import re
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Filter out false positives
                if name.lower() not in {"ein", "a", "the", "nicht", "not", "auch", "auch"}:
                    return name
        
        # Single word response might be a name
        words = text.strip().split()
        if len(words) == 1 and len(words[0]) > 1 and words[0][0].isupper():
            return words[0]
        
        return None

    def _extract_interests(self, text: str) -> list:
        """Extract interests/topics from user text."""
        interests = []
        interest_keywords = {
            "programming": ["code", "programmier", "entwickl", "software", "app", "web", "python", "javascript", "rust"],
            "gaming": ["spiel", "game", "gaming", "minecraft", "steam"],
            "design": ["design", "ui", "ux", "css", "figma", "grafik"],
            "music": ["musik", "music", "guitar", "klavier", "produktion"],
            "fitness": ["sport", "fitness", "gym", "training", "laufen", "workout"],
            "business": ["business", "startup", "gründ", "unternehm", "marketing", "vertrieb"],
            "science": ["forsch", "wissenschaft", "science", "ki", "ai", "machine learning"],
            "cooking": ["koch", "cook", "rezept", "essen", "food"],
            "travel": ["reise", "travel", "urlaub", "vacation", "backpack"],
        }
        
        text_lower = text.lower()
        for interest, keywords in interest_keywords.items():
            if any(kw in text_lower for kw in keywords):
                interests.append(interest)
        
        return interests[:5]  # Max 5 interests

    def _extract_work_context(self, text: str) -> Optional[str]:
        """Extract work/project context from user text."""
        import re
        patterns = [
            r"(?:ich arbeite|ich bin|arbeit als|work as|work at|ich mach)\s+(.+?)(?:\.|!|$)",
            r"(?:mein projekt|my project|ich entwickle|i develop|ich bau)\s+(.+?)(?:\.|!|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                ctx = match.group(1).strip()
                if 5 <= len(ctx) <= 150:
                    return ctx
        return None

    def _detect_comm_style(self, text: str) -> str:
        """Detect communication style preference from user text."""
        terse_markers = {"kurz", "knapp", "knappig", "short", "brief", "concise", "schnell", "quick", "direkt"}
        verbose_markers = {"ausführlich", "detailliert", "detailed", "verbose", "erklärt", "explain", "lang"}
        
        text_lower = text.lower()
        if any(m in text_lower for m in terse_markers):
            return "terse"
        if any(m in text_lower for m in verbose_markers):
            return "verbose"
        
        # Default based on message length
        word_count = len(text.split())
        if word_count <= 5:
            return "terse"
        elif word_count >= 20:
            return "verbose"
        return "normal"

    def _update_soul(self, user_id: str, onboard: UserOnboarding, learned: dict):
        """Update soul relationship with what we learned during onboarding."""
        if not self.soul:
            return
        
        from nexus.soul import UserRelation
        
        if user_id not in self.soul.relationships:
            self.soul.relationships[user_id] = UserRelation()
        
        rel = self.soul.relationships[user_id]
        
        if "name" in learned:
            rel.name = learned["name"]
        
        if "interests" in learned:
            rel.preferences.extend(learned["interests"])
            # Dedupe
            rel.preferences = list(set(rel.preferences))
        
        if "work_context" in learned:
            if learned["work_context"] not in rel.notes:
                rel.notes.append(learned["work_context"])
        
        if "communication_style" in learned:
            style = learned["communication_style"]
            if style == "terse":
                rel.verbosity_preference = 0.2
            elif style == "verbose":
                rel.verbosity_preference = 0.8
            else:
                rel.verbosity_preference = 0.4
        
        rel.conversation_count += 1
        self.soul.save()
