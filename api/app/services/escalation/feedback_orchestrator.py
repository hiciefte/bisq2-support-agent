"""Coordinates trusted escalation rating signals into learning components."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaffRatingSignal:
    """Normalized input for feedback-learning orchestration."""

    message_id: str
    escalation_id: int
    rater_id: str
    confidence_score: float
    edit_distance: float
    user_rating: int
    routing_action: str
    channel: str
    trusted: bool
    sources: Optional[List[Dict[str, Any]]] = None

    @property
    def quadrant(self) -> str:
        approved = self.edit_distance == 0.0
        helpful = self.user_rating == 1
        if approved and helpful:
            return "A"
        if approved and not helpful:
            return "B"
        if not approved and helpful:
            return "C"
        return "D"

    @property
    def learning_action(self) -> str:
        if self.user_rating == 0:
            return "rejected"
        if self.edit_distance > 0:
            return "edited"
        return "approved"


class FeedbackOrchestrator:
    """Lane-B orchestration for trusted ratings."""

    QUADRANT_WEIGHTS: ClassVar[Dict[str, float]] = {
        "A": 1.0,
        "B": 3.0,
        "C": 1.5,
        "D": 5.0,
    }
    SOURCE_WEIGHT_DELTAS: ClassVar[Dict[str, float]] = {
        "A": 0.05,
        "B": -0.10,
        "C": 0.0,
        "D": -0.10,
    }

    def __init__(
        self,
        learning_engine,
        weight_manager=None,
        cross_validator=None,
        settings=None,
    ):
        self.learning_engine = learning_engine
        self.weight_manager = weight_manager
        self.cross_validator = cross_validator
        self._privacy_mode_enabled = bool(
            getattr(settings, "PII_DETECTION_ENABLED", False)
            or getattr(settings, "ENABLE_PRIVACY_MODE", False)
        )

    def record_user_rating(self, signal: StaffRatingSignal) -> None:
        """Record trusted user feedback to learning systems."""
        safe_message_id = str(signal.message_id)
        if self._privacy_mode_enabled:
            safe_message_id = safe_message_id[:8] if safe_message_id else "unknown"
        logger.info(
            "Processing staff rating signal: message=%s trusted=%s quadrant=%s",
            safe_message_id,
            signal.trusted,
            signal.quadrant,
        )
        if not signal.trusted:
            return
        self._feed_threshold_learning(signal)
        if self.weight_manager and signal.sources:
            self._feed_source_weight_learning(signal)
        if self.cross_validator:
            self.cross_validator.record(signal, signal.quadrant)

    def _feed_threshold_learning(self, signal: StaffRatingSignal) -> None:
        weight = self.QUADRANT_WEIGHTS[signal.quadrant]
        effective_conf = signal.confidence_score
        if signal.edit_distance > 0:
            effective_conf = signal.confidence_score * (
                1.0 - 0.5 * signal.edit_distance
            )
        question_id = f"user_rating_{signal.message_id}_{signal.rater_id}"
        count = max(1, round(weight))
        for _ in range(count):
            self.learning_engine.record_review(
                question_id=question_id,
                confidence=effective_conf,
                admin_action=signal.learning_action,
                routing_action=signal.routing_action,
                metadata={
                    "source": "user_rating",
                    "idempotent": True,
                    "channel": signal.channel,
                    "quadrant": signal.quadrant,
                    "edit_distance": signal.edit_distance,
                    "original_confidence": signal.confidence_score,
                    "user_rating": signal.user_rating,
                },
            )

    def _feed_source_weight_learning(self, signal: StaffRatingSignal) -> None:
        delta = self.SOURCE_WEIGHT_DELTAS[signal.quadrant]
        if signal.quadrant == "C":
            delta = 0.02 * (1.0 - signal.edit_distance)
        source_types = [
            source.get("type", source.get("source", "unknown"))
            for source in (signal.sources or [])
        ]
        source_types = [source_type for source_type in source_types if source_type]
        if not source_types:
            return

        if hasattr(self.weight_manager, "apply_quadrant_feedback"):
            for source_type in source_types:
                self.weight_manager.apply_quadrant_feedback(source_type, delta)
            return

        # Backward-compatible fallback
        feedback_entries = [
            {
                "rating": signal.user_rating,
                "sources_used": [{"type": source_type}],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            for source_type in source_types
        ]
        self.weight_manager.apply_feedback_weights(feedback_entries)
