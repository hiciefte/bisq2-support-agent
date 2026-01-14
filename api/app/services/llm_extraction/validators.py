"""Post-LLM validation for extracted questions.

Validates LLM-extracted questions for quality control, filtering out
low-quality extractions that slipped through the initial filtering.
"""

import logging
from typing import List, Tuple

from app.core.config import get_settings
from app.services.llm_extraction.models import ExtractedQuestion

logger = logging.getLogger(__name__)


class QuestionValidator:
    """Validate LLM-extracted questions for quality control."""

    # Question indicator words that suggest genuine questions
    QUESTION_INDICATORS = [
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
        "is",
        "are",
        "do",
        "does",
        "help",
        "issue",
        "problem",
        "stuck",
        "error",
        "scam",
        "scammed",
        "confused",
        "understand",
        "wondering",
        "trying",
        "unable",
    ]

    def __init__(
        self,
        min_question_length: int | None = None,
        min_confidence: float = 0.5,
    ):
        """Initialize validator with configuration.

        Args:
            min_question_length: Minimum character length for valid questions.
                If None, uses settings.LLM_EXTRACTION_MIN_QUESTION_LENGTH.
            min_confidence: Minimum confidence threshold for validation.
        """
        settings = get_settings()
        self.min_question_length = (
            min_question_length
            if min_question_length is not None
            else settings.LLM_EXTRACTION_MIN_QUESTION_LENGTH
        )
        self.min_confidence = min_confidence

    def validate(self, question: ExtractedQuestion) -> Tuple[bool, str]:
        """Validate an extracted question.

        Performs multi-layer validation:
        1. Length check - reject very short questions
        2. Confidence check - reject low confidence extractions
        3. Indicator check - boost validation for obvious questions

        Args:
            question: ExtractedQuestion to validate

        Returns:
            Tuple of (is_valid, rejection_reason)
        """
        text = question.question_text.strip()

        # Check minimum length
        if len(text) < self.min_question_length:
            return False, "too_short"

        # Check confidence (secondary check, primary is in matrix_shadow_mode.py)
        if question.confidence < self.min_confidence:
            return False, "low_confidence"

        # Check for question indicators (boost for obvious questions)
        text_lower = text.lower()
        has_indicator = any(ind in text_lower for ind in self.QUESTION_INDICATORS)
        has_question_mark = "?" in text

        # If no indicators AND no question mark AND confidence < 0.85, reject
        if not has_indicator and not has_question_mark and question.confidence < 0.85:
            return False, "no_question_indicators"

        return True, ""

    def validate_batch(
        self, questions: List[ExtractedQuestion]
    ) -> Tuple[List[ExtractedQuestion], List[Tuple[ExtractedQuestion, str]]]:
        """Validate a batch of questions.

        Args:
            questions: List of ExtractedQuestion objects

        Returns:
            Tuple of (valid_questions, rejected_questions_with_reasons)
        """
        valid = []
        rejected = []

        for q in questions:
            is_valid, reason = self.validate(q)
            if is_valid:
                valid.append(q)
            else:
                rejected.append((q, reason))
                logger.debug(
                    f"Rejected question (reason={reason}): {q.question_text[:50]}..."
                )

        if rejected:
            logger.info(
                f"Post-LLM validation: {len(valid)} passed, {len(rejected)} rejected"
            )

        return valid, rejected
