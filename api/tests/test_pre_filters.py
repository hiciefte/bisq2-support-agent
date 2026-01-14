"""Unit tests for MessagePreFilter and related functionality."""

import pytest
from app.services.llm_extraction.pre_filters import (
    MessagePreFilter,
    SafeRegexMatcher,
    validate_message_input,
)


class TestMessagePreFilter:
    """Tests for MessagePreFilter class."""

    @pytest.fixture
    def pre_filter(self):
        """Create a MessagePreFilter instance."""
        return MessagePreFilter()

    # Test greeting filtering
    @pytest.mark.parametrize(
        "body,expected",
        [
            ("Hello everyone", True),
            ("Hi", True),
            ("Hey!", True),
            ("GM", True),
            ("gm", True),
            ("Good morning", True),
            ("Hello, I need help with my trade", False),  # Has content after greeting
            ("Hey, is anyone here?", False),  # Has question
        ],
    )
    def test_greeting_filter(self, pre_filter, body, expected):
        """Test that standalone greetings are filtered."""
        msg = {"body": body}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter == expected
        if expected:
            assert reason == "greeting"

    # Test acknowledgment filtering
    @pytest.mark.parametrize(
        "body,expected",
        [
            ("Thanks", True),
            ("Thank you", True),
            ("thx", True),
            ("OK", True),
            ("okay", True),
            ("Got it", True),
            ("Yes", True),
            ("No", True),
            ("Thanks for the help with my issue", False),  # Has context
        ],
    )
    def test_acknowledgment_filter(self, pre_filter, body, expected):
        """Test that standalone acknowledgments are filtered."""
        msg = {"body": body}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter == expected
        if expected:
            assert reason == "acknowledgment"

    # Test emoji filtering
    @pytest.mark.parametrize(
        "body,expected_filter,expected_reason",
        [
            ("👍", True, "emoji_only"),
            ("🎉", True, "emoji_only"),
            ("👍👍👍", True, "emoji_only"),
            ("👍 thanks!", True, "too_short"),  # Only 9 chars, no question mark
            ("Nice work! 🎉", False, None),  # Has text, >= 10 chars
            (
                "👍 thanks for the detailed help!",
                False,
                None,
            ),  # Emoji + long text passes
        ],
    )
    def test_emoji_only_filter(
        self, pre_filter, body, expected_filter, expected_reason
    ):
        """Test that emoji-only messages are filtered."""
        msg = {"body": body}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter == expected_filter
        if expected_filter and expected_reason:
            assert reason == expected_reason

    # Test system message filtering
    @pytest.mark.parametrize(
        "body",
        [
            "[User] has joined",
            "[Admin] has left",
            "User invited Admin to the room",
            "Someone changed the room name",
        ],
    )
    def test_system_message_filter(self, pre_filter, body):
        """Test that system messages are filtered."""
        msg = {"body": body}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter is True
        assert "system" in reason

    # Test URL-only filtering
    def test_url_only_filter(self, pre_filter):
        """Test that URL-only messages are filtered."""
        msg = {"body": "https://bisq.network/docs"}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter is True
        assert reason == "url_only"

    def test_url_with_context_passes(self, pre_filter):
        """Test that URLs with context are not filtered."""
        msg = {
            "body": "Check this out: https://bisq.network/docs - is this the right page?"
        }
        should_filter, _ = pre_filter.should_filter(msg)
        assert should_filter is False

    # Test short message filtering
    def test_short_message_filter(self, pre_filter):
        """Test that very short messages without question marks are filtered."""
        msg = {"body": "asdf xyz"}  # Short, non-greeting message
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter is True
        assert reason == "too_short"

    def test_short_message_with_question_passes(self, pre_filter):
        """Test that short messages with question marks pass."""
        msg = {"body": "help?"}
        should_filter, _ = pre_filter.should_filter(msg)
        assert should_filter is False

    # Test empty message filtering
    def test_empty_message_filter(self, pre_filter):
        """Test that empty messages are filtered."""
        msg = {"body": ""}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter is True
        assert reason == "empty_message"

    def test_whitespace_only_filter(self, pre_filter):
        """Test that whitespace-only messages are filtered."""
        msg = {"body": "   "}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter is True
        assert reason == "empty_message"

    # Test punctuation-only filtering
    def test_punctuation_only_filter(self, pre_filter):
        """Test that punctuation-only messages are filtered."""
        msg = {"body": "!!!"}
        should_filter, reason = pre_filter.should_filter(msg)
        assert should_filter is True
        assert reason == "punctuation_only"

    # Test valid questions pass
    @pytest.mark.parametrize(
        "body",
        [
            "I'm having trouble with my trade, the BTC hasn't arrived",
            "How do I complete a trade in Bisq?",
            "Can someone help me with mediation?",
            "Is there a way to get a refund?",
            "My trade is stuck, what should I do?",
            "The other trader hasn't responded for 3 days",
        ],
    )
    def test_valid_question_passes(self, pre_filter, body):
        """Test that valid questions are not filtered."""
        msg = {"body": body}
        should_filter, _ = pre_filter.should_filter(msg)
        assert should_filter is False

    # Test batch filtering
    def test_filter_messages_batch(self, pre_filter):
        """Test batch filtering of messages."""
        messages = [
            {"body": "Hello"},
            {"body": "I need help with Bisq"},
            {"body": "👍"},
            {"body": "How do I start a trade?"},
        ]
        passed, filtered = pre_filter.filter_messages(messages)
        assert len(passed) == 2
        assert len(filtered) == 2
        assert passed[0]["body"] == "I need help with Bisq"
        assert passed[1]["body"] == "How do I start a trade?"


