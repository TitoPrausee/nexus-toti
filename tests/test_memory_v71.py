"""
Tests for v7.1 Memory System improvements:
- L2 structured summaries (topics, key_facts, decisions)
- L3 fuzzy deduplication
- Context deduplication
- Topic extraction
"""

import pytest
import tempfile
import shutil
from nexus.core.memory import MemorySystem


@pytest.fixture
def mem():
    """Create a fresh MemorySystem with temp directory."""
    tmpdir = tempfile.mkdtemp()
    m = MemorySystem(data_dir=tmpdir)
    yield m
    shutil.rmtree(tmpdir)


class TestTopicExtraction:
    def test_extract_topics_basic_german(self):
        topics = MemorySystem._extract_topics("Ich möchte eine Python-Anwendung erstellen")
        assert "python" in topics
        assert "anwendung" in topics
        assert "erstellen" in topics

    def test_extract_topics_filters_stopwords(self):
        topics = MemorySystem._extract_topics("Das ist ein Test und der Code muss funktionieren")
        # Stop words should be filtered
        assert "ist" not in topics
        assert "der" not in topics
        assert "und" not in topics
        # Meaningful words kept
        assert "test" in topics or "code" in topics or "funktionieren" in topics

    def test_extract_topics_english(self):
        topics = MemorySystem._extract_topics("Deploy the FastAPI server with Docker")
        assert "deploy" in topics
        assert "fastapi" in topics
        assert "server" in topics or "docker" in topics

    def test_topic_key_similarity(self):
        key1 = MemorySystem._topic_key("Python ist eine Programmiersprache")
        key2 = MemorySystem._topic_key("Python Programmierung ist toll")
        # Both should have python as a topic
        assert "python" in key1
        assert "python" in key2

    def test_extract_topics_short_text(self):
        topics = MemorySystem._extract_topics("Hi")
        # Short words are filtered (< 3 chars)
        assert len(topics) == 0 or all(len(t) >= 3 for t in topics)


class TestL2StructuredSummaries:
    def test_compress_creates_structured_summary(self, mem):
        mem.l1_max_tokens = 100
        for i in range(10):
            mem.add("user", f"Nachricht {i}: " + "Wort " * 20)
        
        assert len(mem.l2) > 0
        last = mem.l2[-1]
        assert "summary" in last
        assert "topics" in last
        assert isinstance(last["topics"], list)
        assert "entries_removed" in last

    def test_extract_session_summary_with_decisions(self, mem):
        entries = [
            type("MemoryEntry", (), {
                "role": "user",
                "content": "Entscheidung: Wir verwenden PostgreSQL",
                "timestamp": 1000.0,
                "tokens": 10,
                "importance": 0.7,
            })(),
            type("MemoryEntry", (), {
                "role": "assistant",
                "content": "Alles klar, PostgreSQL als Datenbank festgelegt.",
                "timestamp": 1001.0,
                "tokens": 10,
                "importance": 0.8,
            })(),
        ]
        summary = mem._extract_session_summary(entries)
        assert "Decisions" in summary["summary"] or len(summary["decisions"]) > 0
    
    def test_compress_preserves_recent_entries(self, mem):
        mem.l1_max_tokens = 80
        for i in range(15):
            mem.add("user", f"Nachricht {i} " + "Wort " * 10)
        # L1 should keep the most recent entries
        assert len(mem.l1) > 0
        # First entry should still exist
        assert mem.l1[0].content.startswith("Nachricht 0")

    def test_end_session_creates_structured_summary(self, mem):
        mem.add("user", "Ich möchte einen Webserver mit Python erstellen")
        mem.add("assistant", "Gerne! FastAPI ist eine gute Wahl.")
        mem.add("user", "Entscheidung: Wir nehmen PostgreSQL als Datenbank")
        mem.add("assistant", "Alles klar, PostgreSQL festgelegt.", importance=0.8)
        
        mem.end_session()
        
        assert len(mem.l1) == 0  # L1 cleared
        assert len(mem.l2) == 1
        summary = mem.l2[0]
        assert "topics" in summary
        assert isinstance(summary["topics"], list)
        # Should have extracted some topics from the conversation
        assert len(summary["topics"]) > 0


class TestL3FuzzyDedup:
    def test_exact_dedup(self, mem):
        mem.remember("Python ist toll", importance=0.7)
        mem.remember("Python ist toll", importance=0.8)
        assert len(mem.l3) == 1
        # Importance should be max of both
        assert mem.l3[0]["importance"] == 0.8

    def test_fuzzy_dedup_similar_topics(self, mem):
        mem.remember("Python ist eine tolle Sprache", importance=0.7)
        mem.remember("Python ist eine tolle Programmiersprache", importance=0.7)
        # These share "python" and "tolle" — should merge
        assert len(mem.l3) == 1

    def test_different_facts_not_merged(self, mem):
        mem.remember("Benutzer mag Pizza", importance=0.7)
        mem.remember("Der Server läuft auf Port 8080", importance=0.9)
        # Completely different topics — should not merge
        assert len(mem.l3) == 2

    def test_remember_with_topics_field(self, mem):
        mem.remember("FastAPI ist ein Python-Webframework", category="fact", importance=0.7)
        assert len(mem.l3) == 1
        entry = mem.l3[0]
        assert "topics" in entry
        assert "fastapi" in entry["topics"] or "python" in entry["topics"]

    def test_access_count_incremented_on_dedup(self, mem):
        mem.remember("Python ist toll", importance=0.7)
        assert mem.l3[0]["access_count"] == 1
        mem.remember("Python ist toll", importance=0.8)
        assert mem.l3[0]["access_count"] == 2


class TestContextDeduplication:
    def test_context_avoids_redundant_facts(self, mem):
        mem.remember("Python ist eine Programmiersprache", importance=0.8)
        mem.remember("Server läuft auf Port 8080", importance=0.9)
        mem.remember("Kaffee ist lecker", importance=0.5)
        
        ctx = mem.get_context(query="Python Server")
        # Should include both Python and Server facts
        contents = [c["content"] for c in ctx]
        assert len(contents) >= 2

    def test_context_with_no_query(self, mem):
        mem.remember("Wichtiges Fakt", importance=0.9)
        ctx = mem.get_context()
        # Should still return context without query
        assert isinstance(ctx, list)

    def test_context_l2_prefers_structured_over_raw(self, mem):
        # Create an L2 entry with structured data
        mem.l2.append({
            "timestamp": 1000.0,
            "summary": "Themen: python, api | Wichtig: FastAPI",
            "topics": ["python", "api"],
            "key_facts": ["FastAPI ist schnell"],
            "decisions": ["Verwende FastAPI"],
            "entries_removed": 5,
        })
        
        ctx = mem.get_context()
        # Should include the structured L2 data
        l2_ctx = [c for c in ctx if c["content"].startswith("[Kontext]")]
        assert len(l2_ctx) >= 1
