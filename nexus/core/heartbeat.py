"""
NEXUS v9.1 — Heartbeat System
Autonomous health checks, project tracking, and proactive optimization.
Inspired by Mercury's cron-based self-improvement cycle.

Runs as a background thread, checking:
1. Ollama Cloud reachability (via Merge Proxy)
2. Memory health (compression, cleanup)
3. Project status (from project_tracker)
4. Update checking (GitHub releases, every 6 hours)

Usage:
    heartbeat = HeartbeatSystem(agent, config)
    heartbeat.start()  # starts background thread
    heartbeat.stop()   # graceful shutdown
"""

import os
import time
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("nexus.heartbeat")


class HealthStatus:
    """Track health of subsystems."""
    def __init__(self):
        self.ollama_reachable = False
        self.ollama_last_check = 0.0
        self.ollama_response_time = 0.0
        self.merge_proxy_status = {}
        self.memory_entries = 0
        self.memory_size_kb = 0.0
        self.last_heartbeat = 0.0
        self.heartbeat_count = 0
        self.errors = []

    def to_dict(self) -> dict:
        return {
            "ollama_reachable": self.ollama_reachable,
            "ollama_response_time_ms": round(self.ollama_response_time * 1000, 1),
            "merge_proxy": self.merge_proxy_status,
            "memory_entries": self.memory_entries,
            "memory_size_kb": round(self.memory_size_kb, 1),
            "last_heartbeat": datetime.fromtimestamp(self.last_heartbeat).isoformat() if self.last_heartbeat else None,
            "heartbeat_count": self.heartbeat_count,
            "errors": self.errors[-5:],  # last 5 errors
        }


