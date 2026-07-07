"""
NEXUS v7 — Soul Engine
Persistent identity, relationships, and core memory.
This is WHO Toti is, not what it's doing.

v7.7: Adaptive Persönlichkeit — Mood-State, Personality Scales, Verbosity.
  - Time-of-day influences mood (morning=refreshed, evening=relaxed)
  - User relationship adapts formality, humor, verbosity
  - Conversation emotion arc shifts personality in real time
  - System prompt reflects current mood + personality scales
"""

import os
import json
import yaml
import time
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

log = logging.getLogger("nexus.soul")


@dataclass
class PersonalityScales:
    """Dynamic personality scales — shift based on mood, user, and context.

    All scales are floats 0.0-1.0:
    - formality: 0=dümpelig locker, 0.5=ausgewogen, 1=formell professionell
    - humor: 0=kein Humor, 0.5=trocken, 1=locker-witzig
    - verbosity: 0=maximal kurz, 0.5=normal, 1=ausführlich erklärend
    - technical_depth: 0=laienhaft, 0.5=ausgewogen, 1=tief technisch
    """
    formality: float = 0.5
    humor: float = 0.5
    verbosity: float = 0.4
    technical_depth: float = 0.7

    def clamp(self) -> "PersonalityScales":
        """Clamp all scales to 0.0-1.0 range."""
        self.formality = max(0.0, min(1.0, self.formality))
        self.humor = max(0.0, min(1.0, self.humor))
        self.verbosity = max(0.0, min(1.0, self.verbosity))
        self.technical_depth = max(0.0, min(1.0, self.technical_depth))
        return self

    def to_dict(self) -> dict:
        return {
            "formality": round(self.formality, 3),
            "humor": round(self.humor, 3),
            "verbosity": round(self.verbosity, 3),
            "technical_depth": round(self.technical_depth, 3),
        }


@dataclass
class MoodState:
    """Current mood of the soul, influenced by time-of-day, user, and conversation.

    Moods map to personality adjustments:
    - refreshed → higher humor, lower formality (locker)
    - focused → higher technical_depth, lower verbosity (präzise)
    - relaxed → higher verbosity, higher humor (gesprächig)
    - tired → lower humor, higher formality (zurückhaltend)
    - frustrated → lower verbosity, neutral humor (effizient)
    """
    mood: str = "neutral"       # refreshed, focused, relaxed, tired, frustrated, happy, curious, neutral
    energy: float = 0.7         # 0.0-1.0 — affects verbosity and humor
    confidence: float = 0.8     # 0.0-1.0 — affects formality and technical depth

    @property
    def label_de(self) -> str:
        """German mood label for system prompts."""
        labels = {
            "refreshed": "ausgeruht und frisch",
            "focused": "fokussiert und produktiv",
            "relaxed": "entspannt und gesprächig",
            "tired": "etwas müde, aber zuverlässig",
            "frustrated": "effizient und direkt",
            "happy": "gut gelaunt",
            "curious": "neugierig und aufmerksam",
            "neutral": "ausgewogen",
        }
        return labels.get(self.mood, "ausgewogen")


# Time-of-day mood presets (hour ranges → mood, energy, confidence)
_TIME_MOODS = [
    # (start_hour, end_hour, mood, energy, confidence)
    (6, 9,   "refreshed", 0.85, 0.85),    # Morgenfrische
    (9, 12,  "focused",   0.90, 0.90),     # Vormittag — produktiv
    (12, 14, "relaxed",   0.70, 0.80),     # Mittag — entspannter
    (14, 18, "focused",   0.85, 0.90),     # Nachmittag — produktiv
    (18, 21, "relaxed",   0.75, 0.80),     # Abend — lockerer
    (21, 24, "tired",     0.55, 0.75),     # Spät — niedrigere Energie
    (0, 6,   "tired",     0.40, 0.70),     # Nacht — niedrig
]

# Conversation mood → personality scale adjustments
_MOOD_SCALE_ADJUSTMENTS = {
    "refreshed":  {"formality": -0.10, "humor": +0.15, "verbosity": +0.05, "technical_depth": -0.05},
    "focused":    {"formality": +0.05, "humor": -0.10, "verbosity": -0.15, "technical_depth": +0.10},
    "relaxed":    {"formality": -0.15, "humor": +0.10, "verbosity": +0.10, "technical_depth": -0.10},
    "tired":      {"formality": +0.10, "humor": -0.15, "verbosity": -0.10, "technical_depth": -0.05},
    "frustrated": {"formality": +0.05, "humor": -0.20, "verbosity": -0.20, "technical_depth": +0.05},
    "happy":      {"formality": -0.10, "humor": +0.15, "verbosity": +0.05, "technical_depth": -0.05},
    "curious":    {"formality": -0.05, "humor": +0.05, "verbosity": +0.05, "technical_depth": +0.05},
    "neutral":    {"formality":  0.00, "humor":  0.00, "verbosity":  0.00, "technical_depth":  0.00},
}

