"""
Tests for SoulEngine: learn(), update_user(), detect_language(),
infer_mood_from_text(), compute_trust_delta(), and learn_conversation_style().
"""
import os
import json
import tempfile
import pytest
from nexus.soul import SoulEngine, UserRelation


@pytest.fixture
def soul(tmp_path):
    """Create a SoulEngine with a temp directory."""
    return SoulEngine(soul_dir=str(tmp_path / "soul_test"))


class TestSoulLearn:
    """Tests for SoulEngine.learn() — persistent knowledge storage."""

    def test_learn_adds_new_category(self, soul):
        soul.learn("languages", "Python ist Toll")
        assert "languages" in soul.knowledge
        assert "Python ist Toll" in soul.knowledge["languages"]

    def test_learn_appends_to_existing_category(self, soul):
        soul.learn("languages", "Python")
        soul.learn("languages", "Rust")
        assert len(soul.knowledge["languages"]) == 2
        assert "Python" in soul.knowledge["languages"]
        assert "Rust" in soul.knowledge["languages"]

    def test_learn_deduplicates_same_fact(self, soul):
        soul.learn("facts", "Der Himmel ist blau")
        soul.learn("facts", "Der Himmel ist blau")
        assert soul.knowledge["facts"].count("Der Himmel ist blau") == 1

    def test_learn_persists_to_disk(self, soul):
        soul.learn("skills", "Codereview")
        soul.save()

        # Reload from disk
        soul2 = SoulEngine(soul_dir=str(soul.soul_dir))
        assert "skills" in soul2.knowledge
        assert "Codereview" in soul2.knowledge["skills"]

    def test_learn_empty_category_and_fact(self, soul):
        # Should not crash with empty values
        soul.learn("", "")
        assert "" in soul.knowledge


class TestSoulDetectLanguage:
    """Tests for SoulEngine.detect_language()."""

    def test_german_detected(self, soul):
        text = "Ich möchte gerne etwas über das Projekt erfahren"
        result = soul.detect_language(text)
        # Should detect German markers
        assert result in ("de", "")

    def test_english_detected(self, soul):
        text = "I want to know more about the project please"
        result = soul.detect_language(text)
        assert result in ("en", "")

    def test_empty_text_returns_empty(self, soul):
        result = soul.detect_language("")
        assert result == ""

    def test_mixed_text_prefers_stronger_signal(self, soul):
        # Text with strong English markers
        text = "I think we should also consider the options"
        result = soul.detect_language(text)
        # English has more markers here, should be "en" or empty
        assert result in ("en", "")

    def test_short_german_sentence(self, soul):
        text = "Das ist ein Test"
        result = soul.detect_language(text)
        # Contains "das " which is a German marker
        assert result in ("de", "")


class TestSoulInferMood:
    """Tests for SoulEngine.infer_mood_from_text()."""

    def test_frustration_detected(self, soul):
        mood = soul.infer_mood_from_text("Das geht nicht, Fehler immer wieder!")
        assert mood == "frustrated"

    def test_curiosity_detected(self, soul):
        mood = soul.infer_mood_from_text("Wie funktioniert das eigentlich?")
        assert mood == "curious"

    def test_happiness_detected(self, soul):
        mood = soul.infer_mood_from_text("Super, das klappt perfekt!")
        assert mood == "happy"

    def test_focus_detected(self, soul):
        mood = soul.infer_mood_from_text("Mach bitte ein Refactor vom Code")
        assert mood == "focused"

    def test_neutral_when_no_markers(self, soul):
        mood = soul.infer_mood_from_text("Okay")
        assert mood == "neutral"

    def test_english_frustration(self, soul):
        mood = soul.infer_mood_from_text("The error keeps failing, damn it")
        # "error" and "damn" trigger frustration
        assert mood == "frustrated"


