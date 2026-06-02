"""
NEXUS Activity Feedback System — Makes the agent feel alive and responsive.

Generates real-time feedback messages during processing, thinking, tool calls,
and long operations so the user never feels like the agent is offline or stuck.

Core idea: Every agent action should produce visible feedback within seconds.
If a task takes longer, show progress indicators and "still working" messages.

Inspired by how real humans communicate when working on tasks.
"""

import time
import random
import asyncio
from typing import Optional, List, Dict, Callable
from dataclasses import dataclass, field
from enum import Enum


class FeedbackType(Enum):
    """Type of activity feedback."""
    THINKING = "thinking"           # Agent is processing/thinking
    WORKING = "working"             # Agent is executing a task
    TOOL_CALL = "tool_call"         # Agent is calling a tool
    PROGRESS = "progress"           # Progress update on long task
    WAITING = "waiting"             # Waiting for external resource
    SUCCESS = "success"             # Task completed successfully
    ERROR = "error"                 # Task failed
    HINT = "hint"                   # Helpful hint or suggestion
    GREETING = "greeting"           # Start of conversation
    FAREWELL = "farewell"           # End of conversation
    HUMAN_LIKE = "human_like"       # A human-like interjection


@dataclass
class FeedbackMessage:
    """A single feedback message."""
    type: FeedbackType
    text: str
    emoji: str = ""
    timestamp: float = field(default_factory=time.time)
    duration_estimate: float = 0.0   # How long this step might take (seconds)
    progress_pct: float = -1         # Progress percentage (-1 = unknown)


# ── German feedback messages — makes NEXUS feel like a real person ────

THINKING_MESSAGES = [
    "Mmm, mal überlegen... 🤔",
    "Da muss ich kurz nachdenken...",
    "Interessante Frage, eine Sekunde... ⏳",
    "Lass mich das mal durchdenken...",
    "Okay, da muss ich kurz das Gehirn anstrengen 💭",
    "Hmm, das ist eine gute Frage...",
    "Analyziere das mal schnell... 🔍",
    "Da muss ich tief in die Kiste greifen...",
    "Eine Sekunde, sortiere meine Gedanken... 🧠",
    "Kurzer Denkprozess läuft...",
    "Das braucht einen Moment... ⚡",
    "Schnapp mir mal die relevanten Daten... 📊",
]

WORKING_MESSAGES = [
    "Bin dran! 🔧",
    "Arbeite daran... ⚙️",
    "Mache ich direkt! 💪",
    "Wird gemacht! 🛠️",
    "Schon am Werk... 🔨",
    "Auf geht's! 🚀",
    "Hab ich im Griff... ✊",
    "Wird erledigt! ⚡",
    "Sofort! Brauch nur nen Moment... ⏱️",
    "Künstliche Intelligenz am Werk! 🤖",
]

PROGRESS_MESSAGES = [
    "Bin noch da! Arbeite weiter... 🫡",
    "Noch ein Moment, fast fertig... ⏳",
    "Fortschritt: {pct}% — halte durch! 💪",
    "Immer noch am Arbeiten, keine Sorge... 🔄",
    "Das dauert noch etwas, aber ich bin dran! 🏃",
    "Ich bleib dran! Noch {remaining}... ⏰",
    "Kaffeepause kann ich mir nicht leisten 😅 — arbeite weiter...",
    "Zwischenstand: {pct}% erledigt! 📊",
    "Kein Stillstand hier! Weiter geht's... 🎯",
]

TOOL_CALL_MESSAGES = [
    "Rufe {tool} auf... 🔌",
    "Nutze {tool} für dich... 🛠️",
    "{tool} wird ausgeführt... ⚡",
    "Sende Anfrage an {tool}... 📡",
]

SUCCESS_MESSAGES = [
    "Erledigt! ✅",
    "Fertig! Hat geklappt! 🎉",
    "Done! 🏁",
    "Abgeschlossen! ✨",
    "Passt! Alles erledigt! 👍",
    "So, das war's! 🎊",
    "Erledigt war der Auftrag! 🫡",
    "Habs geschafft! 🏆",
]

ERROR_MESSAGES = [
    "Hmm, das hat nicht geklappt... 😬",
    "Da ist was schiefgelaufen... 🚨",
    "Mist, Fehler aufgetreten! Lass mich das nochmal probieren... 🔄",
    "Okay, Plan A hat nicht funktioniert. Versuche Plan B... 💡",
    "Oh nein! Aber ich hab noch Ideen... 🤔",
]

HINT_MESSAGES = [
    "Übrigens: {hint} 💡",
    "Tipp: {hint} 😉",
    "Falls das hilft: {hint} 🤓",
    "Pro-Tipp: {hint} 🎯",
]

