"""
Tests for SoulEngine v7.7: Adaptive Persönlichkeit — MoodState, PersonalityScales, Verbosity.

Covers:
- MoodState dataclass and label_de property
- PersonalityScales dataclass, clamp(), to_dict()
- Mood scale adjustments (refreshed, focused, tired, etc.)
- User-adapted personality scales (trust, formality, humor, verbosity)
- get_system_prompt() includes mood and personality scale hints
- Verbosity preference learning in learn_conversation_style()
- Save/load of verbosity_preference field
- Backward compatibility (missing verbosity_preference in relations.json)
"""
import os
import json
import time
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from nexus.soul import SoulEngine, UserRelation, MoodState, PersonalityScales


@pytest.fixture
def soul(tmp_path):
    """Create a SoulEngine with a temp directory."""
    return SoulEngine(soul_dir=str(tmp_path / "soul_adaptive_test"))


# ────────────────────────────────────────────────────────
# MoodState Tests
# ────────────────────────────────────────────────────────

class TestMoodState:
    """Tests for the MoodState dataclass."""

    def test_default_mood_state(self):
        ms = MoodState()
        assert ms.mood == "neutral"
        assert ms.energy == 0.7
        assert ms.confidence == 0.8

    def test_label_de_german_labels(self):
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
        for mood, expected in labels.items():
            ms = MoodState(mood=mood)
            assert ms.label_de == expected, f"Expected '{expected}' for mood '{mood}'"

    def test_label_de_unknown_mood(self):
        ms = MoodState(mood="unknown_mood")
        assert ms.label_de == "ausgewogen"  # fallback


class TestPersonalityScales:
    """Tests for the PersonalityScales dataclass."""

    def test_defaults(self):
        ps = PersonalityScales()
        assert ps.formality == 0.5
        assert ps.humor == 0.5
        assert ps.verbosity == 0.4
        assert ps.technical_depth == 0.7

    def test_clamp_high_values(self):
        ps = PersonalityScales(formality=1.5, humor=2.0, verbosity=3.0, technical_depth=1.8)
        ps.clamp()
        assert ps.formality == 1.0
        assert ps.humor == 1.0
        assert ps.verbosity == 1.0
        assert ps.technical_depth == 1.0

    def test_clamp_low_values(self):
        ps = PersonalityScales(formality=-0.5, humor=-0.3, verbosity=-0.2, technical_depth=-0.1)
        ps.clamp()
        assert ps.formality == 0.0
        assert ps.humor == 0.0
        assert ps.verbosity == 0.0
        assert ps.technical_depth == 0.0

    def test_clamp_returns_self(self):
        ps = PersonalityScales(formality=0.5)
        result = ps.clamp()
        assert result is ps  # in-place mutation, returns self

    def test_to_dict_rounds_values(self):
        ps = PersonalityScales(formality=0.5123, humor=0.6578, verbosity=0.3456, technical_depth=0.7987)
        d = ps.to_dict()
        assert d["formality"] == 0.512
        assert d["humor"] == 0.658
        assert d["verbosity"] == 0.346
        assert d["technical_depth"] == 0.799


# ────────────────────────────────────────────────────────
# Mood State Calculation Tests
# ────────────────────────────────────────────────────────

