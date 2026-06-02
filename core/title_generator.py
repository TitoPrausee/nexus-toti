"""
NEXUS Title Generator — Generate concise conversation/document titles.

Uses lightweight heuristics and optional LLM calls to generate
descriptive titles from conversation content or user messages.

Inspired by Hermes Agent's title_generator.py, adapted for NEXUS.
"""

import re
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class TitleConfig:
    """Configuration for title generation."""
    max_length: int = 60
    min_length: int = 5
    style: str = "concise"     # "concise", "descriptive", "creative"
    language: str = "auto"      # "auto", "de", "en"
    include_emoji: bool = False


# ── Title Templates ───────────────────────────────────────────────────

TITLE_PATTERNS = [
    # Code-related
    (r"(?:debug|fix|solve|resolved?).*(?:bug|error|issue|problem)", "🐛 Bug-Fix"),
    (r"(?:implement|add|create|build).*(?:feature|function|module|component)", "✨ Feature"),
    (r"(?:refactor|clean|restructure|optimize|improve).*(?:code|module|system)", "🔧 Refactor"),
    (r"(?:test|unit.test|integration.test)", "🧪 Testing"),
    (r"(?:deploy|release|publish|ship)", "🚀 Deploy"),
    (r"(?:document|readme|docs|comment)", "📝 Documentation"),

    # Research-related
    (r"(?:research|investigate|analyze|study).*(?:topic|technology|framework)", "🔍 Research"),
    (r"(?:compare|evaluate|benchmark|review)", "📊 Comparison"),
    (r"(?:find|search|lookup).*(?:data|info|source)", "🔎 Search"),

    # Architecture
    (r"(?:architect|design|plan|blueprint).*(?:system|app|solution)", "🏗️ Architecture"),
    (r"(?:migrate|port|convert|transform)", "🔄 Migration"),
    (r"(?:security|vulnerability|audit|scan)", "🔒 Security"),

    # Chat/conversation
    (r"(?:hallo|hi|hey|moin|guten\s*morgen|guten\s*abend)", "💬 Chat"),
    (r"(?:hilfe|help|support|question|frage)", "❓ Frage"),
]


def generate_title(
    text: str,
    config: TitleConfig = None,
    model_hint: str = "",
) -> str:
    """
    Generate a concise title from text content.

    Uses heuristic pattern matching first, falls back to
    extracting key phrases if no pattern matches.

    Args:
        text: Input text (user message, conversation content, etc.)
        config: Title generation configuration
        model_hint: Optional model name for style hints

    Returns:
        A concise title string
    """
    if not text:
        return "Unbenannt"

    config = config or TitleConfig()

    # Clean input
    clean = text.strip()
    if len(clean) < config.min_length:
        return clean[:config.max_length]

    # 1. Try pattern matching
    for pattern, prefix in TITLE_PATTERNS:
        if re.search(pattern, clean, re.IGNORECASE):
            title = _extract_key_phrase(clean, config.max_length - len(prefix) - 1)
            if config.include_emoji:
                return f"{prefix} {title}"
            # Strip emoji from prefix
            prefix_clean = re.sub(r"[^\w\s-]", "", prefix).strip()
            return f"{prefix_clean}: {title}"

    # 2. No pattern matched — extract key phrase
    title = _extract_key_phrase(clean, config.max_length)

    # 3. Language detection hint
    if config.language == "de" or _is_german(clean):
        # Keep German titles as-is
        pass

    return title


def _extract_key_phrase(text: str, max_len: int = 60) -> str:
    """Extract the most important phrase from text."""
    # Take first meaningful sentence
    sentences = re.split(r'[.!?]\s+', text)
    if not sentences:
        return text[:max_len]

    first = sentences[0].strip()

    # Remove common greetings
    greetings = [
        r"^(?:hallo|hi|hey|moin|guten\s*\w+|please|bitte|kannst\s+du)\s*[,!?]?\s*",
        r"^(?:ich|wir|kannst\s+du|würdest\s+du|please|bitte)\s+",
    ]
    for greeting in greetings:
        first = re.sub(greeting, "", first, flags=re.IGNORECASE).strip()

    # Truncate to max length at word boundary
    if len(first) > max_len:
        truncated = first[:max_len]
        # Find last space within limit
        last_space = truncated.rfind(" ")
        if last_space > max_len // 2:
            truncated = truncated[:last_space]
        first = truncated.rstrip(".,;:") + "…"

    return first if first else text[:max_len]


def _is_german(text: str) -> bool:
    """Quick heuristic to detect German text."""
    german_words = {"und", "oder", "der", "die", "das", "ist", "ein", "eine",
                    "nicht", "mit", "für", "auf", "aus", "von", "zu", "im",
                    "den", "dem", "des", "sich", "auch", "noch", "nach"}
    words = set(text.lower().split())
    overlap = words & german_words
    return len(overlap) >= 2


def generate_conversation_title(
    first_message: str,
    second_message: str = "",
    config: TitleConfig = None,
) -> str:
    """
    Generate a title for a conversation based on the first exchange.

    Combines information from the first user message and
    (optionally) the assistant's first response.
    """
    config = config or TitleConfig()

    # Use the user message as the primary source
    title = generate_title(first_message, config)

    # If title is too generic and we have a second message, enrich it
    if len(title) < config.min_length and second_message:
        enriched = f"{first_message} — {second_message}"
        title = generate_title(enriched, config)

    return title