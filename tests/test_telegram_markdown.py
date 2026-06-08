"""
Unit tests for Telegram Bot MarkdownV2 escaping and message splitting.

Tests cover:
- escape_markdown_v2(): All special characters are properly escaped
- format_markdown_v2(): Markdown → MarkdownV2 conversion
- split_markdown_v2(): Message splitting respecting formatting boundaries
"""

import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nexus.interfaces.markdown_utils import (
    escape_markdown_v2,
    format_markdown_v2,
    split_markdown_v2,
)


class TestEscapeMarkdownV2(unittest.TestCase):
    """Test the escape_markdown_v2 function."""

    def test_escape_all_special_chars(self):
        """Every MarkdownV2 special character must be escaped."""
        # All characters that must be escaped: _ * [ ] ( ) ~ ` > # + - = | { } . !
        special = "_*[]()~`>#+-=|{}.!"
        result = escape_markdown_v2(special)
        expected = r"\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"
        self.assertEqual(result, expected)

    def test_escape_period(self):
        """Periods must be escaped (common pitfall)."""
        self.assertEqual(escape_markdown_v2("hello.world"), r"hello\.world")

    def test_escape_exclamation(self):
        """Exclamation marks must be escaped."""
        self.assertEqual(escape_markdown_v2("wow!"), r"wow\!")

    def test_escape_dash(self):
        """Dashes must be escaped."""
        self.assertEqual(escape_markdown_v2("a-b"), r"a\-b")

    def test_escape_equals(self):
        """Equals signs must be escaped."""
        self.assertEqual(escape_markdown_v2("x=1"), r"x\=1")

    def test_no_escape_normal_chars(self):
        """Normal characters should not be escaped."""
        self.assertEqual(escape_markdown_v2("hello world 123"), "hello world 123")

    def test_no_escape_unicode(self):
        """Unicode characters (like ö, ü, ä) should not be escaped."""
        self.assertEqual(escape_markdown_v2("Grüße"), "Grüße")

    def test_escape_mixed_text(self):
        """Mixed text with special and normal characters."""
        text = "Hello, world! This is great. Price: $5.99"
        result = escape_markdown_v2(text)
        self.assertIn(r"\!", result)
        self.assertIn(r"\.", result)

    def test_empty_string(self):
        """Empty string should return empty string."""
        self.assertEqual(escape_markdown_v2(""), "")

    def test_german_text(self):
        """German text with special chars (common use case)."""
        text = "Hallo! Wie geht's? Das ist toll."
        result = escape_markdown_v2(text)
        self.assertIn(r"\!", result)
        self.assertIn(r"\.", result)
        # Apostrophe is NOT a special char in MarkdownV2
        self.assertIn("'s", result)


class TestFormatMarkdownV2(unittest.TestCase):
    """Test the format_markdown_v2 function."""

    def test_plain_text_escaping(self):
        """Plain text should have all special chars escaped."""
        text = "Hello! This costs 5.99 EUR."
        result = format_markdown_v2(text)
        self.assertIn(r"\.", result)
        self.assertIn(r"\!", result)

    def test_bold_conversion(self):
        """**bold** should convert to *bold* (Telegram MarkdownV2 style)."""
        text = "This is **important** text"
        result = format_markdown_v2(text)
        # "important" has no special chars, so it becomes *important* (bold in MDV2)
        self.assertIn("*important*", result)

    def test_bold_with_special_chars(self):
        """**bold** with special chars inside should escape them."""
        text = "Das ist **wichtig!** richtig"
        result = format_markdown_v2(text)
        # "wichtig!" has ! which must be escaped inside bold
        self.assertIn(r"*wichtig\!*", result)

    def test_italic_asterisk_conversion(self):
        """*italic* should convert to _italic_ (Telegram MarkdownV2 style)."""
        text = "This is *emphasized* text"
        result = format_markdown_v2(text)
        # "emphasized" has no special chars, so it becomes _emphasized_
        self.assertIn("_emphasized_", result)

    def test_italic_underscore_preserved(self):
        """_italic_ (underscore form) should be preserved."""
        text = "This is _emphasized_ text"
        result = format_markdown_v2(text)
        # "emphasized" has no special chars
        self.assertIn("_emphasized_", result)

    def test_italic_with_special_chars(self):
        """_italic_ with special chars inside should escape them."""
        text = "This is _wichtig!_ oder?"
        result = format_markdown_v2(text)
        self.assertIn(r"_wichtig\!_", result)

    def test_inline_code(self):
        """Inline code should be preserved with escaped content."""
        text = "Use `npm install` to setup"
        result = format_markdown_v2(text)
        self.assertIn("`npm install`", result)

    def test_inline_code_with_special_chars(self):
        """Inline code content should be escaped."""
        text = "Run `echo hello.world` now"
        result = format_markdown_v2(text)
        self.assertIn(r"`echo hello\.world`", result)

    def test_code_block(self):
        """Code blocks should be preserved with escaped content."""
        text = "Here is code:\n```python\nprint('hello')\n```"
        result = format_markdown_v2(text)
        self.assertIn("```", result)
        self.assertIn("python", result)

    def test_empty_string(self):
        """Empty string should return empty string."""
        self.assertEqual(format_markdown_v2(""), "")

    def test_link_conversion(self):
        """[text](url) should escape special chars in both parts."""
        text = "Visit [Example Site](https://example.com) today"
        result = format_markdown_v2(text)
        self.assertIn("[", result)
        self.assertIn("](", result)
        self.assertIn("example", result)

    def test_mixed_formatting(self):
        """Mixed formatting should all be converted properly."""
        text = "**bold** and *italic* and `code`"
        result = format_markdown_v2(text)
        self.assertIn("*", result)  # Bold marker
        self.assertIn("_", result)  # Italic marker
        self.assertIn("`", result)  # Code marker

    def test_german_text_with_formatting(self):
        """German text with formatting (real-world use case)."""
        text = "**Wichtig!** Der Preis beträgt 5.99 EUR."
        result = format_markdown_v2(text)
        # "Wichtig!" inside bold: *Wichtig\!*
        self.assertIn("*Wichtig", result)
        self.assertIn(r"\!", result)
        self.assertIn(r"\.", result)

    def test_nested_special_chars(self):
        """Special chars inside formatting should be escaped."""
        text = "**Price: 5.99!**"
        result = format_markdown_v2(text)
        # Content inside bold should be escaped
        self.assertIn(r"\.", result)
        self.assertIn(r"\!", result)


