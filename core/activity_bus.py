"""
NEXUS Activity Bus — Echtzeit-Event-System für Telegram & CLI
==============================================================
Erlaubt Modulen (Tools, Memory, State, Scheduler) Events zu emittieren,
die dann von der Telegram-Bot-UI in Echtzeit angezeigt werden.

Event-Typen:
  - tool_call      → Tool wird aufgerufen
  - tool_result    → Tool-Ergebnis
  - save           → Daten gespeichert
  - cron_start     → Cronjob gestartet
  - cron_done      → Cronjob erledigt
  - self_optimize  → Selbstoptimierung
  - soul_edit      → Soul/Prompt geändert
  - memory_edit    → Memory bearbeitet
  - file_edit      → Datei bearbeitet
  - config_edit    → Config geändert
  - iq_change      → IQ geändert
  - error_learned  → Fehler gelernt
  - error_avoided  → Fehler vermieden
  - llm_call       → LLM wird angefragt
  - llm_response   → LLM-Antwort
  - delegate       → Task delegiert
  - skill_exec     → Skill ausgeführt
  - guard_block    → Guard blockiert
  - loop_detect    → Loop erkannt
  - budget_warn    → Budget-Warnung
  - web_access     → Internet-Zugriff
  - vision_analyze → Bild-Analyse
"""

import time
import json
import asyncio
import logging
from typing import Callable, Optional, Any
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class ActivityEvent:
    """Ein Aktivitäts-Event im NEXUS System."""
    event_type: str          # tool_call, save, cron_start, etc.
    source: str              # Modul/Agent das das Event auslöst
    message: str             # Mensch-lesbare Nachricht
    detail: str = ""         # Zusätzliche Details
    data: dict = field(default_factory=dict)  # Strukturierte Daten
    timestamp: float = field(default_factory=time.time)
    importance: str = "info" # "info", "action", "warning", "success", "error"
    
    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "source": self.source,
            "message": self.message,
            "detail": self.detail,
            "data": self.data,
            "timestamp": self.timestamp,
            "importance": self.importance,
        }


