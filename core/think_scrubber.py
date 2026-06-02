"""
NEXUS Think Scrubber — Strip thinking/reasoning blocks from model output.

Removes <think>, <thinking>, <reasoning>, <reflection>, <chain-of-thought>,
and <scratchpad> blocks that reasoning models (DeepSeek, QwQ, etc.) produce
before their final answer. These blocks should not appear in Telegram messages.

Inspired by Hermes Agent's think_scrubber.py, adapted for NEXUS.
"""

import re
from typing import Tuple


# Thinking block patterns
THINK_TAG_PATTERN = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
THINKING_TAG_PATTERN = re.compile(r"<thinking\b[^>]*>.*?</thinking\s*>", re.DOTALL | re.IGNORECASE)
REASONING_TAG_PATTERN = re.compile(r"<reasoning\b[^>]*>.*?</reasoning\s*>", re.DOTALL | re.IGNORECASE)
REFLECTION_TAG_PATTERN = re.compile(r"<reflection\b[^>]*>.*?</reflection\s*>", re.DOTALL | re.IGNORECASE)
COT_TAG_PATTERN = re.compile(r"<chain-of-thought\b[^>]*>.*?</chain-of-thought\s*>", re.DOTALL | re.IGNORECASE)
SCRATCHPAD_TAG_PATTERN = re.compile(r"<scratchpad\b[^>]*>.*?</scratchpad\s*>", re.DOTALL | re.IGNORECASE)

ALL_THINKING_PATTERNS = [
    THINK_TAG_PATTERN, THINKING_TAG_PATTERN, REASONING_TAG_PATTERN,
    REFLECTION_TAG_PATTERN, COT_TAG_PATTERN, SCRATCHPAD_TAG_PATTERN,
]

# Line-by-line thinking markers
LINE_THINKING_PREFIXES = [
    r"^\s*\x{1F4AD}\s*", r"^\s*\[Thinking\]\s*", r"^\s*\[think\]\s*",
    r"^\s*\[reasoning\]\s*", r"^\s*>\s*think:\s*",
]
LINE_THINKING_PATTERN = re.compile(
    r"(?:^\s*\U0001F4AD\s*|^\s*\[Thinking\]\s*|^\s*\[think\]\s*|^\s*\[reasoning\]\s*|^\s*>\s*think:\s*)",
    re.MULTILINE | re.IGNORECASE,
)


def scrub_thinking(text: str, keep_marker: bool = False) -> str:
    """Remove all thinking/reasoning blocks from model output."""
    if not text:
        return text

    result = text
    for pattern in ALL_THINKING_PATTERNS:
        result = pattern.sub("\u2728" if keep_marker else "", result)

    result = LINE_THINKING_PATTERN.sub("", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def has_thinking_blocks(text: str) -> bool:
    """Check if text contains any thinking/reasoning blocks."""
    if not text:
        return False
    return any(p.search(text) for p in ALL_THINKING_PATTERNS) or bool(LINE_THINKING_PATTERN.search(text))


def extract_thinking(text: str) -> Tuple[str, str]:
    """Extract thinking content separately from final answer."""
    if not text:
        return "", text

    thinking_parts = []
    for pattern in ALL_THINKING_PATTERNS:
        for match in pattern.finditer(text):
            thinking_parts.append(match.group(0))

    for match in LINE_THINKING_PATTERN.finditer(text):
        thinking_parts.append(match.group(0))

    thinking = "\n".join(thinking_parts) if thinking_parts else ""
    final = scrub_thinking(text)
    return thinking, final