"""
NEXUS v9.3 — L0 Hot Memory

Always-in-context memory layer (~800 tokens). Auto-promoted from L3
long-term memory based on importance and access frequency.

YAML format for human readability and easy manual editing.
"""

import json
import time
import logging
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("nexus.hot_memory")


class HotMemory:
    """L0 Hot Memory — critical facts always injected into the system prompt.

    Reads and writes data/memory/hot.yaml. Provides:
    - load/save: YAML persistence with atomic writes
    - get_prompt_text(): Formatted text for system prompt injection (~800 tokens)
    - sync_from_l3(): Auto-promote facts from L3 based on importance/access_count
    - demote_stale(): Remove facts that no longer meet promotion criteria
    - enforce_budget(): Trim lowest-importance facts to stay under token budget
    """

    def __init__(self, data_dir: str = "data/memory", config: dict = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.data_dir / "hot.yaml"

        cfg = config or {}

        # Token budgets
        self.max_tokens = cfg.get("hot_max_tokens", 1000)
        self.soft_token_limit = int(self.max_tokens * 0.8)  # 800
        self.max_facts = cfg.get("hot_max_facts", 10)

        # Promotion thresholds
        self.promotion_importance = cfg.get("hot_promotion_importance", 0.8)
        self.promotion_access_count = cfg.get("hot_promotion_access_count", 3)

        # Demotion thresholds
        self.demotion_age_days = cfg.get("hot_demotion_age_days", 30)
        self.demotion_stale_days = cfg.get("hot_demotion_stale_days", 7)

        # Internal state
        self.user = {}
        self.projects = []
        self.infrastructure = []
        self.critical_facts = []
        self.recent_sessions = []
        self.metadata = {
            "version": 1,
            "last_promotion_check": 0,
            "total_tokens_estimate": 0,
        }

        self._load()

    # ─── Load / Save ──────────────────────────────────────

    def _load(self):
        """Load hot memory from disk. Initialize defaults if not found."""
        if not self.file_path.exists():
            log.info("No hot.yaml found, initializing empty hot memory")
            self.save()
            return

        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            log.warning(f"Failed to load hot.yaml: {e}, reinitializing")
            self.save()
            return

        self.user = data.get("user", {})
        self.projects = data.get("projects", [])
        self.infrastructure = data.get("infrastructure", [])
        self.critical_facts = data.get("critical_facts", [])
        self.recent_sessions = data.get("recent_sessions", [])
        self.metadata = data.get("metadata", {
            "version": 1,
            "last_promotion_check": 0,
            "total_tokens_estimate": 0,
        })

        # Validate structure
        if not isinstance(self.critical_facts, list):
            self.critical_facts = []
        if not isinstance(self.projects, list):
            self.projects = []

        tokens = self.estimate_tokens()
        if tokens > self.max_tokens:
            log.warning(f"Hot memory over budget: {tokens} > {self.max_tokens} tokens, trimming")
            self._enforce_budget()

    def save(self):
        """Persist hot memory to disk with atomic write."""
        self.metadata["total_tokens_estimate"] = self.estimate_tokens()
        self.metadata["last_promotion_check"] = time.time()

        data = {
            "user": self.user,
            "projects": self.projects,
            "infrastructure": self.infrastructure,
            "critical_facts": self.critical_facts,
            "recent_sessions": self.recent_sessions,
            "metadata": self.metadata,
        }

        # Atomic write: write to temp file, then rename
        tmp_path = self.file_path.with_suffix(".yaml.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            tmp_path.rename(self.file_path)
        except Exception as e:
            log.error(f"Failed to save hot.yaml: {e}")
            # Clean up temp file
            if tmp_path.exists():
                tmp_path.unlink()

    # ─── Prompt Generation ─────────────────────────────────

    def get_prompt_text(self, user_id: str = None) -> str:
        """Generate compact text for system prompt injection.

        Target: ~800 tokens (soft limit), never exceed 1000 (hard limit).
        Format: Compact key-value pairs, no fluff.
        """
        lines = ["[Hot Memory — immer aktiv]"]

        # User info
        if self.user:
            name = self.user.get("name", "")
            lang = self.user.get("language", "de")
            prefs = self.user.get("preferences", [])
            if name or lang:
                lines.append(f"Nutzer: {name} ({lang})")
            if prefs:
                lines.append(f"Prefs: {'; '.join(prefs[:5])}")

        # Projects
        if self.projects:
            proj_strs = [f"{p['name']}({p.get('status', '?')})" for p in self.projects[:5]]
            lines.append(f"Projekte: {', '.join(proj_strs)}")

        # Infrastructure
        if self.infrastructure:
            lines.append(f"Infra: {'; '.join(self.infrastructure[:5])}")

        # Critical facts
        if self.critical_facts:
            fact_strs = []
            for fact in self.critical_facts[:self.max_facts]:
                content = fact.get("content", "")
                if content:
                    # Truncate long facts
                    fact_strs.append(content[:120])
            if fact_strs:
                lines.append(f"Wichtig: {'; '.join(fact_strs)}")

        # Recent sessions
        if self.recent_sessions:
            sess_strs = []
            for sess in self.recent_sessions[-3:]:
                topics = sess.get("topics", [])
                date = sess.get("date", "")
                if topics:
                    sess_strs.append(f"{date}: {', '.join(topics[:3])}")
            if sess_strs:
                lines.append(f"Letzte Themen: {' | '.join(sess_strs)}")

        text = "\n".join(lines)

        # Hard enforcement: if over budget, truncate facts
        if self.estimate_tokens_text(text) > self.max_tokens:
            # Remove facts one by one from the end until under budget
            while self.estimate_tokens_text(text) > self.max_tokens and self.critical_facts:
                self.critical_facts.pop()
                text = self.get_prompt_text(user_id)
                if not self.critical_facts:
                    break

        return text

    # ─── Promotion / Demotion ──────────────────────────────

    def sync_from_l3(self, l3_entries: list):
        """Promote facts from L3 that meet criteria, demote stale ones.

        Called after remember() and recall() operations.
        """
        promoted = 0
        demoted = 0

        # Track existing source IDs for dedup
        existing_ids = {f.get("source_id") for f in self.critical_facts if f.get("source_id")}

        # Promote qualifying L3 entries
        for i, entry in enumerate(l3_entries):
            importance = entry.get("importance", 0.5)
            access_count = entry.get("access_count", 0)
            content = entry.get("content", "").strip()

            if not content:
                continue

            source_id = f"l3_{i}_{self._content_hash(content)}"

            # Check promotion criteria
            should_promote = (
                importance >= self.promotion_importance
                or access_count >= self.promotion_access_count
            )

            if should_promote and source_id not in existing_ids:
                self.critical_facts.append({
                    "content": content[:200],  # Truncate for budget
                    "source_id": source_id,
                    "importance": importance,
                    "promoted_at": time.time(),
                })
                existing_ids.add(source_id)
                promoted += 1

        # Demote stale facts
        demoted = self._demote_stale(l3_entries)

        # Enforce token budget
        self._enforce_budget()

        # Update recent sessions from L2 data (caller should set this)
        self.metadata["last_promotion_check"] = time.time()

        if promoted > 0 or demoted > 0:
            log.info(f"Hot memory sync: +{promoted} promoted, -{demoted} demoted, {len(self.critical_facts)} total facts")
            self.save()

    def _demote_stale(self, l3_entries: list) -> int:
        """Remove facts that no longer meet promotion criteria.

        Criteria for demotion:
        - L3 entry no longer exists (source_id missing)
        - importance dropped below threshold AND access_count below threshold
        - Promoted > 30 days ago AND not accessed in 7 days
        """
        now = time.time()
        demoted = 0

        # Build a lookup of current L3 content hashes
        l3_hashes = set()
        for i, entry in enumerate(l3_entries):
            content = entry.get("content", "").strip()
            if content:
                l3_hashes.add(f"l3_{i}_{self._content_hash(content)}")

        to_remove = []
        for fact in self.critical_facts:
            source_id = fact.get("source_id", "")

            # Demote if L3 entry no longer exists
            if source_id and source_id not in l3_hashes:
                to_remove.append(fact)
                continue

            # Demote if promoted long ago and stale
            promoted_at = fact.get("promoted_at", 0)
            age_days = (now - promoted_at) / 86400 if promoted_at else 0

            importance = fact.get("importance", 0.5)

            # Find corresponding L3 entry for access_count
            access_count = 0
            for i, entry in enumerate(l3_entries):
                content = entry.get("content", "").strip()
                if content and f"l3_{i}_{self._content_hash(content)}" == source_id:
                    access_count = entry.get("access_count", 0)
                    break

            # Demote if: old promotion + stale + not highly important
            if (age_days > self.demotion_age_days
                    and access_count < self.promotion_access_count
                    and importance < self.promotion_importance):
                to_remove.append(fact)

        for fact in to_remove:
            self.critical_facts.remove(fact)
            demoted += 1

        return demoted

    def _enforce_budget(self):
        """Remove lowest-importance facts until under token budget."""
        # Sort by importance ascending (lowest first)
        self.critical_facts.sort(key=lambda f: f.get("importance", 0.5))

        while self.estimate_tokens() > self.max_tokens and self.critical_facts:
            self.critical_facts.pop(0)  # Remove lowest importance

        # Also enforce max_facts
        while len(self.critical_facts) > self.max_facts:
            self.critical_facts.pop(0)

        # Re-sort by importance descending (highest first) for readability
        self.critical_facts.sort(key=lambda f: f.get("importance", 0.5), reverse=True)

    # ─── Manual Fact Management ────────────────────────────

    def add_fact(self, content: str, importance: float = 0.7, source_id: str = ""):
        """Manually add a fact to hot memory."""
        # Dedup by content similarity
        topic_key = self._content_hash(content)
        for existing in self.critical_facts:
            if self._content_hash(existing.get("content", "")) == topic_key:
                # Update existing
                existing["importance"] = max(existing.get("importance", 0.5), importance)
                existing["last_accessed"] = time.time()
                self.save()
                return

        self.critical_facts.append({
            "content": content[:200],
            "source_id": source_id or f"manual_{topic_key[:8]}",
            "importance": importance,
            "promoted_at": time.time(),
        })

        self._enforce_budget()
        self.save()

    def remove_fact(self, source_id: str) -> bool:
        """Remove a specific fact by source_id."""
        for i, fact in enumerate(self.critical_facts):
            if fact.get("source_id") == source_id:
                self.critical_facts.pop(i)
                self.save()
                return True
        return False

    # ─── Update Methods ────────────────────────────────────

    def update_user(self, name: str = None, language: str = None, preferences: list = None):
        """Update user section from soul relationship data."""
        if name:
            self.user["name"] = name
        if language:
            self.user["language"] = language
        if preferences is not None:
            self.user["preferences"] = preferences[:10]  # Cap at 10
        self.save()

    def update_projects(self, projects: list):
        """Update projects section."""
        self.projects = projects[:10]  # Cap at 10
        self.save()

    def update_infrastructure(self, infra_facts: list):
        """Update infrastructure section."""
        self.infrastructure = infra_facts[:10]  # Cap at 10
        self.save()

    def update_recent_sessions(self, sessions: list):
        """Update recent sessions from L2 summaries."""
        self.recent_sessions = sessions[-3:]  # Keep last 3
        self.save()

    # ─── Token Estimation ──────────────────────────────────

    def estimate_tokens(self) -> int:
        """Estimate token count of current hot memory state."""
        text = self.get_prompt_text()
        return self.estimate_tokens_text(text)

    def estimate_tokens_text(self, text: str) -> int:
        """Rough token estimate: words * 1.3 (German compound words)."""
        return max(1, int(len(text.split()) * 1.3))

    # ─── Stats ─────────────────────────────────────────────

    def stats(self) -> dict:
        """Return hot memory statistics."""
        return {
            "enabled": True,
            "facts": len(self.critical_facts),
            "max_facts": self.max_facts,
            "tokens_estimate": self.estimate_tokens(),
            "max_tokens": self.max_tokens,
            "projects": len(self.projects),
            "infra_facts": len(self.infrastructure),
        }

    # ─── Helpers ───────────────────────────────────────────

    @staticmethod
    def _content_hash(content: str) -> str:
        """Simple content hash for dedup (not cryptographic)."""
        # Use first 3 meaningful words as hash
        import re
        words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', content.lower())
        return "_".join(sorted(words[:3])) if words else str(hash(content))[:8]