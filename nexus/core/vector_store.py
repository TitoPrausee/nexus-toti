"""
NEXUS v7 — Vector Store for L3 Memory Search

Semantic search using sentence-transformers embeddings.
Replaces keyword-only matching with cosine similarity on dense vectors.

Features:
- Lazy model loading (only loads model on first search, not at import time)
- Persistent embedding cache (numpy .npy files) — no recomputation on restart
- Automatic re-indexing when L3 entries change
- Graceful fallback to keyword search if sentence-transformers unavailable
- Thread-safe index updates
- Configurable model, similarity threshold, and result limits
"""

import json
import time
import logging
import hashlib
import threading
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("nexus.vector_store")


class VectorStore:
    """Semantic vector store for L3 long-term memory.

    Uses sentence-transformers to encode memory entries into dense vectors,
    then performs cosine-similarity search for recall.

    The store maintains an on-disk cache of embeddings (embeddings.npy + index.json)
    so that embeddings survive restarts and are only recomputed for new/changed entries.

    Thread safety: All mutations are protected by a lock. Search is thread-safe
    because numpy array reads are atomic in CPython.
    """

    # Default model — small, fast, multilingual (German + English)
    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, data_dir: str = "data/memory", config: dict = None):
        """Initialize the VectorStore.

        Args:
            data_dir: Directory for persistent embedding cache files.
            config: Optional config dict with keys:
                - model_name: sentence-transformers model name (default: DEFAULT_MODEL)
                - similarity_threshold: minimum cosine similarity for search results (default: 0.3)
                - max_results: maximum number of results from vector search (default: 10)
                - enabled: whether vector search is enabled (default: True)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        cfg = config or {}
        self.model_name = cfg.get("model_name", self.DEFAULT_MODEL)
        self.similarity_threshold = cfg.get("similarity_threshold", 0.3)
        self.max_results = cfg.get("max_results", 10)
        self.enabled = cfg.get("enabled", True)

        # Lazy-loaded model (None until first use)
        self._model = None
        self._model_loaded = False
        self._model_failed = False  # Track if loading failed (don't retry every call)

        # Embedding cache: entry_id -> embedding vector
        self._embeddings: dict[str, np.ndarray] = {}
        self._entry_hashes: dict[str, str] = {}  # entry_id -> content hash (for change detection)
        self._lock = threading.RLock()

        # Persistent cache files
        self._embeddings_file = self.data_dir / "embeddings.npy"
        self._index_file = self.data_dir / "embeddings_index.json"

        # Load cached embeddings from disk (fast, no model needed)
        self._load_cache()

    # ─── Model Management ─────────────────────────────────

    def _ensure_model(self) -> bool:
        """Load the sentence-transformers model if not already loaded.

        Returns:
            True if model is available, False if loading failed or disabled.
        """
        if self._model_loaded:
            return True
        if self._model_failed or not self.enabled:
            return False

        try:
            from sentence_transformers import SentenceTransformer
            log.info(f"Loading sentence-transformers model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            self._model_loaded = True
            log.info(f"Model loaded successfully: {self.model_name}")
            return True
        except ImportError:
            log.warning("sentence-transformers not installed — vector search disabled, falling back to keywords")
            self._model_failed = True
            return False
        except Exception as e:
            log.error(f"Failed to load sentence-transformers model '{self.model_name}': {e}")
            self._model_failed = True
            return False

    # ─── Embedding Computation ─────────────────────────────

    def _compute_embedding(self, text: str) -> Optional[np.ndarray]:
        """Compute embedding vector for a single text string.

        Args:
            text: The text to embed.

        Returns:
            numpy array of shape (dim,) or None if model unavailable.
        """
        if not self._ensure_model():
            return None
        try:
            embedding = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            return embedding
        except Exception as e:
            log.error(f"Embedding computation failed: {e}")
            return None

    def _compute_embeddings_batch(self, texts: list[str]) -> Optional[np.ndarray]:
        """Compute embeddings for multiple texts efficiently.

        Args:
            texts: List of texts to embed.

        Returns:
            numpy array of shape (len(texts), dim) or None if model unavailable.
        """
        if not self._ensure_model():
            return None
        try:
            embeddings = self._model.encode(
                texts, convert_to_numpy=True, normalize_embeddings=True,
                batch_size=64, show_progress_bar=False
            )
            return embeddings
        except Exception as e:
            log.error(f"Batch embedding computation failed: {e}")
            return None

    @staticmethod
    def _content_hash(content: str) -> str:
        """Compute a stable hash of entry content for change detection."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    # ─── Index Management ─────────────────────────────────

    def _build_entry_id(self, entry: dict, index: int) -> str:
        """Create a stable entry ID from an L3 entry.

        Uses the content hash + index to ensure stability across saves.
        """
        return f"l3_{index}_{self._content_hash(entry.get('content', ''))}"

    def index_entries(self, l3_entries: list[dict]) -> None:
        """Rebuild the vector index from L3 entries.

        Only computes embeddings for new/changed entries — cached embeddings
        are reused if the content hash matches.

        Args:
            l3_entries: The current L3 memory entries list.
        """
        if not self._ensure_model():
            return

        with self._lock:
            # Identify which entries need (re-)embedding
            new_texts = []
            new_ids = []
            new_indices = []

            for i, entry in enumerate(l3_entries):
                entry_id = self._build_entry_id(entry, i)
                content = entry.get("content", "")
                content_hash = self._content_hash(content)

                # Skip if we already have this exact embedding
                if entry_id in self._embeddings and self._entry_hashes.get(entry_id) == content_hash:
                    continue

                new_texts.append(content)
                new_ids.append(entry_id)
                new_indices.append(i)
                self._entry_hashes[entry_id] = content_hash

            if not new_texts:
                return

            # Compute embeddings for new/changed entries
            log.info(f"Computing embeddings for {len(new_texts)} entries...")
            embeddings = self._compute_embeddings_batch(new_texts)
            if embeddings is None:
                return

            # Store new embeddings
            for j, (entry_id, idx) in enumerate(zip(new_ids, new_indices)):
                self._embeddings[entry_id] = embeddings[j]

            # Clean up embeddings for entries that no longer exist
            current_ids = {self._build_entry_id(e, i) for i, e in enumerate(l3_entries)}
            stale_ids = [eid for eid in self._embeddings if eid not in current_ids]
            for eid in stale_ids:
                del self._embeddings[eid]
                self._entry_hashes.pop(eid, None)

            # Persist cache to disk
            self._save_cache()

    # ─── Search ────────────────────────────────────────────

    def search(
        self,
        query: str,
        l3_entries: list[dict],
        top_k: int = None,
        threshold: float = None,
    ) -> list[tuple[float, dict]]:
        """Search L3 entries by semantic similarity to the query.

        Args:
            query: The search query string.
            l3_entries: The L3 memory entries to search through.
            top_k: Maximum results to return (default: self.max_results).
            threshold: Minimum cosine similarity (default: self.similarity_threshold).

        Returns:
            List of (similarity_score, entry_dict) tuples, sorted by score descending.
        """
        if not l3_entries:
            return []

        k = top_k or self.max_results
        thresh = threshold if threshold is not None else self.similarity_threshold

        if not self._ensure_model():
            return []

        with self._lock:
            # Ensure all entries are indexed
            self.index_entries(l3_entries)

            # Compute query embedding
            query_embedding = self._compute_embedding(query)
            if query_embedding is None:
                return []

            # Build matrices for entries that have embeddings
            entry_ids = []
            entry_vectors = []
            entry_map = {}

            for i, entry in enumerate(l3_entries):
                entry_id = self._build_entry_id(entry, i)
                if entry_id in self._embeddings:
                    entry_ids.append(entry_id)
                    entry_vectors.append(self._embeddings[entry_id])
                    entry_map[entry_id] = entry

            if not entry_vectors:
                return []

            # Compute cosine similarities (embeddings are normalized, so dot product = cosine sim)
            vectors = np.stack(entry_vectors)
            similarities = vectors @ query_embedding

            # Sort by similarity and filter by threshold
            scored_results = []
            for j, (entry_id, score) in enumerate(zip(entry_ids, similarities)):
                if score >= thresh:
                    scored_results.append((float(score), entry_map[entry_id]))

            # Sort descending by score
            scored_results.sort(key=lambda x: x[0], reverse=True)

            return scored_results[:k]

    # ─── Cache Persistence ─────────────────────────────────

    def _save_cache(self) -> None:
        """Save embedding cache to disk for fast restart."""
        if not self._embeddings:
            return

        try:
            # Save embeddings as a stacked numpy array
            ids = list(self._embeddings.keys())
            vectors = np.stack([self._embeddings[eid] for eid in ids])

            np.save(str(self._embeddings_file), vectors)

            # Save index mapping (id -> position in array, plus content hashes)
            index_data = {
                "ids": ids,
                "hashes": {eid: self._entry_hashes.get(eid, "") for eid in ids},
                "model": self.model_name,
                "dim": vectors.shape[1] if len(vectors.shape) > 1 else 0,
                "timestamp": time.time(),
            }
            with open(self._index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f)

            log.debug(f"Saved embedding cache: {len(ids)} entries, dim={vectors.shape[1] if len(vectors.shape) > 1 else 0}")

        except Exception as e:
            log.error(f"Failed to save embedding cache: {e}")

    def _load_cache(self) -> None:
        """Load embedding cache from disk (if available and model matches)."""
        try:
            if not self._embeddings_file.exists() or not self._index_file.exists():
                return

            with open(self._index_file, "r", encoding="utf-8") as f:
                index_data = json.load(f)

            # Only load cache if it was created with the same model
            cached_model = index_data.get("model", "")
            if cached_model and cached_model != self.model_name:
                log.info(f"Embedding cache model mismatch (cache={cached_model}, config={self.model_name}), rebuilding")
                return

            vectors = np.load(str(self._embeddings_file))
            ids = index_data.get("ids", [])
            hashes = index_data.get("hashes", {})

            if len(ids) != vectors.shape[0]:
                log.warning(f"Embedding cache size mismatch: {len(ids)} ids vs {vectors.shape[0]} vectors, discarding cache")
                return

            # Rebuild embeddings dict
            for i, entry_id in enumerate(ids):
                self._embeddings[entry_id] = vectors[i]
                if entry_id in hashes:
                    self._entry_hashes[entry_id] = hashes[entry_id]

            log.info(f"Loaded embedding cache: {len(ids)} entries from {self._embeddings_file}")

        except Exception as e:
            log.warning(f"Failed to load embedding cache (will rebuild): {e}")
            self._embeddings = {}
            self._entry_hashes = {}

    # ─── Hybrid Search ────────────────────────────────────

    def hybrid_score(
        self,
        query: str,
        entry: dict,
        keyword_score: float,
        vector_score: Optional[float] = None,
    ) -> float:
        """Combine keyword and vector similarity scores.

        Args:
            query: The original query (unused here, but available for future).
            entry: The L3 entry dict.
            keyword_score: Score from keyword matching (0.0 - 1.0 range).
            vector_score: Cosine similarity from vector search, or None if unavailable.

        Returns:
            Combined relevance score (0.0 - 1.0+).
        """
        if vector_score is not None:
            # Weighted combination: vector search gets 60% weight, keywords 40%
            # Vector similarity captures semantics, keywords capture exact matches
            return 0.6 * vector_score + 0.4 * keyword_score
        else:
            # Fallback: pure keyword score (already computed)
            return keyword_score

    # ─── Stats ─────────────────────────────────────────────

    def stats(self) -> dict:
        """Return vector store statistics."""
        return {
            "enabled": self.enabled,
            "model_loaded": self._model_loaded,
            "model_name": self.model_name,
            "cached_embeddings": len(self._embeddings),
            "cache_file_exists": self._embeddings_file.exists(),
            "similarity_threshold": self.similarity_threshold,
        }