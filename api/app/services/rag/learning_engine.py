"""Learning Engine for adaptive threshold tuning based on admin feedback."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class LearningEngine:
    """
    Learning engine that adjusts confidence thresholds based on admin review patterns.

    Uses historical admin decisions to optimize:
    - Auto-send threshold (default 95%)
    - Queue threshold (default 70%)
    - Reject threshold (default 50%)
    """

    def __init__(self):
        """Initialize learning engine with default thresholds."""
        # Current thresholds
        self.auto_send_threshold = 0.95
        self.queue_high_threshold = 0.70
        self.reject_threshold = 0.50

        # Learning parameters
        self.learning_rate = 0.01
        self.min_samples_for_update = 50
        self.confidence_interval = 0.95

        # Historical data storage
        self._review_history: List[Dict[str, Any]] = []
        self._threshold_history: List[Dict[str, Any]] = []

        # Save initial thresholds
        self._save_threshold_snapshot("initial")

    def _save_threshold_snapshot(self, reason: str) -> None:
        """Save current thresholds to history."""
        self._threshold_history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "auto_send": self.auto_send_threshold,
                "queue_high": self.queue_high_threshold,
                "reject": self.reject_threshold,
                "reason": reason,
            }
        )

    def record_review(
        self,
        question_id: str,
        confidence: float,
        admin_action: str,
        routing_action: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an admin review for learning.

        Args:
            question_id: Unique question identifier
            confidence: Model confidence score (0-1)
            admin_action: 'approved', 'edited', or 'rejected'
            routing_action: 'auto_send', 'queue_high', or 'queue_low'
            metadata: Optional additional metadata
        """
        review_record = {
            "question_id": question_id,
            "confidence": confidence,
            "admin_action": admin_action,
            "routing_action": routing_action,
            "metadata": metadata or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._review_history.append(review_record)

        logger.debug(
            f"Recorded review: {question_id} - {admin_action} at {confidence:.2f}"
        )

        # Check if we should update thresholds
        if len(self._review_history) >= self.min_samples_for_update:
            if len(self._review_history) % 10 == 0:  # Update every 10 reviews
                self._update_thresholds()

    def _update_thresholds(self) -> None:
        """Update thresholds based on review history."""
        if len(self._review_history) < self.min_samples_for_update:
            logger.info(
                f"Insufficient samples ({len(self._review_history)}) "
                f"for threshold update, need {self.min_samples_for_update}"
            )
            return

        # Analyze patterns
        approved_confidences = [
            r["confidence"]
            for r in self._review_history
            if r["admin_action"] == "approved"
        ]
        edited_confidences = [
            r["confidence"]
            for r in self._review_history
            if r["admin_action"] == "edited"
        ]
        rejected_confidences = [
            r["confidence"]
            for r in self._review_history
            if r["admin_action"] == "rejected"
        ]

        # Calculate optimal thresholds
        new_auto_send = self._calculate_auto_send_threshold(
            approved_confidences, edited_confidences, rejected_confidences
        )
        new_queue_high = self._calculate_queue_threshold(
            approved_confidences, edited_confidences, rejected_confidences
        )
        new_reject = self._calculate_reject_threshold(rejected_confidences)

        # Apply gradual updates using learning rate
        if new_auto_send is not None:
            old_auto_send = self.auto_send_threshold
            self.auto_send_threshold = (
                self.auto_send_threshold * (1 - self.learning_rate)
                + new_auto_send * self.learning_rate
            )
            logger.info(
                f"Updated auto_send threshold: {old_auto_send:.3f} → "
                f"{self.auto_send_threshold:.3f}"
            )

        if new_queue_high is not None:
            old_queue = self.queue_high_threshold
            self.queue_high_threshold = (
                self.queue_high_threshold * (1 - self.learning_rate)
                + new_queue_high * self.learning_rate
            )
            logger.info(
                f"Updated queue_high threshold: {old_queue:.3f} → "
                f"{self.queue_high_threshold:.3f}"
            )

        if new_reject is not None:
            old_reject = self.reject_threshold
            self.reject_threshold = (
                self.reject_threshold * (1 - self.learning_rate)
                + new_reject * self.learning_rate
            )
            logger.info(
                f"Updated reject threshold: {old_reject:.3f} → "
                f"{self.reject_threshold:.3f}"
            )

        self._save_threshold_snapshot("auto_update")

    def _calculate_auto_send_threshold(
        self,
        approved: List[float],
        edited: List[float],
        rejected: List[float],
    ) -> Optional[float]:
        """
        Calculate optimal auto-send threshold.

        Goal: Find confidence level where nearly all responses are approved without edit.
        """
        if not approved:
            return None

        # Find the confidence percentile where 95% of approved (unedited) were good
        approved_array = np.array(approved)

        # Calculate 5th percentile of approved responses
        # This means 95% of approved responses had confidence above this
        threshold = float(np.percentile(approved_array, 5))

        # Ensure threshold is reasonable (between 0.8 and 0.99)
        threshold = max(0.80, min(0.99, threshold))

        return threshold

    def _calculate_queue_threshold(
        self,
        approved: List[float],
        edited: List[float],
        rejected: List[float],
    ) -> Optional[float]:
        """
        Calculate optimal queue threshold.

        Goal: Find confidence level that separates high-priority (likely good) from
        low-priority (likely needs attention).
        """
        all_positive = approved + edited
        if not all_positive:
            return None

        positive_array = np.array(all_positive)

        # Find the 25th percentile of positive outcomes
        # Responses above this are likely acceptable (maybe with minor edits)
        threshold = float(np.percentile(positive_array, 25))

        # Ensure threshold is reasonable (between 0.5 and 0.9)
        threshold = max(0.50, min(0.90, threshold))

        return threshold

    def _calculate_reject_threshold(self, rejected: List[float]) -> Optional[float]:
        """
        Calculate optimal reject threshold.

        Goal: Find confidence level below which responses are usually rejected.
        """
        if not rejected or len(rejected) < 5:
            return None

        rejected_array = np.array(rejected)

        # Find the 75th percentile of rejected responses
        # Responses below this are likely to be rejected
        threshold = float(np.percentile(rejected_array, 75))

        # Ensure threshold is reasonable (between 0.3 and 0.7)
        threshold = max(0.30, min(0.70, threshold))

        return threshold

    def get_current_thresholds(self) -> Dict[str, float]:
        """Get current threshold values."""
        return {
            "auto_send_threshold": self.auto_send_threshold,
            "queue_high_threshold": self.queue_high_threshold,
            "reject_threshold": self.reject_threshold,
        }

    def get_routing_recommendation(self, confidence: float) -> str:
        """
        Get routing recommendation based on current thresholds.

        Args:
            confidence: Model confidence score

        Returns:
            Routing action: 'auto_send', 'queue_high', 'queue_low', or 'reject'
        """
        if confidence >= self.auto_send_threshold:
            return "auto_send"
        elif confidence >= self.queue_high_threshold:
            return "queue_high"
        elif confidence >= self.reject_threshold:
            return "queue_low"
        else:
            return "reject"

    def get_learning_metrics(self) -> Dict[str, Any]:
        """Get learning metrics for dashboard display."""
        if not self._review_history:
            return {
                "total_reviews": 0,
                "approval_rate": 0.0,
                "edit_rate": 0.0,
                "rejection_rate": 0.0,
                "threshold_updates": len(self._threshold_history),
            }

        total = len(self._review_history)
        approved = sum(
            1 for r in self._review_history if r["admin_action"] == "approved"
        )
        edited = sum(1 for r in self._review_history if r["admin_action"] == "edited")
        rejected = sum(
            1 for r in self._review_history if r["admin_action"] == "rejected"
        )

        # Calculate confidence distribution stats
        confidences = [r["confidence"] for r in self._review_history]
        conf_array = np.array(confidences)

        return {
            "total_reviews": total,
            "approval_rate": approved / total if total > 0 else 0.0,
            "edit_rate": edited / total if total > 0 else 0.0,
            "rejection_rate": rejected / total if total > 0 else 0.0,
            "threshold_updates": len(self._threshold_history),
            "avg_confidence": float(np.mean(conf_array)),
            "std_confidence": float(np.std(conf_array)),
            "min_confidence": float(np.min(conf_array)),
            "max_confidence": float(np.max(conf_array)),
        }

    def get_threshold_history(self) -> List[Dict[str, Any]]:
        """Get history of threshold changes."""
        return self._threshold_history.copy()

    def reset_learning(self) -> None:
        """Reset learning data and restore default thresholds."""
        self._review_history = []
        self._threshold_history = []
        self.auto_send_threshold = 0.95
        self.queue_high_threshold = 0.70
        self.reject_threshold = 0.50
        self._save_threshold_snapshot("reset")
        logger.info("Learning engine reset to defaults")

    def export_learning_data(self) -> Dict[str, Any]:
        """Export all learning data for backup or analysis."""
        return {
            "current_thresholds": self.get_current_thresholds(),
            "learning_metrics": self.get_learning_metrics(),
            "threshold_history": self._threshold_history,
            "review_count": len(self._review_history),
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }


class LaunchReadinessChecker:
    """
    Checker for determining if the system is ready for production launch.

    Evaluates multiple criteria based on shadow mode performance.
    """

    def __init__(self, learning_engine: LearningEngine):
        """Initialize with learning engine reference."""
        self.learning_engine = learning_engine

        # Launch criteria thresholds
        self.min_total_reviews = 100
        self.min_approval_rate = 0.80
        self.max_edit_rate = 0.15
        self.max_rejection_rate = 0.10
        self.min_avg_confidence = 0.70
        self.max_threshold_volatility = 0.05

    def check_readiness(self) -> Dict[str, Any]:
        """
        Check if system is ready for production launch.

        Returns:
            Dictionary with readiness status, score, and detailed criteria results
        """
        metrics = self.learning_engine.get_learning_metrics()
        thresholds = self.learning_engine.get_current_thresholds()
        history = self.learning_engine.get_threshold_history()

        # Calculate threshold volatility
        volatility = self._calculate_threshold_volatility(history)

        # Check individual criteria
        criteria = {
            "sufficient_data": {
                "passed": metrics["total_reviews"] >= self.min_total_reviews,
                "value": metrics["total_reviews"],
                "threshold": self.min_total_reviews,
                "description": "Minimum reviews collected",
            },
            "high_approval_rate": {
                "passed": metrics["approval_rate"] >= self.min_approval_rate,
                "value": metrics["approval_rate"],
                "threshold": self.min_approval_rate,
                "description": "Approval rate meets minimum",
            },
            "low_edit_rate": {
                "passed": metrics["edit_rate"] <= self.max_edit_rate,
                "value": metrics["edit_rate"],
                "threshold": self.max_edit_rate,
                "description": "Edit rate below maximum",
            },
            "low_rejection_rate": {
                "passed": metrics["rejection_rate"] <= self.max_rejection_rate,
                "value": metrics["rejection_rate"],
                "threshold": self.max_rejection_rate,
                "description": "Rejection rate below maximum",
            },
            "stable_thresholds": {
                "passed": volatility <= self.max_threshold_volatility,
                "value": volatility,
                "threshold": self.max_threshold_volatility,
                "description": "Threshold stability achieved",
            },
            "good_confidence": {
                "passed": metrics.get("avg_confidence", 0) >= self.min_avg_confidence,
                "value": metrics.get("avg_confidence", 0),
                "threshold": self.min_avg_confidence,
                "description": "Average confidence meets minimum",
            },
        }

        # Calculate overall readiness
        passed_criteria = sum(1 for c in criteria.values() if c["passed"])
        total_criteria = len(criteria)
        readiness_score = passed_criteria / total_criteria

        # Determine if ready for launch
        is_ready = all(c["passed"] for c in criteria.values())

        # Generate recommendations
        recommendations = []
        if not is_ready:
            for name, criterion in criteria.items():
                if not criterion["passed"]:
                    recommendations.append(
                        f"Improve {name}: current {criterion['value']:.2f}, "
                        f"need {criterion['threshold']:.2f}"
                    )

        return {
            "is_ready": is_ready,
            "readiness_score": readiness_score,
            "passed_criteria": passed_criteria,
            "total_criteria": total_criteria,
            "criteria": criteria,
            "recommendations": recommendations,
            "current_thresholds": thresholds,
            "metrics_summary": {
                "total_reviews": metrics["total_reviews"],
                "approval_rate": metrics["approval_rate"],
                "avg_confidence": metrics.get("avg_confidence", 0),
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def _calculate_threshold_volatility(self, history: List[Dict[str, Any]]) -> float:
        """Calculate how much thresholds have been changing."""
        if len(history) < 2:
            return 0.0

        # Calculate standard deviation of auto_send threshold over history
        auto_send_values = [h["auto_send"] for h in history]
        return float(np.std(auto_send_values))

    def get_launch_checklist(self) -> List[Dict[str, Any]]:
        """Get a checklist format of launch criteria."""
        readiness = self.check_readiness()
        checklist = []

        for name, criterion in readiness["criteria"].items():
            checklist.append(
                {
                    "item": criterion["description"],
                    "status": "pass" if criterion["passed"] else "fail",
                    "current": criterion["value"],
                    "required": criterion["threshold"],
                }
            )

        return checklist
