"""Unit tests for QuestionValidator class."""

import pytest
from app.services.llm_extraction.models import ExtractedQuestion
from app.services.llm_extraction.validators import QuestionValidator


class TestQuestionValidator:
    """Tests for QuestionValidator class."""

    @pytest.fixture
    def validator(self):
        """Create a QuestionValidator with test configuration."""
        return QuestionValidator(min_question_length=10, min_confidence=0.5)

    def test_valid_question_passes(self, validator):
        """Test that a well-formed question with good confidence passes."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="How do I complete a trade in Bisq?",
            question_type="initial_question",
            confidence=0.90,
            sender="User_1",
        )
        is_valid, reason = validator.validate(q)
        assert is_valid is True
        assert reason == ""

    def test_short_question_rejected(self, validator):
        """Test that very short questions are rejected."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="Help?",
            question_type="initial_question",
            confidence=0.90,
            sender="User_1",
        )
        is_valid, reason = validator.validate(q)
        assert is_valid is False
        assert reason == "too_short"

    def test_low_confidence_rejected(self, validator):
        """Test that low confidence questions are rejected."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="This is a question about something important",
            question_type="initial_question",
            confidence=0.40,
            sender="User_1",
        )
        is_valid, reason = validator.validate(q)
        assert is_valid is False
        assert reason == "low_confidence"

    def test_no_indicators_low_confidence_rejected(self, validator):
        """Test that questions without indicators AND low confidence are rejected."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="The trade took a while to complete",
            question_type="initial_question",
            confidence=0.75,  # Below 0.85 threshold for indicator check
            sender="User_1",
        )
        is_valid, reason = validator.validate(q)
        assert is_valid is False
        assert reason == "no_question_indicators"

    def test_question_mark_passes_without_indicators(self, validator):
        """Test that questions with question mark pass even without indicators."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="The payment was sent already?",
            question_type="initial_question",
            confidence=0.75,
            sender="User_1",
        )
        is_valid, _ = validator.validate(q)
        assert is_valid is True  # Has question mark

    def test_question_indicator_passes(self, validator):
        """Test that questions with indicator words pass."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="I have a problem with my trade stuck at confirmation",
            question_type="initial_question",
            confidence=0.75,
            sender="User_1",
        )
        is_valid, _ = validator.validate(q)
        assert is_valid is True  # Has "problem" indicator

    def test_high_confidence_passes_without_indicators(self, validator):
        """Test that high confidence questions pass even without indicators."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="The payment was sent yesterday morning",
            question_type="initial_question",
            confidence=0.90,  # High confidence (>= 0.85)
            sender="User_1",
        )
        is_valid, _ = validator.validate(q)
        assert is_valid is True  # High confidence overrides indicator check

    @pytest.mark.parametrize(
        "indicator",
        [
            "how",
            "what",
            "when",
            "where",
            "why",
            "who",
            "which",
            "can",
            "could",
            "would",
            "should",
            "help",
            "issue",
            "problem",
            "stuck",
            "error",
            "scam",
            "confused",
        ],
    )
    def test_all_question_indicators(self, validator, indicator):
        """Test that all question indicator words are recognized."""
        q = ExtractedQuestion(
            message_id="msg1",
            question_text=f"The {indicator} situation with my trade needs attention",
            question_type="initial_question",
            confidence=0.75,
            sender="User_1",
        )
        is_valid, _ = validator.validate(q)
        assert is_valid is True

    def test_validate_batch_mixed(self, validator):
        """Test batch validation with mixed valid and invalid questions."""
        questions = [
            ExtractedQuestion(
                message_id="msg1",
                question_text="How do I complete a trade?",
                question_type="initial_question",
                confidence=0.90,
                sender="User_1",
            ),
            ExtractedQuestion(
                message_id="msg2",
                question_text="Help?",  # Too short
                question_type="initial_question",
                confidence=0.90,
                sender="User_2",
            ),
            ExtractedQuestion(
                message_id="msg3",
                question_text="This is a statement about my trade",
                question_type="initial_question",
                confidence=0.40,  # Too low
                sender="User_3",
            ),
            ExtractedQuestion(
                message_id="msg4",
                question_text="Can someone help me with mediation?",
                question_type="initial_question",
                confidence=0.85,
                sender="User_4",
            ),
        ]
        valid, rejected = validator.validate_batch(questions)
        assert len(valid) == 2
        assert len(rejected) == 2

        # Check rejection reasons
        rejection_reasons = [reason for _, reason in rejected]
        assert "too_short" in rejection_reasons
        assert "low_confidence" in rejection_reasons

    def test_validate_batch_all_valid(self, validator):
        """Test batch validation when all questions are valid."""
        questions = [
            ExtractedQuestion(
                message_id="msg1",
                question_text="How do I complete a trade?",
                question_type="initial_question",
                confidence=0.90,
                sender="User_1",
            ),
            ExtractedQuestion(
                message_id="msg2",
                question_text="What is the process for mediation?",
                question_type="initial_question",
                confidence=0.88,
                sender="User_2",
            ),
        ]
        valid, rejected = validator.validate_batch(questions)
        assert len(valid) == 2
        assert len(rejected) == 0

    def test_validate_batch_all_rejected(self, validator):
        """Test batch validation when all questions are invalid."""
        questions = [
            ExtractedQuestion(
                message_id="msg1",
                question_text="Hi",  # Too short
                question_type="initial_question",
                confidence=0.90,
                sender="User_1",
            ),
            ExtractedQuestion(
                message_id="msg2",
                question_text="OK",  # Too short
                question_type="initial_question",
                confidence=0.40,  # Also too low
                sender="User_2",
            ),
        ]
        valid, rejected = validator.validate_batch(questions)
        assert len(valid) == 0
        assert len(rejected) == 2

    def test_validator_with_custom_settings(self):
        """Test validator with custom configuration."""
        validator = QuestionValidator(min_question_length=5, min_confidence=0.3)
        q = ExtractedQuestion(
            message_id="msg1",
            question_text="Help?",  # 5 chars - passes custom min length
            question_type="initial_question",
            confidence=0.35,  # Passes custom min confidence
            sender="User_1",
        )
        is_valid, _ = validator.validate(q)
        assert is_valid is True
