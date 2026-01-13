"""Tests for VersionDetector service - Unknown Version Enhancement.

CRITICAL: This test file has been updated to test the 3-tuple return type:
- Old signature: (version, confidence)
- New signature: (version, confidence, clarifying_question)

All tests now verify the third return value (clarifying_question).
"""

import pytest
from app.services.rag.version_detector import VersionDetector


@pytest.fixture
def detector():
    return VersionDetector()


class TestReturnTypeSignature:
    """Test suite for verifying 3-tuple return type (NEW)."""

    @pytest.mark.asyncio
    async def test_detect_version_returns_three_tuple(self, detector):
        """Verify detect_version() returns 3-tuple (version, confidence, clarifying_question)."""
        result = await detector.detect_version("How do I use Bisq?", [])

        assert isinstance(result, tuple), "Result should be a tuple"
        assert len(result) == 3, f"Expected 3 values, got {len(result)}"

        version, confidence, clarifying_question = result
        assert isinstance(version, str), "First value should be version (str)"
        assert isinstance(
            confidence, float
        ), "Second value should be confidence (float)"
        assert clarifying_question is None or isinstance(
            clarifying_question, str
        ), "Third value should be clarifying_question (Optional[str])"


class TestExplicitVersionMentions:
    """Test explicit version detection from direct mentions."""

    @pytest.mark.asyncio
    async def test_explicit_bisq1_mention(self, detector):
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I vote in Bisq 1 DAO?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.95
        assert (
            clarifying_question is None
        ), "Explicit mention should NOT need clarification"

    @pytest.mark.asyncio
    async def test_explicit_bisq1_no_space(self, detector):
        version, confidence, _ = await detector.detect_version(
            "How does bisq1 arbitration work?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.95

    @pytest.mark.asyncio
    async def test_explicit_bisq2_mention(self, detector):
        version, confidence, _ = await detector.detect_version(
            "How do I use Bisq 2?", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.95

    @pytest.mark.asyncio
    async def test_explicit_bisq2_no_space(self, detector):
        version, confidence, _ = await detector.detect_version(
            "Tell me about bisq2 reputation", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.95


class TestKeywordDetection:
    """Test version detection from keywords."""

    @pytest.mark.asyncio
    async def test_bisq1_keywords_dao(self, detector):
        version, confidence, _ = await detector.detect_version(
            "How does the DAO voting work with BSQ?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq1_keywords_arbitration(self, detector):
        version, confidence, _ = await detector.detect_version(
            "What is the arbitration process?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq1_keywords_security_deposit(self, detector):
        version, confidence, _ = await detector.detect_version(
            "How much is the security deposit?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq1_keywords_multisig(self, detector):
        version, confidence, _ = await detector.detect_version(
            "How does the 2-of-2 multisig work?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq2_keywords_reputation(self, detector):
        version, confidence, _ = await detector.detect_version(
            "What is the reputation system in Bisq Easy?", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq2_keywords_trade_limit(self, detector):
        version, confidence, _ = await detector.detect_version(
            "Why is the limit 600 usd?", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq2_keywords_bonded_roles(self, detector):
        version, confidence, _ = await detector.detect_version(
            "What are bonded roles?", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7


class TestChatHistoryContext:
    """Test version detection from chat history."""

    @pytest.mark.asyncio
    async def test_chat_history_explicit_bisq1(self, detector):
        history = [
            {"role": "user", "content": "I'm using Bisq 1"},
            {"role": "assistant", "content": "Great, how can I help?"},
        ]
        version, confidence, _ = await detector.detect_version(
            "How do I make a trade?", history
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_chat_history_explicit_bisq2(self, detector):
        history = [
            {"role": "user", "content": "I'm trying to use Bisq 2"},
            {"role": "assistant", "content": "Great! How can I help?"},
        ]
        version, confidence, _ = await detector.detect_version(
            "How long does a trade take?", history
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_chat_history_keywords(self, detector):
        history = [
            {"role": "user", "content": "I want to vote in the DAO"},
            {"role": "assistant", "content": "Sure, let me help you with voting."},
        ]
        version, confidence, _ = await detector.detect_version(
            "What are the requirements?", history
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_chat_history_only_last_5_messages(self, detector):
        # Old context should be ignored
        history = [
            {"role": "user", "content": "I'm using Bisq 1"},
            {"role": "assistant", "content": "OK"},
            {"role": "user", "content": "Actually switching"},
            {"role": "assistant", "content": "OK"},
            {"role": "user", "content": "Now using Bisq 2"},
            {"role": "assistant", "content": "OK"},
            {"role": "user", "content": "It's great"},
            {"role": "assistant", "content": "Nice"},
        ]
        version, confidence, _ = await detector.detect_version(
            "How do I trade?", history
        )
        assert version == "Bisq 2"


class TestAmbiguousQuestions:
    """Test handling of ambiguous questions - UPDATED for Unknown Version Enhancement."""

    @pytest.mark.asyncio
    async def test_ambiguous_returns_unknown_with_clarification(self, detector):
        """Ambiguous questions now return Unknown with clarifying question."""
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I buy Bitcoin?", []
        )
        assert version == "Unknown", "Ambiguous questions should return Unknown"
        assert confidence == 0.30, "Low confidence for ambiguous questions"
        assert clarifying_question is not None, "Should provide clarifying question"

    @pytest.mark.asyncio
    async def test_ambiguous_generic_question_unknown(self, detector):
        """Generic questions return Unknown with clarification."""
        version, confidence, clarifying_question = await detector.detect_version(
            "What are the fees?", []
        )
        assert version == "Unknown", "Generic questions should return Unknown"
        assert confidence == 0.30
        assert clarifying_question is not None

    @pytest.mark.asyncio
    async def test_no_keywords_low_confidence(self, detector):
        """Questions with no keywords have low confidence."""
        version, confidence, _ = await detector.detect_version("Hello, I need help", [])
        assert confidence <= 0.50


class TestClarificationPrompt:
    """Test clarification prompt generation."""

    def test_clarification_prompt_contains_both_versions(self, detector):
        prompt = detector.get_clarification_prompt("How do I trade?")
        assert "Bisq 1" in prompt
        assert "Bisq 2" in prompt

    def test_clarification_prompt_describes_differences(self, detector):
        """Clarifying prompts should be context-aware."""
        prompt = detector.get_clarification_prompt("How do I trade?")
        # Trade context should mention trading or Bisq Easy
        assert "trading" in prompt.lower() or "Easy" in prompt or "Bisq 1" in prompt


class TestEdgeCases:
    """Test edge cases and boundary conditions - UPDATED for Unknown Version Enhancement."""

    @pytest.mark.asyncio
    async def test_empty_question_returns_unknown(self, detector):
        """Empty questions return Unknown with clarification."""
        version, confidence, clarifying_question = await detector.detect_version("", [])
        assert version == "Unknown", "Empty questions should return Unknown"
        assert confidence == 0.30
        assert clarifying_question is not None

    @pytest.mark.asyncio
    async def test_mixed_version_keywords(self, detector):
        # When both versions are mentioned, should return Unknown or low confidence
        version, confidence, _ = await detector.detect_version(
            "How does DAO compare to reputation system?", []
        )
        # Either version is acceptable but confidence should be lower
        assert confidence < 0.9

    @pytest.mark.asyncio
    async def test_case_insensitivity(self, detector):
        version, confidence, _ = await detector.detect_version(
            "BISQ EASY REPUTATION", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_multiple_keywords_increase_confidence(self, detector):
        # Multiple keywords should increase confidence
        version, confidence, _ = await detector.detect_version(
            "How do I use DAO voting with BSQ and become an arbitrator?", []
        )
        assert version == "Bisq 1"
        assert confidence > 0.8  # Higher confidence with multiple keywords


class TestClarifyingQuestionGeneration:
    """Test suite for clarifying question generation (NEW - Unknown Version Enhancement)."""

    @pytest.mark.asyncio
    async def test_low_confidence_generates_clarifying_question(self, detector):
        """Test confidence < 0.5 returns ('Unknown', 0.30, clarifying_question)."""
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I use Bisq?", []  # Ambiguous question
        )

        assert version == "Unknown", f"Expected 'Unknown', got '{version}'"
        assert confidence == 0.30, f"Expected 0.30 confidence, got {confidence}"
        assert (
            clarifying_question is not None
        ), "Expected clarifying question for low confidence"
        assert isinstance(clarifying_question, str)
        assert len(clarifying_question) > 0

    @pytest.mark.asyncio
    async def test_clarifying_question_trade_context(self, detector):
        """Test 'trade' keyword generates trade-specific question."""
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I trade?", []
        )

        assert version == "Unknown"
        assert clarifying_question is not None
        # Should mention Bisq 1 trading OR Bisq Easy
        assert "Bisq 1" in clarifying_question or "Bisq Easy" in clarifying_question

    @pytest.mark.asyncio
    async def test_clarifying_question_wallet_context(self, detector):
        """Test 'wallet' keyword generates wallet-specific question."""
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I restore my wallet?", []
        )

        assert version == "Unknown"
        assert clarifying_question is not None
        assert "wallet" in clarifying_question.lower()

    @pytest.mark.asyncio
    async def test_clarifying_question_reputation_context(self, detector):
        """Test 'reputation' keyword - might detect Bisq 2 due to strong keyword."""
        version, confidence, clarifying_question = await detector.detect_version(
            "How does reputation work?", []
        )

        # "reputation" is a strong Bisq 2 keyword, so might detect Bisq 2 with high confidence
        # If it does, that's correct - no clarification needed
        if version == "Bisq 2":
            assert confidence > 0.6, "High confidence for strong Bisq 2 keyword"
            # No clarification needed for high confidence
        else:
            # If Unknown, should have clarifying question
            assert version == "Unknown"
            assert clarifying_question is not None
            assert (
                "reputation" in clarifying_question.lower()
                or "Bisq 2" in clarifying_question
            )

    @pytest.mark.asyncio
    async def test_clarifying_question_generic_fallback(self, detector):
        """Test unknown context returns generic version question."""
        version, confidence, clarifying_question = await detector.detect_version(
            "Is Bisq safe?", []
        )

        assert version == "Unknown"
        assert clarifying_question is not None
        # Generic question should mention BOTH versions
        assert "Bisq 1" in clarifying_question and "Bisq 2" in clarifying_question

    @pytest.mark.asyncio
    async def test_high_confidence_no_clarifying_question(self, detector):
        """Test high confidence (>= 0.6) does NOT generate clarifying question."""
        # DAO is a strong Bisq 1 keyword
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I vote in the DAO?", []
        )

        assert version == "Bisq 1"
        assert confidence > 0.6
        assert (
            clarifying_question is None
        ), "High confidence should NOT generate clarifying question"


class TestNoneChatHistory:
    """Test handling of None chat_history to prevent regression of NoneType error."""

    @pytest.mark.asyncio
    async def test_none_chat_history_does_not_crash(self, detector):
        """Verify detect_version() handles None chat_history without crashing.

        This test prevents regression of the bug where _check_chat_history
        tried to slice None: chat_history[-5:] when chat_history was None.
        """
        # This should NOT raise TypeError: 'NoneType' object is not subscriptable
        version, confidence, clarifying_question = await detector.detect_version(
            "How do I buy Bitcoin?", None  # type: ignore - intentionally passing None
        )

        # Behavior should be same as empty list - return Unknown with clarification
        assert version == "Unknown", "None chat_history should return Unknown"
        assert confidence == 0.30, "Low confidence for ambiguous question"
        assert clarifying_question is not None, "Should provide clarifying question"

    @pytest.mark.asyncio
    async def test_none_chat_history_with_explicit_version(self, detector):
        """Verify explicit version in question works even with None chat_history."""
        version, confidence, _ = await detector.detect_version(
            "How do I vote in Bisq 1 DAO?", None  # type: ignore
        )

        assert version == "Bisq 1"
        assert confidence >= 0.95
