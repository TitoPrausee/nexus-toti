"""
NEXUS v7 — Memory System
L1: Working (current conversation)
L2: Session (recent, summarized)
L3: Long-term (important facts)
L4: Soul (identity, persistent)

v7.1: Improved L2 compression with topic extraction and fact distillation.
v7.2: Vector search for L3 memory (sentence-transformers semantic similarity).
v7.3: Query-aware L2 context selection — scores sessions by topic relevance.
"""

import json
import time
import os
import re
import math
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from nexus.core.vector_store import VectorStore

log = logging.getLogger("nexus.memory")


@dataclass
class MemoryEntry:
    role: str
    content: str
    timestamp: float = 0.0
    tokens: int = 0
    importance: float = 0.5  # 0.0-1.0

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "tokens": self.tokens,
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class MemorySystem:
    """
    4-layer memory inspired by human cognition.

    L1 (Working): Current conversation — auto-trimmed to fit token budget
    L2 (Session): Recent conversations, summarized for context
    L3 (Long-term): Important facts, user preferences, learned patterns
    L4 (Soul): Identity, relationships — managed by SoulEngine

    v7.3 improvements:
    - Query-aware L2 context selection: scores sessions by topic relevance
      to the current query, not just recency. Sessions about the same topic
      are prioritized even if they're older.
    - L3 vector search using sentence-transformers for semantic similarity
    - Hybrid scoring: 60% vector similarity + 40% keyword matching
    - Graceful fallback to keyword-only search if model unavailable
    - Persistent embedding cache for fast restarts
    """

    def __init__(self, data_dir: str = "data/memory", config: dict = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        cfg = config or {}
        self.l1_max_tokens = cfg.get("l1_max_tokens", 8000)
        self.l2_max_entries = cfg.get("l2_max_entries", 50)
        self.l2_max_age_hours = cfg.get("l2_max_age_hours", 48)
        self.l3_max_entries = cfg.get("l3_max_entries", 200)
        self.compress_threshold = cfg.get("compress_threshold", 0.7)

        # L1: Active conversation
        self.l1: list[MemoryEntry] = []

        # L2: Recent sessions (loaded from disk)
        self.l2: list[dict] = []

        # L3: Long-term facts (loaded from disk)
        self.l3: list[dict] = []

        # Vector store for semantic L3 search (v7.2)
        vector_config = cfg.get("vector_search", {})
        self.vector_store = VectorStore(
            data_dir=str(self.data_dir),
            config=vector_config,
        )

        self._load()

    def _load(self):
        """Load L2 and L3 from disk."""
        l2_file = self.data_dir / "session.json"
        if l2_file.exists():
            with open(l2_file, "r", encoding="utf-8") as f:
                self.l2 = json.load(f)

        l3_file = self.data_dir / "longterm.json"
        if l3_file.exists():
            with open(l3_file, "r", encoding="utf-8") as f:
                self.l3 = json.load(f)

    def save(self):
        """Persist L2 and L3."""
        with open(self.data_dir / "session.json", "w", encoding="utf-8") as f:
            json.dump(self.l2, f, ensure_ascii=False, indent=2)

        with open(self.data_dir / "longterm.json", "w", encoding="utf-8") as f:
            json.dump(self.l3, f, ensure_ascii=False, indent=2)

    # ─── L1: Working Memory ────────────────────────────

    def add(self, role: str, content: str, importance: float = 0.5):
        """Add message to working memory."""
        # Rough token estimate
        tokens = max(1, len(content.split()))

        entry = MemoryEntry(
            role=role,
            content=content,
            timestamp=time.time(),
            tokens=tokens,
            importance=importance,
        )
        self.l1.append(entry)

        # Auto-trim if over budget
        if self._l1_token_count() > self.l1_max_tokens:
            self._compress_l1()

        return entry

    def get_context(self, max_tokens: int = None, query: str = None) -> list[dict]:
        """Get conversation context for LLM call.

        v7.3: Uses query-aware L2 selection — scores L2 sessions by topic
        overlap with the current query, not just recency. Falls back to
        recency-only when no query is available.

        L3 selection uses hybrid vector + keyword search with deduplication.
        """
        budget = max_tokens or self.l1_max_tokens

        # Start from most recent, work backwards
        context = []
        total = 0

        # 1. L3 facts — relevance-based selection with deduplication
        if query:
            relevant_facts = self.get_relevant_context(query, max_facts=5, budget_pct=0.2)
        else:
            # No query: sort by relevance score for general importance
            relevant_facts = sorted(
                self.l3, key=lambda x: self._relevance_score(x), reverse=True
            )[:5]

        # Deduplicate facts — avoid sending similar content
        seen_topics = set()
        for fact in relevant_facts:
            fact_text = fact.get("content", "")
            # Simple topic dedup: use first 5 significant words
            topic_key = self._topic_key(fact_text)
            if topic_key in seen_topics:
                continue
            seen_topics.add(topic_key)

            tokens = max(1, len(fact_text.split()))
            if total + tokens < budget * 0.2:
                context.append({"role": "system", "content": f"[Erinnerung] {fact_text}"})
                total += tokens

        # 2. L2 summaries — query-aware selection with topic scoring
        # Score L2 sessions by topic overlap with the current query,
        # then prioritize relevant sessions over merely recent ones.
        scored_sessions = []
        for session in self.l2:
            session_topics = set(session.get("topics", []))
            session_summary = session.get("summary", "")
            session_ts = session.get("timestamp", 0)
            session_age_hours = (time.time() - session_ts) / 3600 if session_ts else 9999

            # Relevance: topic overlap with query
            topic_relevance = 0.0
            if query and session_topics:
                query_topics = set(self._extract_topics(query))
                overlap = query_topics & session_topics
                if overlap:
                    topic_relevance = len(overlap) / max(len(query_topics), 1)

            # Recency: exponential decay like L3 (half-life 24h for L2)
            recency_score = math.exp(-session_age_hours / 24.0)

            # Combined score: topic relevance (0.6) + recency (0.4)
            score = topic_relevance * 0.6 + recency_score * 0.4
            scored_sessions.append((score, session))

        # Sort by score descending, take top candidates
        scored_sessions.sort(key=lambda x: x[0], reverse=True)
        l2_candidates = [s for _, s in scored_sessions[:8]]  # Consider top 8

        seen_summary_topics = set()
        for session in l2_candidates:
            summary = session.get("summary", "")
            if not summary:
                continue
            # Skip summaries that overlap with already-included facts
            summary_key = self._topic_key(summary)
            if summary_key in seen_summary_topics:
                continue
            seen_summary_topics.add(summary_key)

            # Prefer structured summaries (v7.1) over raw pipe-joins
            topics = session.get("topics", [])
            if topics:
                summary_lines = [f"Themen: {', '.join(topics)}"]
                key_facts = session.get("key_facts", [])
                if key_facts:
                    summary_lines.append("Wichtig: " + "; ".join(key_facts[:3]))
                decisions = session.get("decisions", [])
                if decisions:
                    summary_lines.append("Entscheidungen: " + "; ".join(decisions[:2]))
                summary_text = " | ".join(summary_lines)
            else:
                summary_text = summary

            tokens = max(1, len(summary_text.split()))
            if total + tokens < budget * 0.3:
                context.append({"role": "system", "content": f"[Kontext] {summary_text}"})
                total += tokens

        # 3. L1 conversation (most recent first, fill remaining budget)
        remaining = budget - total
        conv_entries = []
        conv_tokens = 0
        for entry in reversed(self.l1):
            if conv_tokens + entry.tokens > remaining:
                break
            conv_entries.append(entry.to_dict())
            conv_tokens += entry.tokens

        context.extend(reversed(conv_entries))
        return context

    def _l1_token_count(self) -> int:
        return sum(e.tokens for e in self.l1)

    def _compress_l1(self):
        """Compress L1 by keeping recent + important entries.

        v7.1: Creates structured L2 summaries with topics, key facts, and decisions
        instead of crude pipe-joined concatenation.
        """
        if len(self.l1) < 4:
            return

        # Keep first (system prompt) and last 60%
        keep_count = max(2, int(len(self.l1) * 0.6))
        mid = self.l1[1:-keep_count]
        kept = [self.l1[0]] + self.l1[-keep_count:]

        # Extract structured summary from removed entries
        summary = self._extract_session_summary(mid)

        self.l2.append(summary)
        self._trim_l2()

        self.l1 = kept

    def _extract_session_summary(self, entries: list[MemoryEntry]) -> dict:
        """Extract a structured summary from a list of memory entries.

        Instead of raw pipe-joins, this extracts:
        - topics: key subjects discussed
        - key_facts: important statements or data points
        - decisions: any decisions or conclusions reached
        - summary: a concise text summary
        """
        topics = set()
        key_facts = []
        decisions = []

        for entry in entries:
            content = entry.content.strip()
            if not content:
                continue

            # Extract topics from content (nouns/keywords)
            entry_topics = self._extract_topics(content)
            topics.update(entry_topics)

            # Classify the content
            is_important = entry.importance >= 0.7
            is_decision = any(
                w in content.lower() for w in
                ["entscheidung", "entschieden", "beschluss", "werde ", "soll ",
                 "werden", "sollen", "muss", "decision", "decided", "will "]
            )
            is_question = content.strip().endswith("?")
            is_short = len(content.split()) < 8

            # Only keep substantive content in key facts
            if is_important and not is_question and not is_short:
                # Truncate for summary compactness
                fact = content[:150].rstrip()
                if fact and fact not in key_facts:
                    key_facts.append(fact)

            if is_decision:
                fact = content[:120].rstrip()
                if fact and fact not in decisions:
                    decisions.append(fact)

        # Limit collections to keep summaries compact
        topics = sorted(topics)[:5]
        key_facts = key_facts[:5]
        decisions = decisions[:3]

        # Build text summary
        summary_parts = []
        if topics:
            summary_parts.append(f"Themen: {', '.join(topics)}")
        if key_facts:
            summary_parts.append("Wichtig: " + "; ".join(key_facts[:3]))
        if decisions:
            summary_parts.append("Entscheidungen: " + "; ".join(decisions[:2]))

        # Fallback: if extraction yielded nothing, use truncated content
        if not summary_parts:
            raw = " | ".join(f"{e.role}: {e.content[:80]}" for e in entries[:3])
            summary_text = raw[:500]
        else:
            summary_text = " | ".join(summary_parts)

        return {
            "timestamp": time.time(),
            "summary": summary_text[:1000],
            "topics": topics,
            "key_facts": key_facts,
            "decisions": decisions,
            "entries_removed": len(entries),
        }

    # ─── Topic Extraction ──────────────────────────────────

    # Common German and English stop words to filter out
    # v7.4: Expanded with high-frequency content words that cause false topic overlap
    _STOP_WORDS = frozenset({
        # German — pronouns, articles, prepositions, conjunctions, auxiliaries
        "ich", "du", "er", "sie", "es", "wir", "ihr", "der", "die", "das",
        "ein", "eine", "und", "oder", "aber", "nicht", "ist", "sind", "war", "hat",
        "haben", "mit", "auf", "von", "zu", "an", "im", "in", "aus", "bei", "nach",
        "für", "noch", "auch", "sich", "als", "wie", "so", "wenn", "dann", "dass",
        "dieser", "diese", "dieses", "was", "wer", "wo", "wann", "warum",
        # German — common adverbs, fillers, quantifiers
        "schon", "hier", "mal", "über", "vor", "zur", "zum", "einfach", "gerne",
        "werde", "werden", "muss", "müssen", "sollen", "brauch", "brauchen",
        "viel", "mehr", "ganz", "nur", "immer", "wieder", "durch", "zwischen",
        "gegen", "ohne", "um", "bis", "seit", "wegen", "während", "bevor",
        # English — pronouns, articles, prepositions, conjunctions, auxiliaries
        "the", "is", "are", "was", "were", "a", "an", "and", "or", "but", "not",
        "in", "on", "at", "to", "for", "of", "with", "by", "from", "as", "it",
        "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
        "my", "your", "his", "our", "their", "this", "that", "these", "those",
        "do", "does", "did", "have", "has", "had", "be", "been", "being",
        "can", "could", "will", "would", "should", "may", "might",
        # English — common adverbs, fillers, quantifiers, adjectives
        "about", "also", "just", "really", "very", "much", "many", "some",
        "into", "more", "most", "other", "than", "then", "there", "need",
        "like", "want", "know", "think", "make", "get", "got", "new", "one",
        "two", "first", "last", "long", "great", "little", "right", "big",
        "small", "old", "different", "same", "able", "because", "good", "bad",
        "well", "even", "only", "using", "used", "use", "work", "way", "back",
        "over", "after", "thing", "stuff", "fact",
    })

    @classmethod
    def _extract_topics(cls, text: str) -> list[str]:
        """Extract key topics/keywords from text content.

        Filters stop words, short words, and returns the top 5
        most meaningful words as topic indicators.
        """
        # Tokenize: keep only alphabetic words
        words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', text.lower())

        # Filter stop words
        meaningful = [w for w in words if w not in cls._STOP_WORDS]

        # Count frequency to find most important topics
        from collections import Counter
        word_counts = Counter(meaningful)

        # Return top 5 most frequent meaningful words
        return [word for word, _ in word_counts.most_common(5)]

    @classmethod
    def _topic_key(cls, text: str) -> str:
        """Create a topic deduplication key from text.

        Uses the most significant words to create a canonical key
        for comparing whether two texts cover the same topic.
        """
        topics = cls._extract_topics(text.lower())
        # Use the top 3 topics as the dedup key
        return "|".join(sorted(topics[:3]))

    def _trim_l2(self):
        """Keep L2 within bounds."""
        max_age = self.l2_max_age_hours * 3600
        now = time.time()

        # Remove old entries
        self.l2 = [s for s in self.l2 if now - s.get("timestamp", 0) < max_age]

        # Remove excess entries
        if len(self.l2) > self.l2_max_entries:
            self.l2 = self.l2[-self.l2_max_entries:]

    # ─── L3: Long-term Memory ──────────────────────────

    def remember(self, content: str, category: str = "general", importance: float = 0.7):
        """Store an important fact in long-term memory.

        v7.1: Improved deduplication — fuzzy matching by topic overlap,
        not just exact string match.
        v7.2: Auto-indexes new entries for vector search.
        """
        content_stripped = content.strip()

        # Exact duplicate check
        content_lower = content_stripped.lower()
        for existing in self.l3:
            if existing.get("content", "").lower().strip() == content_lower:
                # Update existing entry instead of duplicating
                existing["importance"] = max(existing.get("importance", 0.5), importance)
                existing["access_count"] = existing.get("access_count", 0) + 1
                existing["last_accessed"] = time.time()
                self.save()
                # Re-index for vector search
                self._index_vector_store()
                return

        # Fuzzy dedup: check if a very similar fact already exists
        new_topic_key = self._topic_key(content_stripped)
        for existing in self.l3:
            existing_key = self._topic_key(existing.get("content", ""))
            # If topics overlap significantly (2+ shared keywords), treat as similar
            new_topics = set(new_topic_key.split("|"))
            existing_topics = set(existing_key.split("|"))
            overlap = new_topics & existing_topics
            if len(overlap) >= 2 and len(new_topics) >= 2:
                # Merge: update existing with higher importance, don't add duplicate
                existing["importance"] = max(existing.get("importance", 0.5), importance)
                existing["access_count"] = existing.get("access_count", 0) + 1
                existing["last_accessed"] = time.time()
                self.save()
                # Re-index for vector search
                self._index_vector_store()
                return

        self.l3.append({
            "content": content_stripped,
            "category": category,
            "importance": importance,
            "timestamp": time.time(),
            "access_count": 1,
            "last_accessed": time.time(),
            "topics": self._extract_topics(content_stripped),
        })

        # Keep within bounds — remove lowest relevance score
        if len(self.l3) > self.l3_max_entries:
            self._apply_decay()
            self.l3.sort(key=lambda x: self._relevance_score(x), reverse=True)
            self.l3 = self.l3[:self.l3_max_entries]

        self.save()
        # Re-index for vector search (new entry added)
        self._index_vector_store()

    def recall(self, query: str, limit: int = 5) -> list[str]:
        """Recall from long-term memory using hybrid search.

        v7.2: Combines vector similarity (semantic) with keyword matching + importance
        + recency + access frequency. Falls back to keyword-only if vector store
        is unavailable.
        """
        if not self.l3:
            return []

        # Step 1: Get vector similarity results
        vector_results: dict[str, float] = {}  # entry content hash -> similarity score
        try:
            if self.vector_store.enabled and self.vector_store._ensure_model():
                vs_results = self.vector_store.search(
                    query, self.l3, top_k=len(self.l3), threshold=0.0
                )
                for score, entry in vs_results:
                    # Map entry to its content for lookup
                    content_key = entry.get("content", "")
                    vector_results[content_key] = score
        except Exception as e:
            log.warning(f"Vector search failed, falling back to keyword-only: {e}")
            vector_results = {}

        # Step 2: Compute keyword scores for all entries
        query_lower = query.lower()
        words = query_lower.split()

        scored = []
        for entry in self.l3:
            content_lower = entry.get("content", "").lower()
            # Keyword match score (normalized to 0-1 range)
            keyword_hits = sum(1 for w in words if w in content_lower)
            if keyword_hits == 0 and not vector_results:
                continue  # Skip entries with no keyword match when no vector search
            keyword_score = min(keyword_hits / max(len(words), 1), 1.0)

            # Get vector similarity score (or None if not available)
            v_score = vector_results.get(entry.get("content", ""))

            # Compute hybrid relevance score
            base_relevance = self._relevance_score(entry, keyword_score=0)
            if v_score is not None:
                # Hybrid: vector similarity (60%) + keyword match (40%)
                hybrid_semantic = self.vector_store.hybrid_score(
                    query, entry, keyword_score, v_score
                )
                # Combine with base relevance (importance + recency + frequency)
                relevance = base_relevance * 0.4 + hybrid_semantic * 0.6
            elif keyword_hits > 0:
                # Keyword-only fallback — weight keywords more heavily
                relevance = base_relevance + min(keyword_hits * 0.1, 0.3)
            else:
                continue

            scored.append((relevance, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Update access counts for recalled entries
        results = []
        for relevance, entry in scored[:limit]:
            entry["access_count"] = entry.get("access_count", 0) + 1
            entry["last_accessed"] = time.time()
            results.append(entry.get("content", ""))

        if results:
            self.save()

        return results

    # ─── Relevance & Decay ─────────────────────────────

    @staticmethod
    def _relevance_score(entry: dict, keyword_score: int = 0) -> float:
        """Calculate relevance score for an L3 entry.

        Components: importance (0-1) + access frequency bonus + recency bonus + keyword match.
        High-access, recent, important entries score higher even without keyword match.
        """
        importance = entry.get("importance", 0.5)
        access_count = entry.get("access_count", 0)
        age_hours = (time.time() - entry.get("timestamp", time.time())) / 3600

        # Base: importance weight (0.0 - 1.0)
        score = importance * 0.4

        # Access frequency bonus: log-scale so frequent access matters but doesn't dominate
        # log2(1 + count) maps 1→1, 5→2.6, 20→4.4, 100→6.7
        freq_bonus = math.log2(1 + access_count) / 7.0  # Normalized to ~0-1 range
        score += freq_bonus * 0.3

        # Recency bonus: exponential decay, half-life ~48 hours
        # Recent entries (age < 48h) get up to 0.3 bonus
        recency_bonus = 0.3 * math.exp(-age_hours / 48.0)
        score += recency_bonus

        # Keyword match bonus
        score += min(keyword_score * 0.1, 0.3)

        return score

    def _apply_decay(self):
        """Apply memory decay to L3 entries.

        Entries with very low relevance fade out:
        - Low importance + never accessed + old = strong decay
        - High importance or frequently accessed = preserved
        """
        now = time.time()
        to_remove = []
        for entry in self.l3:
            age_days = (now - entry.get("timestamp", now)) / 86400
            access_count = entry.get("access_count", 0)
            importance = entry.get("importance", 0.5)

            # Never decay high-importance or frequently accessed
            if importance >= 0.9 or access_count >= 5:
                continue

            # Decay threshold increases with age and lack of access
            if age_days > 30 and access_count == 0 and importance < 0.5:
                to_remove.append(entry)
            elif age_days > 60 and access_count <= 1 and importance < 0.7:
                to_remove.append(entry)

        for entry in to_remove:
            self.l3.remove(entry)

    def get_relevant_context(self, query: str, max_facts: int = 5, budget_pct: float = 0.2) -> list[dict]:
        """Get the most relevant L3 facts for a given query.

        v7.2: Uses hybrid vector + keyword search with semantic deduplication.
        Falls back to keyword-only if vector store is unavailable.
        """
        if not self.l3:
            return []

        if not query:
            # Fallback: recent important entries
            return sorted(self.l3, key=lambda x: self._relevance_score(x), reverse=True)[:max_facts]

        # Step 1: Vector search
        vector_results: dict[str, float] = {}
        try:
            if self.vector_store.enabled and self.vector_store._ensure_model():
                vs_results = self.vector_store.search(
                    query, self.l3, top_k=len(self.l3), threshold=0.0
                )
                for score, entry in vs_results:
                    vector_results[entry.get("content", "")] = score
        except Exception as e:
            log.warning(f"Vector search in get_relevant_context failed: {e}")

        # Step 2: Score all entries with hybrid approach
        words = query.lower().split()
        scored = []
        for entry in self.l3:
            content_lower = entry.get("content", "").lower()
            keyword_hits = sum(1 for w in words if w in content_lower)
            keyword_score = min(keyword_hits / max(len(words), 1), 1.0)

            v_score = vector_results.get(entry.get("content", ""))

            base_relevance = self._relevance_score(entry, keyword_score=0)
            if v_score is not None:
                hybrid_semantic = self.vector_store.hybrid_score(
                    query, entry, keyword_score, v_score
                )
                relevance = base_relevance * 0.4 + hybrid_semantic * 0.6
            elif keyword_hits > 0:
                relevance = base_relevance + min(keyword_hits * 0.1, 0.3)
            else:
                relevance = base_relevance

            # Skip entries with very low relevance
            if relevance <= 0.2:
                continue

            scored.append((relevance, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate: skip entries that overlap significantly with already-selected ones
        selected_topics = set()
        results = []
        for relevance, entry in scored:
            # Check for topic overlap with already-selected entries
            entry_topics = set(entry.get("topics", self._extract_topics(entry.get("content", ""))))
            if entry_topics:
                overlap_with_selected = any(
                    len(entry_topics & sel_topics) >= 2
                    for sel_topics in selected_topics
                    if sel_topics
                )
                if overlap_with_selected:
                    continue  # Skip — too similar to already selected

            # Update access count
            entry["access_count"] = entry.get("access_count", 0) + 1
            entry["last_accessed"] = time.time()
            results.append(entry)
            selected_topics.add(frozenset(entry_topics))

            if len(results) >= max_facts:
                break

        return results

    # ─── Session Management ────────────────────────────

    def end_session(self):
        """Called when conversation ends. Archive to L2.

        v7.1: Creates structured summary with topics, key facts,
        and decisions instead of crude pipe-join.
        """
        if not self.l1:
            return

        # Use the improved structured summary extraction
        summary = self._extract_session_summary(self.l1)
        # Override entries_removed with actual L1 count
        summary["entries_removed"] = len(self.l1)
        # For end_session, the whole conversation is the summary
        # So include user messages in key facts extraction
        user_messages = [e for e in self.l1 if e.role == "user"]
        if user_messages:
            user_topics = set()
            for msg in user_messages:
                user_topics.update(self._extract_topics(msg.content))
            summary["topics"] = sorted(user_topics)[:5]

        self.l2.append(summary)
        self._trim_l2()
        self.l1 = []
        self.save()

    def clear(self):
        """Clear L1 only (keep L2 and L3)."""
        self.l1 = []

    def _index_vector_store(self) -> None:
        """Re-index L3 entries in the vector store.

        Called after modifications to L3 (remember, save).
        Safe to call frequently — only new/changed entries are embedded.
        """
        try:
            if self.vector_store.enabled:
                self.vector_store.index_entries(self.l3)
        except Exception as e:
            log.warning(f"Vector store re-indexing failed: {e}")

    def stats(self) -> dict:
        base_stats = {
            "l1_entries": len(self.l1),
            "l1_tokens": self._l1_token_count(),
            "l2_entries": len(self.l2),
            "l3_entries": len(self.l3),
            "l3_total_accesses": sum(e.get("access_count", 0) for e in self.l3),
            "l3_avg_importance": round(sum(e.get("importance", 0.5) for e in self.l3) / max(1, len(self.l3)), 2),
        }
        # Add vector store stats
        try:
            base_stats["vector_store"] = self.vector_store.stats()
        except Exception:
            base_stats["vector_store"] = {"enabled": False, "model_loaded": False}
        return base_stats