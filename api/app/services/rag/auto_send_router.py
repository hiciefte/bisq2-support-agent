"""Auto-send router for confidence-based response routing."""

import logging
from typing import List

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
    """Route responses based on confidence thresholds."""

    HIGH_CONFIDENCE_THRESHOLD = 0.95
    MEDIUM_CONFIDENCE_THRESHOLD = 0.70

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

        if confidence >= self.HIGH_CONFIDENCE_THRESHOLD:
            logger.info(f"Auto-sending response (confidence={confidence:.2f})")
            action = ResponseAction(
                action="auto_send",
                send_immediately=True,
                queue_for_review=False,
            )
            ROUTING_DECISIONS.labels(action="auto_send").inc()
            return action

        elif confidence >= self.MEDIUM_CONFIDENCE_THRESHOLD:
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
