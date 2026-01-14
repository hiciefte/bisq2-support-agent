"""Unit tests for MessageNormalizer class."""

import pytest
from app.services.llm_extraction.pre_filters import MessageNormalizer


class TestMessageNormalizer:
    """Tests for MessageNormalizer class."""

    @pytest.fixture
    def normalizer(self):
        """Create a MessageNormalizer instance."""
        return MessageNormalizer()

    # Test markdown removal
    def test_bold_markdown_removal(self, normalizer):
        """Test that bold markdown formatting is removed."""
        msg = {"body": "This is **bold** text"}
        result = normalizer.normalize(msg)
        assert result["body"] == "This is bold text"

    def test_italic_markdown_removal(self, normalizer):
        """Test that italic markdown formatting is removed."""
        msg = {"body": "This is *italic* text"}
        result = normalizer.normalize(msg)
        assert result["body"] == "This is italic text"

    def test_inline_code_removal(self, normalizer):
        """Test that inline code formatting is removed."""
        msg = {"body": "Run the `bisq` command"}
        result = normalizer.normalize(msg)
        assert result["body"] == "Run the bisq command"

    def test_code_block_removal(self, normalizer):
        """Test that code blocks are removed entirely."""
        msg = {
            "body": "Here is some code:\n```python\nprint('hello')\n```\nEnd of code."
        }
        result = normalizer.normalize(msg)
        assert "```" not in result["body"]
        assert "print" not in result["body"]
        assert "End of code." in result["body"]

    def test_nested_markdown(self, normalizer):
        """Test handling of nested markdown."""
        msg = {"body": "This is **bold and *italic* inside**"}
        result = normalizer.normalize(msg)
        # After processing, should have stripped formatting
        assert "**" not in result["body"]
        assert "*" not in result["body"]

    # Test whitespace normalization
    def test_multiple_spaces_normalized(self, normalizer):
        """Test that multiple spaces are collapsed to single space."""
        msg = {"body": "Hello    world    test"}
        result = normalizer.normalize(msg)
        assert result["body"] == "Hello world test"

    def test_newlines_normalized(self, normalizer):
        """Test that newlines are converted to spaces."""
        msg = {"body": "Hello\nworld\ntest"}
        result = normalizer.normalize(msg)
        assert result["body"] == "Hello world test"

    def test_tabs_normalized(self, normalizer):
        """Test that tabs are converted to spaces."""
        msg = {"body": "Hello\tworld\ttest"}
        result = normalizer.normalize(msg)
        assert result["body"] == "Hello world test"

    def test_leading_trailing_whitespace_removed(self, normalizer):
        """Test that leading/trailing whitespace is removed."""
        msg = {"body": "  Hello world  "}
        result = normalizer.normalize(msg)
        assert result["body"] == "Hello world"

    # Test quote normalization
    def test_smart_double_quotes_normalized(self, normalizer):
        """Test that smart double quotes are normalized to ASCII."""
        # Use escaped unicode to avoid Black parsing issues
        msg = {"body": "\u201cHello\u201d \u201cWorld\u201d"}
        result = normalizer.normalize(msg)
        assert result["body"] == '"Hello" "World"'
        assert "\u201c" not in result["body"]
        assert "\u201d" not in result["body"]

    def test_smart_single_quotes_normalized(self, normalizer):
        """Test that smart single quotes are normalized to ASCII."""
        # Use escaped unicode to avoid Black parsing issues
        msg = {"body": "\u2018Hello\u2019 \u2018World\u2019"}
        result = normalizer.normalize(msg)
        assert result["body"] == "'Hello' 'World'"
        assert "\u2018" not in result["body"]
        assert "\u2019" not in result["body"]

    # Test combined normalization
    def test_full_normalization(self, normalizer):
        """Test full normalization with multiple transformations."""
        msg = {
            "body": "  **Bold** and *italic*   with   `code` and \u201csmart quotes\u201d\n\n"
        }
        result = normalizer.normalize(msg)
        assert "**" not in result["body"]
        assert "*" not in result["body"]
        assert "`" not in result["body"]
        assert "\u201c" not in result["body"]
        assert result["body"] == 'Bold and italic with code and "smart quotes"'

    # Test edge cases
    def test_empty_message(self, normalizer):
        """Test normalization of empty message."""
        msg = {"body": ""}
        result = normalizer.normalize(msg)
        assert result["body"] == ""

    def test_whitespace_only_message(self, normalizer):
        """Test normalization of whitespace-only message."""
        msg = {"body": "   \n\t   "}
        result = normalizer.normalize(msg)
        assert result["body"] == ""

    def test_preserves_other_fields(self, normalizer):
        """Test that other message fields are preserved."""
        msg = {
            "body": "Hello **world**",
            "sender": "user123",
            "timestamp": 1234567890,
        }
        result = normalizer.normalize(msg)
        assert result["sender"] == "user123"
        assert result["timestamp"] == 1234567890
        assert result["body"] == "Hello world"

    # Test batch normalization
    def test_normalize_batch(self, normalizer):
        """Test batch normalization of multiple messages."""
        messages = [
            {"body": "**Bold** text"},
            {"body": "*Italic* text"},
            {"body": "Normal text"},
        ]
        results = normalizer.normalize_batch(messages)
        assert len(results) == 3
        assert results[0]["body"] == "Bold text"
        assert results[1]["body"] == "Italic text"
        assert results[2]["body"] == "Normal text"

    def test_normalize_batch_empty(self, normalizer):
        """Test batch normalization with empty list."""
        messages = []
        results = normalizer.normalize_batch(messages)
        assert len(results) == 0

    # Test real-world examples
    @pytest.mark.parametrize(
        "input_body,expected",
        [
            # Matrix-style formatting
            ("User said: **important** point", "User said: important point"),
            # Multiple formatting types
            ("**Bold** and *italic* and `code`", "Bold and italic and code"),
            # Smart quotes from copy-paste (using unicode escapes)
            (
                "He said \u201chello\u201d to \u2018everyone\u2019",
                "He said \"hello\" to 'everyone'",
            ),
            # Excessive whitespace
            ("Hello     world\n\n\ntest", "Hello world test"),
            # Code blocks
            ("Before ```code``` after", "Before after"),
        ],
    )
    def test_real_world_examples(self, normalizer, input_body, expected):
        """Test normalization with real-world examples."""
        msg = {"body": input_body}
        result = normalizer.normalize(msg)
        assert result["body"] == expected
