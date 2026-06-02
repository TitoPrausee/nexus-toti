"""
NEXUS Error Learning System — Selbstdiagnose & Fehlervermeidung
Erkennt Fehler, speichert Patterns, warnt vor bekannten Fehlern,
und schlägt Lösungen vor — alles lokal (Level 0), kein Model-Call.

Funktionsweise:
  1. Jeder Tool-Call und Agent-Step wird überwacht
  2. Fehler werden klassifiziert (ERROR_CLASS) und mit Kontext gespeichert
  3. Vor jeder Aktion wird die Fehler-Datenbank geprüft
  4. Bekannte Fehler-Patterns werden als WARNUNG injiziert
  5. Erfolgreiche Fixes werden als SOLUTION gespeichert
  6. Periodische Konsolidierung (GEPA-Trigger)

Fehler-Klassen:
  - TOOL_ERROR: Tool-Aufruf fehlgeschlagen
  - AGENT_ERROR: Agent hat Fehler-Status zurückgegeben
  - PARSE_ERROR: JSON/Format-Parsing fehlgeschlagen
  - LOOP_ERROR: Loop erkannt (Guard)
  - TIMEOUT_ERROR: Zeitüberschreitung
  - LLM_ERROR: Model-Call fehlgeschlagen
  - VALIDATION_ERROR: Ergebnis entspricht nicht accept_if
  - PERMISSION_ERROR: Keine Berechtigung
  - DEPENDENCY_ERROR: Abhängigkeit fehlt
"""

import json
import time
import hashlib
import os
from typing import Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum


class ErrorClass(Enum):
    TOOL_ERROR = "TOOL_ERROR"
    AGENT_ERROR = "AGENT_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    LOOP_ERROR = "LOOP_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    LLM_ERROR = "LLM_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class ErrorRecord:
    """Ein einzelner Fehler-Eintrag in der Lern-Datenbank."""
    error_id: str
    error_class: str
    context: str          # Was war die Aufgabe?
    action: str           # Welche Aktion wurde ausgeführt?
    error_message: str    # Die Fehlermeldung
    agent: str            # Welcher Agent?
    tool: str             # Welches Tool? (leer wenn kein Tool)
    timestamp: float
    occurrence_count: int = 1
    solution: str = ""    # Falls eine Lösung gefunden wurde
    solution_verified: bool = False
    avoid_hint: str = ""  # Kurzer Hinweis zur Vermeidung
    fingerprint: str = "" # Hash für Pattern-Erkennung

    def compute_fingerprint(self) -> str:
        """Erstelle einen eindeutigen Fingerprint für dieses Fehler-Pattern."""
        raw = f"{self.error_class}:{self.tool}:{self.action[:100]}:{self.error_message[:100]}"
        self.fingerprint = hashlib.md5(raw.encode()).hexdigest()
        return self.fingerprint


@dataclass
class ErrorWarning:
    """Warnung die vor einer Aktion ausgegeben wird."""
    error_class: str
    hint: str
    confidence: float     # Wie sicher ist das System dass dieser Fehler auftreten wird?
    occurrences: int      # Wie oft ist dieser Fehler aufgetreten?
    solution: str         # Falls bekannt
    last_seen: float