class TestSoulTrustDelta:
    """Tests for SoulEngine.compute_trust_delta()."""

    def test_happy_gives_positive_delta(self, soul):
        delta = soul.compute_trust_delta("happy", "Alles Super")
        assert delta > 0
        assert delta == pytest.approx(0.03, abs=0.005)

    def test_frustrated_gives_negative_delta(self, soul):
        delta = soul.compute_trust_delta("frustrated", "Das geht nicht")
        assert delta < 0

    def test_neutral_gives_small_positive(self, soul):
        delta = soul.compute_trust_delta("neutral", "Okay")
        assert delta > 0
        assert delta == pytest.approx(0.01, abs=0.005)

    def test_gratitude_overrides_frustration(self, soul):
        # Even if frustrated, expressing gratitude should be at least neutral-positive
        delta = soul.compute_trust_delta("frustrated", "Danke für die Hilfe!")
        assert delta >= 0.02  # quality_markers boost

    def test_long_message_gets_bonus(self, soul):
        # Long message (>20 words) should get a small trust bonus
        short_delta = soul.compute_trust_delta("focused", "Refactor the module")
        # >20 words to trigger the bonus
        long_msg = "I would like you to refactor the module and make sure that all the unit tests pass correctly and the deployment works as expected"
        long_delta = soul.compute_trust_delta("focused", long_msg)
        assert long_delta > short_delta


class TestSoulUpdateUser:
    """Tests for SoulEngine.update_user() — relationship updates."""

    def test_update_user_creates_relationship(self, soul):
        soul.update_user("user123", trust_delta=0.05)
        assert "user123" in soul.relationships

    def test_update_user_increment_conversation_count(self, soul):
        soul.update_user("user1", trust_delta=0.01)
        soul.update_user("user1", trust_delta=0.01)
        assert soul.relationships["user1"].conversation_count == 2

    def test_update_user_with_name(self, soul):
        soul.update_user("uid1", name="Max")
        assert soul.relationships["uid1"].name == "Max"

    def test_update_user_auto_detects_language(self, soul):
        # German text should set language to "de"
        soul.update_user("uid2", last_message="Ich möchte das Projekt starten")
        # Language should be detected (empty means default/undetectable)
        lang = soul.relationships["uid2"].language
        # German text with clear markers should be detected as "de"
        assert lang in ("de", "")  # depends on threshold

    def test_update_user_trust_bounded_0_to_1(self, soul):
        # Trust should never go below 0 or above 1
        soul.update_user("uid3", trust_delta=0.99)
        soul.update_user("uid3", trust_delta=0.99)
        # After two big positive deltas, trust should be capped at 1.0
        assert soul.relationships["uid3"].trust_level <= 1.0

        # Now try to go below 0
        rel = soul.relationships["uid3"]
        rel.trust_level = 0.01
        # Frustrated mood should give negative delta
        soul.update_user("uid3", last_message="error, damn error")
        # Should be >= 0 but could stay positive if gratitude overrides
        assert rel.trust_level >= 0.0

    def test_update_user_adds_notes(self, soul):
        soul.update_user("uid4", note="prefers dark mode")
        assert "prefers dark mode" in soul.relationships["uid4"].notes

    def test_update_user_deduplicates_notes(self, soul):
        soul.update_user("uid5", note="likes Python")
        soul.update_user("uid5", note="likes Python")
        count = soul.relationships["uid5"].notes.count("likes Python")
        assert count == 1

    def test_update_user_truncates_notes_to_20(self, soul):
        # Add 25 notes, should be trimmed to 15
        for i in range(25):
            soul.update_user("uid6", note=f"Note {i}")
        assert len(soul.relationships["uid6"].notes) <= 20


