"""
NEXUS v7 — Memory System
L1: Working (current conversation)
L2: Session (recent, summarized)
L3: Long-term (important facts)
L4: Soul (identity, persistent)
"""

import json
import time
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


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

    def get_context(self, max_tokens: int = None) -> list[dict]:
        """Get conversation context for LLM call."""
        budget = max_tokens or self.l1_max_tokens

        # Start from most recent, work backwards
        context = []
        total = 0

        # System prompt goes first (handled by agent)
        # Then L3 facts
        for fact in self.l3[-10:]:  # Last 10 important facts
            text = fact.get("content", "")
            tokens = max(1, len(text.split()))
            if total + tokens < budget * 0.2:  # Reserve 20% for facts
                context.append({"role": "system", "content": f"[Erinnerung] {text}"})
                total += tokens

        # Then L2 summaries (last 3)
        for session in self.l2[-3:]:
            summary = session.get("summary", "")
            if summary:
                tokens = max(1, len(summary.split()))
                if total + tokens < budget * 0.3:
                    context.append({"role": "system", "content": f"[Kontext] {summary}"})
                    total += tokens

        # Then L1 conversation (most recent first, fill remaining budget)
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
        """Compress L1 by keeping recent + important entries."""
        if len(self.l1) < 4:
            return

        # Keep first (system prompt) and last 60%
        keep_count = max(2, int(len(self.l1) * 0.6))
        mid = self.l1[1:-keep_count]
        kept = [self.l1[0]] + self.l1[-keep_count:]

        # Summarize removed entries into L2
        summary_text = " | ".join(f"{e.role}: {e.content[:100]}" for e in mid[:5])
        if summary_text:
            self.l2.append({
                "timestamp": time.time(),
                "summary": summary_text[:500],
                "entries_removed": len(mid),
            })
            # Trim L2
            self._trim_l2()

        self.l1 = kept

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
        """Store an important fact in long-term memory."""
        self.l3.append({
            "content": content,
            "category": category,
            "importance": importance,
            "timestamp": time.time(),
        })

        # Keep within bounds
        if len(self.l3) > self.l3_max_entries:
            # Remove lowest importance
            self.l3.sort(key=lambda x: x.get("importance", 0), reverse=True)
            self.l3 = self.l3[:self.l3_max_entries]

        self.save()

    def recall(self, query: str, limit: int = 5) -> list[str]:
        """Simple keyword recall from long-term memory."""
        query_lower = query.lower()
        words = query_lower.split()

        results = []
        for entry in self.l3:
            content_lower = entry.get("content", "").lower()
            score = sum(1 for w in words if w in content_lower)
            if score > 0:
                results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1].get("content", "") for r in results[:limit]]

    # ─── Session Management ────────────────────────────

    def end_session(self):
        """Called when conversation ends. Archive to L2."""
        if not self.l1:
            return

        # Create summary of current session
        messages = [f"{e.role}: {e.content[:200]}" for e in self.l1[-10:]]
        summary = " | ".join(messages)

        self.l2.append({
            "timestamp": time.time(),
            "summary": summary[:1000],
            "entries_removed": len(self.l1),
        })

        self._trim_l2()
        self.l1 = []
        self.save()

    def clear(self):
        """Clear L1 only (keep L2 and L3)."""
        self.l1 = []

    def stats(self) -> dict:
        return {
            "l1_entries": len(self.l1),
            "l1_tokens": self._l1_token_count(),
            "l2_entries": len(self.l2),
            "l3_entries": len(self.l3),
        }