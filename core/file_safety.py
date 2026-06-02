"""
NEXUS File Safety — Protects critical files from accidental agent overwrites.

Prevents the AI agent from writing to sensitive files like .env,
config.yaml, auth.json, and system directories.

Inspired by Hermes Agent's file_safety.py, adapted for NEXUS.

Usage:
    from core.file_safety import is_safe_write_path, validate_write_path

    # Check before writing
    if is_safe_write_path("/path/to/file.py"):
        write_file(path, content)
    else:
        log.warning(f"Write denied: {path} is a protected path")

    # Get detailed validation
    result = validate_write_path(path)
    if not result.safe:
        raise WriteDeniedError(result.reason)
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Set, List


@dataclass
class WriteValidation:
    """Result of validating a write path."""
    safe: bool
    reason: str = ""
    path: str = ""


# ── Sensitive filenames that must NEVER be overwritten ────────────────

DENIED_FILENAMES: Set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.test",
    "auth.json",
    "credentials.json",
    ".credentials",
    ".htpasswd",
    ".htaccess",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    ".ssh_config",
    "known_hosts",
    ".netrc",
    ".gitconfig",
    ".npmrc",
    ".pypirc",
    "config.yaml",         # NEXUS config — should only be edited by user
    "config.yml",
    "secrets.yaml",
    "secrets.yml",
    "docker-compose.override.yml",
}

# ── Sensitive file patterns (regex) ─────────────────────────────────

DENIED_PATTERNS = [
    re.compile(r"\.env\.", re.IGNORECASE),          # .env.something
    re.compile(r".*_secret_", re.IGNORECASE),        # anything_secret_
    re.compile(r".*_credential", re.IGNORECASE),      # anything_credential
    re.compile(r".*\.key$", re.IGNORECASE),           # *.key
    re.compile(r".*\.pem$", re.IGNORECASE),           # *.pem
    re.compile(r".*\.p12$", re.IGNORECASE),           # *.p12
    re.compile(r".*\.pfx$", re.IGNORECASE),           # *.pfx
    re.compile(r".*\.jks$", re.IGNORECASE),           # *.jks
    re.compile(r".*\.keystore$", re.IGNORECASE),     # *.keystore
]

# ── Directory prefixes that must NEVER be written to ─────────────────

DENIED_DIRECTORY_PREFIXES: List[str] = [
    "/etc/",
    "/usr/",
    "/bin/",
    "/sbin/",
    "/var/run/",
    "/var/log/",
    "/proc/",
    "/sys/",
    "/boot/",
    "/dev/",
    "/run/",
    "/snap/",
    # Home config dirs
    os.path.expanduser("~/.ssh/"),
    os.path.expanduser("~/.gnupg/"),
    os.path.expanduser("~/.config/gh/"),       # GitHub CLI config
    # NEXUS sensitive dirs
    "/data/auth/",
    "/data/secrets/",
    "/data/credentials/",
]

# ── Additional protection: never delete these ──────────────────────────

NEVER_DELETE_DIRS: Set[str] = {
    "data",
    "memory",
    "skills",
}


def _resolve_path(path: str) -> Path:
    """Resolve a path, handling ~, symlinks, and relative paths."""
    return Path(os.path.expanduser(path)).resolve()


def _get_nexus_home() -> Path:
    """Get the NEXUS home directory."""
    env_home = os.environ.get("NEXUS_HOME")
    if env_home:
        return Path(env_home).resolve()
    return Path(__file__).parent.parent.resolve()


def build_write_denied_paths() -> Set[str]:
    """
    Return exact sensitive paths that must never be written.

    These are absolute paths to files that are always denied,
    regardless of CWD.
    """
    home = _get_nexus_home()
    nexus_home = _get_nexus_home()

    paths = set()

    # NEXUS-specific protected files
    for fname in DENIED_FILENAMES:
        paths.add(str(nexus_home / fname))

    # SSH directory files
    ssh_dir = Path(os.path.expanduser("~/.ssh"))
    if ssh_dir.exists():
        for f in ssh_dir.iterdir():
            if f.is_file():
                paths.add(str(f))

    # Home .env files (top-level + profile)
    home = Path.home()
    paths.add(str(home / ".env"))
    paths.add(str(home / ".env.local"))

    # Git credentials
    paths.add(str(home / ".git-credentials"))

    return paths


def build_write_denied_prefixes() -> List[str]:
    """
    Return sensitive directory prefixes that must never be written to.
    """
    prefixes = list(DENIED_DIRECTORY_PREFIXES)

    # Add NEXUS data protection
    nexus_home = _get_nexus_home()
    prefixes.append(str(nexus_home / "data" / "auth"))
    prefixes.append(str(nexus_home / "data" / "secrets"))

    return prefixes


def is_safe_write_path(path: str) -> bool:
    """
    Check if a path is safe to write to.

    Returns True if the write should be allowed, False otherwise.
    This is the fast path — for detailed validation use validate_write_path().
    """
    result = validate_write_path(path)
    return result.safe


def validate_write_path(path: str) -> WriteValidation:
    """
    Validate a write path against all safety rules.

    Returns a WriteValidation with:
    - safe: True if write should be allowed
    - reason: Human-readable reason if denied
    - path: The resolved path
    """
    if not path:
        return WriteValidation(safe=False, reason="Empty path", path="")

    try:
        resolved = _resolve_path(path)
    except Exception as e:
        return WriteValidation(safe=False, reason=f"Invalid path: {e}", path=path)

    resolved_str = str(resolved)
    filename = resolved.name

    # 1. Check denied filenames
    if filename in DENIED_FILENAMES:
        return WriteValidation(
            safe=False,
            reason=f"Protected filename: {filename} (credential/config file)",
            path=resolved_str,
        )

    # 2. Check denied filename patterns
    for pattern in DENIED_PATTERNS:
        if pattern.search(filename):
            return WriteValidation(
                safe=False,
                reason=f"Protected filename pattern: {filename} matches {pattern.pattern}",
                path=resolved_str,
            )

    # 3. Check denied directory prefixes
    for prefix in build_write_denied_prefixes():
        if resolved_str.startswith(prefix):
            return WriteValidation(
                safe=False,
                reason=f"Protected directory: {resolved_str} is under {prefix}",
                path=resolved_str,
            )

    # 4. Check exact denied paths
    if resolved_str in build_write_denied_paths():
        return WriteValidation(
            safe=False,
            reason=f"Protected file: {resolved_str}",
            path=resolved_str,
        )

    # All checks passed
    return WriteValidation(safe=True, reason="OK", path=resolved_str)


def is_safe_delete_path(path: str) -> bool:
    """
    Check if a path is safe to delete.

    More restrictive than write — protects entire directories
    that contain critical data.
    """
    result = validate_write_path(path)
    if not result.safe:
        return False

    resolved = _resolve_path(path)

    # Extra protection for directory deletion
    if resolved.is_dir():
        dirname = resolved.name.lower()
        if dirname in NEVER_DELETE_DIRS:
            return False

    return True