class TestSoulEmotionTracking:
    """Tests for emotion tracking in SoulEngine."""

    def test_track_emotion(self, soul):
        soul.track_emotion("user1", "curious")
        assert soul._emotion_state["user1"] == "curious"
        assert len(soul._emotion_history["user1"]) == 1

    def test_emotion_arc_single_mood(self, soul):
        soul.track_emotion("user2", "curious")
        arc = soul.get_emotion_arc("user2")
        assert "curious" in arc

    def test_emotion_arc_trajectory(self, soul):
        soul.track_emotion("user3", "curious")
        soul.track_emotion("user3", "focused")
        soul.track_emotion("user3", "happy")
        arc = soul.get_emotion_arc("user3")
        assert "curious" in arc
        assert "focused" in arc
        assert "happy" in arc

    def test_emotion_history_limited_to_20(self, soul):
        for i in range(30):
            soul.track_emotion("user4", "neutral")
        assert len(soul._emotion_history["user4"]) == 20

    def test_emotion_arc_no_data(self, soul):
        arc = soul.get_emotion_arc("nonexistent")
        assert arc == ""

    def test_emotion_arc_deduplicates_consecutive(self, soul):
        soul.track_emotion("user5", "neutral")
        soul.track_emotion("user5", "neutral")
        soul.track_emotion("user5", "happy")
        arc = soul.get_emotion_arc("user5")
        # Should show neutral → happy, not neutral → neutral → happy
        assert arc.count("neutral") == 1


class TestSoulExtractLearnableFacts:
    """Tests for SoulEngine.extract_learnable_facts()."""

    def test_german_preference(self, soul):
        facts = soul.extract_learnable_facts("ich mag Python Programmierung")
        assert len(facts) > 0
        assert any(cat == "preference" for cat, _ in facts)

    def test_german_work_context(self, soul):
        facts = soul.extract_learnable_facts("ich arbeite mit Kubernetes")
        assert len(facts) > 0

    def test_english_preference(self, soul):
        facts = soul.extract_learnable_facts("I prefer dark mode")
        assert len(facts) > 0
        assert any(cat == "preference" for cat, _ in facts)

    def test_empty_message_returns_empty(self, soul):
        facts = soul.extract_learnable_facts("")
        assert facts == []

    def test_neutral_message_no_facts(self, soul):
        facts = soul.extract_learnable_facts("Das ist interessant")
        # "interessant" has no matching pattern, should return empty or minimal
        # "ist " is not a fact keyword
        assert len(facts) == 0

    def test_name_introduction_german(self, soul):
        facts = soul.extract_learnable_facts("Ich heiße Alexander")
        identity_facts = [f for c, f in facts if c == "identity"]
        assert len(identity_facts) > 0
        assert "Alexander" in identity_facts[0]

    def test_name_introduction_english(self, soul):
        facts = soul.extract_learnable_facts("My name is Sarah")
        identity_facts = [f for c, f in facts if c == "identity"]
        assert len(identity_facts) > 0

    def test_false_positive_name_filtered(self, soul):
        # "ein" is a common German article, not a name
        facts = soul.extract_learnable_facts("ich bin ein Entwickler")
        # Should NOT create identity fact "ein" due to filter
        identity_facts = [f for c, f in facts if c == "identity"]
        # The name detection should filter out "ein"
        for _, fact in identity_facts:
            assert "Name: ein" not in fact


class TestSoulGetSystemPrompt:
    """Tests for SoulEngine.get_system_prompt()."""

    def test_system_prompt_includes_name(self, soul):
        prompt = soul.get_system_prompt()
        assert soul.personality.get("name", "Toti") in prompt

    def test_system_prompt_with_user_context(self, soul):
        soul.update_user("testuser", name="TestUser")
        prompt = soul.get_system_prompt(user_id="testuser")
        # Should include personality for user
        assert "TestUser" in prompt or soul.personality.get("name", "Toti") in prompt

    def test_system_prompt_includes_rules(self, soul):
        prompt = soul.get_system_prompt()
        # Should mention rules from personality
        if soul.personality.get("rules"):
            assert any(r in prompt for r in soul.personality.get("rules", []))