class ErrorLearningSystem:
    """
    Selbstdiagnose- und Fehlervermeidungs-System.
    Läuft komplett lokal (Level 0) — keine Model-Calls.
    """

    STORAGE_DIR = Path(__file__).parent.parent / "data" / "error_learning"

    def __init__(self):
        self._errors: dict[str, ErrorRecord] = {}  # fingerprint -> ErrorRecord
        self._recent_errors: list[ErrorRecord] = []  # Letzte Fehler dieser Session
        self._session_error_count: int = 0
        self._session_avoided_count: int = 0
        self._load()

    def _ensure_dir(self):
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    def _load(self):
        """Fehler-Datenbank von Disk laden."""
        self._ensure_dir()
        db_path = self.STORAGE_DIR / "error_db.json"
        if db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for rec_data in data.get("errors", []):
                    rec = ErrorRecord(**rec_data)
                    if rec.fingerprint:
                        self._errors[rec.fingerprint] = rec
            except Exception:
                pass

    def _save(self):
        """Fehler-Datenbank auf Disk speichern."""
        self._ensure_dir()
        db_path = self.STORAGE_DIR / "error_db.json"
        data = {
            "errors": [asdict(rec) for rec in self._errors.values()],
            "last_updated": time.time(),
            "total_unique_errors": len(self._errors),
        }
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def record_error(
        self,
        error_class: str,
        context: str,
        action: str,
        error_message: str,
        agent: str = "",
        tool: str = "",
    ) -> ErrorRecord:
        """
        Einen Fehler aufzeichnen.
        Wenn das Pattern schon existiert, wird der Zähler erhöht.
        """
        rec = ErrorRecord(
            error_id=f"err_{int(time.time())}_{hashlib.md5(action.encode()).hexdigest()[:6]}",
            error_class=error_class,
            context=context[:500],
            action=action[:300],
            error_message=error_message[:500],
            agent=agent,
            tool=tool,
            timestamp=time.time(),
        )
        rec.compute_fingerprint()

        # Prüfe ob Pattern schon bekannt
        if rec.fingerprint in self._errors:
            existing = self._errors[rec.fingerprint]
            existing.occurrence_count += 1
            existing.timestamp = time.time()
            existing.context = rec.context  # Aktualisiere Kontext
        else:
            self._errors[rec.fingerprint] = rec

        self._recent_errors.append(rec)
        self._session_error_count += 1
        self._save()

        return rec

    def record_solution(self, fingerprint: str, solution: str, verified: bool = True):
        """Lösung für ein bekanntes Fehler-Pattern speichern."""
        if fingerprint in self._errors:
            self._errors[fingerprint].solution = solution[:500]
            self._errors[fingerprint].solution_verified = verified
            self._save()

    def check_before_action(self, action: str, tool: str = "", context: str = "") -> list[ErrorWarning]:
        """
        Vor einer Aktion prüfen ob bekannte Fehler-Patterns zutreffen.
        Gibt eine Liste von Warnungen zurück.
        Läuft lokal — Level 0, kein Model-Call.
        """
        warnings = []

        # Fingerprint für die geplante Aktion berechnen
        action_key_parts = [tool, action[:100]]
        action_key = ":".join(p for p in action_key_parts if p)

        for fp, rec in self._errors.items():
            # Prüfe ob die Aktion ähnlich ist
            similarity = self._compute_similarity(action_key, rec, tool)
            if similarity > 0.3:  # 30% Ähnlichkeitsschwelle
                confidence = min(1.0, similarity * (rec.occurrence_count / max(rec.occurrence_count, 3)))
                warnings.append(ErrorWarning(
                    error_class=rec.error_class,
                    hint=rec.avoid_hint or f"{rec.error_class} bei {rec.tool}: {rec.error_message[:100]}",
                    confidence=confidence,
                    occurrences=rec.occurrence_count,
                    solution=rec.solution,
                    last_seen=rec.timestamp,
                ))

        # Sortiere nach Confidence
        warnings.sort(key=lambda w: w.confidence, reverse=True)

        # Zähler für vermiedene Fehler
        if warnings:
            self._session_avoided_count += 1

        return warnings[:5]  # Max 5 Warnungen

    def _compute_similarity(self, action_key: str, rec: ErrorRecord, tool: str) -> float:
        """
        Berechne Ähnlichkeit zwischen geplanter Aktion und bekanntem Fehler.
        Einfache Heuristik — kein Model-Call.
        """
        score = 0.0

        # Tool-Match (starkes Signal)
        if tool and rec.tool and tool == rec.tool:
            score += 0.5

        # Error-Class-Match bei gleichem Tool
        if tool and rec.tool and tool == rec.tool:
            score += 0.2

        # Action-Text-Ähnlichkeit (einfache Wortüberschneidung)
        action_words = set(action_key.lower().split())
        rec_words = set((rec.action + " " + rec.tool).lower().split())
        if action_words and rec_words:
            overlap = len(action_words & rec_words) / max(len(action_words | rec_words), 1)
            score += overlap * 0.3

        return min(1.0, score)

    def get_warnings_text(self, action: str, tool: str = "", context: str = "") -> str:
        """Formatiere Warnungen als Text für Injection in Agent-Prompt."""
        warnings = self.check_before_action(action, tool, context)
        if not warnings:
            return ""

        parts = ["[ERROR_LEARNING WARNUNGEN]"]
        for w in warnings:
            icon = "!!!" if w.confidence > 0.7 else "!!" if w.confidence > 0.5 else "!"
            parts.append(
                f"  {icon} {w.error_class} (x{w.occurrences}, Confidence: {w.confidence:.0%}): {w.hint}"
            )
            if w.solution:
                parts.append(f"     Lösung: {w.solution}")
        return "\n".join(parts)

    def auto_record_from_result(self, result: dict, action: str = "", agent: str = "", tool: str = ""):
        """
        Automatisch Fehler aus einem Tool/Agent-Result extrahieren und aufzeichnen.
        Wird nach jedem Tool-Call und Agent-Step aufgerufen.
        """
        # Tool-Fehler
        if isinstance(result, dict) and "error" in result:
            error_msg = result["error"]
            self.record_error(
                error_class=ErrorClass.TOOL_ERROR.value,
                context=action[:500],
                action=action[:300],
                error_message=error_msg,
                agent=agent,
                tool=tool,
            )

        # Agent-Fehler
        elif isinstance(result, dict) and result.get("status") == "error":
            self.record_error(
                error_class=ErrorClass.AGENT_ERROR.value,
                context=result.get("message", ""),
                action=action[:300],
                error_message=result.get("message", "Unknown agent error"),
                agent=agent,
                tool=tool,
            )

        # Loop-Detection
        elif isinstance(result, dict) and "LOOP_DETECTED" in result.get("flags", []):
            self.record_error(
                error_class=ErrorClass.LOOP_ERROR.value,
                context=action[:500],
                action=action[:300],
                error_message="Loop detected — wiederholte Aktion ohne Fortschritt",
                agent=agent,
                tool=tool,
            )

        # Timeout
        elif isinstance(result, dict) and "timed out" in str(result.get("error", "")).lower():
            self.record_error(
                error_class=ErrorClass.TIMEOUT_ERROR.value,
                context=action[:500],
                action=action[:300],
                error_message=result.get("error", "Timeout"),
                agent=agent,
                tool=tool,
            )

    def get_error_stats(self) -> dict:
        """Statistiken über die Fehler-Datenbank."""
        by_class = {}
        for rec in self._errors.values():
            by_class[rec.error_class] = by_class.get(rec.error_class, 0) + rec.occurrence_count

        return {
            "total_unique_errors": len(self._errors),
            "total_occurrences": sum(r.occurrence_count for r in self._errors.values()),
            "session_errors": self._session_error_count,
            "session_avoided": self._session_avoided_count,
            "by_class": by_class,
            "solved_errors": sum(1 for r in self._errors.values() if r.solution_verified),
            "top_errors": sorted(
                [(r.error_class, r.tool, r.occurrence_count, r.avoid_hint)
                 for r in self._errors.values()],
                key=lambda x: x[2], reverse=True
            )[:5],
        }

    def generate_avoid_hints(self) -> list[str]:
        """
        Generiere Vermeidungshinweise aus den häufigsten Fehlern.
        Wird vom GEPA-Protokoll aufgerufen.
        """
        hints = []
        sorted_errors = sorted(
            self._errors.values(),
            key=lambda r: r.occurrence_count,
            reverse=True
        )

        for rec in sorted_errors[:10]:
            if rec.occurrence_count >= 2:
                hint = f"VERMEIDE: {rec.error_class} bei {rec.tool or rec.agent} — {rec.error_message[:80]}"
                if rec.solution:
                    hint += f" | FIX: {rec.solution[:80]}"
                hints.append(hint)
                # Speichere den Hint
                if not rec.avoid_hint:
                    rec.avoid_hint = hint
                    self._save()

        return hints

    def consolidate(self):
        """
        Konsolidierung: Alte Fehler entfernen, Hints generieren.
        Wird periodisch (THRESHOLD_TRIGGER) aufgerufen.
        """
        now = time.time()
        cutoff = now - (7 * 24 * 3600)  # 7 Tage

        # Entferne sehr alte, nicht wiederholte Fehler
        to_remove = []
        for fp, rec in self._errors.items():
            if rec.timestamp < cutoff and rec.occurrence_count == 1 and not rec.solution_verified:
                to_remove.append(fp)

        for fp in to_remove:
            del self._errors[fp]

        # Generiere Hints
        self.generate_avoid_hints()
        self._save()

    def get_recent_errors(self, limit: int = 5) -> list[dict]:
        """Letzte Fehler dieser Session."""
        return [
            {
                "error_class": r.error_class,
                "tool": r.tool,
                "agent": r.agent,
                "message": r.error_message[:200],
                "time": r.timestamp,
            }
            for r in self._recent_errors[-limit:]
        ]

    def build_error_context(self, task: str) -> str:
        """
        Baue Kontext für den Agent-Prompt mit Fehler-Warnungen.
        Wird vor jedem Agent-Call injiziert.
        """
        parts = []

        # Allgemeine Fehler-Statistiken
        stats = self.get_error_stats()
        if stats["total_unique_errors"] > 0:
            parts.append(f"[ERROR_LEARNING: {stats['total_unique_errors']} bekannte Fehler-Patterns, "
                         f"{stats['solved_errors']} gelöst, {stats['session_avoided']} vermieden diese Session]")

        # Spezifische Warnungen für die aktuelle Aufgabe
        warnings = self.get_warnings_text(task)
        if warnings:
            parts.append(warnings)

        # Letzte Fehler
        recent = self.get_recent_errors(3)
        if recent:
            parts.append("[LETZTE FEHLER]")
            for err in recent:
                parts.append(f"  - {err['error_class']} ({err['tool'] or err['agent']}): {err['message']}")

        return "\n".join(parts)
