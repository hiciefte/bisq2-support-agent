"""NLI Validator for answer entailment checking."""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Try to import transformers, but make it optional
try:
    from transformers import pipeline

    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    logger.warning(
        "transformers not installed. NLI validation will return neutral scores. "
        "Install with: pip install transformers"
    )


@dataclass
class NLICacheEntry:
    """A cache entry for NLI validation results."""

    score: float
    timestamp: float


class NLIValidator:
    """Validate answer entailment from source documents using NLI."""

    def __init__(
        self,
        enable_cache: bool = False,
        cache_size: int = 1000,
        cache_ttl_seconds: float = 3600.0,
    ):
        """Initialize NLI pipeline with lightweight model.

        Args:
            enable_cache: Whether to enable result caching
            cache_size: Maximum cache entries
            cache_ttl_seconds: Time-to-live for cache entries
        """
        self.nli_pipeline: Optional[Any] = None
        self._cache_enabled = enable_cache
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl_seconds
        self._cache: OrderedDict[str, NLICacheEntry] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0

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

        if enable_cache:
            logger.info(
                f"NLI caching enabled: size={cache_size}, ttl={cache_ttl_seconds}s"
            )

    def _get_cache_key(self, answer: str, source_text: str) -> str:
        """Generate cache key for answer/source pair."""
        combined = f"{answer}|||{source_text}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    def _get_from_cache(self, answer: str, source_text: str) -> Optional[float]:
        """Get cached result if available and not expired."""
        if not self._cache_enabled:
            return None

        key = self._get_cache_key(answer, source_text)

        with self._cache_lock:
            if key in self._cache:
                entry = self._cache[key]
                if (time.time() - entry.timestamp) <= self._cache_ttl:
                    self._cache.move_to_end(key)
                    self._cache_hits += 1
                    return entry.score
                else:
                    del self._cache[key]

            self._cache_misses += 1
            return None

    def _add_to_cache(self, answer: str, source_text: str, score: float) -> None:
        """Add result to cache."""
        if not self._cache_enabled:
            return

        key = self._get_cache_key(answer, source_text)

        with self._cache_lock:
            while len(self._cache) >= self._cache_size:
                self._cache.popitem(last=False)

            self._cache[key] = NLICacheEntry(score=score, timestamp=time.time())

    def _run_inference(self, context: str, answer: str) -> float:
        """Run NLI inference (internal method for caching to wrap)."""
        result = self.nli_pipeline(f"{context} [SEP] {answer}", top_k=3)

        # Handle transformers v5 which can return nested list [[{...}, ...]]
        if result and isinstance(result[0], list):
            result = result[0]

        # Extract entailment probability
        scores = {r["label"]: r["score"] for r in result}
        entailment = scores.get("ENTAILMENT", 0)
        contradiction = scores.get("CONTRADICTION", 0)

        # Return normalized score
        if entailment > contradiction:
            return 0.5 + (entailment * 0.5)
        else:
            return 0.5 - (contradiction * 0.5)

    def validate_answer(self, answer: str, source_text: str) -> float:
        """
        Check if answer is entailed by source text (sync version with caching).

        Args:
            answer: Generated answer to validate
            source_text: Source text to check against

        Returns:
            float: Entailment score (0-1)
        """
        # Return neutral score if pipeline not available
        if self.nli_pipeline is None:
            return 0.5

        # Check cache first
        cached = self._get_from_cache(answer, source_text)
        if cached is not None:
            return cached

        # Run inference
        score = self._run_inference(source_text, answer)

        # Cache result
        self._add_to_cache(answer, source_text, score)

        return score

    async def validate_answer_async(self, context: str, answer: str) -> float:
        """
        Check if answer is entailed by context (async version).

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

        # Check cache first
        cached = self._get_from_cache(answer, context)
        if cached is not None:
            return cached

        # Run inference
        score = self._run_inference(context, answer)

        # Cache result
        self._add_to_cache(answer, context, score)

        return score

    def get_cache_statistics(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._cache_lock:
            total = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total if total > 0 else 0.0
            return {
                "enabled": self._cache_enabled,
                "size": len(self._cache),
                "max_size": self._cache_size,
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "hit_rate": hit_rate,
            }

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

        # Handle transformers v5 which can return nested list [[[{...}], ...]]
        # Normalize to flat list of result lists: [[{...}, ...], [{...}, ...], ...]
        if (
            results
            and isinstance(results[0], list)
            and results[0]
            and isinstance(results[0][0], list)
        ):
            results = [r[0] for r in results]

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