GREETING_MESSAGES = [
    "Hey! 👋 Was gibt's?",
    "Hallo! Bereit für alles! 🚀",
    "Moin! Was steht an? ⚡",
    "Servus! Ich bin NEXUS, dein KI-Assistent. Was kann ich für dich tun? 🤖",
    "Hi! Lass uns loslegen! 💪",
]

FAREWELL_MESSAGES = [
    "Bis später! 🫡",
    "Alles klar, bis bald! ✌️",
    "Mach's gut! 🤙",
    "Bis zum nächsten Mal! 🚀",
]

HUMAN_LIKE_MESSAGES = [
    "So, jetzt mal im Ernst... 😄",
    "Kurze Pause im Denkprozess — nein, Spaß, ich rechne weiter! 🧮",
    "Gute Frage übrig, die habe ich mich auch gefragt 🤔",
    "Das ist genau die Art von Problem, die mir Spaß macht! 🔥",
    "Ah, jetzt wird es interessant! 👀",
    "Endlich mal was Spannendes! 😎",
    "Okay okay, ich geb mir Mühe! 💪",
    "Kein Problem, das kriege ich hin! 🤝",
    "Da muss ich ehrlich sein... 🤷",
    "Ich würde sagen: Ja! Aber lass mich es dir genau zeigen... 📝",
]


class ActivityFeedback:
    """
    Generates human-like feedback messages during agent processing.
    
    Makes NEXUS feel alive by providing constant feedback about what
    it's doing, thinking, or waiting for.
    """

    def __init__(self, language: str = "de"):
        self.language = language
        self._last_feedback_time: float = 0.0
        self._last_feedback_type: Optional[FeedbackType] = None
        self._feedback_count: int = 0
        self._min_interval: float = 2.0  # Minimum seconds between feedback
        self._task_start: float = 0.0
        self._task_progress: float = 0.0

    def _should_show_feedback(self, feedback_type: FeedbackType) -> bool:
        """Check if enough time has passed since last feedback."""
        now = time.time()

        # Always show success/error/greeting/farewell
        if feedback_type in (FeedbackType.SUCCESS, FeedbackType.ERROR,
                           FeedbackType.GREETING, FeedbackType.FAREWELL):
            return True

        # Rate-limit other types
        if now - self._last_feedback_time < self._min_interval:
            # But for progress, show at least every 10 seconds
            if feedback_type == FeedbackType.PROGRESS:
                if now - self._last_feedback_time >= 10.0:
                    return True
            return False

        return True

    def _pick_message(self, messages: List[str], **kwargs) -> str:
        """Pick a random message from a list, formatting any placeholders."""
        msg = random.choice(messages)
        try:
            return msg.format(**kwargs)
        except (KeyError, IndexError):
            return msg

    def thinking(self, context: str = "") -> FeedbackMessage:
        """Generate a 'thinking' feedback message."""
        msg = self._pick_message(THINKING_MESSAGES)
        if context:
            msg = f"{msg} ({context})"
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.THINKING
        return FeedbackMessage(
            type=FeedbackType.THINKING,
            text=msg,
            emoji="🤔",
            duration_estimate=3.0,
        )

    def working(self, task: str = "") -> FeedbackMessage:
        """Generate a 'working on it' feedback message."""
        msg = self._pick_message(WORKING_MESSAGES)
        if task:
            msg = f"{msg} → {task}"
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.WORKING
        return FeedbackMessage(
            type=FeedbackType.WORKING,
            text=msg,
            emoji="⚙️",
            duration_estimate=5.0,
        )

    def tool_call(self, tool_name: str) -> FeedbackMessage:
        """Generate a 'calling tool' feedback message."""
        msg = self._pick_message(TOOL_CALL_MESSAGES, tool=tool_name)
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.TOOL_CALL
        return FeedbackMessage(
            type=FeedbackType.TOOL_CALL,
            text=msg,
            emoji="🔌",
            duration_estimate=2.0,
        )

    def progress(self, pct: float, remaining: str = "") -> FeedbackMessage:
        """Generate a progress update message."""
        msg = self._pick_message(PROGRESS_MESSAGES, pct=f"{pct:.0f}", remaining=remaining)
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.PROGRESS
        self._task_progress = pct
        return FeedbackMessage(
            type=FeedbackType.PROGRESS,
            text=msg,
            emoji="📊",
            progress_pct=pct,
        )

    def success(self, detail: str = "") -> FeedbackMessage:
        """Generate a success message."""
        msg = self._pick_message(SUCCESS_MESSAGES)
        if detail:
            msg = f"{msg} {detail}"
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.SUCCESS
        return FeedbackMessage(
            type=FeedbackType.SUCCESS,
            text=msg,
            emoji="✅",
        )

    def error(self, detail: str = "") -> FeedbackMessage:
        """Generate an error message (with hope!)."""
        msg = self._pick_message(ERROR_MESSAGES)
        if detail:
            msg = f"{msg} ({detail})"
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.ERROR
        return FeedbackMessage(
            type=FeedbackType.ERROR,
            text=msg,
            emoji="🚨",
        )

    def hint(self, hint_text: str) -> FeedbackMessage:
        """Generate a helpful hint message."""
        msg = self._pick_message(HINT_MESSAGES, hint=hint_text)
        self._last_feedback_time = time.time()
        return FeedbackMessage(
            type=FeedbackType.HINT,
            text=msg,
            emoji="💡",
        )

    def greeting(self) -> FeedbackMessage:
        """Generate a greeting message."""
        msg = self._pick_message(GREETING_MESSAGES)
        self._last_feedback_time = time.time()
        return FeedbackMessage(
            type=FeedbackType.GREETING,
            text=msg,
            emoji="👋",
        )

    def farewell(self) -> FeedbackMessage:
        """Generate a farewell message."""
        msg = self._pick_message(FAREWELL_MESSAGES)
        self._last_feedback_time = time.time()
        return FeedbackMessage(
            type=FeedbackType.FAREWELL,
            text=msg,
            emoji="✌️",
        )

    def human_like(self) -> FeedbackMessage:
        """Generate a human-like interjection."""
        msg = self._pick_message(HUMAN_LIKE_MESSAGES)
        self._last_feedback_time = time.time()
        self._last_feedback_type = FeedbackType.HUMAN_LIKE
        return FeedbackMessage(
            type=FeedbackType.HUMAN_LIKE,
            text=msg,
            emoji="😄",
        )

    def start_task(self, description: str = "") -> FeedbackMessage:
        """Mark the start of a task — resets progress tracking."""
        self._task_start = time.time()
        self._task_progress = 0.0
        self._feedback_count = 0
        return self.working(description)

    def update_task(self, pct: float, detail: str = "") -> FeedbackMessage:
        """Update task progress."""
        self._task_progress = pct
        self._feedback_count += 1

        if not self._should_show_feedback(FeedbackType.PROGRESS):
            # Return a minimal update
            return FeedbackMessage(
                type=FeedbackType.PROGRESS,
                text=f"{pct:.0f}%...",
                emoji="📊",
                progress_pct=pct,
            )

        # Every 3rd progress update, add a human-like message
        if self._feedback_count % 3 == 0 and pct > 30:
            return self.human_like()

        return self.progress(pct, remaining=detail)

    def finish_task(self, success: bool = True, detail: str = "") -> FeedbackMessage:
        """Mark task completion."""
        if success:
            return self.success(detail)
        return self.error(detail)

    def auto_feedback(self, elapsed_seconds: float) -> Optional[FeedbackMessage]:
        """
        Generate automatic feedback based on elapsed time.
        
        Call this in a loop while waiting for a long operation.
        Only produces feedback if enough time has passed.
        """
        if not self._should_show_feedback(FeedbackType.WAITING):
            return None

        if elapsed_seconds < 3:
            return None
        elif elapsed_seconds < 10:
            return self.thinking("Noch einen Moment...")
        elif elapsed_seconds < 30:
            return self.progress(self._task_progress or 50, remaining="noch ein paar Sekunden")
        elif elapsed_seconds < 60:
            return self.human_like()
        else:
            return self.progress(self._task_progress or 75, remaining="fast geschafft!")