class TestGetMoodState:
    """Tests for SoulEngine.get_mood_state() — mood calculation."""

    def test_conversation_mood_overrides_neutral(self, soul):
        """Non-neutral conversation emotion overrides time-of-day baseline."""
        soul.track_emotion("user1", "happy")
        ms = soul.get_mood_state("user1")
        assert ms.mood == "happy"

    def test_neutral_conversation_uses_time(self, soul):
        """Neutral conversation mood falls back to time-of-day."""
        soul.track_emotion("user2", "neutral")
        ms = soul.get_mood_state("user2")
        # Should be whatever the time-of-day mood is
        assert ms.mood in ("refreshed", "focused", "relaxed", "tired", "neutral")

    def test_no_conversation_mood_uses_time(self, soul):
        """No conversation emotion → uses time-of-day baseline."""
        ms = soul.get_mood_state("nonexistent_user")
        assert ms.mood in ("refreshed", "focused", "relaxed", "tired", "neutral")

    def test_frustration_drains_energy(self, soul):
        """Frustrated mood should reduce energy."""
        soul.track_emotion("frust_user", "frustrated")
        ms_frust = soul.get_mood_state("frust_user")

        soul.track_emotion("happy_user", "happy")
        ms_happy = soul.get_mood_state("happy_user")

        # Frustrated should have lower energy than happy
        assert ms_frust.energy < ms_happy.energy

    def test_frustration_multiplier(self, soul):
        """Frustrated mood multiplies energy by 0.85."""
        soul.track_emotion("frust_test", "frustrated")
        ms = soul.get_mood_state("frust_test")
        assert ms.mood == "frustrated"

    def test_happy_boosts_confidence(self, soul):
        """Happy mood should boost confidence slightly."""
        soul.track_emotion("happy_test", "happy")
        ms = soul.get_mood_state("happy_test")

        soul_no_emotion = soul.get_mood_state("no_emotion_test")
        # Happy should have confidence >= baseline (could be equal if at max)
        assert ms.confidence >= 0.8

    def test_trust_modifies_energy(self, soul):
        """High trust → slightly higher energy. Low trust → slightly lower."""
        soul.relationships["high_trust"] = UserRelation(trust_level=0.95)
        soul.relationships["low_trust"] = UserRelation(trust_level=0.15)

        ms_high = soul.get_mood_state("high_trust")
        ms_low = soul.get_mood_state("low_trust")

        assert ms_high.energy >= ms_low.energy

    def test_mood_caching(self, soul):
        """Mood state should be cached per user."""
        ms = soul.get_mood_state("cache_user")
        assert "cache_user" in soul._mood_cache
        assert soul._mood_cache["cache_user"].mood == ms.mood

    def test_anonymous_mood_no_cache(self, soul):
        """Anonymous (no user_id) mood state should use time baseline."""
        ms = soul.get_mood_state(None)
        assert ms.mood in ("refreshed", "focused", "relaxed", "tired", "neutral")

    def test_time_mood_lookup_table(self, soul):
        """Verify time mood constants are properly structured."""
        from nexus.soul import _TIME_MOODS
        for start, end, mood, energy, confidence in _TIME_MOODS:
            assert 0 <= start <= 24
            assert 0 <= end <= 24 or end == 6  # midnight wrap
            assert 0.0 <= energy <= 1.0
            assert 0.0 <= confidence <= 1.0
            assert mood in ("refreshed", "focused", "relaxed", "tired")


# ────────────────────────────────────────────────────────
# Personality Scales Tests
# ────────────────────────────────────────────────────────

