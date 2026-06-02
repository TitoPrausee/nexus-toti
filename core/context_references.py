"""
NEXUS Context Reference System — Parse @file:path and @url:url references.

Allows users to inject file contents or web content into their messages
by referencing paths and URLs with @file: and @url: prefixes.

Inspired by Hermes Agent's context_references.py, adapted for NEXUS.

Usage:
    from core.context_references import preprocess_context_references

    # In user message processing:
    processed = preprocess_context_references(
        "Analyze this code @file:core/agent_base.py",
        base_path="/project/nexus-toti"
    )
    # → "Analyze this code <context-ref file=\"core/agent_base.py\">\n...file contents...\n</context-ref>"
"""

import re
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
from urllib.parse import urlparse


@dataclass
class ContextReference:
    """A parsed context reference from a user message."""
    ref_type: str       # "file" or "url"
    path: str           # The file path or URL
    start: int          # Start position in original message
    end: int             # End position in original message

    @property
    def raw(self) -> str:
        return f"@{self.ref_type}:{self.path}"


@dataclass
class ContextReferenceResult:
    """Result of processing context references in a message."""
    original: str                   # Original message
    processed: str                   # Message with references replaced
    references: List[ContextReference]  # Parsed references
    loaded: int = 0                 # Number successfully loaded
    failed: int = 0                 # Number that failed to load
    errors: List[str] = None        # Error messages for failed references

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# ── Reference Parsing ────────────────────────────────────────────────

# Match @file:path/to/file and @url:https://...
FILE_REF_PATTERN = re.compile(r"@file:([^\s,.)\]]+)", re.IGNORECASE)
URL_REF_PATTERN = re.compile(r"@url:(https?://[^\s,.)\]]+)", re.IGNORECASE)

# Combined pattern for efficiency
CONTEXT_REF_PATTERN = re.compile(r"@(?P<type>file|url):(?P<path>[^\s,.)\]]+)", re.IGNORECASE)

# Maximum file size to inject (1MB)
MAX_FILE_SIZE = 1_000_000

# Maximum URL content size (2MB)
MAX_URL_SIZE = 2_000_000

# Maximum total context injection (4MB — well within most model windows)
MAX_TOTAL_CONTEXT = 4_000_000

# ── Supported file extensions ────────────────────────────────────────

BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flv",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".sqlite", ".db",
}


def parse_context_references(message: str) -> List[ContextReference]:
    """
    Parse all @file:path and @url:url references from a message.
    """
    refs = []
    for match in CONTEXT_REF_PATTERN.finditer(message):
        ref_type = match.group("type").lower()
        path = match.group("path")
        refs.append(ContextReference(
            ref_type=ref_type,
            path=path,
            start=match.start(),
            end=match.end(),
        ))
    return refs


def _load_file_content(path: str, base_path: str = "") -> tuple[str, bool]:
    """
    Load file content from a path relative to base_path.

    Returns (content, success).
    """
    if base_path:
        full_path = Path(base_path) / path
    else:
        full_path = Path(path)

    # Security: prevent path traversal
    try:
        full_path = full_path.resolve()
    except Exception:
        return f"Error: Invalid path '{path}'", False

    # Check file extension
    if full_path.suffix.lower() in BLOCKED_EXTENSIONS:
        return f"Error: Cannot inject binary file '{path}' (blocked extension: {full_path.suffix})", False

    # Check file exists
    if not full_path.exists():
        return f"Error: File not found '{path}'", False

    if not full_path.is_file():
        return f"Error: Not a file '{path}'", False

    # Check file size
    try:
        size = full_path.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"Error: File too large '{path}' ({size} bytes, max {MAX_FILE_SIZE})", False
    except OSError:
        return f"Error: Cannot stat file '{path}'", False

    # Read content
    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        return content, True
    except Exception as e:
        return f"Error: Cannot read file '{path}': {e}", False


def _load_url_content(url: str, timeout: int = 30) -> tuple[str, bool]:
    """
    Fetch content from a URL.

    Returns (content, success).
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "NEXUS-Toti/5.0 (Context Reference System)",
                "Accept": "text/html,text/plain,application/json,application/xml,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return f"Error: HTTP {resp.status} for '{url}'", False

            # Check content length
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_URL_SIZE:
                return f"Error: URL content too large ({content_length} bytes, max {MAX_URL_SIZE})", False

            content = resp.read(MAX_URL_SIZE).decode("utf-8", errors="replace")
            return content, True

    except ImportError:
        return "Error: urllib not available", False
    except Exception as e:
        return f"Error: Cannot fetch URL '{url}': {e}", False


def preprocess_context_references(
    message: str,
    base_path: str = "",
    max_context: int = MAX_TOTAL_CONTEXT,
) -> ContextReferenceResult:
    """
    Process all context references in a user message.

    Replaces @file:path and @url:url references with their content,
    wrapped in <context-ref> tags.

    Args:
        message: The user message containing @file: and @url: references
        base_path: Base directory for resolving relative file paths
        max_context: Maximum total context injection size in bytes

    Returns:
        ContextReferenceResult with processed message and statistics
    """
    refs = parse_context_references(message)
    if not refs:
        return ContextReferenceResult(
            original=message,
            processed=message,
            references=[],
            loaded=0,
            failed=0,
        )

    loaded = 0
    failed = 0
    errors = []
    total_size = 0

    # Process references in reverse order to preserve positions
    result = message
    for ref in reversed(refs):
        content = ""
        success = False

        if ref.ref_type == "file":
            content, success = _load_file_content(ref.path, base_path)
        elif ref.ref_type == "url":
            content, success = _load_url_content(ref.path)

        if success:
            # Check total context budget
            if total_size + len(content) > max_context:
                errors.append(f"Context budget exceeded: cannot inject {ref.raw}")
                failed += 1
                continue

            total_size += len(content)
            loaded += 1

            # Wrap in context-ref tags
            tag = f'<context-ref {ref.ref_type}="{ref.path}">\n{content}\n</context-ref>'
            result = result[:ref.start] + tag + result[ref.end:]
        else:
            failed += 1
            errors.append(content)  # content contains error message

            # Replace with error tag
            tag = f'<context-ref-error {ref.ref_type}="{ref.path}">{content}</context-ref-error>'
            result = result[:ref.start] + tag + result[ref.end:]

    return ContextReferenceResult(
        original=message,
        processed=result,
        references=refs,
        loaded=loaded,
        failed=failed,
        errors=errors,
    )