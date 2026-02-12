"""Auto-send router for confidence-based response routing."""

import logging
from typing import Any, List, Optional, Tuple

from app.models.response_action import ResponseAction
from langchain_core.documents import Document
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Prometheus metrics
ROUTING_DECISIONS = Counter(
    "rag_routing_decisions_total",
    "Total routing decisions by action",
    ["action"],
)

CONFIDENCE_HISTOGRAM = Histogram(
    "rag_confidence_score",
    "Distribution of confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
)


class AutoSendRouter:
    """Route responses based on confidence thresholds.

    Supports optional LearningEngine integration for dynamic threshold
    calibration based on admin review patterns.
    """

    HIGH_CONFIDENCE_THRESHOLD = 0.95
    MEDIUM_CONFIDENCE_THRESHOLD = 0.70

    def __init__(self, learning_engine: Optional[Any] = None):
        self._learning_engine = learning_engine

    def _get_thresholds(self) -> Tuple[float, float]:
        """Get current routing thresholds.

        Uses LearningEngine thresholds if available and sufficiently trained,
        otherwise falls back to static defaults.
        """
        if self._learning_engine is not None:
            try:
                history = self._learning_engine._review_history
                min_samples = self._learning_engine.min_samples_for_update
                if len(history) >= min_samples:
                    t = self._learning_engine.get_current_thresholds()
                    return t["auto_send_threshold"], t["queue_high_threshold"]
            except Exception as e:
                logger.warning("Failed to get LearningEngine thresholds: %s", e)
        return self.HIGH_CONFIDENCE_THRESHOLD, self.MEDIUM_CONFIDENCE_THRESHOLD

    async def route_response(
        self,
        confidence: float,
        question: str,
        answer: str,
        sources: List[Document],
    ) -> ResponseAction:
        """
        Route response based on confidence:
        - >=95%: Auto-send immediately
        - 70-95%: Queue for moderator review
        - <70%: Queue + flag as "needs human expertise"

        Args:
            confidence: Confidence score (0-1)
            question: Original user question
            answer: Generated answer
            sources: Retrieved source documents

        Returns:
            ResponseAction: Routing decision
        """
        # Record metrics
        CONFIDENCE_HISTOGRAM.observe(confidence)

        high_threshold, medium_threshold = self._get_thresholds()

        if confidence >= high_threshold:
            logger.info(f"Auto-sending response (confidence={confidence:.2f})")
            action = ResponseAction(
                action="auto_send",
                send_immediately=True,
                queue_for_review=False,
            )
            ROUTING_DECISIONS.labels(action="auto_send").inc()
            return action

        elif confidence >= medium_threshold:
            logger.info(f"Queueing for review (confidence={confidence:.2f})")
            action = ResponseAction(
                action="queue_medium",
                send_immediately=False,
                queue_for_review=True,
                priority="normal",
            )
            ROUTING_DECISIONS.labels(action="queue_medium").inc()
            return action

        else:
            logger.info(f"Queueing with high priority (confidence={confidence:.2f})")
            action = ResponseAction(
                action="needs_human",
                send_immediately=False,
                queue_for_review=True,
                priority="high",
                flag="needs_human_expertise",
            )
            ROUTING_DECISIONS.labels(action="needs_human").inc()
            return action
