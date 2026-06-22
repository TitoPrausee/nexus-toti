"""
NEXUS v7 — Feedback Emitter
Real-time activity feedback during agent processing.
Shows step-by-step progress like Mercury: 💻 terminal, 📖 read_file, etc.
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Callable, Optional, List
from concurrent.futures import Future
import asyncio
import threading

log = logging.getLogger("nexus.feedback")


class FeedbackType(Enum):
    THINKING = "thinking"
    LLM_CALL = "llm_call"
    TOOL_START = "tool_start"
    TOOL_RESULT = "tool_result"
    PROGRESS = "progress"
    DONE = "done"
    AGENT_START = "agent_start"
    AGENT_PROGRESS = "agent_progress"
    AGENT_DONE = "agent_done"
    STREAM_TOKEN = "stream_token"


# Mercury-style icons per tool type
_TOOL_ICONS = {
    "terminal": "💻",
    "file_read": "📖",
    "file_write": "✏️",
    "file_search": "🔍",
    "web_search": "🌐",
    "web_fetch": "🌐",
    "code_exec": "⚡",
    "calculator": "🔢",
    "time": "🕐",
    "delegation": "🤝",
    "memory": "🧠",
    "session": "💾",
    "skill": "📚",
    "thinking": "🧠",
    "llm_call": "💭",
}


@dataclass
class FeedbackEvent:
    type: FeedbackType
    message: str
    detail: str = ""
    icon: str = ""
    timestamp: float = 0.0
    step: int = 0
    department: str = ""
    model_name: str = ""
    elapsed: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    @property
    def display(self) -> str:
        """Format for chat display — one line per step."""
        icon = self.icon or _TOOL_ICONS.get(self.type.value, "⏳")
        # Short, punchy format like Mercury
        if self.detail:
            return f'{icon} {self.message}: "{self.detail}"'
        return f"{icon} {self.message}"


class FeedbackEmitter:
    """
    Emits feedback events during agent processing.

    Thread-safe — can be called from sync code while async consumer reads via queue.
    Usage with Telegram:
        emitter = FeedbackEmitter()
        # Pass emitter to agent.process(feedback=emitter)
        # In async handler: poll emitter.events_queue for real-time updates
    """

    def __init__(self, callback: Optional[Callable[[FeedbackEvent], None]] = None,
                 async_queue: Optional[asyncio.Queue] = None):
        self.callback = callback
        self.async_queue = async_queue
        self.events: List[FeedbackEvent] = []
        self._step = 0
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._stream_buffer: List[str] = []  # Accumulate streamed tokens
        self._stream_lock = threading.Lock()

    def emit(self, event_type: FeedbackType, message: str,
             detail: str = "", icon: str = "",
             department: str = "", model_name: str = "",
             elapsed: float = 0.0):
        """Emit a feedback event — thread-safe."""
        with self._lock:
            self._step += 1
            event = FeedbackEvent(
                type=event_type,
                message=message,
                detail=detail[:120],  # Keep it short
                icon=icon,
                step=self._step,
                department=department,
                model_name=model_name,
                elapsed=elapsed,
            )
            self.events.append(event)

        # Callback (sync)
        if self.callback:
            try:
                self.callback(event)
            except Exception as e:
                log.debug(f"Feedback callback error: {e}")

        # Async queue (for Telegram bot)
        if self.async_queue:
            try:
                self.async_queue.put_nowait(event)
            except Exception:
                pass

    @property
    def step(self) -> int:
        with self._lock:
            return self._step

    @property
    def is_done(self) -> bool:
        return self._done.is_set()

    def mark_done(self):
        """Signal that processing is complete."""
        self._done.set()
        if self.async_queue:
            try:
                self.async_queue.put_nowait(None)  # Sentinel
            except Exception:
                pass

    # ─── Convenience Methods ────────────────────────

    def thinking(self, message: str = "Denke nach..."):
        self.emit(FeedbackType.THINKING, message, icon="🧠")

    def llm_call(self, model: str = ""):
        detail = f"Modell: {model}" if model else ""
        self.emit(FeedbackType.LLM_CALL, "Antwort generieren...", detail=detail, icon="💭")

    def tool_start(self, tool_name: str, args_summary: str = ""):
        icon = _TOOL_ICONS.get(tool_name, "🔧")
        if args_summary:
            self.emit(FeedbackType.TOOL_START, tool_name, detail=args_summary[:120], icon=icon)
        else:
            self.emit(FeedbackType.TOOL_START, tool_name, icon=icon)

    def tool_result(self, tool_name: str, success: bool, summary: str = ""):
        icon = "✅" if success else "❌"
        msg = tool_name
        if summary:
            msg = f"{tool_name}: {summary[:80]}"
        self.emit(FeedbackType.TOOL_RESULT, msg, icon=icon)

    def progress(self, message: str, detail: str = ""):
        icon = "📋"
        self.emit(FeedbackType.PROGRESS, message, detail=detail, icon=icon)

    def done(self, summary: str = ""):
        self.emit(FeedbackType.DONE, summary or "Fertig", icon="✨")
        self.mark_done()

    # ─── Agent Events ──────────────────────────────

    def agent_start(self, department: str, model_name: str = "", icon: str = ""):
        """Emit AGENT_START — a department agent has started working."""
        dept_icons = {
            "ceo": "👔", "research": "🔍", "engineering": "💻",
            "creative": "🎨", "operations": "📋",
        }
        if not icon:
            icon = dept_icons.get(department, "🤖")
        name = department.capitalize()
        self.emit(
            FeedbackType.AGENT_START, name,
            detail=model_name, icon=icon,
            department=department, model_name=model_name,
        )

    def agent_progress(self, department: str, message: str, detail: str = ""):
        """Emit AGENT_PROGRESS — a department agent made progress."""
        self.emit(
            FeedbackType.AGENT_PROGRESS, message,
            detail=detail[:120], icon="⏳",
            department=department,
        )

    def agent_done(self, department: str, model_name: str = "",
                   elapsed: float = 0.0, success: bool = True):
        """Emit AGENT_DONE — a department agent has finished."""
        icon = "✅" if success else "❌"
        name = department.capitalize()
        detail = f"{elapsed:.1f}s" if elapsed > 0 else ""
        self.emit(
            FeedbackType.AGENT_DONE, name,
            detail=detail, icon=icon,
            department=department, model_name=model_name,
            elapsed=elapsed,
        )

    def format_progress(self, last_n: int = 0) -> str:
        """Format events as display string. last_n=0 means all."""
        with self._lock:
            events = self.events[-last_n:] if last_n else self.events
        return "\n".join(e.display for e in events)

    # ─── Streaming ──────────────────────────────────────

    def stream_token(self, token: str):
        """Receive a streamed token from the LLM and forward it to the async queue.
        Called from the sync thread (agent.process) — forwards tokens to the
        Telegram bot for real-time message editing."""
        with self._stream_lock:
            self._stream_buffer.append(token)

        if self.async_queue:
            try:
                event = FeedbackEvent(
                    type=FeedbackType.STREAM_TOKEN,
                    message=token,
                    icon="",
                )
                self.async_queue.put_nowait(event)
            except Exception:
                pass

    def get_streamed_text(self) -> str:
        """Get all streamed tokens accumulated so far (thread-safe)."""
        with self._stream_lock:
            return "".join(self._stream_buffer)

    def clear_stream_buffer(self):
        """Clear the stream buffer (e.g., between iterations)."""
        with self._stream_lock:
            self._stream_buffer.clear()