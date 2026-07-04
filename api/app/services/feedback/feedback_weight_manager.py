"""
Feedback Weight Manager for source prioritization.

This module handles:
- Source weight calculation based on feedback
- Idempotent weight recomputation from the 30-day feedback window
  (Wilson score lower bound mapped into the weight bounds)
- Durable persistence of learned weights via the learning_state store
- Cold start dampening (minimum sample count before leaving defaults)
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, DefaultDict, Dict, List, Optional

logger = logging.getLogger(__name__)

# Weight bounds
_WEIGHT_MIN = 0.75
_WEIGHT_MAX = 1.25
# Time window for feedback processing
_TIME_WINDOW_DAYS = 30
# Minimum per-source sample count before a weight leaves its default
_MIN_SAMPLE_THRESHOLD = 10

# Default weights per source type; only these keys are recomputed from feedback
_DEFAULT_WEIGHTS = {
    "faq": 1.2,
    "wiki": 1.0,
    "llm_wiki": 1.25,
}

# Key under which weights are persisted in the learning_state table
SOURCE_WEIGHTS_STATE_KEY = "source_weights"


class FeedbackWeightManager:
    """Manager for feedback-based source weight calculations.

    This class handles:
    - Calculating source weights based on user feedback
    - Wilson score lower bound for sample-size-aware calibration
    - Idempotent recomputation: weights are a pure function of the
      30-day feedback window, so reapplying the same data is a no-op
    - Persistence through an optional repository (learning_state table),
      so learned weights survive restarts and process boundaries
    """

    def __init__(self, repository: Optional[Any] = None):
        """Initialize the feedback weight manager.

        Args:
            repository: Optional FeedbackRepository used to persist and
                reload weights. Without it the manager is in-memory only
                (used by unit tests and legacy callers).
        """
        self.repository = repository
        self.source_weights: Dict[str, float] = dict(_DEFAULT_WEIGHTS)
        self.load_weights()
        logger.info("Feedback weight manager initialized")

    @staticmethod
    def _clamp(weight: float) -> float:
        """Clamp a weight to the allowed bounds."""
        return max(_WEIGHT_MIN, min(_WEIGHT_MAX, weight))

    def load_weights(self) -> Dict[str, float]:
        """Reload persisted weights from the learning_state store.

        Unknown or non-numeric persisted values are ignored; missing keys
        fall back to their defaults. No-op without a repository.

        Returns:
            The current source weights after the reload attempt
        """
        if self.repository is None:
            return self.source_weights

        try:
            stored = self.repository.get_learning_state(SOURCE_WEIGHTS_STATE_KEY)
        except Exception as e:
            logger.warning("Could not load persisted source weights: %s", e)
            return self.source_weights

        if isinstance(stored, dict):
            merged = dict(_DEFAULT_WEIGHTS)
            for source_type, weight in stored.items():
                if isinstance(weight, (int, float)):
                    merged[source_type] = self._clamp(float(weight))
            self.source_weights = merged
            logger.debug("Loaded persisted source weights: %s", self.source_weights)

        return self.source_weights

    def _persist_weights(self) -> None:
        """Persist current weights to the learning_state store (best-effort)."""
        if self.repository is None:
            return
        try:
            self.repository.set_learning_state(
                SOURCE_WEIGHTS_STATE_KEY, self.source_weights
            )
        except Exception as e:
            logger.warning("Could not persist source weights: %s", e)

    @staticmethod
    def _calculate_wilson_lower_bound(
        positive: int, total: int, z: float = 1.96
    ) -> float:
        """Wilson score lower bound for binomial proportion confidence interval.

        Penalizes small sample sizes: a source with 3/3 positive (~0.44) ranks
        lower than one with 90/100 positive (~0.83).

        Args:
            positive: Number of positive responses
            total: Total responses
            z: Z-score for confidence level (1.96 = 95%)

        Returns:
            Wilson lower bound score (0-1)
        """
        if total == 0:
            return 0.5  # Neutral default
        p_hat = positive / total
        z_sq = z * z
        denominator = 1 + (z_sq / total)
        center = p_hat + (z_sq / (2 * total))
        margin = z * math.sqrt(
            (p_hat * (1 - p_hat) / total) + (z_sq / (4 * total * total))
        )
        return max(0.0, min(1.0, (center - margin) / denominator))

    def apply_feedback_aggregates(
        self, aggregates: Dict[str, Dict[str, int]]
    ) -> Dict[str, float]:
        """Recompute weights as a pure function of windowed feedback aggregates.

        The weight for each default source type is derived solely from the
        aggregate counts (Wilson lower bound mapped into the weight bounds),
        so reapplying the same aggregates is a no-op regardless of how often
        feedback events trigger a recompute. Sources with at most
        _MIN_SAMPLE_THRESHOLD responses stay at their default (cold start
        dampening). Transient quadrant nudges on default source types are
        superseded by each recompute.

        Args:
            aggregates: Mapping of source type -> {positive, negative, total},
                typically produced by
                FeedbackRepository.get_source_feedback_aggregates()

        Returns:
            Updated source weights dictionary
        """
        if not aggregates:
            logger.info("No recent feedback aggregates for weight adjustment")
            return self.source_weights

        updated = dict(self.source_weights)

        for source_type, default_weight in _DEFAULT_WEIGHTS.items():
            scores = aggregates.get(source_type)
            total = scores.get("total", 0) if scores else 0

            if scores and total > _MIN_SAMPLE_THRESHOLD:
                wilson_score = self._calculate_wilson_lower_bound(
                    scores.get("positive", 0), total
                )
                # Map Wilson score to the weight range [0.75, 1.25]
                new_weight = self._clamp(
                    _WEIGHT_MIN + (wilson_score * (_WEIGHT_MAX - _WEIGHT_MIN))
                )
                if updated.get(source_type) != new_weight:
                    logger.info(
                        "Adjusted weight for %s: %.2f → %.2f (wilson=%.3f, n=%d)",
                        source_type,
                        updated.get(source_type, default_weight),
                        new_weight,
                        wilson_score,
                        total,
                    )
                updated[source_type] = new_weight
            else:
                # Cold start dampening: insufficient samples → default weight
                updated[source_type] = default_weight

        self.source_weights = updated
        self._persist_weights()
        logger.info("Updated source weights based on feedback: %s", self.source_weights)
        return self.source_weights

    def apply_feedback_weights(
        self, feedback_data: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Update source weights based on raw feedback entries.

        Legacy entry point kept for callers holding raw feedback dictionaries;
        it aggregates the entries in Python (30-day window, rating field,
        sources_used → sources fallback) and delegates to the idempotent
        aggregate-based recompute.

        Args:
            feedback_data: List of feedback entries

        Returns:
            Updated source weights dictionary
        """
        if not feedback_data:
            logger.info("No feedback available for weight adjustment")
            return self.source_weights

        aggregates = self._aggregate_entries(feedback_data)
        if not aggregates:
            logger.info(
                "No recent feedback (within %d days) for weight adjustment",
                _TIME_WINDOW_DAYS,
            )
            return self.source_weights

        return self.apply_feedback_aggregates(aggregates)

    @staticmethod
    def _aggregate_entries(
        feedback_data: List[Dict[str, Any]],
    ) -> Dict[str, Dict[str, int]]:
        """Aggregate raw feedback entries into per-source counts.

        Mirrors FeedbackRepository.get_source_feedback_aggregates(): only the
        last 30 days count, entries need a 'rating' field, and 'sources_used'
        falls back to 'sources'.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_TIME_WINDOW_DAYS)
        ).isoformat()

        source_scores: DefaultDict[str, Dict[str, int]] = defaultdict(
            lambda: {"positive": 0, "negative": 0, "total": 0}
        )

        for item in feedback_data:
            ts = item.get("timestamp", "")
            if not ts or ts < cutoff:
                continue

            # Use 'rating' field (not legacy 'helpful')
            if "rating" not in item:
                continue

            # Fallback: sources_used → sources
            sources = item.get("sources_used") or item.get("sources", [])
            if not sources:
                continue

            helpful = item["rating"] == 1

            for source in sources:
                source_type = source.get("type", "unknown")
                if helpful:
                    source_scores[source_type]["positive"] += 1
                else:
                    source_scores[source_type]["negative"] += 1
                source_scores[source_type]["total"] += 1

        return dict(source_scores)

    def get_source_weights(self) -> Dict[str, float]:
        """Get the current source weights."""
        return self.source_weights

    def apply_quadrant_feedback(self, source_type: str, delta: float) -> None:
        """Apply a small immediate delta for trusted quadrant feedback.

        Quadrant nudges are transient by design: the next windowed recompute
        replaces them for default source types. They are persisted so they
        survive restarts until that recompute happens.
        """
        if abs(delta) > 0.10:
            logger.warning(
                "Circuit breaker rejected quadrant delta %.3f for %s",
                delta,
                source_type,
            )
            return
        if source_type not in self.source_weights:
            self.source_weights[source_type] = 1.0
        learning_rate = 0.02
        old_weight = self.source_weights[source_type]
        new_weight = old_weight + (learning_rate * delta)
        self.source_weights[source_type] = self._clamp(new_weight)
        self._persist_weights()
        logger.info(
            "Quadrant feedback adjusted %s: %.3f -> %.3f (delta=%.3f)",
            source_type,
            old_weight,
            self.source_weights[source_type],
            delta,
        )
