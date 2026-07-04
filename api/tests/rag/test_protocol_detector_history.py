"""Tests for chat-history version detection (review finding A1).

Covers word-boundary matching, negation handling, and switch-phrase handling
in ProtocolDetector._detect_version_in_history_content and its integration
with detect_version().
"""

import pytest
from app.services.rag.protocol_detector import ProtocolDetector


@pytest.fixture
def detector():
    return ProtocolDetector()


class TestHistoryPlainMentions:
    """Plain one-sided mentions keep their existing behavior."""

    def test_plain_bisq1_mention(self, detector):
        result = detector._detect_version_in_history_content("i am using bisq 1")
        assert result == ("Bisq 1", 0.80)

    def test_plain_bisq2_mention(self, detector):
        result = detector._detect_version_in_history_content("i am on bisq 2 now")
        assert result == ("Bisq 2", 0.80)

    def test_compact_mention_without_space(self, detector):
        result = detector._detect_version_in_history_content("bisq1 keeps crashing")
        assert result == ("Bisq 1", 0.80)

    def test_word_boundary_prevents_partial_match(self, detector):
        """'bisq123' must not be read as a Bisq 1 mention."""
        result = detector._detect_version_in_history_content(
            "my username is bisq123 on the forum"
        )
        assert result is None

    def test_mixed_mentions_without_switch_stay_ambiguous(self, detector):
        result = detector._detect_version_in_history_content(
            "i keep comparing bisq 1 and bisq 2"
        )
        assert result is None


class TestHistoryNegation:
    """Negated mentions must not count as positive signals."""

    def test_not_on_bisq1_is_not_a_bisq1_signal(self, detector):
        result = detector._detect_version_in_history_content("i'm not on bisq 1")
        assert result is not None
        version, confidence = result
        assert version == "Bisq 2"
        assert confidence < 0.80

    def test_dont_use_bisq1_is_not_a_bisq1_signal(self, detector):
        result = detector._detect_version_in_history_content("i don't use bisq 1")
        assert result is not None
        assert result[0] == "Bisq 2"

    def test_no_longer_on_bisq1_is_not_a_bisq1_signal(self, detector):
        result = detector._detect_version_in_history_content("i am no longer on bisq 1")
        assert result is not None
        assert result[0] == "Bisq 2"

    def test_not_using_bisq2_is_weak_bisq1_signal(self, detector):
        result = detector._detect_version_in_history_content("i'm not using bisq 2")
        assert result is not None
        version, confidence = result
        assert version == "Bisq 1"
        assert confidence < 0.80

    def test_negated_bisq1_with_positive_bisq2_mention(self, detector):
        result = detector._detect_version_in_history_content(
            "i'm not on bisq 1, i'm on bisq 2"
        )
        assert result == ("Bisq 2", 0.80)

    @pytest.mark.asyncio
    async def test_detect_version_negation_does_not_lock_bisq1(self, detector):
        """'I'm NOT on Bisq 1' must never lock Bisq 1 at 0.80 confidence."""
        history = [
            {"role": "user", "content": "I'm NOT on Bisq 1"},
            {"role": "assistant", "content": "Understood."},
        ]
        version, confidence, _ = await detector.detect_version(
            "How do I complete my trade?", history
        )
        assert version != "Bisq 1"


class TestHistorySwitchPhrases:
    """'switched from X to Y' counts as a signal for Y."""

    def test_switched_from_bisq1_to_bisq2(self, detector):
        result = detector._detect_version_in_history_content(
            "i switched from bisq 1 to bisq 2"
        )
        assert result == ("Bisq 2", 0.80)

    def test_migrated_from_bisq2_to_bisq1(self, detector):
        result = detector._detect_version_in_history_content(
            "i migrated from bisq 2 to bisq 1 last week"
        )
        assert result == ("Bisq 1", 0.80)

    def test_moved_over_from_bisq1_to_bisq2(self, detector):
        result = detector._detect_version_in_history_content(
            "we moved over from bisq1 to bisq2 recently"
        )
        assert result == ("Bisq 2", 0.80)

    @pytest.mark.asyncio
    async def test_switch_message_beats_older_one_sided_message(self, detector):
        """A newer switch message must win over an older one-sided mention."""
        history = [
            {"role": "user", "content": "I have a question about Bisq 1"},
            {"role": "assistant", "content": "Sure, go ahead."},
            {"role": "user", "content": "I switched from Bisq 1 to Bisq 2 yesterday"},
        ]
        version, confidence, _ = await detector.detect_version(
            "How do I buy bitcoin now?", history
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7


class TestHistoryRolePreference:
    """User signals stay preferred over assistant messages (existing behavior)."""

    @pytest.mark.asyncio
    async def test_user_signal_preferred_over_newer_assistant_signal(self, detector):
        history = [
            {"role": "user", "content": "I'm on Bisq 1"},
            {"role": "assistant", "content": "Bisq 2 has a reputation system"},
        ]
        version, _, _ = await detector.detect_version(
            "How do I complete my trade?", history
        )
        assert version == "Bisq 1"

    @pytest.mark.asyncio
    async def test_assistant_fallback_when_no_user_signal(self, detector):
        history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Welcome to Bisq 2 support"},
        ]
        version, _, _ = await detector.detect_version(
            "How do I complete my trade?", history
        )
        assert version == "Bisq 2"
