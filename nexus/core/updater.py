"""
NEXUS v9.1 — Auto-Updater
Checks GitHub for new releases, notifies via Telegram, and performs auto-updates.
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, Callable

import requests

from nexus import __version__

log = logging.getLogger("nexus.updater")

GITHUB_REPO = "***REMOVED***/nexus-toti"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
INSTALL_DIR = Path(__file__).resolve().parent.parent.parent  # nexus-toti root
NOTIFICATION_FILE = Path("data/update_notifications.json")
CACHE_TTL = 3600  # 1 hour cache for GitHub API
CHECK_INTERVAL = 6 * 3600  # 6 hours between update checks


class VersionInfo:
    """Parsed version and release information."""
    def __init__(self, current: str, latest: str = None, changelog: str = "",
                 html_url: str = "", published_at: str = ""):
        self.current = current
        self.latest = latest or current
        self.changelog = changelog
        self.html_url = html_url
        self.published_at = published_at

    @property
    def has_update(self) -> bool:
        """Check if a newer version is available."""
        if not self.latest:
            return False
        # Compare semantic versions (major.minor.patch)
        try:
            current_parts = [int(p) for p in self.current.split(".")]
            latest_parts = [int(p) for p in self.latest.split(".")]
            # Pad to same length
            while len(current_parts) < 3:
                current_parts.append(0)
            while len(latest_parts) < 3:
                latest_parts.append(0)
            return latest_parts > current_parts
        except (ValueError, TypeError):
            return self.latest != self.current

    def format_update_message(self) -> str:
        """Format a Telegram-friendly update notification."""
        if not self.has_update:
            return f"✅ Nexus ist auf dem neuesten Stand \\(v{self.current}\\)"

        # Truncate changelog for Telegram (max 1000 chars, escape for MarkdownV2)
        changelog = self.changelog[:800]
        # Simple MarkdownV2 escaping for the changelog
        for char in ['.', '!', '-', '(', ')', '{', '}', '=', '+', '|']:
            changelog = changelog.replace(char, f"\\{char}")

        return (
            f"🆕 *Nexus v{self.latest} verfügbar\\!*\n\n"
            f"Aktuelle Version: v{self.current}\n"
            f"Neueste Version: v{self.latest}\n\n"
            f"📋 *Changelog:*\n{changelog}\n\n"
            f"🔗 [Release auf GitHub]({self.html_url})\n\n"
            f"/update now — Update durchführen"
        )


class VersionChecker:
    """Check GitHub for new releases with caching."""

    def __init__(self):
        self._cache_time = 0.0
        self._cache_result: Optional[dict] = None
        self._last_notification_version = ""
        self._load_notification_state()

    def _load_notification_state(self):
        """Load which version was last notified about."""
        if NOTIFICATION_FILE.exists():
            try:
                data = json.loads(NOTIFICATION_FILE.read_text(encoding="utf-8"))
                self._last_notification_version = data.get("last_notified_version", "")
            except Exception:
                self._last_notification_version = ""

    def _save_notification_state(self, version: str):
        """Save which version was last notified about."""
        try:
            NOTIFICATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"last_notified_version": version}
            NOTIFICATION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._last_notification_version = version
        except Exception as e:
            log.warning(f"Failed to save notification state: {e}")

    def check_github_release(self) -> VersionInfo:
        """Check GitHub for the latest release.

        Returns VersionInfo with update status.
        Uses a 1-hour cache to avoid rate limiting.
        """
        # Use cache if fresh
        now = time.time()
        if self._cache_result and (now - self._cache_time) < CACHE_TTL:
            return self._cache_result

        try:
            response = requests.get(
                GITHUB_API_URL,
                timeout=10,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "nexus-updater"},
            )
            response.raise_for_status()
            data = response.json()

            latest_version = data.get("tag_name", "").lstrip("v")
            changelog = data.get("body", "")[:800]
            html_url = data.get("html_url", "")
            published_at = data.get("published_at", "")

            info = VersionInfo(
                current=__version__,
                latest=latest_version,
                changelog=changelog,
                html_url=html_url,
                published_at=published_at,
            )

            self._cache_result = info
            self._cache_time = now
            log.info(f"Update check: current=v{__version__}, latest=v{latest_version}, has_update={info.has_update}")
            return info

        except requests.RequestException as e:
            log.warning(f"GitHub release check failed: {e}")
            return VersionInfo(current=__version__)
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"GitHub release parse failed: {e}")
            return VersionInfo(current=__version__)

    def should_notify(self, version_info: VersionInfo) -> bool:
        """Check if we should send a notification for this version.

        Only notify once per new version (don't spam on every heartbeat).
        """
        if not version_info.has_update:
            return False
        if version_info.latest == self._last_notification_version:
            return False
        return True

    def mark_notified(self, version: str):
        """Mark that we've notified about this version."""
        self._save_notification_state(version)


class AutoUpdater:
    """Perform auto-updates via git pull + docker rebuild + restart."""

    def __init__(self, install_dir: Path = None):
        self.install_dir = install_dir or INSTALL_DIR

    def update(self) -> tuple[bool, str]:
        """Perform the update sequence.

        Returns (success, message).
        """
        steps = [
            ("Git Pull", self._git_pull),
            ("Docker Build", self._docker_build),
            ("Docker Restart", self._docker_restart),
        ]

        for step_name, step_func in steps:
            log.info(f"Update step: {step_name}")
            success, msg = step_func()
            if not success:
                log.error(f"Update failed at {step_name}: {msg}")
                return False, f"❌ Update fehlgeschlagen bei {step_name}: {msg}"

        return True, f"✅ Update erfolgreich! Nexus wurde neu gestartet."

    def _git_pull(self) -> tuple[bool, str]:
        """Pull latest changes from GitHub."""
        try:
            result = subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=str(self.install_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip()[:500]
        except subprocess.TimeoutExpired:
            return False, "git pull timeout (120s)"
        except Exception as e:
            return False, str(e)[:500]

    def _docker_build(self) -> tuple[bool, str]:
        """Rebuild the Docker image."""
        try:
            result = subprocess.run(
                ["docker", "compose", "build", "nexus-telegram"],
                cwd=str(self.install_dir),
                capture_output=True,
                text=True,
                timeout=600,  # 10 min timeout for build
            )
            if result.returncode == 0:
                return True, "Build erfolgreich"
            return False, result.stderr.strip()[:500]
        except subprocess.TimeoutExpired:
            return False, "docker build timeout (600s)"
        except Exception as e:
            return False, str(e)[:500]

    def _docker_restart(self) -> tuple[bool, str]:
        """Restart the container with the new image."""
        try:
            # Stop current container
            subprocess.run(
                ["docker", "compose", "stop", "nexus-telegram"],
                cwd=str(self.install_dir),
                capture_output=True,
                timeout=60,
            )
            # Start with new image
            result = subprocess.run(
                ["docker", "compose", "up", "-d", "nexus-telegram"],
                cwd=str(self.install_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return True, "Container neu gestartet"
            return False, result.stderr.strip()[:500]
        except Exception as e:
            return False, str(e)[:500]

    def get_current_version(self) -> str:
        """Get the current installed version."""
        return __version__

    def get_install_dir(self) -> str:
        """Get the installation directory."""
        return str(self.install_dir)