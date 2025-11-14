"""
Feedback Weight Manager for source prioritization.

This module handles:
- Source weight calculation based on feedback
- Weight adjustment using gradual learning
- Source effectiveness scoring
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class FeedbackWeightManager:
    """Manager for feedback-based source weight calculations.

    This class handles:
    - Calculating source weights based on user feedback
    - Gradual weight adjustment to prevent volatility
    - Source effectiveness tracking
    """

    def __init__(self):
        """Initialize the feedback weight manager."""
        # Source weights to be applied to different content types
        # These are influenced by feedback but used by RAG
        self.source_weights = {
            "faq": 1.2,  # Prioritize FAQ content
            "wiki": 1.0,  # Standard weight for wiki content
        }

        logger.info("Feedback weight manager initialized")

    def apply_feedback_weights(
        self, feedback_data: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """Update source weights based on feedback data.

        This method analyzes feedback to determine which sources
        are most helpful and adjusts weights accordingly.

        Args:
            feedback_data: List of feedback entries

        Returns:
            Updated source weights dictionary
        """
        if not feedback_data:
            logger.info("No feedback available for weight adjustment")
            return self.source_weights

        # Count positive/negative responses by source type
        source_scores: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"positive": 0, "negative": 0, "total": 0}
        )

        for item in feedback_data:
            # Skip items without necessary data
            if "sources_used" not in item or "helpful" not in item:
                continue

            helpful = item["helpful"]

            for source in item["sources_used"]:
                source_type = source.get("type", "unknown")

                if helpful:
                    source_scores[source_type]["positive"] += 1
                else:
                    source_scores[source_type]["negative"] += 1

                source_scores[source_type]["total"] += 1

        # Calculate new weights
        for source_type, scores in source_scores.items():
            if scores["total"] > 10:  # Only adjust if we have enough data
                # Calculate success rate: positive / total
                success_rate = scores["positive"] / scores["total"]

                # Scale it between 0.5 and 1.5
                new_weight = 0.5 + success_rate

                # Update weight if this source type exists
                if source_type in self.source_weights:
                    old_weight = self.source_weights[source_type]
                    # Apply gradual adjustment (70% old, 30% new)
                    self.source_weights[source_type] = (0.7 * old_weight) + (
                        0.3 * new_weight
                    )
                    logger.info(
                        f"Adjusted weight for {source_type}: {old_weight:.2f} → {self.source_weights[source_type]:.2f}"
                    )

        logger.info(f"Updated source weights based on feedback: {self.source_weights}")
        return self.source_weights

    def get_source_weights(self) -> Dict[str, float]:
        """Get the current source weights.

        Returns:
            Dictionary mapping source types to their weights
        """
        return self.source_weights
