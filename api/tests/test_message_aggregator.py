"""Tests for message aggregation and version confidence scoring."""

import pytest
from app.services.shadow_mode.message_aggregator import (
    MessageAggregator,
    VersionConfidenceScorer,
)


class TestMessageAggregator:
    """Tests for MessageAggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator with 2-minute window."""
        return MessageAggregator(window_minutes=2)

    def test_empty_messages(self, aggregator):
        """Test aggregating empty message list."""
        result = aggregator.aggregate_messages([])
        assert result == []

    def test_single_message(self, aggregator):
        """Test single message becomes one group."""
        messages = [{"content": "Help me", "timestamp": "2024-01-01T10:00:00Z"}]
        result = aggregator.aggregate_messages(messages)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_messages_within_window(self, aggregator):
        """Test messages within 2 minutes are grouped together."""
        messages = [
            {"content": "First", "timestamp": "2024-01-01T10:00:00Z"},
            {"content": "Second", "timestamp": "2024-01-01T10:01:00Z"},
            {"content": "Third", "timestamp": "2024-01-01T10:01:30Z"},
        ]
        result = aggregator.aggregate_messages(messages)
        assert len(result) == 1
        assert len(result[0]) == 3

    def test_messages_outside_window(self, aggregator):
        """Test messages outside window become separate groups."""
        messages = [
            {"content": "First", "timestamp": "2024-01-01T10:00:00Z"},
            {"content": "Second", "timestamp": "2024-01-01T10:05:00Z"},
        ]
        result = aggregator.aggregate_messages(messages)
        assert len(result) == 2

    def test_mixed_timing(self, aggregator):
        """Test mix of messages inside and outside window."""
        messages = [
            {"content": "A", "timestamp": "2024-01-01T10:00:00Z"},
            {"content": "B", "timestamp": "2024-01-01T10:01:00Z"},
            {"content": "C", "timestamp": "2024-01-01T10:10:00Z"},
            {"content": "D", "timestamp": "2024-01-01T10:11:00Z"},
        ]
        result = aggregator.aggregate_messages(messages)
        assert len(result) == 2
        assert len(result[0]) == 2  # A, B
        assert len(result[1]) == 2  # C, D

    def test_unsorted_messages(self, aggregator):
        """Test that unsorted messages are sorted by timestamp."""
        messages = [
            {"content": "Third", "timestamp": "2024-01-01T10:02:00Z"},
            {"content": "First", "timestamp": "2024-01-01T10:00:00Z"},
            {"content": "Second", "timestamp": "2024-01-01T10:01:00Z"},
        ]
        result = aggregator.aggregate_messages(messages)
        assert len(result) == 1
        assert result[0][0]["content"] == "First"
        assert result[0][2]["content"] == "Third"

    def test_synthesize_question_simple(self, aggregator):
        """Test synthesizing single message."""
        messages = [{"content": "How do I trade?", "sender_type": "user"}]
        result = aggregator.synthesize_question(messages)
        assert result == "How do I trade?"

    def test_synthesize_question_multiple(self, aggregator):
        """Test synthesizing multiple user messages."""
        messages = [
            {"content": "My trade is stuck", "sender_type": "user"},
            {"content": "The seller isn't responding", "sender_type": "user"},
        ]
        result = aggregator.synthesize_question(messages)
        assert result == "My trade is stuck The seller isn't responding"

    def test_synthesize_filters_support_messages(self, aggregator):
        """Test that support messages are filtered out."""
        messages = [
            {"content": "Help me", "sender_type": "user"},
            {"content": "What's your trade ID?", "sender_type": "support"},
            {"content": "It's ABC123", "sender_type": "user"},
        ]
        result = aggregator.synthesize_question(messages)
        assert "What's your trade ID?" not in result
        assert "Help me" in result
        assert "ABC123" in result

    def test_synthesize_cleans_whitespace(self, aggregator):
        """Test that extra whitespace is cleaned up."""
        messages = [
            {"content": "  Help   me  ", "sender_type": "user"},
            {"content": "please", "sender_type": "user"},
        ]
        result = aggregator.synthesize_question(messages)
        assert "  " not in result
        assert result == "Help me please"


