"""
NEXUS RAG System — Retrieval Augmented Generation
===================================================
Lightweight RAG with TF-IDF scoring — no vector DB needed.

Features:
  - Ingest documents (text, markdown, code files, URLs)
  - Configurable chunk splitting (size + overlap)
  - TF-IDF keyword scoring (no embeddings required)
  - Top-k retrieval with scored results
  - Context builder for LLM injection
  - JSON-based persistence (chunks, inverted index, metadata)
  - URL ingestion via WebBrowser

Storage Layout (data/rag/):
  chunks.json    — [{id, text, source, metadata, tokens}]
  index.json     — {term: {chunk_id: tf_score}}
  metadata.json  — stats and config
"""

import json
import math
import os
import re
import time
import logging
from typing import Optional
from pathlib import Path
from collections import Counter

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# SAFE IMPORTS
# ═══════════════════════════════════════════════════════════

try:
    from ..core.web_browser import WebBrowser
    WEB_BROWSER_AVAILABLE = True
except (ImportError, ValueError):
    try:
        from core.web_browser import WebBrowser
        WEB_BROWSER_AVAILABLE = True
    except ImportError:
        WEB_BROWSER_AVAILABLE = False
        WebBrowser = None


# ═══════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════

# Terms to ignore when building the inverted index
STOP_WORDS: set[str] = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "were",
    "been", "are", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "not",
    "this", "that", "these", "those", "i", "you", "he", "she", "we",
    "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "its", "our", "their", "what", "which", "who", "whom", "how",
    "when", "where", "why", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "only",
    "own", "same", "so", "than", "too", "very", "just", "because",
    "if", "then", "else", "while", "about", "up", "out", "also",
    "into", "over", "after", "before", "between", "through", "during",
    "der", "die", "das", "und", "oder", "aber", "in", "auf", "am",
    "ist", "ein", "eine", "für", "mit", "von", "zu", "den", "dem",
    "im", "es", "sie", "er", "wir", "ich", "nicht", "auch", "sich",
    "des", "als", "wie", "nach", "bei", "noch", "wird", "hat",
}


# ═══════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════

def tokenize(text: str) -> list[str]:
    """
    Tokenize text into lowercase terms.
    Splits on non-alphanumeric characters, filters short tokens and stop words.
    """
    # Split on anything that's not a letter, digit, or underscore
    raw_tokens = re.split(r"[^\w]+", text.lower())
    # Filter: min 2 chars, not a stop word, not purely numeric
    tokens = [
        t for t in raw_tokens
        if len(t) >= 2 and t not in STOP_WORDS and not t.isdigit()
    ]
    return tokens


