"""Confidence scorer for RAG responses."""

import logging
import re
from typing import List

from app.services.rag.nli_validator import NLIValidator
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

MIN_SOURCE_WEIGHT = 0.75
MAX_SOURCE_WEIGHT = 1.25
DEFAULT_SOURCE_WEIGHT = 1.0


class ConfidenceScorer:
    """Calculate confidence scores for RAG responses."""

    def __init__(self, nli_validator: NLIValidator):
        """
        Initialize confidence scorer.

        Args:
            nli_validator: NLI validator for entailment checking
        """
        self.nli = nli_validator

    async def calculate_confidence(
        self,
        answer: str,
        sources: List[Document],
        question: str,
    ) -> float:
        """
        Calculate confidence score using:
        1. NLI entailment (40%) - Does answer follow from sources?
        2. Source quality (30%) - Are sources authoritative?
        3. Answer completeness (30%) - Does answer address question?

        Args:
            answer: Generated answer text
            sources: Retrieved source documents
            question: Original user question

        Returns:
            float: Confidence score 0-1
        """
        if not sources:
            return 0.0

        # 1. NLI Entailment Score (40%)
        combined_context = "\n".join([doc.page_content for doc in sources[:5]])
        nli_score = await self.nli.validate_answer_async(combined_context, answer)

        # 2. Source Quality Score (30%)
        source_scores = [
            self._normalize_source_weight(doc.metadata.get("source_weight"))
            for doc in sources
        ]
        avg_source_quality = sum(source_scores) / len(source_scores)

        # 3. Answer Completeness Score (30%)
        completeness = self._calculate_completeness(question, answer)

        # Weighted combination
        confidence = 0.40 * nli_score + 0.30 * avg_source_quality + 0.30 * completeness

        logger.debug(
            f"Confidence breakdown: NLI={nli_score:.2f}, "
            f"Quality={avg_source_quality:.2f}, "
            f"Complete={completeness:.2f}, "
            f"Total={confidence:.2f}"
        )

        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _normalize_source_weight(raw_weight: object) -> float:
        """Map source weights from the 0.75-1.25 tuning range to quality 0-1."""
        try:
            if raw_weight is None:
                weight = DEFAULT_SOURCE_WEIGHT
            elif isinstance(raw_weight, (int, float, str)):
                weight = float(raw_weight)
            else:
                weight = DEFAULT_SOURCE_WEIGHT
        except (TypeError, ValueError):
            weight = DEFAULT_SOURCE_WEIGHT

        normalized = (weight - MIN_SOURCE_WEIGHT) / (
            MAX_SOURCE_WEIGHT - MIN_SOURCE_WEIGHT
        )
        return max(0.0, min(1.0, normalized))

    def _calculate_completeness(self, question: str, answer: str) -> float:
        """
        Check if answer contains key entities from question.

        Args:
            question: Original user question
            answer: Generated answer

        Returns:
            float: Completeness score 0-1
        """
        question_entities = self._extract_entities(question)
        answer_entities = self._extract_entities(answer)

        if not question_entities:
            return 0.5  # Neutral if no entities found

        overlap = len(question_entities & answer_entities)
        return overlap / len(question_entities)

    def _extract_entities(self, text: str) -> set:
        """
        Extract key entities from text.

        Args:
            text: Text to extract entities from

        Returns:
            set: Set of extracted entities
        """
        # Extract capitalized words (proper nouns)
        proper_nouns = set(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text))

        # Extract Bisq-specific terms
        bisq_terms = set(
            re.findall(
                r"\b(?:Bisq|BSQ|DAO|Burningman|Easy|reputation|arbitration|mediator)\b",
                text,
                re.IGNORECASE,
            )
        )

        # Extract numbers and amounts
        numbers = set(re.findall(r"\$?\d+(?:,\d{3})*(?:\.\d+)?", text))

        return proper_nouns | bisq_terms | numbers