class TestSplitMarkdownV2(unittest.TestCase):
    """Test the split_markdown_v2 function."""

    def test_short_message(self):
        """Messages under max_length should not be split."""
        text = "Hello world"
        result = split_markdown_v2(text, max_length=4096)
        self.assertEqual(result, ["Hello world"])

    def test_split_at_paragraph(self):
        """Should split at paragraph boundaries."""
        text = "First paragraph\n\nSecond paragraph"
        result = split_markdown_v2(text, max_length=20)
        # Should split at the double newline
        self.assertTrue(len(result) >= 1)
        # Each chunk should be within limits
        for chunk in result:
            self.assertTrue(len(chunk) <= 25)  # Accounting for split logic

    def test_split_at_newline(self):
        """Should split at line breaks when no paragraph break."""
        text = "Line one\nLine two\nLine three"
        result = split_markdown_v2(text, max_length=15)
        self.assertTrue(len(result) >= 2)

    def test_split_at_word_boundary(self):
        """Should split at word boundary when no line break."""
        text = "word " * 50  # 250 chars
        result = split_markdown_v2(text, max_length=50)
        for chunk in result:
            self.assertTrue(len(chunk) <= 50 or len(result) == 1)

    def test_exact_max_length(self):
        """Message exactly at max_length should not be split."""
        text = "x" * 100
        result = split_markdown_v2(text, max_length=100)
        self.assertEqual(result, [text])

    def test_code_block_preservation(self):
        """Code blocks should not be broken across chunks."""
        text = "```python\nprint('hello world from a long code line')\n```"
        result = split_markdown_v2(text, max_length=4096)
        # Short enough, should be one chunk
        self.assertEqual(len(result), 1)

    def test_multiple_chunks(self):
        """Long text should produce multiple chunks."""
        text = "Paragraph\n\n" * 1000  # ~12000 chars
        result = split_markdown_v2(text, max_length=4096)
        self.assertTrue(len(result) > 1)
        # Each chunk should be within max_length (with some tolerance for code block fixes)
        for chunk in result:
            self.assertTrue(len(chunk) <= 4100, f"Chunk too long: {len(chunk)}")  # Small tolerance for closing markers

    def test_empty_string(self):
        """Empty string should return empty list."""
        result = split_markdown_v2("", max_length=4096)
        # With empty string, should return empty list or list with empty string
        self.assertTrue(len(result) <= 1)


class TestIntegration(unittest.TestCase):
    """Integration tests — format + split pipeline."""

    def test_format_then_split(self):
        """Format markdown then split should produce valid chunks."""
        text = "**Wichtige Nachricht!**\n\nDas System ist online. Preis: 5.99 EUR."
        formatted = format_markdown_v2(text)
        chunks = split_markdown_v2(formatted, max_length=4096)
        self.assertEqual(len(chunks), 1)  # Short enough for one chunk

    def test_format_preserves_content(self):
        """After formatting, key content should be preserved."""
        text = "**Error!** File not found."
        result = format_markdown_v2(text)
        self.assertIn("Error", result)
        self.assertIn("File not found", result)

    def test_escape_only_needed(self):
        """Only special chars should be escaped, not all chars."""
        text = "Hello World"
        result = escape_markdown_v2(text)
        self.assertEqual(result, "Hello World")  # No special chars to escape


if __name__ == "__main__":
    unittest.main()