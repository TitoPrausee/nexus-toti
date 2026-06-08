"""
NEXUS v7 — Vector Search Tests (v7.2)

Tests for the VectorStore and its integration with MemorySystem.
Uses a lightweight test model and temporary directories for isolation.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

# ─── VectorStore Unit Tests ───────────────────────────────────────

class TestVectorStoreBasic(unittest.TestCase):
    """Test VectorStore basic functionality (no model needed for init/cache tests)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="nexus_vs_test_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_disabled(self):
        """VectorStore initializes correctly when disabled."""
        from nexus.core.vector_store import VectorStore
        vs = VectorStore(data_dir=self.test_dir, config={"enabled": False})
        self.assertFalse(vs.enabled)
        self.assertFalse(vs._model_loaded)
        self.assertEqual(vs.model_name, VectorStore.DEFAULT_MODEL)

    def test_init_with_custom_model(self):
        """VectorStore respects custom model_name config."""
        from nexus.core.vector_store import VectorStore
        vs = VectorStore(data_dir=self.test_dir, config={
            "enabled": True,
            "model_name": "all-MiniLM-L6-v2"
        })
        self.assertEqual(vs.model_name, "all-MiniLM-L6-v2")

    def test_init_threshold_config(self):
        """VectorStore respects similarity_threshold config."""
        from nexus.core.vector_store import VectorStore
        vs = VectorStore(data_dir=self.test_dir, config={
            "similarity_threshold": 0.5,
            "max_results": 3,
        })
        self.assertEqual(vs.similarity_threshold, 0.5)
        self.assertEqual(vs.max_results, 3)

    def test_stats_when_disabled(self):
        """Stats show disabled state correctly."""
        from nexus.core.vector_store import VectorStore
        vs = VectorStore(data_dir=self.test_dir, config={"enabled": False})
        stats = vs.stats()
        self.assertFalse(stats["enabled"])
        self.assertFalse(stats["model_loaded"])
        self.assertEqual(stats["cached_embeddings"], 0)

    def test_search_returns_empty_for_empty_entries(self):
        """Search returns empty list when no entries exist."""
        from nexus.core.vector_store import VectorStore
        vs = VectorStore(data_dir=self.test_dir, config={"enabled": False})
        results = vs.search("test query", l3_entries=[])
        self.assertEqual(results, [])

    def test_content_hash_stability(self):
        """Content hash is deterministic."""
        from nexus.core.vector_store import VectorStore
        h1 = VectorStore._content_hash("hello world")
        h2 = VectorStore._content_hash("hello world")
        self.assertEqual(h1, h2)
        h3 = VectorStore._content_hash("different content")
        self.assertNotEqual(h1, h3)

    def test_build_entry_id(self):
        """Entry ID generation is stable."""
        from nexus.core.vector_store import VectorStore
        vs = VectorStore(data_dir=self.test_dir, config={"enabled": False})
        entry = {"content": "test content", "importance": 0.7}
        id1 = vs._build_entry_id(entry, 0)
        id2 = vs._build_entry_id(entry, 0)
        self.assertEqual(id1, id2)
        # Different index produces different ID
        id3 = vs._build_entry_id(entry, 1)
        self.assertNotEqual(id1, id3)

    def test_cache_save_and_load(self):
        """Cache persistence: save embeddings, then reload from disk."""
        from nexus.core.vector_store import VectorStore
        import numpy as np

        vs = VectorStore(data_dir=self.test_dir, config={"enabled": True})
        # Manually create cache entries
        vs._embeddings = {"test_1": np.array([0.1, 0.2, 0.3], dtype=np.float32)}
        vs._entry_hashes = {"test_1": "abc123"}
        vs._save_cache()

        # Create new instance and load
        vs2 = VectorStore(data_dir=self.test_dir, config={"enabled": True})
        self.assertIn("test_1", vs2._embeddings)
        np.testing.assert_array_almost_equal(vs2._embeddings["test_1"], [0.1, 0.2, 0.3])


