"""
NEXUS v9.2 — Response Cache
Caches frequently asked question-answer pairs for instant responses.
Like skills, but for Q&A — stores answers to repeated questions
so they can be served < 10ms instead of calling the LLM.

How it works:
1. When a question is asked, check the cache for similar questions (fuzzy match)
2. If found with high confidence → return cached answer instantly
3. If not found → process normally, then store if the question seems recurring
4. Periodically prune old/low-hit entries

Storage: data/response_cache.json
"""

import json
import time
import hashlib
import logging
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field, asdict

log = logging.getLogger("nexus.response_cache")

CACHE_DIR = Path("data")
CACHE_FILE = CACHE_DIR / "response_cache.json"

# Minimum similarity (0-1) to consider a cache hit
SIMILARITY_THRESHOLD = 0.85
# Minimum hits before a cached answer is considered "recurring"
MIN_HITS_FOR_PRIORITY = 2
# Maximum cache entries
MAX_CACHE_SIZE = 500
# TTL in seconds (7 days)
CACHE_TTL = 7 * 24 * 3600


@dataclass
class CacheEntry:
    """A cached question-answer pair."""
    question: str           # Original question (normalized)
    answer: str            # The response that was given
    question_hash: str      # MD5 hash for fast lookup
    hits: int = 0          # How many times this entry was used
    last_hit: float = 0.0  # Timestamp of last hit
    created: float = 0.0   # When this entry was created
    importance: float = 0.5  # How important (0-1, based on frequency)
    source: str = "auto"    # "auto" = auto-learned, "manual" = user-defined