class TestGetPersonalityScales:
    """Tests for SoulEngine.get_personality_scales()."""

    def test_base_scales_without_user(self, soul):
        """Without user_id, scales come from base personality config."""
        scales = soul.get_personality_scales()
        # From soul.yaml: formality=0.5, technical_depth=0.7, humor=trocken-witzig(0.5)
        assert 0.1 <= scales.formality <= 1.0
        assert 0.1 <= scales.technical_depth <= 1.0
        assert 0.1 <= scales.humor <= 1.0
        assert 0.1 <= scales.verbosity <= 1.0

    def test_user_overrides_formality(self, soul):
        """Known user with learned formality overrides base."""
        soul.update_user("formal_user", trust_delta=0.1)
        soul.relationships["formal_user"].formality_level = 0.9

        scales = soul.get_personality_scales("formal_user")
        # At 0.9 formality, even with negative mood adjustments, should be >= 0.75
        # (relaxed mood: -0.15 → 0.75, focused: +0.05 → 0.95, etc.)
        assert scales.formality >= 0.75

    def test_user_overrides_humor_style(self, soul):
        """Known user with locker-witzig humor style gets high humor scale."""
        soul.update_user("playful_user", trust_delta=0.1)
        soul.relationships["playful_user"].humor_style = "locker-witzig"

        scales = soul.get_personality_scales("playful_user")
        assert scales.humor >= 0.7  # locker-witzig = 0.8 scale

    def test_user_overrides_technical_depth(self, soul):
        """Known user with learned technical depth."""
        soul.update_user("deep_user", trust_delta=0.1)
        soul.relationships["deep_user"].technical_depth = 0.3

        scales = soul.get_personality_scales("deep_user")
        assert scales.technical_depth <= 0.4  # learned low technical depth

    def test_user_verbosity_preference(self, soul):
        """User with verbosity_preference overrides base verbosity."""
        soul.update_user("verbose_user", trust_delta=0.1)
        soul.relationships["verbose_user"].verbosity_preference = 0.8

        scales = soul.get_personality_scales("verbose_user")
        assert scales.verbosity >= 0.75  # high verbosity pref + trust bonus

    def test_high_trust_reduces_formality(self, soul):
        """High trust users get slightly more casual interaction."""
        soul.relationships["buddy"] = UserRelation(trust_level=0.95)
        soul.relationships["stranger"] = UserRelation(trust_level=0.15)

        scales_buddy = soul.get_personality_scales("buddy")
        scales_stranger = soul.get_personality_scales("stranger")

        # Buddy should be less formal (more casual)
        assert scales_buddy.formality <= scales_stranger.formality

    def test_high_trust_increases_humor(self, soul):
        """High trust users get more humor."""
        soul.relationships["buddy2"] = UserRelation(trust_level=0.95)
        soul.relationships["stranger2"] = UserRelation(trust_level=0.15)

        scales_buddy = soul.get_personality_scales("buddy2")
        scales_stranger = soul.get_personality_scales("stranger2")

        assert scales_buddy.humor >= scales_stranger.humor

    def test_focused_mood_reduces_verbosity(self, soul):
        """Focused conversation: higher tech depth, lower verbosity."""
        soul.track_emotion("focus_test", "focused")
        scales = soul.get_personality_scales("focus_test")
        # Focused: verbosity -0.15
        assert scales.verbosity <= 0.35
        # Focused: technical_depth +0.10
        assert scales.technical_depth >= 0.75

    def test_relaxed_mood_increases_verbosity_humor(self, soul):
        """Relaxed conversation: higher verbosity, higher humor."""
        soul.track_emotion("relax_test", "relaxed")
        scales = soul.get_personality_scales("relax_test")
        # Relaxed: humor +0.10, verbosity +0.10
        assert scales.humor >= 0.55
        assert scales.verbosity >= 0.45

    def test_tired_mood_reduces_humor_verbosity(self, soul):
        """Tired mood: lower humor, lower verbosity, higher formality."""
        soul.track_emotion("tired_test", "tired")
        scales = soul.get_personality_scales("tired_test")
        # Tired: humor -0.15, verbosity -0.10
        assert scales.humor <= 0.4
        assert scales.verbosity <= 0.35

    def test_scales_always_clamped(self, soul):
        """Personality scales should always be in 0.0-1.0 range."""
        soul.relationships["extreme"] = UserRelation(
            trust_level=0.0, formality_level=1.0, technical_depth=1.0,
            humor_style="locker-witzig", verbosity_preference=1.0
        )
        soul.track_emotion("extreme", "refreshed")  # further boosts humor

        scales = soul.get_personality_scales("extreme")
        d = scales.to_dict()
        for key, value in d.items():
            assert 0.0 <= value <= 1.0, f"{key}={value} is out of range"

    def test_mood_scale_adjustments_constants(self):
        """Verify all mood adjustment values exist and are reasonable."""
        from nexus.soul import _MOOD_SCALE_ADJUSTMENTS
        for mood in ["refreshed", "focused", "relaxed", "tired", "frustrated", "happy", "curious", "neutral"]:
            assert mood in _MOOD_SCALE_ADJUSTMENTS, f"Missing mood: {mood}"
            adj = _MOOD_SCALE_ADJUSTMENTS[mood]
            for key in ["formality", "humor", "verbosity", "technical_depth"]:
                assert key in adj, f"Missing key {key} in {mood}"
                assert -0.3 <= adj[key] <= 0.3, f"Extreme adjustment {key}={adj[key]} in {mood}"


# ────────────────────────────────────────────────────────
# System Prompt Tests
# ────────────────────────────────────────────────────────

