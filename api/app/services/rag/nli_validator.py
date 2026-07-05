"""NLI Validator for answer entailment checking."""

import asyncio
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

pipeline = None
HAS_TRANSFORMERS = False

if os.getenv("BISQ_DISABLE_TRANSFORMERS", "").lower() not in ("1", "true", "yes"):
    # Try to import transformers, but make it optional
    try:
        from transformers import pipeline as hf_pipeline

        pipeline = hf_pipeline

        HAS_TRANSFORMERS = True
    except ImportError:
        logger.warning(
            "transformers not installed. NLI validation will return neutral scores. "
            "Install with: pip install transformers"
        )
else:
    logger.info("transformers import disabled via BISQ_DISABLE_TRANSFORMERS")


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

        if pipeline is not None:
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

    @staticmethod
    def _build_pair_input(context: str, answer: str) -> dict[str, str]:
        """Build the text/text_pair input expected by cross-encoder pipelines."""
        return {"text": context, "text_pair": answer}

    @staticmethod
    def _score_from_result(result: Any) -> float:
        """Convert a HuggingFace NLI result into a calibrated 0-1 score."""
        # Transformers v5 may return nested lists such as [[{...}, ...]].
        while (
            isinstance(result, list)
            and len(result) == 1
            and isinstance(result[0], list)
        ):
            result = result[0]

        if isinstance(result, dict):
            rows = [result]
        elif isinstance(result, list):
            rows = [row for row in result if isinstance(row, dict)]
        else:
            rows = []

        scores = {
            str(row.get("label", "")).casefold(): float(row.get("score", 0.0))
            for row in rows
        }
        entailment = scores.get("entailment", 0.0)
        contradiction = scores.get("contradiction", 0.0)

        if entailment > contradiction:
            return 0.5 + (entailment * 0.5)
        return 0.5 - (contradiction * 0.5)

    def _run_inference(self, context: str, answer: str) -> float:
        """Run NLI inference (internal method for caching to wrap)."""
        result = self.nli_pipeline(
            self._build_pair_input(context, answer),
            top_k=3,
        )
        return self._score_from_result(result)

    def validate_answer(self, answer: str, source_text: str) -> float:
        """
        Check if answer is entailed by source text (sync version with caching).

        Args:
            answer: Generated answer to validate
            source_text: Source text to check against

        Returns:
            float: Entailment score (0-1)
        """
        # Check cache first (even for fallback scores)
        cached = self._get_from_cache(answer, source_text)
        if cached is not None:
            return cached

        # Return and cache neutral score if pipeline not available
        if self.nli_pipeline is None:
            self._add_to_cache(answer, source_text, 0.5)
            return 0.5

        # Run inference
        score = self._run_inference(source_text, answer)

        # Cache result
        self._add_to_cache(answer, source_text, score)

        return score

    async def validate_answer_async(self, context: str, answer: str) -> float:
        """
        Check if answer is entailed by context (async version).

        Offloads CPU-bound NLI inference to a thread pool to avoid
        blocking the event loop.

        Args:
            context: Source text to check against
            answer: Generated answer to validate

        Returns:
            float: Entailment score (0-1)
            - 1.0 = answer fully supported by context
            - 0.5 = neutral/partially supported
            - 0.0 = contradicts context
        """
        # Check cache first (even for fallback scores)
        cached = self._get_from_cache(answer, context)
        if cached is not None:
            return cached

        # Return and cache neutral score if pipeline not available
        if self.nli_pipeline is None:
            self._add_to_cache(answer, context, 0.5)
            return 0.5

        # Run CPU-bound inference in thread pool to avoid blocking event loop
        score = await asyncio.to_thread(self._run_inference, context, answer)

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

    def _batch_inference(self, pairs: list[dict[str, str]]) -> list[float]:
        """Run batch NLI inference (internal method for thread offloading)."""
        results = self.nli_pipeline(pairs, top_k=3, batch_size=8)

        if not isinstance(results, list):
            return [self._score_from_result(results)]

        # A single-item batch can come back as [{...}, ...] instead of
        # [[{...}, ...]], so handle that shape before per-pair scoring.
        if results and all(isinstance(row, dict) for row in results):
            return [self._score_from_result(results)]

        return [self._score_from_result(result) for result in results]

    async def batch_validate(
        self, contexts: list[str], answers: list[str], cache_results: bool = True
    ) -> list[float]:
        """
        Batch validation for efficiency.

        Offloads CPU-bound NLI inference to a thread pool and optionally
        caches individual results for future single-item lookups.

        Args:
            contexts: List of source texts
            answers: List of answers to validate
            cache_results: Whether to cache individual results (default True)

        Returns:
            list[float]: List of entailment scores

        Raises:
            ValueError: If contexts and answers have different lengths
        """
        # Validate input lengths to avoid silent truncation
        if len(contexts) != len(answers):
            raise ValueError(
                f"contexts and answers must have the same length, "
                f"got {len(contexts)} and {len(answers)}"
            )

        # Return and cache neutral scores if pipeline not available
        if self.nli_pipeline is None:
            if cache_results:
                for context, answer in zip(contexts, answers, strict=True):
                    self._add_to_cache(answer, context, 0.5)
            return [0.5] * len(contexts)

        # Check cache for each pair, collect uncached indices
        scores: list[Optional[float]] = [None] * len(contexts)
        uncached_indices: list[int] = []
        uncached_pairs: list[dict[str, str]] = []

        for i, (context, answer) in enumerate(zip(contexts, answers, strict=True)):
            cached = self._get_from_cache(answer, context)
            if cached is not None:
                scores[i] = cached
            else:
                uncached_indices.append(i)
                uncached_pairs.append(self._build_pair_input(context, answer))

        # If all cached, return early
        if not uncached_indices:
            return [s for s in scores if s is not None]

        # Run batch inference in thread pool for uncached items
        batch_scores = await asyncio.to_thread(self._batch_inference, uncached_pairs)

        # Populate results and optionally cache
        for idx, batch_idx in enumerate(uncached_indices):
            score = batch_scores[idx]
            scores[batch_idx] = score
            if cache_results:
                context = contexts[batch_idx]
                answer = answers[batch_idx]
                self._add_to_cache(answer, context, score)

        return [s for s in scores if s is not None]