class ResponseCache:
    """
    Cache for frequently asked questions.
    Provides instant responses for recurring questions without LLM calls.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.max_size = self.config.get("max_cache_size", MAX_CACHE_SIZE)
        self.ttl = self.config.get("cache_ttl", CACHE_TTL)
        self.similarity_threshold = self.config.get("similarity_threshold", SIMILARITY_THRESHOLD)
        self._entries: List[CacheEntry] = []
        self._hash_index: dict[str, int] = {}  # hash -> index in _entries
        self._dirty = False
        self._load()

    def _load(self):
        """Load cache from disk."""
        if not CACHE_FILE.exists():
            self._entries = []
            self._rebuild_index()
            return

        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            entries = []
            for item in data.get("entries", []):
                entry = CacheEntry(
                    question=item.get("question", ""),
                    answer=item.get("answer", ""),
                    question_hash=item.get("question_hash", ""),
                    hits=item.get("hits", 0),
                    last_hit=item.get("last_hit", 0),
                    created=item.get("created", 0),
                    importance=item.get("importance", 0.5),
                    source=item.get("source", "auto"),
                )
                entries.append(entry)

            # Sort by importance (highest first) for better search
            entries.sort(key=lambda e: e.importance, reverse=True)
            self._entries = entries
            self._rebuild_index()
            log.info(f"Loaded {len(self._entries)} cached responses")
        except Exception as e:
            log.warning(f"Failed to load response cache: {e}")
            self._entries = []
            self._rebuild_index()

    def _rebuild_index(self):
        """Rebuild hash index for fast lookups."""
        self._hash_index = {}
        for i, entry in enumerate(self._entries):
            self._hash_index[entry.question_hash] = i

    def _save(self):
        """Save cache to disk."""
        if not self._dirty:
            return

        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 1,
                "entries": [asdict(e) for e in self._entries],
            }
            CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._dirty = False
            log.debug(f"Saved {len(self._entries)} cached responses")
        except Exception as e:
            log.warning(f"Failed to save response cache: {e}")

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison: lowercase, strip punctuation, collapse whitespace."""
        text = text.lower().strip()
        # Remove common filler words
        fillers = ["bitte", "mal", "kannst du", "könntest du", "kannst", "würde", "würdest"]
        for f in fillers:
            text = text.replace(f, "")
        # Collapse whitespace
        import re
        text = re.sub(r'\s+', ' ', text).strip()
        # Remove trailing punctuation
        text = text.rstrip('?.!')
        return text

    @staticmethod
    def _hash(text: str) -> str:
        """MD5 hash of normalized text for fast exact matching."""
        return hashlib.md5(ResponseCache._normalize(text).encode()).hexdigest()[:16]

    def _similarity(self, text1: str, text2: str) -> float:
        """
        Simple word-overlap similarity for fuzzy matching.
        Fast enough for real-time use, no ML model needed.
        """
        words1 = set(self._normalize(text1).split())
        words2 = set(self._normalize(text2).split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def lookup(self, question: str) -> Optional[CacheEntry]:
        """
        Look up a cached response for a question.
        Returns CacheEntry if found with high confidence, None otherwise.
        """
        # 1. Fast exact hash lookup
        q_hash = self._hash(question)
        if q_hash in self._hash_index:
            idx = self._hash_index[q_hash]
            entry = self._entries[idx]
            entry.hits += 1
            entry.last_hit = time.time()
            entry.importance = min(1.0, entry.importance + 0.05)
            self._dirty = True
            log.debug(f"Cache HIT (exact): '{question[:50]}' -> {entry.hits} hits")
            return entry

        # 2. Fuzzy similarity search (only top entries by importance)
        best_match = None
        best_score = 0.0
        normalized_q = self._normalize(question)

        # Only search top entries (sorted by importance)
        for entry in self._entries[:200]:
            score = self._similarity(normalized_q, entry.question)
            if score > best_score:
                best_score = score
                best_match = entry

        if best_match and best_score >= self.similarity_threshold:
            best_match.hits += 1
            best_match.last_hit = time.time()
            best_match.importance = min(1.0, best_match.importance + 0.05)
            self._dirty = True
            log.debug(f"Cache HIT (fuzzy {best_score:.2f}): '{question[:50]}' -> '{best_match.question[:50]}'")
            return best_match

        log.debug(f"Cache MISS: '{question[:50]}'")
        return None

    def store(self, question: str, answer: str, importance: float = 0.5,
              source: str = "auto") -> bool:
        """
        Store a question-answer pair in the cache.
        Only stores if the question seems worth caching (not too generic).
        Returns True if stored, False if skipped.
        """
        # Don't cache very short or very long questions
        normalized = self._normalize(question)
        if len(normalized) < 5 or len(normalized) > 300:
            return False

        # Don't cache very short answers (acknowledgments, etc.)
        if len(answer.strip()) < 20:
            return False

        # Don't cache if it looks like a one-off command
        if normalized.startswith(("/", "!")):
            return False

        # Check if already cached (exact or fuzzy)
        existing = self.lookup(question)
        if existing:
            # Update existing entry with potentially better answer
            if len(answer) > len(existing.answer) * 1.2:
                existing.answer = answer
                existing.importance = max(existing.importance, importance)
                self._dirty = True
            return False

        # Create new entry
        entry = CacheEntry(
            question=normalized,
            answer=answer,
            question_hash=self._hash(question),
            hits=1,
            last_hit=time.time(),
            created=time.time(),
            importance=importance,
            source=source,
        )

        self._entries.append(entry)
        self._hash_index[entry.question_hash] = len(self._entries) - 1
        self._dirty = True

        # Prune if over max size
        if len(self._entries) > self.max_size:
            self._prune()

        self._save()
        log.info(f"Cached response for: '{normalized[:50]}' (importance={importance:.2f})")
        return True

    def _prune(self):
        """Remove low-importance, old entries."""
        now = time.time()
        pruned = []
        for entry in self._entries:
            # Keep if: important, recent, or frequently used
            if (entry.importance >= 0.7 or
                entry.hits >= MIN_HITS_FOR_PRIORITY or
                (now - entry.last_hit) < self.ttl or
                entry.source == "manual"):
                pruned.append(entry)
        removed = len(self._entries) - len(pruned)
        self._entries = sorted(pruned, key=lambda e: e.importance, reverse=True)
        self._rebuild_index()
        if removed > 0:
            log.info(f"Pruned {removed} cache entries (kept {len(self._entries)})")

    def stats(self) -> dict:
        """Return cache statistics."""
        total_hits = sum(e.hits for e in self._entries)
        avg_importance = sum(e.importance for e in self._entries) / max(1, len(self._entries))
        return {
            "entries": len(self._entries),
            "total_hits": total_hits,
            "avg_importance": round(avg_importance, 3),
            "manual_entries": sum(1 for e in self._entries if e.source == "manual"),
            "auto_entries": sum(1 for e in self._entries if e.source == "auto"),
        }

    def add_manual(self, question: str, answer: str, importance: float = 0.9) -> bool:
        """Manually add a cached response (high priority, won't be pruned)."""
        return self.store(question, answer, importance=importance, source="manual")

    def search(self, query: str, limit: int = 10) -> List[CacheEntry]:
        """Search cached entries by question text (for /cache command)."""
        normalized = self._normalize(query)
        results = []
        for entry in self._entries:
            score = self._similarity(normalized, entry.question)
            if score > 0.3 or normalized in entry.question:
                results.append((score, entry))
        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]