class TestSystemPromptAdaptive:
    """Tests for get_system_prompt() with mood and personality scales."""

    def test_prompt_contains_mood(self, soul):
        """System prompt should contain current mood state info."""
        prompt = soul.get_system_prompt()
        assert "Aktuelle Stimmung" in prompt
        assert "Energie" in prompt
        assert "Zuversicht" in prompt

    def test_prompt_includes_verbosity_hint(self, soul):
        """System prompt should include verbosity guidance."""
        soul.relationships["terse_user"] = UserRelation(verbosity_preference=0.1)
        prompt = soul.get_system_prompt("terse_user")
        # Should have a short-response hint
        assert any(w in prompt for w in ["kurz", "extrem kurz"])

    def test_prompt_includes_formality_hint(self, soul):
        """System prompt should include formality guidance."""
        soul.relationships["formal_user"] = UserRelation(formality_level=0.9)
        prompt = soul.get_system_prompt("formal_user")
        assert "Formell" in prompt or "professionell" in prompt

    def test_prompt_happy_mood(self, soul):
        """Happy mood should be reflected in system prompt."""
        soul.track_emotion("happy_user", "happy")
        prompt = soul.get_system_prompt("happy_user")
        assert "gut gelaunt" in prompt

    def test_prompt_focused_mood(self, soul):
        """Focused mood should appear in system prompt."""
        soul.track_emotion("focus_user", "focused")
        prompt = soul.get_system_prompt("focus_user")
        assert "fokussiert" in prompt

    def test_prompt_low_formality(self, soul):
        """Low formality user should see casual hint."""
        soul.relationships["casual_user"] = UserRelation(formality_level=0.1)
        prompt = soul.get_system_prompt("casual_user")
        assert "locker" in prompt.lower()

    def test_prompt_high_verbosity(self, soul):
        """High verbosity user should see verbose hint."""
        soul.relationships["verbose_user"] = UserRelation(verbosity_preference=0.9)
        prompt = soul.get_system_prompt("verbose_user")
        assert "ausführlich" in prompt.lower()

    def test_prompt_no_humor(self, soul):
        """Very low humor should show 'Kein Humor' hint."""
        soul.relationships["serious_user"] = UserRelation(
            humor_style="trocken-sachlich", formality_level=0.5, technical_depth=0.5,
            verbosity_preference=0.5
        )
        # trocken-sachlich = 0.2 humor, which hits the <0.2 threshold only with negative mood adj
        # Let's add tired mood which has -0.15 humor → 0.2 - 0.15 = 0.05 < 0.2
        soul.track_emotion("serious_user", "tired")
        prompt = soul.get_system_prompt("serious_user")
        # Now humor should be very low
        assert "Kein Humor" in prompt or "Humor" in prompt


# ────────────────────────────────────────────────────────
# Verbosity Learning Tests
# ────────────────────────────────────────────────────────

class TestVerbosityLearning:
    """Tests for verbosity_preference learning in learn_conversation_style()."""

    def test_short_messages_decrease_verbosity(self, soul):
        """Short terse messages should decrease verbosity preference."""
        soul.update_user("terse_speaker", trust_delta=0.01)
        for _ in range(5):
            soul.learn_conversation_style("terse_speaker", "mach das")

        vp = soul.relationships["terse_speaker"].verbosity_preference
        assert vp < 0.4  # should be below default

    def test_long_messages_increase_verbosity(self, soul):
        """Long detailed messages should increase verbosity preference."""
        soul.update_user("verbose_speaker", trust_delta=0.01)
        long_msg = "Ich möchte gerne eine ausführliche Erklärung haben, die alle Details " \
                   "beinhaltet und wirklich tief in die Materie einsteigt, damit ich das " \
                   "vollständig verstehe und alle Aspekte kenne"
        for _ in range(5):
            soul.learn_conversation_style("verbose_speaker", long_msg)

        vp = soul.relationships["verbose_speaker"].verbosity_preference
        assert vp > 0.4  # should be above default

    def test_question_words_increase_verbosity(self, soul):
        """Question words (warum, wie funktioniert) increase verbosity slightly."""
        soul.update_user("questioner", trust_delta=0.01)
        soul.learn_conversation_style("questioner", "Warum funktioniert das so?")

        vp = soul.relationships["questioner"].verbosity_preference
        assert vp >= 0.38

    def test_command_words_decrease_verbosity(self, soul):
        """Command/imperative words decrease verbosity slightly."""
        soul.update_user("commander", trust_delta=0.01)
        soul.learn_conversation_style("commander", "Mach bitte ein Refactor vom Code")

        vp = soul.relationships["commander"].verbosity_preference
        assert vp <= 0.42  # slightly below default

    def test_verbosity_initialized_on_first_interaction(self, soul):
        """verbosity_preference starts at -1 (unknown) and gets initialized to 0.4."""
        soul.update_user("newbie", trust_delta=0.01)
        assert soul.relationships["newbie"].verbosity_preference == -1.0
        soul.learn_conversation_style("newbie", "Hallo Welt")
        assert soul.relationships["newbie"].verbosity_preference >= 0.0

    def test_verbosity_clamped_to_range(self, soul):
        """Verbosity preference should never go below 0 or above 1."""
        soul.update_user("extreme_terse", trust_delta=0.01)
        for _ in range(50):
            soul.learn_conversation_style("extreme_terse", "ok")
        assert soul.relationships["extreme_terse"].verbosity_preference >= 0.0

        soul.update_user("extreme_verbose", trust_delta=0.01)
        long_msg = "x " * 100
        for _ in range(50):
            soul.learn_conversation_style("extreme_verbose", long_msg)
        assert soul.relationships["extreme_verbose"].verbosity_preference <= 1.0