class StreamingFeedback:
    """
    Streaming feedback for real-time display in Telegram.
    
    Periodically sends typing indicators and status updates
    so the user sees the agent is alive and working.
    """

    def __init__(self, feedback: ActivityFeedback, send_callback: Callable = None):
        self.feedback = feedback
        self._send_callback = send_callback
        self._running = False
        self._task_start = 0.0

    async def start(self, description: str = ""):
        """Start streaming feedback."""
        self._running = True
        self._task_start = time.time()
        msg = self.feedback.start_task(description)
        if self._send_callback:
            await self._send_callback(msg)
        return msg

    async def update(self, pct: float, detail: str = ""):
        """Send a progress update."""
        msg = self.feedback.update_task(pct, detail)
        if self._send_callback:
            await self._send_callback(msg)
        return msg

    async def finish(self, success: bool = True, detail: str = ""):
        """Stop streaming feedback."""
        self._running = False
        msg = self.feedback.finish_task(success, detail)
        if self._send_callback:
            await self._send_callback(msg)
        return msg

    async def stream_loop(self, total_seconds: float, steps: int = 10):
        """
        Stream progress updates over time.
        
        Useful for long-running operations where you want to
        show periodic progress to the user.
        """
        step_duration = total_seconds / steps
        for i in range(1, steps + 1):
            pct = (i / steps) * 100
            msg = self.feedback.update_task(pct)
            if self._send_callback:
                await self._send_callback(msg)
            await asyncio.sleep(step_duration)