def estimate_tokens(text: str) -> int:
    """Rough token count estimate (~4 chars per token)."""
    return max(1, len(text) // 4)


# ═══════════════════════════════════════════════════════════
# RAG SYSTEM
# ═══════════════════════════════════════════════════════════

class RAGSystem:
    """
    Lightweight RAG with TF-IDF scoring — no vector DB needed.

    Usage:
        rag = RAGSystem()
        rag.ingest_file("docs/readme.md")
        rag.ingest_url("https://example.com/docs")
        results = rag.search("how to deploy", top_k=5)
        context = rag.build_context("how to deploy", max_tokens=2000)
    """

    def __init__(
        self,
        storage_dir: str = "data/rag",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        max_chunks: int = 5000,
    ):
        """
        Initialize the RAG system.

        Args:
            storage_dir: Directory for JSON persistence.
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Overlap characters between consecutive chunks.
            max_chunks: Maximum number of chunks to store.
        """
        self.storage_dir = Path(storage_dir)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_chunks = max_chunks

        # Internal state
        self._chunks: list[dict] = []
        self._index: dict[str, dict[str, float]] = {}  # term -> {chunk_id: tf_score}
        self._next_id: int = 0
        self._sources: set[str] = set()

        # Ensure storage directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Try to load existing data
        self.load()

    # ─── INGESTION ────────────────────────────────────────

    def ingest_file(self, path: str, metadata: Optional[dict] = None) -> dict:
        """
        Read a file, split into chunks, and store.

        Supports text files, markdown, code files, and any
        UTF-8 decodable content.

        Args:
            path: File path to ingest.
            metadata: Optional metadata dict to attach to each chunk.

        Returns:
            Dict with ingestion stats: {source, chunks_created, total_chunks, status}
        """
        file_path = Path(path)
        if not file_path.exists():
            logger.error(f"File not found: {path}")
            return {"source": path, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "error", "error": f"File not found: {path}"}

        if not file_path.is_file():
            logger.error(f"Not a file: {path}")
            return {"source": path, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "error", "error": f"Not a file: {path}"}

        try:
            # Try UTF-8 first, then fallback
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="latin-1")

            if not text.strip():
                return {"source": path, "chunks_created": 0, "total_chunks": len(self._chunks),
                        "status": "empty", "error": "File is empty"}

            # Build metadata
            file_metadata = {
                "filename": file_path.name,
                "extension": file_path.suffix,
                "size_bytes": file_path.stat().st_size,
                "modified": file_path.stat().st_mtime,
            }
            if metadata:
                file_metadata.update(metadata)

            result = self.ingest_text(text, source=str(path), metadata=file_metadata)
            result["file"] = path
            return result

        except PermissionError:
            logger.error(f"Permission denied: {path}")
            return {"source": path, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "error", "error": f"Permission denied: {path}"}
        except Exception as e:
            logger.error(f"Failed to ingest file {path}: {e}")
            return {"source": path, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "error", "error": str(e)}

    def ingest_text(
        self,
        text: str,
        source: str = "direct_input",
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Split text into chunks and store with TF-IDF indexing.

        Args:
            text: The text content to ingest.
            source: Source identifier for the text.
            metadata: Optional metadata dict to attach to each chunk.

        Returns:
            Dict with ingestion stats.
        """
        if not text or not text.strip():
            return {"source": source, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "empty"}

        # Check max_chunks limit
        if len(self._chunks) >= self.max_chunks:
            logger.warning(f"Max chunks limit reached ({self.max_chunks}). Trimming oldest.")
            self._trim_oldest(len(text) // self.chunk_size + 1)

        # Split into chunks
        chunks_text = self._split_text(text)
        chunks_created = 0

        for chunk_text in chunks_text:
            if len(self._chunks) >= self.max_chunks:
                logger.warning(f"Max chunks limit ({self.max_chunks}) reached during ingestion.")
                break

            chunk_id = f"chunk_{self._next_id}"
            self._next_id += 1

            token_count = estimate_tokens(chunk_text)

            chunk_entry = {
                "id": chunk_id,
                "text": chunk_text,
                "source": source,
                "metadata": metadata or {},
                "tokens": token_count,
                "created": time.time(),
            }

            self._chunks.append(chunk_entry)
            self._sources.add(source)

            # Update inverted index
            self._index_chunk(chunk_id, chunk_text)

            chunks_created += 1

        logger.info(f"Ingested {chunks_created} chunks from '{source}'")

        return {
            "source": source,
            "chunks_created": chunks_created,
            "total_chunks": len(self._chunks),
            "total_sources": len(self._sources),
            "status": "ok",
        }

    def ingest_url(self, url: str) -> dict:
        """
        Fetch URL content via WebBrowser, then ingest.

        Args:
            url: URL to fetch and ingest.

        Returns:
            Dict with ingestion stats.
        """
        if not WEB_BROWSER_AVAILABLE:
            logger.error("WebBrowser not available. Install core.web_browser module.")
            return {"source": url, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "error", "error": "WebBrowser module not available"}

        try:
            browser = WebBrowser()
            result = browser.extract_text(url)

            if "error" in result:
                logger.error(f"Failed to fetch URL {url}: {result['error']}")
                return {"source": url, "chunks_created": 0, "total_chunks": len(self._chunks),
                        "status": "error", "error": result["error"]}

            text = result.get("text", "")
            if not text or not text.strip():
                return {"source": url, "chunks_created": 0, "total_chunks": len(self._chunks),
                        "status": "empty", "error": "No text content extracted from URL"}

            url_metadata = {
                "url": url,
                "title": result.get("title", ""),
                "size": result.get("size", 0),
                "ingested_via": "web_browser",
            }

            return self.ingest_text(text, source=url, metadata=url_metadata)

        except Exception as e:
            logger.error(f"Failed to ingest URL {url}: {e}")
            return {"source": url, "chunks_created": 0, "total_chunks": len(self._chunks),
                    "status": "error", "error": str(e)}

    # ─── SEARCH ───────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Search for relevant chunks using TF-IDF scoring.

        Args:
            query: Search query string.
            top_k: Number of top results to return.

        Returns:
            List of dicts: [{id, text, source, metadata, score, tokens}]
        """
        if not self._chunks:
            logger.warning("No chunks stored. Ingest documents first.")
            return []

        if not query or not query.strip():
            return []

        query_terms = tokenize(query)
        if not query_terms:
            return []

        # Calculate TF-IDF scores for each chunk
        total_chunks = len(self._chunks)
        scores: dict[str, float] = {}

        for term in query_terms:
            if term not in self._index:
                continue

            # IDF = log(total_chunks / chunks_containing_term)
            chunks_with_term = len(self._index[term])
            if chunks_with_term == 0:
                continue
            idf = math.log(total_chunks / chunks_with_term)

            for chunk_id, tf_score in self._index[term].items():
                tf_idf = tf_score * idf
                scores[chunk_id] = scores.get(chunk_id, 0.0) + tf_idf

        if not scores:
            return []

        # Sort by score descending
        sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Build result list
        chunk_map = {c["id"]: c for c in self._chunks}
        results = []

        for chunk_id, score in sorted_results[:top_k]:
            chunk = chunk_map.get(chunk_id)
            if chunk:
                results.append({
                    "id": chunk["id"],
                    "text": chunk["text"],
                    "source": chunk["source"],
                    "metadata": chunk.get("metadata", {}),
                    "tokens": chunk.get("tokens", 0),
                    "score": round(score, 4),
                })

        return results

    def build_context(self, query: str, max_tokens: int = 2000) -> str:
        """
        Build a context string for LLM from top search results.

        Retrieves relevant chunks and assembles them into a single
        context string, respecting the max_tokens limit.

        Args:
            query: The query to search for.
            max_tokens: Approximate maximum token count for the context.

        Returns:
            Formatted context string with source annotations.
        """
        if not self._chunks:
            return ""

        # Retrieve more results than we might need, then trim
        results = self.search(query, top_k=10)
        if not results:
            return ""

        context_parts: list[str] = []
        current_tokens = 0

        for i, result in enumerate(results):
            chunk_text = result["text"]
            source = result["source"]
            chunk_tokens = estimate_tokens(chunk_text)

            # Check if adding this chunk would exceed the limit
            header = f"[Source {i + 1}: {source}]"
            header_tokens = estimate_tokens(header)
            total_add = chunk_tokens + header_tokens + 2  # +2 for newlines

            if current_tokens + total_add > max_tokens:
                # Try to fit a truncated version
                remaining = max_tokens - current_tokens - header_tokens - 2
                if remaining > 50:
                    # Estimate how many chars we can keep
                    chars_allowed = remaining * 4
                    truncated = chunk_text[:chars_allowed] + "..."
                    context_parts.append(f"{header}\n{truncated}")
                    current_tokens += remaining + header_tokens
                break

            context_parts.append(f"{header}\n{chunk_text}")
            current_tokens += total_add

        if not context_parts:
            return ""

        return "\n\n".join(context_parts)

    # ─── STATS & MANAGEMENT ───────────────────────────────

    def get_stats(self) -> dict:
        """Return statistics about the RAG system."""
        sources = set(c["source"] for c in self._chunks)
        total_tokens = sum(c.get("tokens", 0) for c in self._chunks)
        index_size = sum(
            len(postings) for postings in self._index.values()
        )

        return {
            "total_chunks": len(self._chunks),
            "total_sources": len(sources),
            "sources": sorted(sources),
            "total_tokens_approx": total_tokens,
            "index_terms": len(self._index),
            "index_postings": index_size,
            "max_chunks": self.max_chunks,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "next_id": self._next_id,
            "storage_dir": str(self.storage_dir),
        }

    def clear(self) -> None:
        """Clear all stored data (in-memory and on-disk)."""
        self._chunks = []
        self._index = {}
        self._next_id = 0
        self._sources = set()

        # Remove on-disk files
        for filename in ["chunks.json", "index.json", "metadata.json"]:
            filepath = self.storage_dir / filename
            if filepath.exists():
                try:
                    filepath.unlink()
                except OSError as e:
                    logger.warning(f"Failed to delete {filepath}: {e}")

        logger.info("RAG system cleared.")

    # ─── PERSISTENCE ──────────────────────────────────────

    def save(self) -> None:
        """Persist all data to disk."""
        try:
            # Save chunks
            chunks_path = self.storage_dir / "chunks.json"
            with open(chunks_path, "w", encoding="utf-8") as f:
                json.dump(self._chunks, f, ensure_ascii=False, indent=2)

            # Save inverted index
            index_path = self.storage_dir / "index.json"
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)

            # Save metadata
            meta_path = self.storage_dir / "metadata.json"
            metadata = {
                "next_id": self._next_id,
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "max_chunks": self.max_chunks,
                "saved_at": time.time(),
                "stats": self.get_stats(),
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            logger.info(f"RAG data saved to {self.storage_dir}")

        except Exception as e:
            logger.error(f"Failed to save RAG data: {e}")

    def load(self) -> bool:
        """
        Load persisted data from disk.

        Returns:
            True if data was loaded successfully, False otherwise.
        """
        chunks_path = self.storage_dir / "chunks.json"
        index_path = self.storage_dir / "index.json"
        meta_path = self.storage_dir / "metadata.json"

        if not chunks_path.exists():
            return False

        try:
            # Load chunks
            with open(chunks_path, "r", encoding="utf-8") as f:
                self._chunks = json.load(f)

            # Load inverted index
            if index_path.exists():
                with open(index_path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)

            # Load metadata
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                self._next_id = metadata.get("next_id", len(self._chunks))

                # Restore sources set from chunks
                self._sources = set(c.get("source", "") for c in self._chunks if c.get("source"))

            else:
                self._next_id = len(self._chunks)
                self._sources = set(c.get("source", "") for c in self._chunks if c.get("source"))

            logger.info(
                f"RAG data loaded: {len(self._chunks)} chunks, "
                f"{len(self._index)} index terms from {self.storage_dir}"
            )
            return True

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to load RAG data (corrupt file?): {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to load RAG data: {e}")
            return False

    # ─── INTERNAL: TEXT SPLITTING ─────────────────────────

    def _split_text(self, text: str) -> list[str]:
        """
        Split text into overlapping chunks.

        Tries to split at paragraph or sentence boundaries first,
        falling back to character-level splitting.

        Args:
            text: The text to split.

        Returns:
            List of chunk strings.
        """
        if len(text) <= self.chunk_size:
            return [text]

        chunks: list[str] = []

        # Try paragraph-aware splitting first
        paragraphs = re.split(r"\n\s*\n", text)

        current_chunk = ""
        for para in paragraphs:
            # If adding this paragraph would exceed chunk_size, flush current
            if current_chunk and len(current_chunk) + len(para) + 2 > self.chunk_size:
                chunks.append(current_chunk.strip())
                # Overlap: keep tail of current chunk
                overlap_text = current_chunk[-self.chunk_overlap:] if self.chunk_overlap > 0 else ""
                current_chunk = overlap_text + "\n\n" + para
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para

        # Flush remaining
        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # Validate chunk sizes — split any that are still too large
        final_chunks: list[str] = []
        for chunk in chunks:
            if len(chunk) <= self.chunk_size:
                final_chunks.append(chunk)
            else:
                # Hard split with overlap
                sub_chunks = self._hard_split(chunk)
                final_chunks.extend(sub_chunks)

        return final_chunks

    def _hard_split(self, text: str) -> list[str]:
        """
        Hard character-level splitting with overlap.

        Used as fallback when paragraph-aware splitting produces
        chunks that are still too large.

        Args:
            text: Text to split.

        Returns:
            List of chunk strings.
        """
        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = start + self.chunk_size

            # Try to find a sentence boundary near the end
            if end < len(text):
                # Look for sentence-ending punctuation
                boundary = -1
                for sep in [". ", "! ", "? ", "\n", "; ", ", "]:
                    pos = text.rfind(sep, start + self.chunk_size // 2, end)
                    if pos > boundary:
                        boundary = pos + len(sep)

                if boundary > start:
                    end = boundary

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move forward with overlap
            start = end - self.chunk_overlap if end < len(text) else end

        return chunks

    # ─── INTERNAL: INDEXING ───────────────────────────────

    def _index_chunk(self, chunk_id: str, text: str) -> None:
        """
        Add a chunk's terms to the inverted index.

        TF = count of term in chunk / total terms in chunk
        """
        tokens = tokenize(text)
        if not tokens:
            return

        total_terms = len(tokens)
        term_counts = Counter(tokens)

        for term, count in term_counts.items():
            tf_score = count / total_terms  # Normalized term frequency

            if term not in self._index:
                self._index[term] = {}

            self._index[term][chunk_id] = tf_score

    def _deindex_chunk(self, chunk_id: str) -> None:
        """
        Remove a chunk's entries from the inverted index.

        Args:
            chunk_id: The chunk ID to remove.
        """
        terms_to_remove: list[str] = []

        for term, postings in self._index.items():
            if chunk_id in postings:
                del postings[chunk_id]
                if not postings:
                    terms_to_remove.append(term)

        for term in terms_to_remove:
            del self._index[term]

    def _trim_oldest(self, count: int) -> None:
        """
        Remove the oldest chunks to make room for new ones.

        Args:
            count: Number of chunks to remove.
        """
        to_remove = min(count, len(self._chunks))
        for i in range(to_remove):
            chunk = self._chunks[i]
            self._deindex_chunk(chunk["id"])

        self._chunks = self._chunks[to_remove:]
        logger.info(f"Trimmed {to_remove} oldest chunks (max_chunks limit).")

    # ─── CONVENIENCE ──────────────────────────────────────

    def search_by_source(self, source: str, top_k: int = 10) -> list[dict]:
        """
        Retrieve chunks from a specific source.

        Args:
            source: Source identifier to filter by.
            top_k: Maximum number of chunks to return.

        Returns:
            List of chunk dicts from the specified source.
        """
        matching = [c for c in self._chunks if c.get("source") == source]
        return matching[:top_k]

    def delete_source(self, source: str) -> dict:
        """
        Delete all chunks from a specific source.

        Args:
            source: Source identifier to remove.

        Returns:
            Dict with deletion stats.
        """
        chunks_to_remove = [c for c in self._chunks if c.get("source") == source]
        removed_count = len(chunks_to_remove)

        for chunk in chunks_to_remove:
            self._deindex_chunk(chunk["id"])

        self._chunks = [c for c in self._chunks if c.get("source") != source]
        self._sources.discard(source)

        logger.info(f"Deleted {removed_count} chunks from source '{source}'")

        return {
            "source": source,
            "chunks_removed": removed_count,
            "total_chunks": len(self._chunks),
            "status": "ok",
        }

    def __len__(self) -> int:
        return len(self._chunks)

    def __repr__(self) -> str:
        return (
            f"RAGSystem(chunks={len(self._chunks)}, "
            f"sources={len(self._sources)}, "
            f"terms={len(self._index)})"
        )
