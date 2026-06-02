"""
NEXUS Message Sanitization — Clean LLM output before processing or display.

Strips think tags, reformats tool-call blocks, removes system injection
artifacts, and normalizes whitespace. Prepares model output for clean
presentation in Telegram, CLI, or conversation history.

Inspired by Hermes Agent's message_sanitization.py, adapted for NEXUS.
"""

import re
from typing import Optional


# ── Patterns to strip ────────────────────────────────────────────────

# System prompt injection artifacts
SYSTEM_INJECTION_PATTERN = re.compile(
    r"<system\s*>.*?</system\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Tool call artifacts (malformed XML-like blocks)
MALFORMED_TOOL_CALL_PATTERN = re.compile(
    r"<tool_call\s*>.*?</tool_call\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Function call artifacts (some models emit these)
FUNCTION_CALL_PATTERN = re.compile(
    r"<function_call\s*>.*?</function_call\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Assistant role markers
ASSISTANT_MARKER_PATTERN = re.compile(
    r"<assistant\s*>.*?</assistant\s*>",
    re.DOTALL | re.IGNORECASE,
)

# Stray XML tags that models sometimes emit
STRAY_XML_PATTERN = re.compile(
    r"</?(?:response|output|result|answer|reply|message|content|text)\b[^>]*>",
    re.IGNORECASE,
)

# Empty code blocks
EMPTY_CODE_BLOCK_PATTERN = re.compile(
    r"```\s*\n\s*```",
    re.MULTILINE,
)

# Trailing whitespace on lines
TRAILING_WHITESPACE_PATTERN = re.compile(
    r"[ \t]+\n",
    re.MULTILINE,
)

# Multiple blank lines
EXCESSIVE_BLANK_LINES = re.compile(
    r"\n{4,}",
)

# Markdown artifacts from model output
STRAY_INLINE_CODE_MARKER = re.compile(
    r"(?<!`)`{3,}(?!`)",  # More than 3 backticks not in a block
)


def sanitize_message(
    text: str,
    strip_thinking: bool = True,
    strip_tool_artifacts: bool = True,
    strip_system_injection: bool = True,
    normalize_whitespace: bool = True,
    max_length: Optional[int] = None,
) -> str:
    """
    Sanitize LLM output for clean display.

    Args:
        text: Raw model output
        strip_thinking: Remove thinking/reasoning blocks
        strip_tool_artifacts: Remove malformed tool call blocks
        strip_system_injection: Remove system prompt injection artifacts
        normalize_whitespace: Clean up whitespace
        max_length: Truncate to this length (None = no truncation)

    Returns:
        Clean text ready for display or conversation history
    """
    if not text:
        return text

    result = text

    # 1. Strip thinking blocks
    if strip_thinking:
        from core.think_scrubber import scrub_thinking
        result = scrub_thinking(result)

    # 2. Strip system injection artifacts
    if strip_system_injection:
        result = SYSTEM_INJECTION_PATTERN.sub("", result)

    # 3. Strip tool call artifacts
    if strip_tool_artifacts:
        result = MALFORMED_TOOL_CALL_PATTERN.sub("", result)
        result = FUNCTION_CALL_PATTERN.sub("", result)
        result = ASSISTANT_MARKER_PATTERN.sub("", result)

    # 4. Strip stray XML tags
    result = STRAY_XML_PATTERN.sub("", result)

    # 5. Clean up empty code blocks
    result = EMPTY_CODE_BLOCK_PATTERN.sub("", result)

    # 6. Normalize whitespace
    if normalize_whitespace:
        result = TRAILING_WHITESPACE_PATTERN.sub("\n", result)
        result = EXCESSIVE_BLANK_LINES.sub("\n\n", result)

    # 7. Strip stray inline code markers
    result = STRAY_INLINE_CODE_MARKER.sub("```", result)

    # 8. Strip leading/trailing whitespace
    result = result.strip()

    # 9. Truncate if needed
    if max_length and len(result) > max_length:
        result = result[:max_length] + f"\n... [truncated, {len(result) - max_length} chars omitted]"

    return result


def sanitize_for_telegram(text: str) -> str:
    """
    Sanitize text specifically for Telegram display.

    More aggressive sanitization: strips thinking, tool artifacts,
    and truncates to Telegram's 4096 char message limit.
    """
    return sanitize_message(
        text,
        strip_thinking=True,
        strip_tool_artifacts=True,
        strip_system_injection=True,
        normalize_whitespace=True,
        max_length=3900,  # Leave room for Telegram formatting overhead
    )


def sanitize_for_conversation_history(text: str) -> str:
    """
    Sanitize text for inclusion in conversation history.

    Keeps tool call blocks intact (they may be valid) but strips
    thinking and system artifacts.
    """
    return sanitize_message(
        text,
        strip_thinking=True,
        strip_tool_artifacts=False,  # Keep tool calls for context
        strip_system_injection=True,
        normalize_whitespace=True,
        max_length=50000,  # Generous limit for history
    )


def sanitize_for_logging(text: str) -> str:
    """
    Sanitize text for logging — removes secrets but keeps structure.
    """
    from core.redact import redact_text
    text = sanitize_message(
        text,
        strip_thinking=True,
        strip_tool_artifacts=True,
        strip_system_injection=True,
        normalize_whitespace=True,
        max_length=10000,
    )
    return redact_text(text)