class ActivityBus:
    """
    Zentraler Event-Bus für Echtzeit-Aktivitätsmeldungen.
    
    Module emittieren Events → UI (Telegram/CLI) zeigt sie an.
    
    Usage:
        bus = ActivityBus()
        bus.subscribe(callback)
        bus.emit(ActivityEvent(event_type="tool_call", source="FORGE", message="Führe Terminal aus"))
    """

    def __init__(self, max_history: int = 100):
        self._subscribers: list[Callable] = []
        self._history: deque[ActivityEvent] = deque(maxlen=max_history)
        self._async_subscribers: list[Callable] = []
        self._counters: dict[str, int] = {}

    def subscribe(self, callback: Callable):
        """Registriere Callback für Events (sync)."""
        self._subscribers.append(callback)

    def subscribe_async(self, callback: Callable):
        """Registriere async Callback für Events."""
        self._async_subscribers.append(callback)

    def unsubscribe(self, callback: Callable):
        """Callback entfernen."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
        if callback in self._async_subscribers:
            self._async_subscribers.remove(callback)

    def emit(self, event: ActivityEvent):
        """Event emittieren an alle Subscriber."""
        self._history.append(event)
        self._counters[event.event_type] = self._counters.get(event.event_type, 0) + 1

        # Sync Subscriber
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Activity subscriber error: {e}")

    async def emit_async(self, event: ActivityEvent):
        """Event async emittieren."""
        self._history.append(event)
        self._counters[event.event_type] = self._counters.get(event.event_type, 0) + 1

        # Async Subscriber
        for cb in self._async_subscribers:
            try:
                await cb(event)
            except Exception as e:
                logger.error(f"Async activity subscriber error: {e}")

        # Auch sync Subscriber
        for cb in self._subscribers:
            try:
                cb(event)
            except Exception as e:
                logger.error(f"Activity subscriber error: {e}")

    # ─── CONVENIENCE METHODS ──────────────────────────────

    def tool_call(self, tool_name: str, params: str = "", source: str = "TOTI"):
        """Tool-Aufruf Event."""
        self.emit(ActivityEvent(
            event_type="tool_call",
            source=source,
            message=f"🔧 Tool: {tool_name}",
            detail=params[:100],
            data={"tool": tool_name, "params": params[:200]},
            importance="action",
        ))

    def tool_result(self, tool_name: str, result: str, source: str = "TOTI", success: bool = True):
        """Tool-Ergebnis Event."""
        emoji = "✅" if success else "❌"
        imp = "success" if success else "error"
        self.emit(ActivityEvent(
            event_type="tool_result",
            source=source,
            message=f"{emoji} {tool_name}: {result[:60]}",
            detail=result[:200],
            data={"tool": tool_name, "success": success, "result_preview": result[:500]},
            importance=imp,
        ))

    def save(self, what: str, where: str = "", source: str = "TOTI"):
        """Speichern Event."""
        self.emit(ActivityEvent(
            event_type="save",
            source=source,
            message=f"💾 Gespeichert: {what}",
            detail=where,
            data={"what": what, "where": where},
            importance="action",
        ))

    def cron_start(self, task_name: str, schedule: str = ""):
        """Cronjob gestartet."""
        self.emit(ActivityEvent(
            event_type="cron_start",
            source="SCHEDULER",
            message=f"⏰ Cronjob gestartet: {task_name}",
            detail=schedule,
            data={"task": task_name, "schedule": schedule},
            importance="action",
        ))

    def cron_done(self, task_name: str, result: str = ""):
        """Cronjob erledigt."""
        self.emit(ActivityEvent(
            event_type="cron_done",
            source="SCHEDULER",
            message=f"✅ Cronjob erledigt: {task_name}",
            detail=result[:100],
            data={"task": task_name, "result": result[:200]},
            importance="success",
        ))

    def self_optimize(self, what: str, detail: str = ""):
        """Selbstoptimierung Event."""
        self.emit(ActivityEvent(
            event_type="self_optimize",
            source="GEPA",
            message=f"🧬 Optimiere: {what}",
            detail=detail,
            data={"what": what, "detail": detail},
            importance="action",
        ))

    def soul_edit(self, agent_id: str, change: str):
        """Soul/Prompt geändert."""
        self.emit(ActivityEvent(
            event_type="soul_edit",
            source="GEPA",
            message=f"🧠 Soul geändert: {agent_id}",
            detail=change[:100],
            data={"agent": agent_id, "change": change[:200]},
            importance="warning",
        ))

    def memory_edit(self, action: str, key: str = ""):
        """Memory bearbeitet."""
        self.emit(ActivityEvent(
            event_type="memory_edit",
            source="MEMORY",
            message=f"🗄️ Memory: {action}",
            detail=key,
            data={"action": action, "key": key},
            importance="action",
        ))

    def file_edit(self, path: str, action: str = "edit"):
        """Datei bearbeitet."""
        self.emit(ActivityEvent(
            event_type="file_edit",
            source="TOTI",
            message=f"📄 Datei {action}: {os.path.basename(path)}",
            detail=path,
            data={"path": path, "action": action},
            importance="action",
        ))

    def config_edit(self, key: str, value: str = ""):
        """Config geändert."""
        self.emit(ActivityEvent(
            event_type="config_edit",
            source="CONFIG",
            message=f"⚙️ Config: {key}",
            detail=value[:100],
            data={"key": key, "value": value[:200]},
            importance="warning",
        ))

    def iq_change(self, delta: float, reason: str, new_iq: float):
        """IQ-Änderung."""
        arrow = "⬆️" if delta > 0 else "⬇️"
        imp = "success" if delta > 0 else "error"
        self.emit(ActivityEvent(
            event_type="iq_change",
            source="IQ",
            message=f"🧠 IQ {arrow} {delta:+.1f} ({reason})",
            detail=f"Neuer IQ: {new_iq:.1f}",
            data={"delta": delta, "reason": reason, "new_iq": new_iq},
            importance=imp,
        ))

    def error_learned(self, error_class: str, message: str):
        """Fehler gelernt."""
        self.emit(ActivityEvent(
            event_type="error_learned",
            source="ERROR_LEARNING",
            message=f"⚠️ Fehler gelernt: {error_class}",
            detail=message[:100],
            data={"error_class": error_class, "message": message[:200]},
            importance="warning",
        ))

    def error_avoided(self, error_class: str):
        """Fehler vermieden."""
        self.emit(ActivityEvent(
            event_type="error_avoided",
            source="ERROR_LEARNING",
            message=f"🎉 Fehler vermieden: {error_class}",
            data={"error_class": error_class},
            importance="success",
        ))

    def llm_call(self, agent_id: str, model: str):
        """LLM-Anfrage."""
        self.emit(ActivityEvent(
            event_type="llm_call",
            source=agent_id,
            message=f"🤖 Frage {model} an...",
            data={"agent": agent_id, "model": model},
            importance="info",
        ))

    def llm_response(self, agent_id: str, model: str, elapsed: float, tokens: int = 0):
        """LLM-Antwort."""
        self.emit(ActivityEvent(
            event_type="llm_response",
            source=agent_id,
            message=f"💬 {model} antwortete ({elapsed:.1f}s)",
            data={"agent": agent_id, "model": model, "elapsed": elapsed, "tokens": tokens},
            importance="info",
        ))

    def delegate(self, agent_id: str, task: str):
        """Task delegiert."""
        self.emit(ActivityEvent(
            event_type="delegate",
            source="NEXUS-0",
            message=f"📤 Delegiere an {agent_id}",
            detail=task[:80],
            data={"agent": agent_id, "task": task[:200]},
            importance="action",
        ))

    def web_access(self, url: str, method: str = "GET"):
        """Internet-Zugriff."""
        self.emit(ActivityEvent(
            event_type="web_access",
            source="WEB",
            message=f"🌐 {method} {url[:60]}",
            data={"url": url, "method": method},
            importance="action",
        ))

    def vision_analyze(self, source: str, result: str = ""):
        """Bild-Analyse."""
        self.emit(ActivityEvent(
            event_type="vision_analyze",
            source="VISION",
            message=f"👁️ Bild-Analyse: {source[:40]}",
            detail=result[:100],
            data={"source": source, "result": result[:200]},
            importance="action",
        ))

    # ─── HISTORY & STATS ──────────────────────────────────

    def get_history(self, limit: int = 20, event_type: Optional[str] = None) -> list[ActivityEvent]:
        """Event-History abrufen."""
        events = list(self._history)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    def get_stats(self) -> dict:
        """Statistiken."""
        return {
            "total_events": len(self._history),
            "counters": dict(self._counters),
            "subscribers": len(self._subscribers) + len(self._async_subscribers),
        }


# ─── Singleton ────────────────────────────────────────────

_global_bus: Optional[ActivityBus] = None

def get_activity_bus() -> ActivityBus:
    """Globaler Activity Bus (Singleton)."""
    global _global_bus
    if _global_bus is None:
        _global_bus = ActivityBus()
    return _global_bus

def set_activity_bus(bus: ActivityBus):
    """Globalen Activity Bus setzen."""
    global _global_bus
    _global_bus = bus


# os import needed for os.path.basename in file_edit
import os
