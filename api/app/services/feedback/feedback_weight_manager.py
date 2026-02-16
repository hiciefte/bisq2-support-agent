"""
Feedback Weight Manager for source prioritization.

This module handles:
- Source weight calculation based on feedback
- Weight adjustment using gradual learning with Wilson score
- Source effectiveness scoring
- Time-window filtering (30 days)
- Cold start dampening
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, DefaultDict, Dict, List

logger = logging.getLogger(__name__)

# Weight bounds
_WEIGHT_MIN = 0.75
_WEIGHT_MAX = 1.25
# Time window for feedback processing
_TIME_WINDOW_DAYS = 30
# Cold start threshold
_COLD_START_THRESHOLD = 100


class FeedbackWeightManager:
    """Manager for feedback-based source weight calculations.

    This class handles:
    - Calculating source weights based on user feedback
    - Wilson score lower bound for sample-size-aware calibration
    - Gradual weight adjustment to prevent volatility
    - Source effectiveness tracking
    """

    def __init__(self):
        """Initialize the feedback weight manager."""
        self.source_weights = {
            "faq": 1.2,
            "wiki": 1.0,
        }
        logger.info("Feedback weight manager initialized")

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

    def apply_feedback_weights(
        self, feedback_data: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Update source weights based on feedback data.

        Args:
            feedback_data: List of feedback entries

        Returns:
            Updated source weights dictionary
        """
        if not feedback_data:
            logger.info("No feedback available for weight adjustment")
            return self.source_weights

        # Time-window filter: only process last 30 days
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_TIME_WINDOW_DAYS)
        ).isoformat()
        recent_data = []
        for item in feedback_data:
            ts = item.get("timestamp", "")
            if ts and ts >= cutoff:
                recent_data.append(item)

        if not recent_data:
            logger.info(
                "No recent feedback (within %d days) for weight adjustment",
                _TIME_WINDOW_DAYS,
            )
            return self.source_weights

        # Cold start dampening: lower learning rate for small samples
        learning_rate = 0.1 if len(recent_data) <= _COLD_START_THRESHOLD else 0.3

        # Count positive/negative responses by source type
        source_scores: DefaultDict[str, Dict[str, int]] = defaultdict(
            lambda: {"positive": 0, "negative": 0, "total": 0}
        )

        for item in recent_data:
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

        # Calculate new weights using Wilson score
        for source_type, scores in source_scores.items():
            if scores["total"] > 10:
                # Wilson score lower bound for conservative estimate
                wilson_score = self._calculate_wilson_lower_bound(
                    scores["positive"], scores["total"]
                )

                # Map Wilson score to weight range [0.75, 1.25]
                new_weight = _WEIGHT_MIN + (wilson_score * (_WEIGHT_MAX - _WEIGHT_MIN))

                # Clamp to bounds
                new_weight = max(_WEIGHT_MIN, min(_WEIGHT_MAX, new_weight))

                if source_type in self.source_weights:
                    old_weight = self.source_weights[source_type]
                    # Apply gradual adjustment with cold-start-aware learning rate
                    self.source_weights[source_type] = (
                        (1 - learning_rate) * old_weight
                    ) + (learning_rate * new_weight)
                    # Final clamp
                    self.source_weights[source_type] = max(
                        _WEIGHT_MIN,
                        min(_WEIGHT_MAX, self.source_weights[source_type]),
                    )
                    logger.info(
                        "Adjusted weight for %s: %.2f → %.2f (wilson=%.3f, lr=%.1f)",
                        source_type,
                        old_weight,
                        self.source_weights[source_type],
                        wilson_score,
                        learning_rate,
                    )

        logger.info("Updated source weights based on feedback: %s", self.source_weights)
        return self.source_weights

    def get_source_weights(self) -> Dict[str, float]:
        """Get the current source weights."""
        return self.source_weights

    def apply_quadrant_feedback(self, source_type: str, delta: float) -> None:
        """Apply a small immediate delta for trusted quadrant feedback."""
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
        self.source_weights[source_type] = max(
            _WEIGHT_MIN, min(_WEIGHT_MAX, new_weight)
        )
        logger.info(
            "Quadrant feedback adjusted %s: %.3f -> %.3f (delta=%.3f)",
            source_type,
            old_weight,
            self.source_weights[source_type],
            delta,
        )