class HeartbeatSystem:
    """
    Background heartbeat that checks system health and triggers
    autonomous improvements.

    Mercury-inspired: instead of waiting for user input, Toti
    proactively checks its environment and optimizes itself.
    """

    def __init__(self, agent=None, config: dict = None, update_callback: Optional[Callable] = None):
        self.agent = agent
        self.config = config or {}
        self.health = HealthStatus()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.update_callback = update_callback  # Called when update is available

        # Config
        hb_config = self.config.get("heartbeat", {})
        self.interval = hb_config.get("interval_seconds", 300)  # 5 minutes default
        self.ollama_url = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11435")
        self.data_dir = Path(hb_config.get("data_dir", "data"))
        self.health_file = self.data_dir / "health_status.json"

        # Update checking
        self._update_check_counter = 0
        self._update_check_interval = 72  # Every 72 heartbeats ≈ 6 hours (72 * 5min)

        # Ensure data dir exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def start(self):
        """Start the heartbeat background thread."""
        if self._running:
            log.warning("Heartbeat already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="nexus-heartbeat")
        self._thread.start()
        log.info(f"[HEARTBEAT] Started (interval={self.interval}s, url={self.ollama_url})")

    def stop(self):
        """Stop the heartbeat gracefully."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        log.info("[HEARTBEAT] Stopped")

    def check_ollama(self) -> bool:
        """Check if Ollama Cloud (via Merge Proxy) is reachable."""
        import requests
        try:
            start = time.time()
            url = f"{self.ollama_url}/health"
            resp = requests.get(url, timeout=5)
            elapsed = time.time() - start

            self.health.ollama_reachable = resp.status_code == 200
            self.health.ollama_response_time = elapsed
            self.health.ollama_last_check = time.time()

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    self.health.merge_proxy_status = {
                        "status": data.get("status", "unknown"),
                        "mode": data.get("mode", "unknown"),
                        "cloud_reachable": data.get("cloudReachable", False),
                        "accounts": len(data.get("accounts", [])),
                    }
                except (json.JSONDecodeError, ValueError):
                    pass
                log.info(f"[HEARTBEAT] Ollama OK ({elapsed*1000:.0f}ms, cloud={self.health.merge_proxy_status.get('cloud_reachable')})")
            else:
                log.warning(f"[HEARTBEAT] Ollama returned {resp.status_code}")

            return self.health.ollama_reachable

        except requests.exceptions.RequestException as e:
            self.health.ollama_reachable = False
            self.health.ollama_last_check = time.time()
            self.health.errors.append(f"{datetime.now().isoformat()}: Ollama unreachable: {e}")
            log.error(f"[HEARTBEAT] Ollama unreachable: {e}")
            return False

    def check_memory(self) -> dict:
        """Check memory system health."""
        memory_dir = self.data_dir / "memory"
        sessions_dir = self.data_dir / "sessions"

        stats = {
            "memory_files": 0,
            "session_files": 0,
            "total_size_kb": 0.0,
        }

        if memory_dir.exists():
            files = list(memory_dir.rglob("*.json"))
            stats["memory_files"] = len(files)
            stats["total_size_kb"] += sum(f.stat().st_size for f in files) / 1024

        if sessions_dir.exists():
            files = list(sessions_dir.rglob("*.json"))
            stats["session_files"] = len(files)
            stats["total_size_kb"] += sum(f.stat().st_size for f in files) / 1024

        self.health.memory_entries = stats["memory_files"] + stats["session_files"]
        self.health.memory_size_kb = stats["total_size_kb"]

        return stats

    def cleanup_old_sessions(self, max_age_hours: int = 48):
        """Clean up old session files to prevent disk bloat."""
        sessions_dir = self.data_dir / "sessions"
        if not sessions_dir.exists():
            return 0

        cutoff = time.time() - (max_age_hours * 3600)
        cleaned = 0

        for f in sessions_dir.rglob("*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    cleaned += 1
            except OSError:
                pass

        if cleaned > 0:
            log.info(f"[HEARTBEAT] Cleaned {cleaned} old session files (>{max_age_hours}h)")
        return cleaned

    def save_health_status(self):
        """Persist current health status to disk."""
        try:
            status = self.health.to_dict()
            status["timestamp"] = datetime.now().isoformat()
            self.health_file.parent.mkdir(parents=True, exist_ok=True)
            self.health_file.write_text(json.dumps(status, indent=2, ensure_ascii=False))
        except Exception as e:
            log.error(f"[HEARTBEAT] Failed to save health status: {e}")

    def _run_loop(self):
        """Main heartbeat loop — runs in background thread."""
        # Initial check
        self.check_ollama()
        self.check_memory()
        self.save_health_status()

        while self._running:
            try:
                time.sleep(self.interval)

                if not self._running:
                    break

                self.health.heartbeat_count += 1
                self.health.last_heartbeat = time.time()

                # Check Ollama
                self.check_ollama()

                # Check memory
                self.check_memory()

                # Sync git memory (periodic push/pull)
                if self.health.heartbeat_count % 10 == 0:  # Every ~50min at 5min interval
                    try:
                        if hasattr(self.agent, 'memory') and hasattr(self.agent.memory, 'git_memory'):
                            self.agent.memory.git_memory.maybe_sync()
                    except Exception as e:
                        log.warning(f"[HEARTBEAT] Git memory sync failed: {e}")

                # Cleanup old sessions (every 6th heartbeat = ~30min)
                if self.health.heartbeat_count % 6 == 0:
                    self.cleanup_old_sessions()

                # Check for updates (every ~6 hours)
                self._update_check_counter += 1
                if self._update_check_counter >= self._update_check_interval:
                    self._update_check_counter = 0
                    self._check_for_updates()

                # Save health status
                self.save_health_status()

                log.debug(f"[HEARTBEAT] #{self.health.heartbeat_count} complete")

            except Exception as e:
                log.error(f"[HEARTBEAT] Error in heartbeat loop: {e}")
                self.health.errors.append(f"{datetime.now().isoformat()}: {e}")
                time.sleep(10)  # Back off on errors

    def get_status(self) -> dict:
        """Get current health status."""
        return self.health.to_dict()

    def _check_for_updates(self):
        """Check GitHub for new releases and notify via callback if available."""
        try:
            from nexus.core.updater import VersionChecker
            checker = VersionChecker()
            version_info = checker.check_github_release()

            if version_info.has_update and checker.should_notify(version_info):
                log.info(f"[HEARTBEAT] Update available: v{version_info.current} → v{version_info.latest}")
                checker.mark_notified(version_info.latest)

                # Notify via callback (Telegram bot)
                if self.update_callback:
                    try:
                        self.update_callback(version_info)
                    except Exception as e:
                        log.error(f"[HEARTBEAT] Update callback failed: {e}")
            elif not version_info.has_update:
                log.debug(f"[HEARTBEAT] No update available (v{version_info.current})")
        except Exception as e:
            log.error(f"[HEARTBEAT] Update check failed: {e}")

    def is_healthy(self) -> bool:
        """Quick health check — is Ollama reachable?"""
        return self.health.ollama_reachable