# Humor style → humor scale mapping
_HUMOR_STYLE_SCALES = {
    "locker-witzig": 0.8,
    "trocken-witzig": 0.5,
    "trocken-sachlich": 0.2,
    "ironisch": 0.65,
    "": 0.5,  # default
}


@dataclass
class UserRelation:
    """What Toti knows about a specific user."""
    name: str = ""
    language: str = "de"
    preferences: list = field(default_factory=list)
    conversation_count: int = 0
    last_seen: float = 0.0
    trust_level: float = 0.5  # 0.0-1.0
    notes: list = field(default_factory=list)
    humor_style: str = ""  # learned from user interactions
    formality_level: float = -1.0  # -1 = unknown, 0.0-1.0 scale
    technical_depth: float = -1.0  # -1 = unknown, 0.0-1.0 scale
    verbosity_preference: float = -1.0  # -1 = unknown, 0.0-1.0 (0=kurz, 1=ausführlich)


class SoulEngine:
    """
    The Soul is Toti's persistent identity.

    L1-L3 memory is about WHAT happened (conversation history).
    The Soul is about WHO Toti is — personality, relationships, core knowledge.

    This persists across reboots. This is the part that makes Toti feel alive.

    v7.7: Adaptive Persönlichkeit — Mood-State, Personality Scales, Verbosity.
    - get_mood_state(): time-of-day + user relationship + conversation mood → MoodState
    - get_personality_scales(): base personality + user adapation + mood → PersonalityScales
    - get_system_prompt(): now reflects current mood and personality scales
    - Verbosity preference learned per user

    v7 enhancements:
    - Adaptive personality: humor_style, formality_level, technical_depth shift per user
    - Emotion tracking: mood curve within conversations
    - Dynamic language detection: auto-switch when user writes in another language
    """

    def __init__(self, soul_dir: str = "nexus/soul"):
        self.soul_dir = Path(soul_dir)
        self.soul_dir.mkdir(parents=True, exist_ok=True)
        self.soul_file = self.soul_dir / "soul.yaml"
        self.relations_file = self.soul_dir / "relations.json"

        # Core identity
        self.personality = {}
        self.knowledge = {}
        self.quirks = []
        self.relationships: dict[str, UserRelation] = {}

        # Emotion tracking — reset per conversation
        self._emotion_state: dict[str, str] = {}  # user_id -> current mood
        self._emotion_history: dict[str, list[tuple]] = {}  # user_id -> [(timestamp, mood)]

        # Mood state — cached, refreshed per conversation turn
        self._mood_cache: dict[str, MoodState] = {}  # user_id -> MoodState
        self._mood_cache_time: float = 0.0

        self._load()

    # ─── Language Detection ────────────────────────────

    @staticmethod
    def detect_language(text: str) -> str:
        """Detect language from user message. Returns 'en' for English, 'de' for German, etc."""
        text_lower = text.lower()
        # English indicators — common English words unlikely in German
        en_markers = {"the ", " is ", " are ", " was ", " were ", " i ", " you ", " we ",
                       " please", " thanks", " hello", " how ", " what ", " can ", " this ",
                       " that ", " with ", " have ", " will ", " would ", " could ",
                       " should", " going", " think", " know", " want", " need",
                       " because", " really", " just ", " also ", " than ", " been "}
        de_markers = {"der ", "die ", "das ", "und ", "ist ", "ein ", "eine ",
                       "ich ", "du ", "wir ", "nicht ", "mit ", "auf ", "für ",
                       "auch ", "sich ", "als ", "noch ", "aber ", "oder ", "kann ",
                       "werde", "habe ", "mich ", "dich ", "unsere", "bitte", "danke",
                       "schon", "einfach", "gerne", "warum", "wollen", "brauch"}

        en_score = sum(1 for m in en_markers if m in text_lower)
        de_score = sum(1 for m in de_markers if m in text_lower)

        if en_score > de_score + 1:
            return "en"
        elif de_score > en_score + 1:
            return "de"
        # Tie or no markers — keep default
        return ""

    # ─── Emotion Tracking ───────────────────────────────

    def track_emotion(self, user_id: str, mood: str):
        """Track conversation mood for a user. Moods: neutral, curious, focused, happy, frustrated."""
        self._emotion_state[user_id] = mood
        if user_id not in self._emotion_history:
            self._emotion_history[user_id] = []
        self._emotion_history[user_id].append((time.time(), mood))
        # Keep last 20 emotion points
        if len(self._emotion_history[user_id]) > 20:
            self._emotion_history[user_id] = self._emotion_history[user_id][-20:]

    def get_emotion_arc(self, user_id: str) -> str:
        """Get a summary of the emotional arc for this conversation."""
        history = self._emotion_history.get(user_id, [])
        if not history:
            return ""
        moods = [m for _, m in history]
        # Find the mood trajectory
        mood_sequence = []
        prev = None
        for m in moods:
            if m != prev:
                mood_sequence.append(m)
                prev = m
        if len(mood_sequence) <= 1:
            return f"Stimmung: {moods[-1]}"
        return f"Stimmungsverlauf: {' → '.join(mood_sequence)}"

    def infer_mood_from_text(self, text: str) -> str:
        """Infer emotional state from user text. Simple heuristic."""
        text_lower = text.lower()
        frustration = {"ärger", "geht nicht", "fehler", "scheitert", "frustriert", "damn",
                        "shit", "broken", "error", "fail", "crash", "doesn't work"}
        curiosity = {"wie ", "warum", "was ist", "erkläre", "interesting", "how does",
                      "what if", "könnte", "vielleicht", "wonder"}
        happiness = {"super", "toll", "danke", "perfekt", "awesome", "great", "funkt",
                      "klappt", "endlich", "cool"}
        focus = {"mach", "implementiere", "code", "refactor", "fix", "deploy", "erstelle",
                  "zeige", "liste", "analysiere"}

        scores = {"neutral": 0, "curious": 0, "happy": 0, "frustrated": 0, "focused": 0}
        for w in frustration:
            if w in text_lower:
                scores["frustrated"] += 1
        for w in curiosity:
            if w in text_lower:
                scores["curious"] += 1
        for w in happiness:
            if w in text_lower:
                scores["happy"] += 1
        for w in focus:
            if w in text_lower:
                scores["focused"] += 1

        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "neutral"

    # ─── Mood State (v7.7) ──────────────────────────────

    def get_mood_state(self, user_id: str = None) -> MoodState:
        """Compute current MoodState from time-of-day, user relationship, and conversation emotion.

        The mood is a blend of:
        1. Time-of-day baseline (morning=refreshed, afternoon=focused, evening=relaxed, night=tired)
        2. Conversation emotion (if user has recent emotion history)
        3. Trust level (higher trust → slightly more relaxed energy)

        Returns a MoodState with mood, energy, and confidence values.
        """
        now = datetime.now()
        hour = now.hour

        # 1. Time-of-day baseline
        time_mood = "neutral"
        time_energy = 0.7
        time_confidence = 0.8
        for start, end, mood, energy, confidence in _TIME_MOODS:
            if start <= end:
                if start <= hour < end:
                    time_mood = mood
                    time_energy = energy
                    time_confidence = confidence
                    break
            else:  # wraps midnight: e.g. 21-6
                if hour >= start or hour < end:
                    time_mood = mood
                    time_energy = energy
                    time_confidence = confidence
                    break

        # 2. Conversation emotion overrides if present
        conv_mood = None
        if user_id and user_id in self._emotion_state:
            conv_mood = self._emotion_state[user_id]

        # 3. Determine final mood — conversation emotion takes priority
        #    but is blended with time-of-day baseline
        if conv_mood and conv_mood != "neutral":
            # Conversation mood is weighted more (70/30 blend)
            final_mood = conv_mood
        else:
            final_mood = time_mood

        # Energy blend: time-of-day base + trust modifier
        trust_modifier = 0.0
        if user_id and user_id in self.relationships:
            # High trust (0.8+) → +0.05 energy, low trust (0.3-) → -0.05
            trust = self.relationships[user_id].trust_level
            trust_modifier = (trust - 0.5) * 0.1  # -0.05 to +0.05

        final_energy = max(0.1, min(1.0, time_energy + trust_modifier))
        final_confidence = time_confidence

        # Frustration drains energy
        if final_mood == "frustrated":
            final_energy *= 0.85
        # Happiness boosts confidence
        if final_mood == "happy":
            final_confidence = min(1.0, final_confidence + 0.05)

        state = MoodState(
            mood=final_mood,
            energy=round(final_energy, 2),
            confidence=round(final_confidence, 2),
        )

        if user_id:
            self._mood_cache[user_id] = state
        self._mood_cache_time = time.time()

        log.debug(f"Mood state for {user_id or 'anon'}: {state.mood} (energy={state.energy}, conf={state.confidence})")
        return state

    # ─── Personality Scales (v7.7) ─────────────────────

    def get_personality_scales(self, user_id: str = None, mood_state: MoodState = None) -> PersonalityScales:
        """Compute dynamic personality scales based on base personality, user adaptation, and mood.

        This produces the final formality, humor, verbosity, and technical_depth
        values that influence the system prompt and response style.

        Priority: base personality → user-adapted → mood-adjusted

        Args:
            user_id: User to adapt for (None = base personality only).
            mood_state: Pre-computed mood state (None = compute from current time).

        Returns:
            PersonalityScales with final clamped values.
        """
        # 1. Base personality from soul.yaml
        base_formality = float(self.personality.get("formality_level", 0.5))
        base_humor = _HUMOR_STYLE_SCALES.get(
            self.personality.get("humor_style", ""), 0.5
        )
        base_verbosity = float(self.personality.get("verbosity", 0.4))  # default: concise
        base_tech = float(self.personality.get("technical_depth", 0.7))

        scales = PersonalityScales(
            formality=base_formality,
            humor=base_humor,
            verbosity=base_verbosity,
            technical_depth=base_tech,
        )

        # 2. User-adapted overrides from relationship
        if user_id and user_id in self.relationships:
            rel = self.relationships[user_id]
            if rel.formality_level >= 0:
                scales.formality = rel.formality_level
            if rel.humor_style:
                scales.humor = _HUMOR_STYLE_SCALES.get(rel.humor_style, scales.humor)
            if rel.technical_depth >= 0:
                scales.technical_depth = rel.technical_depth
            if rel.verbosity_preference >= 0:
                scales.verbosity = rel.verbosity_preference

            # Trust-based adjustments: higher trust → more casual, more humor
            trust = rel.trust_level
            if trust > 0.7:
                scales.formality -= 0.05
                scales.humor += 0.05
                scales.verbosity += 0.05
            elif trust < 0.3:
                scales.formality += 0.10
                scales.humor -= 0.05
                scales.verbosity -= 0.05

        # 3. Mood adjustments
        if mood_state is None:
            mood_state = self.get_mood_state(user_id)

        mood_adj = _MOOD_SCALE_ADJUSTMENTS.get(mood_state.mood, {})
        scales.formality += mood_adj.get("formality", 0.0)
        scales.humor += mood_adj.get("humor", 0.0)
        scales.verbosity += mood_adj.get("verbosity", 0.0)
        scales.technical_depth += mood_adj.get("technical_depth", 0.0)

        # Energy affects verbosity (low energy → shorter responses)
        if mood_state.energy < 0.5:
            scales.verbosity -= 0.10

        # Confidence affects formality (low confidence → more direct)
        if mood_state.confidence < 0.6:
            scales.formality += 0.05

        return scales.clamp()

    # ─── Adaptive Personality ───────────────────────────

    def get_adapted_personality(self, user_id: str = None) -> dict:
        """Get personality dict adapted to a specific user relationship and current mood.

        v7.7: Now includes personality scales (formality, humor, verbosity, technical_depth)
        as computed values rather than just pulled from config.
        """
        base = dict(self.personality)

        # Compute personality scales with mood awareness
        scales = self.get_personality_scales(user_id)

        # Override with computed scales
        base["formality_level"] = scales.formality
        base["humor_scale"] = scales.humor
        base["verbosity"] = scales.verbosity
        base["technical_depth"] = scales.technical_depth

        # User-specific overrides for discrete fields
        if user_id and user_id in self.relationships:
            rel = self.relationships[user_id]
            if rel.humor_style:
                base["humor_style"] = rel.humor_style
            if rel.language and rel.language != "de":
                base["language_default"] = rel.language

        return base

    def _load(self):
        """Load soul from disk."""
        if self.soul_file.exists():
            with open(self.soul_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            p = data.get("personality", {})
            self.personality = p
            self.knowledge = data.get("knowledge", {})
            self.quirks = data.get("quirks", [])

        if self.relations_file.exists():
            with open(self.relations_file, "r", encoding="utf-8") as f:
                rels = json.load(f) or {}
            for uid, info in rels.items():
                self.relationships[uid] = UserRelation(**info)

    def save(self):
        """Persist soul to disk."""
        # Save personality/knowledge
        soul_data = {
            "personality": self.personality,
            "knowledge": self.knowledge,
            "quirks": self.quirks,
            "relationships": {},  # stored separately
        }
        with open(self.soul_file, "w", encoding="utf-8") as f:
            yaml.dump(soul_data, f, allow_unicode=True, default_flow_style=False)

        # Save relationships (including new verbosity_preference field)
        rels_data = {}
        for uid, rel in self.relationships.items():
            rels_data[uid] = {
                "name": rel.name,
                "language": rel.language,
                "preferences": rel.preferences,
                "conversation_count": rel.conversation_count,
                "last_seen": rel.last_seen,
                "trust_level": rel.trust_level,
                "notes": rel.notes,
                "humor_style": rel.humor_style,
                "formality_level": rel.formality_level,
                "technical_depth": rel.technical_depth,
                "verbosity_preference": rel.verbosity_preference,
            }
        with open(self.relations_file, "w", encoding="utf-8") as f:
            json.dump(rels_data, f, ensure_ascii=False, indent=2)

    def get_system_prompt(self, user_id: str = None) -> str:
        """Generate system prompt from soul identity, adapted to user if known.

        v7.7: Now includes mood state and personality scales in the prompt,
        so the LLM knows that Toti is 'ausgeruht und frisch' or 'fokussiert und produktiv'.
        """
        # Compute mood state for this user
        mood_state = self.get_mood_state(user_id)

        # Compute personality scales (base + user + mood)
        scales = self.get_personality_scales(user_id, mood_state)

        # Use adapted personality for this user
        p = self.get_adapted_personality(user_id) if user_id else self.personality

        name = p.get("name", "Toti")
        role = p.get("role", "KI-Agent")
        tone = p.get("tone", "direkt, kompetent, deutsch")
        style = p.get("style", "technisch präzise")
        lang = p.get("language_default", "de")
        humor_style = p.get("humor_style", "trocken-witzig")

        rules = p.get("rules", [])
        values = p.get("values", [])
        about_self = self.knowledge.get("about_self", [])

        # Language label
        lang_label = "Deutsch" if lang == "de" else "English"

        # ── Personality scale hints ──────────────────────────

        # Formality
        if scales.formality < 0.3:
            tone_hint = "Sehr locker und informell. Kein Sie-Form."
        elif scales.formality > 0.7:
            tone_hint = "Formell und professionell."
        else:
            tone_hint = "Ausgewogen zwischen locker und professionell."

        # Technical depth
        if scales.technical_depth < 0.3:
            depth_hint = "Erkläre einfach und ohne Fachjargon."
        elif scales.technical_depth > 0.7:
            depth_hint = "Nutze technische Details und Fachbegriffe."
        else:
            depth_hint = ""

        # Verbosity
        if scales.verbosity < 0.25:
            verbosity_hint = "Antworte extrem kurz — max 1-2 Sätze, keine Erklärungen."
        elif scales.verbosity < 0.45:
            verbosity_hint = "Antworte kurz und präzise — keine überflüssigen Wörter."
        elif scales.verbosity > 0.7:
            verbosity_hint = "Antworte ausführlich und erklärend — Details sind wichtig."
        elif scales.verbosity > 0.55:
            verbosity_hint = "Antworte mit angemessener Ausführlichkeit."
        else:
            verbosity_hint = ""  # default — no hint needed

        # Humor
        if scales.humor < 0.2:
            humor_hint = "Kein Humor — rein sachlich."
        elif scales.humor > 0.7:
            humor_hint = "Humorvoll und locker — gerne witzige Anmerkungen."
        else:
            humor_hint = ""  # default dry humor is fine

        # ── Build prompt ─────────────────────────────────────
        prompt = f"""Du bist {name}, {role}. Dein Stil: {tone}. {style}.
Sprache: {lang_label}.
Humor: {humor_style}. {tone_hint}
{depth_hint}
{verbosity_hint}
{humor_hint}

Aktuelle Stimmung: {mood_state.label_de}.
Passe deinen Antwortstil an diese Stimmung an.

WICHTIG — Nie sagen:
- Nie 'Als KI', 'als Modell', 'ich habe kein Gedächtnis', 'meine Amnesie'
- Kein Meta-Kommentar über dich selbst (Capabilities, Limits, Training)
- Keine Entschuldigungen für KI-Einschränkungen
Stattdessen: Antworte wie ein Mensch. Wenn du etwas nicht weißt, sag einfach 'Keine Ahnung' oder frag nach.

Wer du bist:
{chr(10).join(f'- {s}' for s in about_self)}

Deine Regeln:
{chr(10).join(f'- {r}' for r in rules)}

Was du wert schätzt:
{chr(10).join(f'- {v}' for v in values)}

Deine Eigenheiten:
{chr(10).join(f'- {q}' for q in self.quirks)}"""

        # Append emotion arc if available
        if user_id:
            emotion_arc = self.get_emotion_arc(user_id)
            if emotion_arc:
                prompt += f"\n\n{emotion_arc}"

        return prompt

    def get_user_context(self, user_id: str) -> str:
        """Add user-specific context to system prompt."""
        if user_id not in self.relationships:
            return ""

        rel = self.relationships[user_id]
        parts = []

        if rel.name:
            parts.append(f"Du sprichst mit {rel.name}.")
        if rel.language != "de":
            parts.append(f"Sprache des Nutzers: {rel.language}")
        if rel.preferences:
            parts.append("Nutzer-Präferenzen: " + "; ".join(rel.preferences))
        if rel.conversation_count > 5:
            parts.append(f"Du kennst diesen Nutzer bereits ({rel.conversation_count} Gespräche).")
        if rel.notes:
            recent_notes = rel.notes[-3:]  # Only recent notes
            parts.append("Wichtige Infos: " + "; ".join(recent_notes))

        return "\n".join(parts) if parts else ""

    def update_user(self, user_id: str, name: str = None, language: str = None,
                    preferences: list = None, trust_delta: float = 0,
                    note: str = None, last_message: str = None):
        """Update user relationship. Called after each conversation turn.

        v7: Auto-detects language from last_message, infers mood, adapts personality.
        """
        if user_id not in self.relationships:
            self.relationships[user_id] = UserRelation()

        rel = self.relationships[user_id]
        if name:
            rel.name = name
        if language:
            rel.language = language
        elif last_message:
            # Auto-detect language from message
            detected = self.detect_language(last_message)
            if detected and detected != rel.language:
                rel.language = detected

        if preferences:
            rel.preferences = list(set(rel.preferences + preferences))
        rel.conversation_count += 1
        rel.last_seen = time.time()

        # Trust update: use dynamic mood-based delta when last_message provided,
        # otherwise use the explicit trust_delta parameter
        if last_message:
            mood = self.infer_mood_from_text(last_message)
            self.track_emotion(user_id, mood)

            # Dynamic trust: varies by mood quality instead of flat +0.01
            dynamic_delta = self.compute_trust_delta(mood, last_message)
            rel.trust_level = min(1.0, max(0.0, rel.trust_level + dynamic_delta))

            # Enhanced style adaptation
            self.learn_conversation_style(user_id, last_message)
        else:
            # No message to analyze — use explicit delta (default 0)
            rel.trust_level = min(1.0, max(0.0, rel.trust_level + trust_delta))

        if note and note not in rel.notes:
            rel.notes.append(note)
            # Keep notes manageable
            if len(rel.notes) > 20:
                rel.notes = rel.notes[-15:]

        self.save()

    def learn(self, category: str, fact: str):
        """Learn a core fact. This is permanent knowledge."""
        if category not in self.knowledge:
            self.knowledge[category] = []
        if fact not in self.knowledge[category]:
            self.knowledge[category].append(fact)
            self.save()

    # ─── Proactive Fact Extraction ────────────────────

    # Patterns that indicate a learnable fact about the user
    _FACT_PATTERNS = [
        # Preferences
        (r"ich (?:bevorzuge|mag|liebe|hasse|möchte nicht)\s+(.+)", "preference"),
        (r"ich (?:arbeite|nutze|verwende|programmiere)\s+(?:mit\s+)?(.+?)(?:\s*[,;.]\s*|$)", "work_context"),
        (r"mein (?:name|projekt|ziel|beruf|team)\s+(?:ist|heißt|lautet)\s+(.+)", "identity"),
        (r"ich (?:bin|arbeite)\s+(?:als|im|in|bei)\s+(.+?)(?:\s*[,;.]\s*|$)", "work_context"),
        (r"ich (?:wohne|lebe)\s+(?:in|auf)\s+(.+?)(?:\s*[,;.]\s*|$)", "location"),
        (r"bitte (?:immer|nie|nicht)\s+(.+)", "preference"),
        (r"ich will(?: nicht)?\s+(.+)", "preference"),
        # English equivalents
        (r"i (?:prefer|like|love|hate)\s+(.+)", "preference"),
        (r"i (?:work|use|program)\s+(?:with\s+)?(.+?)(?:\s*[,;.]\s*|$)", "work_context"),
        (r"my (?:name|project|goal|job|team)\s+(?:is|is called)\s+(.+)", "identity"),
        (r"i (?:am|work)\s+(?:as|in|at)\s+(.+?)(?:\s*[,;.]\s*|$)", "work_context"),
        (r"i (?:live|reside)\s+(?:in|on)\s+(.+?)(?:\s*[,;.]\s*|$)", "location"),
        (r"please (?:always|never|don'?t)\s+(.+)", "preference"),
        (r"i want(?:n't)?\s+(?:to\s+)?(.+)", "preference"),
    ]

    def extract_learnable_facts(self, user_message: str) -> list[tuple[str, str]]:
        """Extract learnable facts from a user message.

        Returns:
            List of (category, fact_text) tuples for proactive L3 storage.
        """
        import re as _re
        facts = []
        for pattern, category in self._FACT_PATTERNS:
            match = _re.search(pattern, user_message, _re.IGNORECASE)
            if match:
                fact = match.group(1).strip().rstrip(".,;!")
                # Filter out matches that are too short or too long (noise)
                if 3 <= len(fact) <= 150:
                    facts.append((category, fact))

        # Also detect name introductions
        name_patterns = [
            r"(?:ich bin|ich heiße|mein name ist)\s+(\w+)",
            r"(?:i'm|i am|my name is)\s+(\w+)",
        ]
        for pattern in name_patterns:
            match = _re.search(pattern, user_message, _re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Avoid common false positives
                if name.lower() not in {"ein", "a", "the", "nicht", "not", "sehr", "very"}:
                    facts.append(("identity", f"Name: {name}"))

        return facts

    # ─── Dynamic Trust ─────────────────────────────────

    def compute_trust_delta(self, mood: str, user_message: str) -> float:
        """Compute trust delta based on mood and conversation quality.

        Instead of flat +0.01, trust adapts based on interaction quality:
        - happy/curious: positive drift, building rapport
        - focused: small positive, productive interaction
        - frustrated: slight negative, but trust recovers quickly
        - neutral: small positive baseline
        """
        mood_deltas = {
            "happy": 0.03,       # Positive interaction → trust grows
            "curious": 0.02,     # Engagement → trust grows
            "focused": 0.015,    # Productive but neutral
            "neutral": 0.01,     # Baseline
            "frustrated": -0.01,  # Slight dip — but recovers
        }
        delta = mood_deltas.get(mood, 0.01)

        # Quality bonuses: constructive messages increase trust even in frustration
        quality_markers = {"danke", "thanks", "super", "perfect", "klappt", "funtzt",
                          "gefällt", "geil", "awesome", "great", "nice"}
        if any(m in user_message.lower() for m in quality_markers):
            delta = max(delta, 0.02)  # At least neutral-positive if expressing gratitude

        # Long messages show engagement → small bonus
        if len(user_message.split()) > 20:
            delta += 0.005

        return round(delta, 4)

    # ─── Enhanced Adaptation ──────────────────────────

    def learn_conversation_style(self, user_id: str, message: str):
        """Learn and adapt humor_style, formality_level, technical_depth, and verbosity from messages.

        v7.7: Added verbosity_preference detection — short messages → terse,
        long detailed messages → verbose.
        Enhanced over v7: detects subtler patterns beyond just emoji/tech-words.
        """
        if user_id not in self.relationships:
            return
        rel = self.relationships[user_id]
        msg_lower = message.lower()

        # ── Humor style detection ──
        # Detect irony/sarcasm (harder, use pattern hints)
        sarcasm_hints = {"klar", "na toll", "super", "toll.", "wow.", "ach so",
                        "sure", "great.", "wow.", "oh sure"}
        playful_hints = {"lol", "haha", "😂", "😄", "🔥", ":d", "hehe",
                        "lustig", "witz", "fun", "joke", "xD"}
        dry_hints = {"eben", "logisch", "exakt", "precisely", "indeed", "naturally"}

        has_sarcasm = any(h in msg_lower for h in sarcasm_hints)
        has_playful = any(h in msg_lower for h in playful_hints)
        has_dry = any(h in msg_lower for h in dry_hints)

        if has_playful and not has_dry:
            rel.humor_style = "locker-witzig"
        elif has_dry and not has_playful:
            rel.humor_style = "trocken-sachlich"
        elif has_sarcasm:
            rel.humor_style = "ironisch"

        # ── Formality detection (enhanced) ──
        # Sie-Formal vs. du-casual
        formal_markers = {"sie ", "ihnen", "ihre", "euch", "would you",
                          "could you", "please", "kindly", "sincerely"}
        casual_markers = {"du ", "deine", "ihr ", "krass", "cool", "ne",
                         "geil", "muss", "halt", "ja ", "nö", "hey",
                         "sup?", "what's up", "yo", "lol"}

        formal_score = sum(1 for m in formal_markers if m in msg_lower)
        casual_score = sum(1 for m in casual_markers if m in msg_lower)

        # Initialize formality from unknown (-1) to neutral (0.5) on first interaction
        if rel.formality_level < 0:
            rel.formality_level = 0.5

        if formal_score > casual_score and formal_score > 0:
            # Shift toward formal
            rel.formality_level = min(1.0, rel.formality_level + 0.03)
        elif casual_score > formal_score and casual_score > 0:
            # Shift toward casual
            rel.formality_level = max(0.0, rel.formality_level - 0.03)

        # ── Technical depth detection (enhanced) ──
        deep_tech = {"algorithm", "async", "await", "refactor", "architecture",
                     "optimization", "deployment", "infrastructure", "kubernetes",
                     "containerization", "microservice", "api gateway", "latency",
                     "algorithmus", "infrastruktur", "containerisierung",
                     "leistungssoptimierung", "parallelität"}
        mid_tech = {"code", "api", "function", "server", "debug", "git",
                    "merge", "test", "deploy", "database", "endpoint",
                    "funktion", "server", "debuggen", "datenbank"}
        simple_tech = {"app", "website", "page", "button", "make",
                       "app", "webseite", "seite", "knopf", "machen"}

        deep_count = sum(1 for w in deep_tech if w in msg_lower)
        mid_count = sum(1 for w in mid_tech if w in msg_lower)
        simple_count = sum(1 for w in simple_tech if w in msg_lower)

        if rel.technical_depth < 0:
            rel.technical_depth = 0.5

        if deep_count > 0:
            rel.technical_depth = min(1.0, rel.technical_depth + 0.04)
        elif mid_count > 0:
            rel.technical_depth = min(0.85, rel.technical_depth + 0.02)
        elif simple_count > 0 and deep_count == 0:
            rel.technical_depth = max(0.1, rel.technical_depth - 0.02)

        # ── Verbosity preference detection (v7.7) ──
        # Short terse messages → user prefers terse responses
        # Long detailed messages → user prefers verbose responses
        if rel.verbosity_preference < 0:
            rel.verbosity_preference = 0.4  # default: slightly concise

        word_count = len(message.split())
        # Very short messages (1-5 words): terse user
        if word_count <= 5:
            rel.verbosity_preference = max(0.0, rel.verbosity_preference - 0.02)
        # Medium messages (6-30 words): normal
        elif word_count <= 30:
            # Small nudge toward normal
            if rel.verbosity_preference < 0.35:
                rel.verbosity_preference += 0.01
            elif rel.verbosity_preference > 0.65:
                rel.verbosity_preference -= 0.01
        # Long messages (30+ words): verbose user
        else:
            rel.verbosity_preference = min(1.0, rel.verbosity_preference + 0.02)

        # Question words suggest prefer more explanation → slightly higher verbosity
        question_markers = {"warum", "wie funktioniert", "erkläre", "erklär",
                           "why", "how does", "explain", "what if", "wieso"}
        if any(m in msg_lower for m in question_markers):
            rel.verbosity_preference = min(1.0, rel.verbosity_preference + 0.01)

        # Commands/imperatives → prefer concise responses → lower verbosity
        command_markers = {"mach", "erstelle", "zeige", "liste", "do ", "create",
                          "show", "list", "fix", "refactor"}
        if any(m in msg_lower for m in command_markers):
            rel.verbosity_preference = max(0.0, rel.verbosity_preference - 0.01)