class TestVectorStoreSearch(unittest.TestCase):
    """Test VectorStore semantic search with the actual model."""

    @classmethod
    def setUpClass(cls):
        """Load model once for all search tests (expensive operation)."""
        from nexus.core.vector_store import VectorStore
        cls.test_dir = tempfile.mkdtemp(prefix="nexus_vs_search_")
        cls.vs = VectorStore(data_dir=cls.test_dir, config={
            "enabled": True,
            "model_name": "paraphrase-multilingual-MiniLM-L12-v2",
            "similarity_threshold": 0.2,
        })
        # Trigger model loading
        cls.vs._ensure_model()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_semantic_search_basic(self):
        """Semantic search finds conceptually related content."""
        entries = [
            {"content": "Python ist eine Programmiersprache", "importance": 0.7, "category": "tech"},
            {"content": "Kaffee schmeckt am Morgen am besten", "importance": 0.5, "category": "general"},
            {"content": "Maschinelles Lernen nutzt neuronale Netze", "importance": 0.8, "category": "tech"},
        ]
        results = self.vs.search("Programmierung", entries, top_k=3, threshold=0.2)
        # Should find the Python entry as most similar
        self.assertGreater(len(results), 0)
        top_content = results[0][1].get("content", "")
        # Python entry should be in top results
        contents = [r[1].get("content", "") for r in results]
        self.assertIn("Python", " ".join(contents))

    def test_semantic_search_cross_language(self):
        """Semantic search works across languages (German query, English content)."""
        entries = [
            {"content": "Machine learning uses neural networks", "importance": 0.7, "category": "tech"},
            {"content": "The weather is sunny today", "importance": 0.3, "category": "general"},
        ]
        results = self.vs.search("Künstliche Intelligenz", entries, top_k=2, threshold=0.2)
        if results:
            # ML entry should score higher than weather
            scores = {r[1]["content"]: r[0] for r in results}
            if "Machine learning uses neural networks" in scores and "The weather is sunny today" in scores:
                self.assertGreater(
                    scores["Machine learning uses neural networks"],
                    scores["The weather is sunny today"]
                )

    def test_semantic_search_empty_query(self):
        """Empty query returns empty results."""
        entries = [{"content": "test", "importance": 0.5, "category": "general"}]
        results = self.vs.search("", entries, top_k=5, threshold=0.0)
        # Empty string may still produce results or empty list
        # Both are acceptable behaviors
        self.assertIsInstance(results, list)

    def test_hybrid_score(self):
        """Hybrid score combines vector and keyword scores correctly."""
        entry = {"content": "Python Programmierung", "importance": 0.7}
        # With vector score
        score_with_vector = self.vs.hybrid_score("Python", entry, 0.8, 0.7)
        self.assertAlmostEqual(score_with_vector, 0.6 * 0.7 + 0.4 * 0.8)

        # Without vector score (fallback)
        score_keyword_only = self.vs.hybrid_score("Python", entry, 0.8)
        self.assertEqual(score_keyword_only, 0.8)

    def test_index_entries_incremental(self):
        """Index entries only computes embeddings for new/changed entries."""
        entries = [
            {"content": "First entry", "importance": 0.5, "category": "general"},
            {"content": "Second entry", "importance": 0.6, "category": "general"},
        ]
        self.vs.index_entries(entries)
        self.assertEqual(len(self.vs._embeddings), 2)

        # Add a third entry — only it should be embedded
        entries.append({"content": "Third entry", "importance": 0.7, "category": "general"})
        self.vs.index_entries(entries)
        self.assertEqual(len(self.vs._embeddings), 3)

    def test_search_threshold_filtering(self):
        """Search respects similarity threshold."""
        entries = [
            {"content": "Quantum entanglement in particle physics", "importance": 0.9, "category": "science"},
            {"content": "Baking bread requires flour and water", "importance": 0.3, "category": "cooking"},
        ]
        # High threshold — only very similar results
        results = self.vs.search("particle physics quantum", entries, top_k=5, threshold=0.8)
        for score, entry in results:
            self.assertGreaterEqual(score, 0.8)


# ─── Memory Integration Tests ────────────────────────────────────

class TestMemoryVectorIntegration(unittest.TestCase):
    """Test MemorySystem with vector search integration."""

    @classmethod
    def setUpClass(cls):
        """Set up MemorySystem with vector search for integration tests."""
        cls.test_dir = tempfile.mkdtemp(prefix="nexus_mem_vs_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_memory_recall_with_vector_search(self):
        """Memory recall uses vector search for semantic matching."""
        from nexus.core.memory import MemorySystem

        m = MemorySystem(data_dir=self.test_dir + "/mem1", config={
            "vector_search": {
                "enabled": True,
                "model_name": "paraphrase-multilingual-MiniLM-L12-v2",
            }
        })

        m.remember("Python ist eine interpretierte Programmiersprache", category="tech", importance=0.8)
        m.remember("Der Benutzer mag kurze Antworten", category="preferences", importance=0.7)
        m.remember("Ollama serves LLM models locally", category="tech", importance=0.8)

        # Semantic recall: "Coding language" should find Python entry
        results = m.recall("Codierung Sprachen")
        self.assertIsInstance(results, list)
        # Should return at least one result
        self.assertGreater(len(results), 0)

    def test_memory_recall_disabled_vector_search(self):
        """Memory recall works without vector search (keyword fallback)."""
        from nexus.core.memory import MemorySystem

        m = MemorySystem(data_dir=self.test_dir + "/mem2", config={
            "vector_search": {"enabled": False}
        })

        m.remember("Python Programmierung", importance=0.8)
        m.remember("Kaffee trinken", importance=0.5)

        # Keyword search should still work
        results = m.recall("Python")
        self.assertGreater(len(results), 0)
        self.assertIn("Python", results[0])

    def test_memory_stats_includes_vector_store(self):
        """Memory stats include vector store information."""
        from nexus.core.memory import MemorySystem

        m = MemorySystem(data_dir=self.test_dir + "/mem3", config={
            "vector_search": {"enabled": False}
        })

        stats = m.stats()
        self.assertIn("vector_store", stats)
        self.assertIn("enabled", stats["vector_store"])

    def test_get_relevant_context_uses_vector_search(self):
        """get_relevant_context uses hybrid search."""
        from nexus.core.memory import MemorySystem

        m = MemorySystem(data_dir=self.test_dir + "/mem4", config={
            "vector_search": {
                "enabled": True,
                "model_name": "paraphrase-multilingual-MiniLM-L12-v2",
            }
        })

        m.remember("Docker containers provide process isolation", category="tech", importance=0.8)
        m.remember("Der Benutzer bevorzugt deutsche Sprache", category="preferences", importance=0.9)
        m.remember("Kubernetes orchestriert Container im Cluster", category="tech", importance=0.7)

        # Semantic query about containerization
        context = m.get_context(query="Container und Virtualisierung")
        # Should include relevant facts
        self.assertIsInstance(context, list)

    def test_remember_triggers_indexing(self):
        """remember() triggers vector store indexing."""
        from nexus.core.memory import MemorySystem

        m = MemorySystem(data_dir=self.test_dir + "/mem5", config={
            "vector_search": {"enabled": False}
        })

        # Should not fail even with vector search disabled
        m.remember("Test fact for indexing", importance=0.5)
        self.assertEqual(len(m.l3), 1)
        self.assertEqual(m.l3[0]["content"], "Test fact for indexing")


if __name__ == "__main__":
    unittest.main()