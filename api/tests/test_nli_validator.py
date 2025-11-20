"""Tests for NLI Validator - TDD approach."""

from unittest.mock import MagicMock, patch

import pytest


class TestNLIValidator:
    """Test suite for NLI entailment validation."""

    @pytest.fixture
    def mock_pipeline(self):
        """Mock the HuggingFace pipeline to avoid loading actual model."""
        with patch("app.services.rag.nli_validator.pipeline") as mock:
            mock_instance = MagicMock()
            mock.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def validator(self, mock_pipeline):
        """Create validator with mocked pipeline."""
        from app.services.rag.nli_validator import NLIValidator

        return NLIValidator()

    @pytest.mark.asyncio
    async def test_entailment_detection(self, validator, mock_pipeline):
        """AC-0.1.1, AC-0.1.2: NLI model validates entailment correctly."""
        # Mock high entailment response
        mock_pipeline.return_value = [
            {"label": "ENTAILMENT", "score": 0.95},
            {"label": "NEUTRAL", "score": 0.03},
            {"label": "CONTRADICTION", "score": 0.02},
        ]

        context = "Bisq Easy allows trading up to $600 without security deposits."
        answer = "The trade limit in Bisq Easy is $600."

        score = await validator.validate_answer(context, answer)

        # Should be high entailment: 0.5 + (0.95 * 0.5) = 0.975
        assert score > 0.7
        assert score <= 1.0
        mock_pipeline.assert_called_once()

    @pytest.mark.asyncio
    async def test_contradiction_detection(self, validator, mock_pipeline):
        """AC-0.1.3: Correctly identifies contradictions."""
        # Mock contradiction response
        mock_pipeline.return_value = [
            {"label": "CONTRADICTION", "score": 0.90},
            {"label": "NEUTRAL", "score": 0.07},
            {"label": "ENTAILMENT", "score": 0.03},
        ]

        context = "Bisq Easy uses reputation-based security."
        answer = "Bisq Easy requires security deposits for all trades."

        score = await validator.validate_answer(context, answer)

        # Should be low score: 0.5 - (0.90 * 0.5) = 0.05
        assert score < 0.3
        assert score >= 0.0

    @pytest.mark.asyncio
    async def test_neutral_returns_middle_score(self, validator, mock_pipeline):
        """Neutral responses return ~0.5 score."""
        mock_pipeline.return_value = [
            {"label": "NEUTRAL", "score": 0.80},
            {"label": "ENTAILMENT", "score": 0.10},
            {"label": "CONTRADICTION", "score": 0.10},
        ]

        score = await validator.validate_answer("Some context", "Some answer")

        # Equal entailment/contradiction → score around 0.5
        assert 0.4 <= score <= 0.6

    @pytest.mark.asyncio
    async def test_returns_float_in_valid_range(self, validator, mock_pipeline):
        """AC-0.1.2: Always returns float between 0-1."""
        mock_pipeline.return_value = [
            {"label": "ENTAILMENT", "score": 1.0},
            {"label": "NEUTRAL", "score": 0.0},
            {"label": "CONTRADICTION", "score": 0.0},
        ]

        score = await validator.validate_answer("context", "answer")

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_batch_validate(self, validator, mock_pipeline):
        """AC-0.1.5: Batch validation processes multiple pairs."""
        # Mock responses for 3 pairs
        mock_pipeline.return_value = [
            [
                {"label": "ENTAILMENT", "score": 0.9},
                {"label": "NEUTRAL", "score": 0.05},
                {"label": "CONTRADICTION", "score": 0.05},
            ],
            [
                {"label": "CONTRADICTION", "score": 0.8},
                {"label": "NEUTRAL", "score": 0.1},
                {"label": "ENTAILMENT", "score": 0.1},
            ],
            [
                {"label": "NEUTRAL", "score": 0.7},
                {"label": "ENTAILMENT", "score": 0.2},
                {"label": "CONTRADICTION", "score": 0.1},
            ],
        ]

        contexts = ["ctx1", "ctx2", "ctx3"]
        answers = ["ans1", "ans2", "ans3"]

        scores = await validator.batch_validate(contexts, answers)

        assert len(scores) == 3
        assert all(isinstance(s, float) for s in scores)
        assert all(0.0 <= s <= 1.0 for s in scores)
        # First should be high (entailment)
        assert scores[0] > 0.7
        # Second should be low (contradiction)
        assert scores[1] < 0.3

    @pytest.mark.asyncio
    async def test_handles_missing_labels(self, validator, mock_pipeline):
        """Gracefully handles missing label keys."""
        # Some models may not return all labels
        mock_pipeline.return_value = [
            {"label": "ENTAILMENT", "score": 0.8},
        ]

        score = await validator.validate_answer("context", "answer")

        # Should still return valid score
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_model_initialization(self):
        """AC-0.1.1: Model loads successfully."""
        with patch("app.services.rag.nli_validator.pipeline") as mock:
            from app.services.rag.nli_validator import NLIValidator

            _validator = NLIValidator()  # noqa: F841

            mock.assert_called_once_with(
                "text-classification",
                model="cross-encoder/nli-deberta-v3-small",
                device=-1,
            )

    @pytest.mark.asyncio
    async def test_empty_context_handling(self, validator, mock_pipeline):
        """Handles empty context gracefully."""
        mock_pipeline.return_value = [
            {"label": "NEUTRAL", "score": 0.9},
            {"label": "ENTAILMENT", "score": 0.05},
            {"label": "CONTRADICTION", "score": 0.05},
        ]

        score = await validator.validate_answer("", "Some answer")

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_empty_answer_handling(self, validator, mock_pipeline):
        """Handles empty answer gracefully."""
        mock_pipeline.return_value = [
            {"label": "NEUTRAL", "score": 0.9},
            {"label": "ENTAILMENT", "score": 0.05},
            {"label": "CONTRADICTION", "score": 0.05},
        ]

        score = await validator.validate_answer("Some context", "")

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0
