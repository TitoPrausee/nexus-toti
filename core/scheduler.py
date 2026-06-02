"""
NEXUS Smart Scheduler — No dumb cronjobs.
4 Trigger Types: CHANGE_TRIGGER, IDLE_TRIGGER, THRESHOLD_TRIGGER, INTERVAL_TRIGGER
Runs locally — zero GPU cost.
"""

import hashlib
import time
import os
import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScheduledTask:
    task_id: str
    trigger: str  # CHANGE_TRIGGER, IDLE_TRIGGER, THRESHOLD_TRIGGER, INTERVAL_TRIGGER
    fn: Optional[Callable] = None
    model_level: int = 0  # 0 = local (no model call)
    last_run: Optional[float] = None
    last_hash: Optional[str] = None
    watch: Optional[str] = None  # Path/URL to watch for changes
    metric: Optional[str] = None  # Metric name for threshold
    threshold: Optional[float] = None  # Threshold value
    interval_seconds: Optional[int] = None  # For INTERVAL_TRIGGER
    skip_if: Optional[str] = None  # Skip condition
    enabled: bool = True
    run_count: int = 0
    last_result: Optional[Any] = None


class SmartScheduler:
    """
    Smart task scheduler — tasks only run when they would actually do something.
    No wasted GPU cycles on empty runs.
    """

    def __init__(self, state_dir: Optional[str] = None):
        self.tasks: dict[str, ScheduledTask] = {}
        self._state_dir = state_dir
        self._running = False

    def register(self, task_id: str, trigger: str, fn: Optional[Callable] = None,
                 model_level: int = 0, **kwargs):
        """Register a scheduled task."""
        self.tasks[task_id] = ScheduledTask(
            task_id=task_id,
            trigger=trigger,
            fn=fn,
            model_level=model_level,
            watch=kwargs.get("watch"),
            metric=kwargs.get("metric"),
            threshold=kwargs.get("threshold"),
            interval_seconds=kwargs.get("interval_seconds"),
            skip_if=kwargs.get("skip_if"),
        )

    def unregister(self, task_id: str):
        if task_id in self.tasks:
            del self.tasks[task_id]

    async def tick(self) -> list[dict]:
        """
        Run one scheduler tick — check all tasks and execute eligible ones.
        Returns list of results.
        """
        results = []
        for task in list(self.tasks.values()):
            if not task.enabled:
                continue
            if await self._should_run(task):
                result = await self._execute(task)
                results.append(result)
        return results

    async def _should_run(self, task: ScheduledTask) -> bool:
        """Determine if a task should run based on its trigger type."""
        trigger = task.trigger

        # CHANGE_TRIGGER: only run if watched path/state has changed
        if trigger == "CHANGE_TRIGGER":
            if not task.watch:
                return False
            current_hash = self._get_state_hash(task.watch)
            if current_hash == task.last_hash:
                return False  # Nothing changed — skip, 0 GPU cost
            task.last_hash = current_hash
            return True

        # IDLE_TRIGGER: only run when system is idle
        if trigger == "IDLE_TRIGGER":
            return self._system_is_idle()

        # THRESHOLD_TRIGGER: only run when metric exceeds threshold
        if trigger == "THRESHOLD_TRIGGER":
            if task.metric is None or task.threshold is None:
                return False
            value = self._get_metric(task.metric)
            return value >= task.threshold

        # INTERVAL_TRIGGER: time-based but with skip logic
        if trigger == "INTERVAL_TRIGGER":
            if not task.last_run:
                return True
            if task.interval_seconds is None:
                return False
            elapsed = time.time() - task.last_run
            if elapsed < task.interval_seconds:
                return False
            # Skip if nothing to do
            if task.skip_if and self._check_skip(task.skip_if):
                return False
            return True

        return False

    async def _execute(self, task: ScheduledTask) -> dict:
        """Execute a scheduled task."""
        task.last_run = time.time()
        task.run_count += 1

        result = {"task_id": task.task_id, "trigger": task.trigger, "run_count": task.run_count}

        if task.fn:
            try:
                if asyncio.iscoroutinefunction(task.fn):
                    fn_result = await task.fn()
                else:
                    fn_result = task.fn()
                task.last_result = fn_result
                result["status"] = "executed"
                result["result"] = str(fn_result)[:500]
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
        else:
            result["status"] = "no_fn"

        return result

    def _get_state_hash(self, watch_path: str) -> str:
        """Hash of watched path — no API call, purely local."""
        try:
            if os.path.isfile(watch_path):
                with open(watch_path, "rb") as f:
                    return hashlib.md5(f.read()).hexdigest()
            elif os.path.isdir(watch_path):
                # Hash directory listing + modification times
                items = []
                for entry in sorted(os.listdir(watch_path)):
                    full = os.path.join(watch_path, entry)
                    mtime = os.path.getmtime(full) if os.path.exists(full) else 0
                    items.append(f"{entry}:{mtime}")
                return hashlib.md5("|".join(items).encode()).hexdigest()
        except Exception:
            pass
        return ""

    def _system_is_idle(self) -> bool:
        """Check if system is idle — no active tasks running."""
        running = [t for t in self.tasks.values() if t.last_run and
                   t.last_run > time.time() - 60]
        return len(running) == 0

    def _get_metric(self, metric_name: str) -> float:
        """Get a system metric value. Extensible."""
        metrics = {
            "time_hour": datetime.now(timezone.utc).hour,
        }
        return metrics.get(metric_name, 0.0)

    def _check_skip(self, skip_condition: str) -> bool:
        """Check if a skip condition is met."""
        # Simple skip conditions
        if skip_condition == "state_unchanged":
            return True  # Placeholder — would check actual state
        if skip_condition == "no_new_logs_since_last_run":
            return True  # Placeholder
        return False

    def get_status(self) -> dict:
        """Get scheduler status."""
        return {
            "total_tasks": len(self.tasks),
            "enabled_tasks": sum(1 for t in self.tasks.values() if t.enabled),
            "tasks": {
                tid: {
                    "trigger": t.trigger,
                    "last_run": t.last_run,
                    "run_count": t.run_count,
                    "enabled": t.enabled,
                }
                for tid, t in self.tasks.items()
            },
        }

    def get_pending(self) -> list[dict]:
        """Get tasks that would run on next tick."""
        pending = []
        for task in self.tasks.values():
            if task.enabled and not task.last_run:
                pending.append({"task_id": task.task_id, "trigger": task.trigger})
        return pending
