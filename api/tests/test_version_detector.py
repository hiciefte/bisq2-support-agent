"""Tests for VersionDetector service."""

import pytest
from app.services.rag.version_detector import VersionDetector


@pytest.fixture
def detector():
    return VersionDetector()


class TestExplicitVersionMentions:
    """Test explicit version detection from direct mentions."""

    @pytest.mark.asyncio
    async def test_explicit_bisq1_mention(self, detector):
        version, confidence = await detector.detect_version(
            "How do I vote in Bisq 1 DAO?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.95

    @pytest.mark.asyncio
    async def test_explicit_bisq1_no_space(self, detector):
        version, confidence = await detector.detect_version(
            "How does bisq1 arbitration work?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.95

    @pytest.mark.asyncio
    async def test_explicit_bisq2_mention(self, detector):
        version, confidence = await detector.detect_version("How do I use Bisq 2?", [])
        assert version == "Bisq 2"
        assert confidence >= 0.95

    @pytest.mark.asyncio
    async def test_explicit_bisq2_no_space(self, detector):
        version, confidence = await detector.detect_version(
            "Tell me about bisq2 reputation", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.95


class TestKeywordDetection:
    """Test version detection from keywords."""

    @pytest.mark.asyncio
    async def test_bisq1_keywords_dao(self, detector):
        version, confidence = await detector.detect_version(
            "How does the DAO voting work with BSQ?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq1_keywords_arbitration(self, detector):
        version, confidence = await detector.detect_version(
            "What is the arbitration process?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq1_keywords_security_deposit(self, detector):
        version, confidence = await detector.detect_version(
            "How much is the security deposit?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq1_keywords_multisig(self, detector):
        version, confidence = await detector.detect_version(
            "How does the 2-of-2 multisig work?", []
        )
        assert version == "Bisq 1"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq2_keywords_reputation(self, detector):
        version, confidence = await detector.detect_version(
            "What is the reputation system in Bisq Easy?", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq2_keywords_trade_limit(self, detector):
        version, confidence = await detector.detect_version(
            "Why is the limit 600 usd?", []
        )
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_bisq2_keywords_bonded_roles(self, detector):
        version, confidence = await detector.detect_version(
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
        version, confidence = await detector.detect_version(
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
        version, confidence = await detector.detect_version(
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
        version, confidence = await detector.detect_version(
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
        version, confidence = await detector.detect_version("How do I trade?", history)
        assert version == "Bisq 2"


class TestAmbiguousQuestions:
    """Test handling of ambiguous questions."""

    @pytest.mark.asyncio
    async def test_ambiguous_defaults_to_bisq2(self, detector):
        version, confidence = await detector.detect_version("How do I buy Bitcoin?", [])
        assert version == "Bisq 2"
        assert confidence == 0.50  # Low confidence default

    @pytest.mark.asyncio
    async def test_ambiguous_generic_question(self, detector):
        version, confidence = await detector.detect_version("What are the fees?", [])
        assert version == "Bisq 2"
        assert confidence == 0.50

    @pytest.mark.asyncio
    async def test_no_keywords_low_confidence(self, detector):
        version, confidence = await detector.detect_version("Hello, I need help", [])
        assert confidence <= 0.50


class TestClarificationPrompt:
    """Test clarification prompt generation."""

    def test_clarification_prompt_contains_both_versions(self, detector):
        prompt = detector.get_clarification_prompt("How do I trade?")
        assert "Bisq 1" in prompt
        assert "Bisq 2" in prompt

    def test_clarification_prompt_describes_differences(self, detector):
        prompt = detector.get_clarification_prompt("How do I trade?")
        assert "DAO" in prompt or "desktop" in prompt
        assert "Easy" in prompt or "simple" in prompt


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_question(self, detector):
        version, confidence = await detector.detect_version("", [])
        assert version == "Bisq 2"
        assert confidence == 0.50

    @pytest.mark.asyncio
    async def test_mixed_version_keywords(self, detector):
        # When both versions are mentioned, should return Unknown or low confidence
        version, confidence = await detector.detect_version(
            "How does DAO compare to reputation system?", []
        )
        # Either version is acceptable but confidence should be lower
        assert confidence < 0.9

    @pytest.mark.asyncio
    async def test_case_insensitivity(self, detector):
        version, confidence = await detector.detect_version("BISQ EASY REPUTATION", [])
        assert version == "Bisq 2"
        assert confidence >= 0.7

    @pytest.mark.asyncio
    async def test_multiple_keywords_increase_confidence(self, detector):
        # Multiple keywords should increase confidence
        version, confidence = await detector.detect_version(
            "How do I use DAO voting with BSQ and become an arbitrator?", []
        )
        assert version == "Bisq 1"
        assert confidence > 0.8  # Higher confidence with multiple keywords
