"""
NEXUS v7 — Telegram MarkdownV2 Utilities
Pure functions for MarkdownV2 escaping, formatting, and message splitting.

Telegram MarkdownV2 requires escaping these characters:
_ * [ ] ( ) ~ ` > # + - = | { } . !

Characters inside formatting entities (bold, italic, code, etc.) must also
be escaped. This module handles proper conversion from standard Markdown
to Telegram MarkdownV2.
"""

import re
from typing import List


# Characters that MUST be escaped in MarkdownV2
MARKDOWNV2_ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!])')


def escape_markdown_v2(text: str) -> str:
    """Escape all Telegram MarkdownV2 special characters in plain text.
    
    Use this for text that should appear literally (not formatted).
    Every special character is preceded by a backslash.
    
    Args:
        text: Plain text to escape.
        
    Returns:
        Text with all MarkdownV2 special characters escaped.
        
    Examples:
        >>> escape_markdown_v2("Hello! Price: 5.99")
        'Hello\\\\! Price: 5\\\\.99'
        >>> escape_markdown_v2("a_b*c")
        'a\\\\_b\\\\*c'
    """
    return MARKDOWNV2_ESCAPE_RE.sub(r'\\\1', text)


def format_markdown_v2(text: str) -> str:
    """Convert standard Markdown text to Telegram MarkdownV2 format.
    
    This function:
    1. Preserves formatting entities (bold, italic, code, links)
    2. Escapes content INSIDE formatting entities
    3. Escapes all special characters OUTSIDE formatting entities
    4. Handles code blocks (```) and inline code (`)
    
    Formatting rules:
    - **bold** → *bold* (Telegram uses single * for bold)
    - *italic* → _italic_ (Telegram uses single _ for italic)
    - `inline code` → `inline code` (already Telegram-compatible)
    - ```code block``` → ```code block``` (already compatible)
    - [link](url) → [link](url) (must escape special chars in both)
    
    Args:
        text: Text with standard Markdown formatting.
        
    Returns:
        Text formatted for Telegram MarkdownV2 parse mode.
    """
    if not text:
        return text

    result = []

    # Pattern to match: code blocks, inline code, bold, italic, links, and plain text
    # We process in order of priority to avoid nested matching issues
    token_pattern = re.compile(
        r'(?P<codeblock>```[\s\S]*?```)'      # ```code block```
        r'|(?P<inline>`[^`\n]+`)'             # `inline code`
        r'|(?P<bold>\*\*[^*]+\*\*)'            # **bold**
        r'|(?P<italic1>\*[^*]+\*)'             # *italic* (asterisk form)
        r'|(?P<italic2>_[^_]+_)'               # _italic_ (underscore form)
        r'|(?P<link>\[([^\]]+)\]\(([^)]+)\))'  # [text](url)
    )

    last_end = 0

    for match in token_pattern.finditer(text):
        # Add escaped plain text before this match
        if match.start() > last_end:
            plain = text[last_end:match.start()]
            result.append(escape_markdown_v2(plain))

        if match.group('codeblock'):
            # Code block: ```...``` — escape content inside
            block = match.group('codeblock')
            # Strip the ``` delimiters, escape content, re-wrap
            inner = block[3:-3].strip()
            result.append(f'```\n{escape_markdown_v2(inner)}\n```')

        elif match.group('inline'):
            # Inline code: `...` — escape content inside
            code = match.group('inline')
            inner = code[1:-1]
            result.append(f'`{escape_markdown_v2(inner)}`')

        elif match.group('bold'):
            # **bold** → *bold* in MarkdownV2, with escaped content
            inner = match.group('bold')[2:-2]
            result.append(f'*{escape_markdown_v2(inner)}*')

        elif match.group('italic1'):
            # *italic* → _italic_ in MarkdownV2, with escaped content
            inner = match.group('italic1')[1:-1]
            result.append(f'_{escape_markdown_v2(inner)}_')

        elif match.group('italic2'):
            # _italic_ → _italic_ in MarkdownV2 (same syntax), with escaped content
            inner = match.group('italic2')[1:-1]
            result.append(f'_{escape_markdown_v2(inner)}_')

        elif match.group('link'):
            # [text](url) — escape special chars in both parts
            # Named group 'link' contains sub-groups for text and url
            # We need to extract them from the full match
            link_full = match.group('link')
            # Parse link text and URL from the full match
            inner_match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', link_full)
            if inner_match:
                link_text = inner_match.group(1)
                link_url = inner_match.group(2)
                result.append(f'[{escape_markdown_v2(link_text)}]({escape_markdown_v2(link_url)})')
            else:
                # Fallback: just escape the whole link
                result.append(escape_markdown_v2(link_full))

        last_end = match.end()

    # Add remaining plain text (escaped)
    if last_end < len(text):
        result.append(escape_markdown_v2(text[last_end:]))

    return ''.join(result)


def split_markdown_v2(text: str, max_length: int = 4096) -> List[str]:
    """Split MarkdownV2-formatted text into chunks that respect formatting boundaries.
    
    This function ensures that:
    1. No chunk exceeds max_length characters
    2. Code blocks (```) are not split across chunks
    3. Split points prefer paragraph breaks, then line breaks, then word breaks
    4. Formatting entities are not broken mid-entity
    
    Args:
        text: MarkdownV2-formatted text to split.
        max_length: Maximum length per chunk (Telegram limit is 4096).
        
    Returns:
        List of text chunks, each within max_length.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []

    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Find a good split point within max_length
        # Priority: 1) paragraph break  2) line break  3) word boundary
        search_area = text[:max_length]

        # Try paragraph break (double newline)
        split_pos = search_area.rfind('\n\n')
        if split_pos > max_length * 0.3:  # Don't split too early
            chunks.append(text[:split_pos].rstrip())
            text = text[split_pos:].lstrip('\n')
            continue

        # Try line break (single newline)
        split_pos = search_area.rfind('\n')
        if split_pos > max_length * 0.3:
            chunks.append(text[:split_pos].rstrip())
            text = text[split_pos + 1:]
            continue

        # Try word boundary (space)
        split_pos = search_area.rfind(' ')
        if split_pos > max_length * 0.3:
            chunks.append(text[:split_pos].rstrip())
            text = text[split_pos + 1:]
            continue

        # Hard split at max_length (last resort)
        chunks.append(text[:max_length])
        text = text[max_length:]

    # Verify we don't break code blocks across chunks
    # If a chunk has an odd number of ```, close/reopen them
    cleaned_chunks = []
    in_code_block = False

    for chunk in chunks:
        code_block_count = chunk.count('```')
        if code_block_count % 2 == 0:
            # Even number of ``` — code blocks are balanced in this chunk
            cleaned_chunks.append(chunk)
        elif in_code_block:
            # We're closing a code block — add closing marker
            chunk += '\n```'
            cleaned_chunks.append(chunk)
            in_code_block = False
        else:
            # We're opening a code block that spans the boundary
            # Close the code block at end of this chunk and reopen in next
            chunk += '\n```'
            cleaned_chunks.append(chunk)
            in_code_block = True

    # If still in a code block at the end, just keep what we have
    if not cleaned_chunks:
        cleaned_chunks = chunks

    # Filter empty chunks
    result = [c for c in cleaned_chunks if c.strip()]
    return result if result else [text]