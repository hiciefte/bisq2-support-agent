"""NLI Validator for answer entailment checking."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import transformers, but make it optional
try:
    from transformers import pipeline  # type: ignore[import-untyped]

    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    logger.warning(
        "transformers not installed. NLI validation will return neutral scores. "
        "Install with: pip install transformers"
    )


class NLIValidator:
    """Validate answer entailment from source documents using NLI."""

    def __init__(self):
        """Initialize NLI pipeline with lightweight model."""
        self.nli_pipeline: Optional[object] = None
        if HAS_TRANSFORMERS:
            try:
                self.nli_pipeline = pipeline(
                    "text-classification",
                    model="cross-encoder/nli-deberta-v3-small",
                    device=-1,  # CPU for compatibility
                )
            except Exception as e:
                logger.error(f"Failed to initialize NLI pipeline: {e}")
                self.nli_pipeline = None

    async def validate_answer(self, context: str, answer: str) -> float:
        """
        Check if answer is entailed by context.

        Args:
            context: Source text to check against
            answer: Generated answer to validate

        Returns:
            float: Entailment score (0-1)
            - 1.0 = answer fully supported by context
            - 0.5 = neutral/partially supported
            - 0.0 = contradicts context
        """
        # Return neutral score if pipeline not available
        if self.nli_pipeline is None:
            return 0.5

        # NLI expects premise-hypothesis pairs
        result = self.nli_pipeline(f"{context} [SEP] {answer}", top_k=3)

        # Extract entailment probability
        scores = {r["label"]: r["score"] for r in result}
        entailment = scores.get("ENTAILMENT", 0)
        contradiction = scores.get("CONTRADICTION", 0)

        # Return normalized score
        if entailment > contradiction:
            return 0.5 + (entailment * 0.5)
        else:
            return 0.5 - (contradiction * 0.5)

    async def batch_validate(
        self, contexts: list[str], answers: list[str]
    ) -> list[float]:
        """
        Batch validation for efficiency.

        Args:
            contexts: List of source texts
            answers: List of answers to validate

        Returns:
            list[float]: List of entailment scores
        """
        # Return neutral scores if pipeline not available
        if self.nli_pipeline is None:
            return [0.5] * len(contexts)

        pairs = [f"{c} [SEP] {a}" for c, a in zip(contexts, answers)]
        results = self.nli_pipeline(pairs, top_k=3, batch_size=8)

        scores = []
        for result in results:
            score_dict = {r["label"]: r["score"] for r in result}
            entailment = score_dict.get("ENTAILMENT", 0)
            contradiction = score_dict.get("CONTRADICTION", 0)

            if entailment > contradiction:
                scores.append(0.5 + (entailment * 0.5))
            else:
                scores.append(0.5 - (contradiction * 0.5))

        return scores