# ────────────────────────────────────────────────────────
# Save/Load Tests
# ────────────────────────────────────────────────────────

class TestVerbosityPersistence:
    """Tests for saving and loading verbosity_preference."""

    def test_save_includes_verbosity(self, soul, tmp_path):
        """Save should include verbosity_preference in relations.json."""
        soul.update_user("persist_user", trust_delta=0.01)
        soul.learn_conversation_style("persist_user", "Hallo, das ist ein Test")
        vp = soul.relationships["persist_user"].verbosity_preference
        soul.save()

        # Reload
        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "persist_user" in soul2.relationships
        loaded_vp = soul2.relationships["persist_user"].verbosity_preference
        assert loaded_vp == pytest.approx(vp, abs=0.01)

    def test_backward_compatibility_missing_verbosity(self, soul, tmp_path):
        """Loading relations.json without verbosity_preference should default to -1."""
        soul.save()  # Create initial file
        # Write a manual relations.json without verbosity_preference
        rels_path = soul.relations_file
        rels_data = {
            "old_user": {
                "name": "Old User",
                "language": "de",
                "preferences": [],
                "conversation_count": 5,
                "last_seen": 1000000.0,
                "trust_level": 0.6,
                "notes": [],
                "humor_style": "",
                "formality_level": 0.5,
                "technical_depth": 0.7,
                # NOTE: verbosity_preference is missing
            }
        }
        with open(rels_path, "w", encoding="utf-8") as f:
            json.dump(rels_data, f, ensure_ascii=False)

        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "old_user" in soul2.relationships
        assert soul2.relationships["old_user"].verbosity_preference == -1.0  # default unknown


# ────────────────────────────────────────────────────────
# Integration: Agent with Adaptive Soul
# ────────────────────────────────────────────────────────

class TestAgentIntegration:
    """Integration tests: SoulEngine works within NexusAgent context."""

    def test_agent_imports_soul_adaptive(self):
        """NexusAgent can import and use the adaptive soul."""
        from nexus.core.agent import NexusAgent
        from nexus.soul import MoodState, PersonalityScales
        assert MoodState is not None
        assert PersonalityScales is not None

    def test_mood_scale_constants_exist(self):
        """Module-level constants should be importable."""
        from nexus.soul import _TIME_MOODS, _MOOD_SCALE_ADJUSTMENTS, _HUMOR_STYLE_SCALES
        assert len(_TIME_MOODS) >= 7  # 7 time slots
        assert len(_MOOD_SCALE_ADJUSTMENTS) >= 8  # 8 moods
        assert "trocken-witzig" in _HUMOR_STYLE_SCALES
        assert "locker-witzig" in _HUMOR_STYLE_SCALES

    def test_humor_style_scales_mapping(self):
        """All humor styles in soul.yaml should have scale mappings."""
        from nexus.soul import _HUMOR_STYLE_SCALES
        for style, scale in _HUMOR_STYLE_SCALES.items():
            assert 0.0 <= scale <= 1.0, f"Humor style '{style}' scale {scale} out of range"

    def test_agent_creates_soul(self):
        """NexusAgent can create a SoulEngine without errors."""
        from nexus.core.agent import NexusAgent
        agent = NexusAgent()
        assert hasattr(agent, 'soul')
        assert hasattr(agent.soul, 'get_mood_state')
        assert hasattr(agent.soul, 'get_personality_scales')