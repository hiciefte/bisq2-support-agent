"""Tests for centralized error message constants.

TDD Step 3 (RED): These tests define the expected behavior of the error
messages before implementation exists.
"""

from app.prompts import error_messages


class TestErrorMessages:
    """Tests for error message constants."""

    def test_all_constants_are_nonempty_strings(self):
        """Every error constant must be a non-empty string."""
        constants = [
            error_messages.INSUFFICIENT_INFO,
            error_messages.NOT_INITIALIZED,
            error_messages.QUERY_ERROR,
            error_messages.NO_QUESTION,
            error_messages.GENERATION_FAILED,
            error_messages.TECHNICAL_ERROR,
        ]
        for msg in constants:
            assert isinstance(msg, str), f"Expected str, got {type(msg)}"
            assert len(msg) > 0, "Error message must not be empty"

    def test_no_duplicate_messages(self):
        """All error messages must be unique."""
        constants = [
            error_messages.INSUFFICIENT_INFO,
            error_messages.NOT_INITIALIZED,
            error_messages.QUERY_ERROR,
            error_messages.NO_QUESTION,
            error_messages.GENERATION_FAILED,
            error_messages.TECHNICAL_ERROR,
        ]
        assert len(set(constants)) == len(constants), "Duplicate error messages found"

    def test_no_messages_start_with_i_apologize(self):
        """No error message should use corporate-drone 'I apologize' phrasing."""
        constants = [
            error_messages.INSUFFICIENT_INFO,
            error_messages.NOT_INITIALIZED,
            error_messages.QUERY_ERROR,
            error_messages.NO_QUESTION,
            error_messages.GENERATION_FAILED,
            error_messages.TECHNICAL_ERROR,
        ]
        for msg in constants:
            assert not msg.lower().startswith(
                "i apologize"
            ), f"Message starts with 'I apologize': {msg[:50]}"
            assert (
                "i apologize" not in msg.lower()
            ), f"Message contains 'I apologize': {msg[:50]}"

    def test_insufficient_info_mentions_human_support(self):
        """INSUFFICIENT_INFO should direct users to human support."""
        msg = error_messages.INSUFFICIENT_INFO
        assert "human" in msg.lower() or "support" in msg.lower()

    def test_not_initialized_suggests_retry(self):
        """NOT_INITIALIZED should suggest trying again."""
        msg = error_messages.NOT_INITIALIZED
        assert "again" in msg.lower() or "moment" in msg.lower()

    def test_all_expected_constants_importable(self):
        """All six expected constants must be importable from error_messages."""
        expected = [
            "INSUFFICIENT_INFO",
            "NOT_INITIALIZED",
            "QUERY_ERROR",
            "NO_QUESTION",
            "GENERATION_FAILED",
            "TECHNICAL_ERROR",
        ]
        for name in expected:
            assert hasattr(error_messages, name), f"Missing constant: {name}"
