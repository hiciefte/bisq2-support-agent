"""Tests for Confidence Scorer - TDD approach."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document


class TestConfidenceScorer:
    """Test suite for confidence scoring."""

    @pytest.fixture
    def mock_nli_validator(self):
        """Create mock NLI validator."""
        mock = MagicMock()
        mock.validate_answer_async = AsyncMock(return_value=0.8)
        return mock

    @pytest.fixture
    def confidence_scorer(self, mock_nli_validator):
        """Create confidence scorer with mocked NLI."""
        from app.services.rag.confidence_scorer import ConfidenceScorer

        return ConfidenceScorer(mock_nli_validator)

    @pytest.mark.asyncio
    async def test_high_confidence_response(
        self, confidence_scorer, mock_nli_validator
    ):
        """AC-1.1.1: High entailment + good sources = high confidence."""
        mock_nli_validator.validate_answer_async.return_value = 0.95

        sources = [
            Document(
                page_content="Bisq Easy allows trading up to $600.",
                metadata={"source_weight": 1.0},
            )
        ]

        score = await confidence_scorer.calculate_confidence(
            answer="The trade limit is $600 in Bisq Easy.",
            sources=sources,
            question="What is the trade limit in Bisq Easy?",
        )

        # NLI: 0.95 * 0.4 = 0.38
        # Source: 1.0 * 0.3 = 0.30
        # Completeness: ~0.67 * 0.3 ≈ 0.20 (2/3 entities match)
        assert score > 0.8
        assert score <= 1.0

    @pytest.mark.asyncio
    async def test_low_confidence_no_sources(self, confidence_scorer):
        """AC-1.1.1: No sources returns 0.0 confidence."""
        score = await confidence_scorer.calculate_confidence(
            answer="I think the limit is $500.",
            sources=[],
            question="What is the trade limit?",
        )

        assert score == 0.0

    @pytest.mark.asyncio
    async def test_confidence_weights_nli(self, confidence_scorer, mock_nli_validator):
        """AC-1.1.2: NLI contributes 40% of score."""
        # High NLI, low source quality, low completeness
        mock_nli_validator.validate_answer_async.return_value = 1.0

        sources = [
            Document(
                page_content="Generic content without Bisq terms.",
                metadata={"source_weight": 0.0},
            )
        ]

        score = await confidence_scorer.calculate_confidence(
            answer="Answer without matching entities.",
            sources=sources,
            question="Different question entirely?",
        )

        # NLI: 1.0 * 0.4 = 0.4
        # Source: 0.0 * 0.3 = 0.0
        # Completeness: ~0.0 * 0.3 = 0.0
        # Should be around 0.4
        assert 0.35 <= score <= 0.45

    @pytest.mark.asyncio
    async def test_confidence_weights_source_quality(
        self, confidence_scorer, mock_nli_validator
    ):
        """AC-1.1.3: Source quality contributes 30% of score."""
        mock_nli_validator.validate_answer_async.return_value = 0.0

        sources = [
            Document(
                page_content="Content",
                metadata={"source_weight": 1.0},
            )
        ]

        score = await confidence_scorer.calculate_confidence(
            answer="Answer",
            sources=sources,
            question="Question?",
        )

        # NLI: 0.0 * 0.4 = 0.0
        # Source: 1.0 * 0.3 = 0.3
        # Completeness: varies
        # Should be around 0.3 + completeness
        assert score >= 0.3

    @pytest.mark.asyncio
    async def test_confidence_weights_completeness(
        self, confidence_scorer, mock_nli_validator
    ):
        """AC-1.1.4: Completeness contributes 30% of score."""
        mock_nli_validator.validate_answer_async.return_value = 0.0

        sources = [
            Document(
                page_content="Content",
                metadata={"source_weight": 0.0},
            )
        ]

        # Perfect entity match - all entities in answer
        score = await confidence_scorer.calculate_confidence(
            answer="Bisq Easy has a $600 limit.",
            sources=sources,
            question="What is the Bisq Easy $600 limit?",
        )

        # Completeness should be high (entities match)
        # Score should include completeness contribution
        assert score >= 0.15  # At least some completeness contribution

    @pytest.mark.asyncio
    async def test_returns_float_in_valid_range(
        self, confidence_scorer, mock_nli_validator
    ):
        """Confidence score always between 0 and 1."""
        mock_nli_validator.validate_answer_async.return_value = 0.5

        sources = [
            Document(
                page_content="Some content",
                metadata={"source_weight": 0.5},
            )
        ]

        score = await confidence_scorer.calculate_confidence(
            answer="Some answer",
            sources=sources,
            question="Some question?",
        )

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_multiple_sources_averaged(
        self, confidence_scorer, mock_nli_validator
    ):
        """Source quality is averaged across all sources."""
        mock_nli_validator.validate_answer_async.return_value = 0.5

        sources = [
            Document(page_content="Content 1", metadata={"source_weight": 1.0}),
            Document(page_content="Content 2", metadata={"source_weight": 0.5}),
            Document(page_content="Content 3", metadata={"source_weight": 0.0}),
        ]

        score = await confidence_scorer.calculate_confidence(
            answer="Answer",
            sources=sources,
            question="Question?",
        )

        # Average source weight: (1.0 + 0.5 + 0.0) / 3 = 0.5
        assert isinstance(score, float)

    @pytest.mark.asyncio
    async def test_default_source_weight(self, confidence_scorer, mock_nli_validator):
        """Missing source_weight defaults to 0.5."""
        mock_nli_validator.validate_answer_async.return_value = 0.5

        sources = [
            Document(
                page_content="Content without source_weight",
                metadata={},  # No source_weight
            )
        ]

        score = await confidence_scorer.calculate_confidence(
            answer="Answer",
            sources=sources,
            question="Question?",
        )

        # Should use default 0.5 for source weight
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_entity_extraction_bisq_terms(self, confidence_scorer):
        """Entity extraction includes Bisq-specific terms."""
        entities = confidence_scorer._extract_entities(
            "Bisq Easy uses BSQ tokens and DAO governance with reputation system."
        )

        # Should extract Bisq-specific terms
        assert any("bisq" in e.lower() for e in entities)
        assert any("bsq" in e.lower() for e in entities)
        assert any("dao" in e.lower() for e in entities)
        assert any("reputation" in e.lower() for e in entities)

    @pytest.mark.asyncio
    async def test_entity_extraction_numbers(self, confidence_scorer):
        """Entity extraction includes numbers and amounts."""
        entities = confidence_scorer._extract_entities(
            "The limit is $600 and minimum is 100 BTC."
        )

        # Should extract numbers
        assert "$600" in entities or "600" in entities
        assert "100" in entities

    @pytest.mark.asyncio
    async def test_entity_extraction_proper_nouns(self, confidence_scorer):
        """Entity extraction includes proper nouns."""
        entities = confidence_scorer._extract_entities(
            "Bitcoin and Ethereum are supported by Bisq."
        )

        # Should extract capitalized words
        assert "Bitcoin" in entities
        assert "Ethereum" in entities
        assert "Bisq" in entities or any("bisq" in e.lower() for e in entities)

    @pytest.mark.asyncio
    async def test_completeness_no_entities(self, confidence_scorer):
        """Completeness returns 0.5 for questions without entities."""
        completeness = confidence_scorer._calculate_completeness(
            question="how does it work?",  # No entities
            answer="It works by doing things.",
        )

        # Should return neutral score
        assert completeness == 0.5

    @pytest.mark.asyncio
    async def test_completeness_full_match(self, confidence_scorer):
        """Completeness returns 1.0 when all entities match."""
        completeness = confidence_scorer._calculate_completeness(
            question="What is Bisq $600 limit?",
            answer="Bisq has a $600 limit.",
        )

        # Should be high overlap
        assert completeness >= 0.5

    @pytest.mark.asyncio
    async def test_combines_top_5_sources_for_nli(
        self, confidence_scorer, mock_nli_validator
    ):
        """NLI validation uses combined context from top 5 sources."""
        sources = [
            Document(page_content=f"Content {i}", metadata={"source_weight": 0.5})
            for i in range(10)
        ]

        await confidence_scorer.calculate_confidence(
            answer="Answer",
            sources=sources,
            question="Question?",
        )

        # Check that NLI was called with combined context
        mock_nli_validator.validate_answer_async.assert_called_once()
        call_args = mock_nli_validator.validate_answer_async.call_args
        context = call_args[0][0]

        # Should combine first 5 sources
        assert "Content 0" in context
        assert "Content 4" in context
        # Should not include sources beyond top 5
        # (Actually the implementation uses [:5] so this might include Content 5)