class TestVersionConfidenceScorer:
    """Tests for VersionConfidenceScorer."""

    @pytest.fixture
    def scorer(self):
        """Create confidence scorer."""
        return VersionConfidenceScorer()

    def test_explicit_bisq2_mention(self, scorer):
        """Test explicit Bisq 2 mention gets high confidence."""
        messages = [{"content": "I'm using Bisq 2 and have a problem"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"
        assert result["confidence"] >= 0.4  # At least explicit mention weight
        assert result["signals"]["explicit_mention"] == 1.0

    def test_explicit_bisq1_mention(self, scorer):
        """Test explicit Bisq 1 mention gets high confidence."""
        messages = [{"content": "I'm using Bisq 1 desktop app"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq1"
        assert result["confidence"] >= 0.4
        assert result["signals"]["explicit_mention"] == 1.0

    def test_bisq_easy_mention(self, scorer):
        """Test Bisq Easy is detected as Bisq 2."""
        messages = [{"content": "I'm trading on Bisq Easy"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"
        assert result["confidence"] >= 0.4

    def test_feature_patterns_bisq2(self, scorer):
        """Test Bisq 2 feature patterns."""
        messages = [{"content": "My reputation score is low and I have no deposit"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"
        assert result["signals"]["feature_patterns"] > 0

    def test_feature_patterns_bisq1(self, scorer):
        """Test Bisq 1 feature patterns."""
        messages = [{"content": "The multisig arbitration is stuck"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq1"
        assert result["signals"]["feature_patterns"] > 0

    def test_terminology_bisq1(self, scorer):
        """Test Bisq 1 terminology."""
        messages = [{"content": "The maker fee seems too high"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq1"
        assert result["signals"]["terminology"] > 0

    def test_unknown_version(self, scorer):
        """Test unknown version when no clear signals."""
        messages = [{"content": "I have a question about trading"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "unknown"
        assert result["confidence"] < 0.5

    def test_multiple_signals_bisq2(self, scorer):
        """Test multiple signals increase confidence."""
        messages = [
            {"content": "Using Bisq 2 with reputation system and no security deposit"}
        ]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"
        assert result["confidence"] >= 0.6  # Multiple signals

    def test_conflicting_signals(self, scorer):
        """Test conflicting signals result in unknown with lower confidence."""
        messages = [{"content": "Bisq 2 multisig arbitration"}]  # Equal signals
        result = scorer.calculate_confidence(messages)
        # Equal signals = unknown with halved confidence
        assert result["detected_version"] == "unknown"
        assert result["confidence"] < 0.5  # Reduced due to unknown

    def test_auto_confirm_threshold_met(self, scorer):
        """Test auto-confirm when threshold met."""
        assert scorer.should_auto_confirm(0.85, threshold=0.8) is True
        assert scorer.should_auto_confirm(0.80, threshold=0.8) is True

    def test_auto_confirm_threshold_not_met(self, scorer):
        """Test no auto-confirm when below threshold."""
        assert scorer.should_auto_confirm(0.79, threshold=0.8) is False
        assert scorer.should_auto_confirm(0.5, threshold=0.8) is False

    def test_version_number_context(self, scorer):
        """Test version number detection in context."""
        messages = [{"content": "I'm on version 2.1.2"}]
        result = scorer.calculate_confidence(messages)

        assert result["signals"]["context_clues"] > 0
        assert result["detected_version"] == "bisq2"

    def test_case_insensitive(self, scorer):
        """Test detection is case insensitive."""
        messages = [{"content": "BISQ 2 REPUTATION"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"
        assert result["confidence"] >= 0.4

    def test_multiple_messages(self, scorer):
        """Test combining multiple messages."""
        messages = [
            {"content": "Help with trade"},
            {"content": "Using Bisq Easy"},
            {"content": "No deposit needed"},
        ]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"
        assert result["confidence"] >= 0.5

    def test_600_usd_limit(self, scorer):
        """Test $600 trade limit detection."""
        messages = [{"content": "Why is there a $600 limit?"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq2"

    def test_dao_detection(self, scorer):
        """Test DAO feature detection as Bisq 1."""
        messages = [{"content": "How does DAO voting work?"}]
        result = scorer.calculate_confidence(messages)

        assert result["detected_version"] == "bisq1"
