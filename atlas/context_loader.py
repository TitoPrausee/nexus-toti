#!/usr/bin/env python3
"""
Atlas Context Loader — Relevanz-basiertes Laden statt Kompression.
Statt Context-Window zu komprimieren, wird nur das geladen,
was für die aktuelle Frage relevant ist.

L0: Hot Memory (immer im Context)
L2: Session Memory (relevante Sessions)
L3: Long-term Memory (relevante Fakten)
L1: Working Memory (aktuelle Konversation, nie komprimiert)
"""
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from git_memory import GitMemory
from hot_memory import HotMemory
from session_manager import SessionManager


class ContextLoader:
    """Lädt relevanten Kontext aus allen Memory-Layern."""

    def __init__(self):
        self.mem = GitMemory()
        self.hot = HotMemory()
        self.sessions = SessionManager(self.mem)
        self.max_context_tokens = 6000  # Max Tokens für Context

    def load_for_query(self, query: str) -> str:
        """Lädt relevanten Kontext für eine Query — keine Kompression!"""
        blocks = []

        # L0: Hot Memory (immer)
        hot_block = self.hot.get_context_block()
        blocks.append(hot_block)

        # L2: Relevante Sessions
        session_block = self.sessions.get_context_block(query)
        if session_block:
            blocks.append(session_block)

        # L3: Relevante Long-term Fakten
        facts_block = self._load_relevant_facts(query)
        if facts_block:
            blocks.append(facts_block)

        # L3: Relevante Learnings
        learnings_block = self._load_relevant_learnings(query)
        if learnings_block:
            blocks.append(learnings_block)

        # L3: Relevante Decisions
        decisions_block = self._load_relevant_decisions(query)
        if decisions_block:
            blocks.append(decisions_block)

        # Zusammenbauen
        context = "\n".join(blocks)

        # Prüfen ob Context zu groß ist
        estimated_tokens = len(context) // 4
        if estimated_tokens > self.max_context_tokens:
            # Nicht komprimieren! Nur weniger relevante Blöcke weglassen
            context = self._trim_to_budget(context, blocks)

        return context

    def _load_relevant_facts(self, query: str) -> str:
        """Lädt relevante Fakten aus L3."""
        keywords = self._extract_keywords(query)
        if not keywords:
            return ""

        found = set()
        for kw in keywords:
            results = self.mem.search(kw, "projects/*.md")
            for r in results:
                found.add(r["file"])

        if not found:
            return ""

        lines = ["[LONG-TERM MEMORY — relevante Projekte]"]
        for f in sorted(found)[:3]:  # Max 3 Dateien
            content = self.mem.load(f)
            if content:
                # Nur ersten 10 Zeilen
                snippet_lines = content.strip().split("\n")[:10]
                lines.append(f"  📄 {f}:")
                for sl in snippet_lines:
                    if sl.strip() and not sl.startswith("---"):
                        lines.append(f"    {sl[:150]}")
                lines.append("")
        return "\n".join(lines)

    def _load_relevant_learnings(self, query: str) -> str:
        """Lädt relevante Learnings aus L3."""
        keywords = self._extract_keywords(query)
        if not keywords:
            return ""

        found = set()
        for kw in keywords:
            results = self.mem.search(kw, "learnings/*.md")
            for r in results:
                found.add(r["file"])

        if not found:
            return ""

        lines = ["[LEARNINGS — relevante Fehler/Lösungen]"]
        for f in sorted(found)[:2]:
            content = self.mem.load(f)
            if content:
                snippet_lines = content.strip().split("\n")[:8]
                lines.append(f"  📖 {f}:")
                for sl in snippet_lines:
                    if sl.strip() and not sl.startswith("---"):
                        lines.append(f"    {sl[:150]}")
                lines.append("")
        return "\n".join(lines)

    def _load_relevant_decisions(self, query: str) -> str:
        """Lädt relevante Decisions aus L3."""
        keywords = self._extract_keywords(query)
        if not keywords:
            return ""

        found = set()
        for kw in keywords:
            results = self.mem.search(kw, "decisions/*.md")
            for r in results:
                found.add(r["file"])

        if not found:
            return ""

        lines = ["[DECISIONS — relevante Architekturentscheidungen]"]
        for f in sorted(found)[:2]:
            content = self.mem.load(f)
            if content:
                snippet_lines = content.strip().split("\n")[:8]
                lines.append(f"  📐 {f}:")
                for sl in snippet_lines:
                    if sl.strip() and not sl.startswith("---"):
                        lines.append(f"    {sl[:150]}")
                lines.append("")
        return "\n".join(lines)

    def _extract_keywords(self, query: str) -> list[str]:
        """Extrahiert relevante Keywords aus einer Query."""
        # Stoppwörter
        stopwords = {
            "der", "die", "das", "den", "dem", "des", "ein", "eine",
            "einen", "einem", "eines", "ist", "war", "wird", "wurde",
            "hat", "habe", "hast", "haben", "mit", "von", "für", "auf",
            "bei", "nach", "aus", "zu", "zur", "zum", "in", "im", "am",
            "wie", "was", "wer", "wem", "wen", "und", "oder", "aber",
            "nicht", "kein", "keine", "the", "a", "an", "is", "are",
            "was", "were", "been", "have", "has", "had", "do", "does",
            "did", "will", "would", "can", "could", "shall", "should",
            "may", "might", "must", "i", "you", "he", "she", "it",
            "we", "they", "me", "him", "her", "us", "them",
        }
        words = re.findall(r'\b[a-zA-ZäöüßÄÖÜ][a-zA-ZäöüßÄÖÜ-]{2,}\b', query.lower())
        return [w for w in words if w not in stopwords][:8]

    def _trim_to_budget(self, full_context: str, blocks: list[str]) -> str:
        """Kürzt Context durch Weglassen weniger relevanter Blöcke (KEINE Kompression)."""
        # Reihenfolge: Hot Memory zuerst behalten, dann Sessions, dann Facts
        # Hot Memory ist immer essentiell
        hot = blocks[0] if blocks else ""

        # Budget: 80% für Hot + Sessions, 20% für Facts
        hot_tokens = len(hot) // 4
        remaining = self.max_context_tokens - hot_tokens

        result = [hot]
        for block in blocks[1:]:
            block_tokens = len(block) // 4
            if block_tokens <= remaining:
                result.append(block)
                remaining -= block_tokens
            else:
                # Block weglassen statt komprimieren!
                pass

        return "\n".join(result)

    def load_memory_index(self) -> str:
        """Lädt den MEMORY.md Index (immer verfügbar)."""
        content = self.mem.load("MEMORY.md")
        return content or "# Memory Index (leer)"


# Regex für Keyword-Extraktion
import re