class TestValidateMessageInput:
    """Tests for validate_message_input function."""

    def test_normal_message(self):
        """Test that normal messages pass through unchanged."""
        msg = {"body": "Hello, this is a test message"}
        result = validate_message_input(msg)
        assert result["body"] == "Hello, this is a test message"

    def test_null_byte_removal(self):
        """Test that null bytes are removed from messages."""
        msg = {"body": "Hello\x00World"}
        result = validate_message_input(msg)
        assert result["body"] == "HelloWorld"
        assert "\x00" not in result["body"]

    def test_unicode_preservation(self):
        """Test that valid Unicode is preserved."""
        msg = {"body": "Hello 👋 World 🌍"}
        result = validate_message_input(msg)
        assert result["body"] == "Hello 👋 World 🌍"


class TestSafeRegexMatcher:
    """Tests for SafeRegexMatcher class."""

    def test_basic_matching(self):
        """Test basic pattern matching."""
        patterns = [
            (r"^hello$", "greeting"),
            (r"^thanks$", "acknowledgment"),
        ]
        matcher = SafeRegexMatcher(patterns)

        matched, reason = matcher.safe_match("hello")
        assert matched is True
        assert reason == "greeting"

        matched, reason = matcher.safe_match("thanks")
        assert matched is True
        assert reason == "acknowledgment"

        matched, reason = matcher.safe_match("something else")
        assert matched is False
        assert reason == ""

    def test_case_insensitivity(self):
        """Test that matching is case insensitive."""
        patterns = [(r"^hello$", "greeting")]
        matcher = SafeRegexMatcher(patterns)

        matched, _ = matcher.safe_match("HELLO")
        assert matched is True

        matched, _ = matcher.safe_match("Hello")
        assert matched is True

    def test_input_truncation(self):
        """Test that very long inputs are truncated."""
        patterns = [(r"test", "found")]
        matcher = SafeRegexMatcher(patterns, max_input_length=100)

        # Create a long string with "test" at position 50
        long_input = "a" * 50 + "test" + "a" * 100
        matched, _ = matcher.safe_match(long_input)
        assert matched is True

        # Create a long string with "test" beyond the truncation limit
        long_input = "a" * 110 + "test"
        matched, _ = matcher.safe_match(long_input)
        assert matched is False  # "test" is beyond truncation limit

    def test_invalid_pattern_handling(self):
        """Test that invalid regex patterns are handled gracefully."""
        patterns = [
            (r"[", "broken"),  # Invalid regex
            (r"^valid$", "valid"),
        ]
        # Should not raise, invalid patterns are skipped
        matcher = SafeRegexMatcher(patterns)
        matched, reason = matcher.safe_match("valid")
        assert matched is True
        assert reason == "valid"
