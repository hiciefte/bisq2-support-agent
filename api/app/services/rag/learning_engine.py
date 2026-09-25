"""Review audit history and threshold calibration from actual answer judgments."""

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

# Import shared threshold constants from central config
from app.core.config import (
    PIPELINE_AUTO_APPROVE_THRESHOLD,
    PIPELINE_SPOT_CHECK_THRESHOLD,
)

# Import metrics for recording learning engine activity
from app.metrics.training_metrics import (
    learning_reviews_total,
    learning_threshold_updates,
    update_learning_thresholds,
)

logger = logging.getLogger(__name__)


class LearningEngine:
    """
    Adjust confidence thresholds using distinct, explicitly judged answers.

    Knowledge decisions remain audit history, but cannot calibrate delivery.
    Loading historical thresholds does not prove they were calibrated this way;
    existing values and history are preserved for separately reviewed migration.

    Uses historical admin decisions to optimize:
    - Auto-send threshold (default 95%)
    - Queue threshold (default 70%)
    - Reject threshold (default 50%)
    """

    def __init__(self, repository: Optional[Any] = None):
        """Initialize learning engine with default thresholds.

        Default thresholds are sourced from central config constants:
        - auto_send_threshold: PIPELINE_AUTO_APPROVE_THRESHOLD (0.90)
        - queue_high_threshold: PIPELINE_SPOT_CHECK_THRESHOLD (0.75)

        Args:
            repository: Optional repository for automatic state persistence.
                        If provided, state is loaded on init and saved after
                        each threshold update. Should have save_learning_state()
                        and get_learning_state() methods.
        """
        # Store repository for auto-persistence
        self._repository = repository

        # Current thresholds - sourced from central config for consistency
        self.auto_send_threshold = PIPELINE_AUTO_APPROVE_THRESHOLD
        self.queue_high_threshold = PIPELINE_SPOT_CHECK_THRESHOLD
        self.reject_threshold = 0.50

        # Learning parameters
        self.learning_rate = 0.01
        self.min_samples_for_update = 50
        self.confidence_interval = 0.95

        # Historical data storage
        self._review_history: List[Dict[str, Any]] = []
        self._threshold_history: List[Dict[str, Any]] = []

        # Load state from repository if provided
        if self._repository is not None:
            self.load_state(self._repository)

        # Save initial thresholds snapshot (if not loaded from repository)
        if not self._threshold_history:
            self._save_threshold_snapshot("initial")

    def _save_threshold_snapshot(self, reason: str) -> None:
        """Save current thresholds to history and persist to repository if available."""
        self._threshold_history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "auto_send": self.auto_send_threshold,
                "queue_high": self.queue_high_threshold,
                "reject": self.reject_threshold,
                "reason": reason,
            }
        )

        # Auto-persist to repository if available (skip for initial snapshot)
        if self._repository is not None and reason != "initial":
            self._auto_persist()

    def _auto_persist(self) -> None:
        """Automatically persist state to repository.

        Called after threshold updates when a repository is configured.
        Errors are logged but do not raise exceptions to prevent disruption.
        """
        if self._repository is None:
            return

        try:
            self._repository.save_learning_state(
                auto_send_threshold=self.auto_send_threshold,
                queue_high_threshold=self.queue_high_threshold,
                reject_threshold=self.reject_threshold,
                review_history=self.bounded_review_history(self._review_history),
                threshold_history=self._threshold_history,
            )
            logger.debug("LearningEngine state auto-persisted to repository")
        except Exception as e:
            logger.warning(f"Failed to auto-persist LearningEngine state: {e}")

    def record_review(
        self,
        question_id: str,
        confidence: float,
        admin_action: str,
        routing_action: str,
        metadata: Optional[Dict[str, Any]] = None,
        weight: float = 1.0,
    ) -> None:
        """
        Record a review; only answer-quality judgments calibrate thresholds.

        Args:
            question_id: Unique question identifier
            confidence: Model confidence score (0-1)
            admin_action: 'approved', 'edited', or 'rejected'
            routing_action: 'auto_send', 'queue_high', or 'queue_low'
            metadata: Use review_kind='answer_quality' only for an actual answer
                judgment; calibration_question_id identifies the question across
                raters. Knowledge decisions and unknown legacy rows are audit only.
            weight: Relative review weight used for threshold percentiles
        """
        metadata_dict: Dict[str, Any] = dict(metadata or {})
        previous_samples = self._calibration_reviews()
        normalized_action = self._normalize_admin_action(admin_action)
        try:
            review_weight = float(weight)
        except (TypeError, ValueError):
            review_weight = 1.0
        if not math.isfinite(review_weight) or review_weight <= 0:
            review_weight = 1.0

        review_record = {
            "question_id": question_id,
            "confidence": confidence,
            "admin_action": normalized_action,
            "routing_action": routing_action,
            "metadata": metadata_dict,
            "weight": review_weight,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        replaced = False
        if metadata_dict.get("idempotent"):
            for i in range(len(self._review_history) - 1, -1, -1):
                existing = self._review_history[i]
                if existing.get("question_id") == question_id and self._review_kind(
                    existing
                ) == self._review_kind(review_record):
                    self._review_history.pop(i)
                    self._review_history.append(review_record)
                    replaced = True
                    break
        if not replaced:
            self._review_history.append(review_record)

        # Record metrics for admin review
        learning_reviews_total.labels(admin_action=normalized_action).inc()

        logger.debug(
            "Recorded review%s: %s - %s at %.2f",
            " (replaced)" if replaced else "",
            question_id,
            normalized_action,
            confidence,
        )

        self._auto_persist()

        # Audit events and duplicate identical judgments must not trigger updates.
        samples = self._calibration_reviews()
        if (
            self._sample_signature(samples) != self._sample_signature(previous_samples)
            and len(samples) >= self.min_samples_for_update
        ):
            # Every ten distinct answers, or a changed judgment of an existing one.
            if len(samples) == len(previous_samples) or len(samples) % 10 == 0:
                self._update_thresholds()

    @staticmethod
    def _review_kind(review: Dict[str, Any]) -> str:
        metadata = review.get("metadata") or {}
        if metadata.get("review_kind") is not None:
            return str(metadata["review_kind"])
        # Legacy escalation and rating callers also recorded staff-only replies.
        # Their metadata cannot establish that an AI answer existed. Keep those
        # rows as audit evidence unless an independent review explicitly marks
        # answer quality; never infer eligibility from their shape or action.
        return "unclassified"

    @classmethod
    def bounded_review_history(
        cls, reviews: List[Dict[str, Any]], per_kind_limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Preserve separate bounded quality/audit cohorts in their original order.

        Knowledge audit churn must not evict answer-quality history at persistence.
        This retains rows without relabeling them or changing stored thresholds.
        """
        counts = {True: 0, False: 0}
        retained = []
        for review in reversed(reviews):
            quality = cls._review_kind(review) == "answer_quality"
            if counts[quality] < per_kind_limit:
                retained.append(review)
                counts[quality] += 1
        return list(reversed(retained))

    @classmethod
    def _calibration_key(cls, review: Dict[str, Any]) -> Optional[str]:
        if cls._review_kind(review) != "answer_quality":
            return None
        metadata = review.get("metadata") or {}
        subject = metadata.get("calibration_question_id")
        if isinstance(subject, str) and subject.strip():
            return subject
        question_id = str(review.get("question_id") or "")
        escalation = re.fullmatch(r"escalation_(\d+)", question_id)
        if escalation:
            return "escalation:" + escalation[1]
        answer_rating = re.fullmatch(r"answer_rating:(\d+):.+", question_id)
        if answer_rating:
            return "candidate:" + answer_rating[1]
        if metadata.get("source") == "user_rating":
            # Legacy message+rater concatenation cannot reliably identify the
            # underlying question. Retain the audit row without inflating n.
            return None
        return "question:" + question_id if question_id else None

    def _calibration_reviews(self) -> List[Dict[str, Any]]:
        """Latest judgment per question, without changing persisted audit rows."""
        latest: Dict[str, Dict[str, Any]] = {}
        timestamps: Dict[str, Optional[datetime]] = {}
        for review in self._review_history:
            key = self._calibration_key(review)
            if key is not None:
                try:
                    timestamp = datetime.fromisoformat(
                        review["timestamp"].replace("Z", "+00:00")
                    )
                    timestamp = (
                        timestamp.replace(tzinfo=timezone.utc)
                        if timestamp.tzinfo is None
                        else timestamp
                    )
                except (KeyError, TypeError, ValueError, AttributeError):
                    timestamp = None
                previous = timestamps.get(key)
                if (
                    timestamp is not None
                    and previous is not None
                    and timestamp < previous
                ):
                    continue
                latest[key] = review
                timestamps[key] = timestamp
        samples = []
        for key, review in latest.items():
            try:
                confidence = float(review["confidence"])
                weight = float(review.get("weight", 1.0))
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not math.isfinite(confidence)
                or not 0 <= confidence <= 1
                or not math.isfinite(weight)
                or weight <= 0
                or review.get("admin_action")
                not in {
                    "approved",
                    "edited",
                    "rejected",
                    "answer_approved",
                    "answer_rejected",
                }
            ):
                continue
            samples.append(
                {
                    **review,
                    "calibration_question_id": key,
                    "confidence": confidence,
                    "weight": weight,
                    "admin_action": self._normalize_admin_action(
                        review["admin_action"]
                    ),
                }
            )
        return samples

    @staticmethod
    def _sample_signature(samples: List[Dict[str, Any]]) -> List[tuple]:
        return sorted(
            (
                r["calibration_question_id"],
                r["confidence"],
                r["admin_action"],
                r["weight"],
            )
            for r in samples
        )

    def has_sufficient_calibration_samples(self) -> bool:
        return len(self._calibration_reviews()) >= self.min_samples_for_update

    def get_calibration_metrics(self) -> Dict[str, Any]:
        """Metrics for the distinct answer cohort used by routing and readiness."""
        samples = self._calibration_reviews()
        total = len(samples)
        return {
            "total_reviews": total,
            **{
                name: (
                    sum(r["admin_action"] == action for r in samples) / total
                    if total
                    else 0.0
                )
                for name, action in (
                    ("approval_rate", "approved"),
                    ("edit_rate", "edited"),
                    ("rejection_rate", "rejected"),
                )
            },
            "avg_confidence": (
                sum(r["confidence"] for r in samples) / total if total else 0.0
            ),
        }

    def _update_thresholds(self) -> None:
        """Update only from the eligible, deduplicated answer-quality cohort."""
        samples = self._calibration_reviews()
        if len(samples) < self.min_samples_for_update:
            logger.info(
                f"Insufficient answer-quality samples ({len(samples)}) "
                f"for threshold update, need {self.min_samples_for_update}"
            )
            return

        # Analyze patterns
        approved_reviews = [r for r in samples if r["admin_action"] == "approved"]
        edited_reviews = [r for r in samples if r["admin_action"] == "edited"]
        rejected_reviews = [r for r in samples if r["admin_action"] == "rejected"]
        approved_confidences = [r["confidence"] for r in approved_reviews]
        edited_confidences = [r["confidence"] for r in edited_reviews]
        rejected_confidences = [r["confidence"] for r in rejected_reviews]
        approved_weights = [float(r.get("weight", 1.0)) for r in approved_reviews]
        edited_weights = [float(r.get("weight", 1.0)) for r in edited_reviews]
        rejected_weights = [float(r.get("weight", 1.0)) for r in rejected_reviews]

        # Calculate optimal thresholds
        new_auto_send = self._calculate_auto_send_threshold(
            approved_confidences,
            edited_confidences,
            rejected_confidences,
            approved_weights=approved_weights,
        )
        new_queue_high = self._calculate_queue_threshold(
            approved_confidences,
            edited_confidences,
            rejected_confidences,
            approved_weights=approved_weights,
            edited_weights=edited_weights,
        )
        new_reject = self._calculate_reject_threshold(
            rejected_confidences, rejected_weights=rejected_weights
        )

        # Apply gradual updates using learning rate
        if new_auto_send is not None:
            old_auto_send = self.auto_send_threshold
            self.auto_send_threshold = (
                self.auto_send_threshold * (1 - self.learning_rate)
                + new_auto_send * self.learning_rate
            )
            learning_threshold_updates.labels(threshold_type="auto_send").inc()
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
            learning_threshold_updates.labels(threshold_type="queue_high").inc()
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
            learning_threshold_updates.labels(threshold_type="reject").inc()
            logger.info(
                f"Updated reject threshold: {old_reject:.3f} → "
                f"{self.reject_threshold:.3f}"
            )

        # Update threshold gauge metrics with current values
        update_learning_thresholds(
            auto_send=self.auto_send_threshold,
            queue_high=self.queue_high_threshold,
            reject=self.reject_threshold,
        )

        self._save_threshold_snapshot("auto_update")

    def _calculate_auto_send_threshold(
        self,
        approved: List[float],
        edited: List[float],
        rejected: List[float],
        approved_weights: Optional[List[float]] = None,
    ) -> Optional[float]:
        """
        Calculate optimal auto-send threshold.

        Goal: Find confidence level where nearly all responses are approved without edit.
        """
        if not approved:
            return None

        # Find the confidence percentile where 95% of approved (unedited) were good
        # Calculate 5th percentile of approved responses
        # This means 95% of approved responses had confidence above this
        threshold = self._weighted_percentile(approved, 5, approved_weights)

        # Ensure threshold is reasonable (between 0.8 and 0.99)
        threshold = max(0.80, min(0.99, threshold))

        return threshold

    def _calculate_queue_threshold(
        self,
        approved: List[float],
        edited: List[float],
        rejected: List[float],
        approved_weights: Optional[List[float]] = None,
        edited_weights: Optional[List[float]] = None,
    ) -> Optional[float]:
        """
        Calculate optimal queue threshold.

        Goal: Find confidence level that separates high-priority (likely good) from
        low-priority (likely needs attention).
        """
        all_positive = approved + edited
        if not all_positive:
            return None
        positive_weights: Optional[List[float]] = None
        if approved_weights is not None or edited_weights is not None:
            positive_weights = (approved_weights or [1.0] * len(approved)) + (
                edited_weights or [1.0] * len(edited)
            )

        # Find the 25th percentile of positive outcomes
        # Responses above this are likely acceptable (maybe with minor edits)
        threshold = self._weighted_percentile(all_positive, 25, positive_weights)

        # Ensure threshold is reasonable (between 0.5 and 0.9)
        threshold = max(0.50, min(0.90, threshold))

        return threshold

    def _calculate_reject_threshold(
        self, rejected: List[float], rejected_weights: Optional[List[float]] = None
    ) -> Optional[float]:
        """
        Calculate optimal reject threshold.

        Goal: Find confidence level below which responses are usually rejected.
        """
        if not rejected or len(rejected) < 5:
            return None

        # Find the 75th percentile of rejected responses
        # Responses below this are likely to be rejected
        threshold = self._weighted_percentile(rejected, 75, rejected_weights)

        # Ensure threshold is reasonable (between 0.3 and 0.7)
        threshold = max(0.30, min(0.70, threshold))

        return threshold

    @staticmethod
    def _weighted_percentile(
        values: List[float], percentile: float, weights: Optional[List[float]] = None
    ) -> float:
        if not values:
            raise ValueError("values must not be empty")
        pairs = []
        effective_weights = weights if weights is not None else [1.0] * len(values)
        for value, weight in zip(values, effective_weights, strict=False):
            try:
                numeric_weight = float(weight)
            except (TypeError, ValueError):
                numeric_weight = 1.0
            pairs.append((float(value), max(0.0, numeric_weight)))

        if len(pairs) != len(values) or sum(weight for _, weight in pairs) <= 0:
            pairs = [(float(value), 1.0) for value in values]

        target = (percentile / 100.0) * sum(weight for _, weight in pairs)
        cumulative = 0.0
        for value, weight in sorted(pairs, key=lambda pair: pair[0]):
            cumulative += weight
            if cumulative >= target:
                return value
        return sorted(pairs, key=lambda pair: pair[0])[-1][0]

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
            Routing action: 'AUTO_APPROVE', 'SPOT_CHECK', or 'FULL_REVIEW'
            (matches pipeline routing constants)
        """
        if confidence >= self.auto_send_threshold:
            return "AUTO_APPROVE"
        elif confidence >= self.queue_high_threshold:
            return "SPOT_CHECK"
        else:
            return "FULL_REVIEW"

    def get_learning_metrics(self) -> Dict[str, Any]:
        """Get learning metrics for dashboard display.

        P5: Added error handling for edge cases (empty arrays, NaN values).
        """
        if not self._review_history:
            return {
                "total_reviews": 0,
                "approval_rate": 0.0,
                "edit_rate": 0.0,
                "rejection_rate": 0.0,
                "threshold_updates": len(self._threshold_history),
                "faq_reviews_total": 0,
                "answer_quality_reviews_total": 0,
                "answer_quality_good_rate": 0.0,
                "answer_quality_needs_work_rate": 0.0,
            }

        faq_reviews = [
            r for r in self._review_history if self._review_kind(r) != "answer_quality"
        ]
        answer_quality_reviews = [
            r for r in self._review_history if self._review_kind(r) == "answer_quality"
        ]

        total = len(faq_reviews)
        approved = sum(1 for r in faq_reviews if r["admin_action"] == "approved")
        edited = sum(1 for r in faq_reviews if r["admin_action"] == "edited")
        rejected = sum(1 for r in faq_reviews if r["admin_action"] == "rejected")
        quality_total = len(answer_quality_reviews)
        quality_good = sum(
            1 for r in answer_quality_reviews if r["admin_action"] == "approved"
        )
        quality_needs_work = sum(
            1 for r in answer_quality_reviews if r["admin_action"] == "rejected"
        )

        # Calculate confidence distribution stats with error handling (P5)
        try:
            confidences = [
                r["confidence"]
                for r in self._review_history
                if r.get("confidence") is not None
            ]

            if confidences:
                conf_array = np.array(confidences, dtype=float)
                # Filter out any NaN values
                conf_array = conf_array[~np.isnan(conf_array)]

                if len(conf_array) > 0:
                    avg_confidence = float(np.mean(conf_array))
                    std_confidence = float(np.std(conf_array))
                    min_confidence = float(np.min(conf_array))
                    max_confidence = float(np.max(conf_array))
                else:
                    avg_confidence = None
                    std_confidence = None
                    min_confidence = None
                    max_confidence = None
            else:
                avg_confidence = None
                std_confidence = None
                min_confidence = None
                max_confidence = None
        except (ValueError, TypeError) as e:
            logger.warning(f"Error calculating confidence stats: {e}")
            avg_confidence = None
            std_confidence = None
            min_confidence = None
            max_confidence = None

        return {
            "total_reviews": len(self._review_history),
            "approval_rate": approved / total if total > 0 else 0.0,
            "edit_rate": edited / total if total > 0 else 0.0,
            "rejection_rate": rejected / total if total > 0 else 0.0,
            "threshold_updates": len(self._threshold_history),
            "avg_confidence": avg_confidence,
            "std_confidence": std_confidence,
            "min_confidence": min_confidence,
            "max_confidence": max_confidence,
            "faq_reviews_total": total,
            "answer_quality_reviews_total": quality_total,
            "answer_quality_good_rate": (
                quality_good / quality_total if quality_total > 0 else 0.0
            ),
            "answer_quality_needs_work_rate": (
                quality_needs_work / quality_total if quality_total > 0 else 0.0
            ),
        }

    @staticmethod
    def _normalize_admin_action(admin_action: str) -> str:
        """Normalize historical action aliases to approved/edited/rejected."""
        normalized = str(admin_action or "").strip().lower()
        if normalized == "answer_approved":
            return "approved"
        if normalized == "answer_rejected":
            return "rejected"
        if normalized in {"approved", "edited", "rejected"}:
            return normalized
        return "rejected"

    def get_threshold_history(self) -> List[Dict[str, Any]]:
        """Get history of threshold changes."""
        return self._threshold_history.copy()

    def prune_review_history_before(
        self,
        cutoff: datetime,
        *,
        dry_run: bool = False,
    ) -> int:
        """Remove review records older than ``cutoff`` without touching aggregates.

        Records with missing or malformed timestamps are retained for operator
        review because their age cannot be proven. A record exactly at the cutoff
        is retained.
        """
        effective_cutoff = (
            cutoff.replace(tzinfo=timezone.utc)
            if cutoff.tzinfo is None
            else cutoff.astimezone(timezone.utc)
        )

        def is_retained(review: Dict[str, Any]) -> bool:
            raw_timestamp = review.get("timestamp")
            if not isinstance(raw_timestamp, str):
                return True
            try:
                timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            except ValueError:
                return True
            timestamp = (
                timestamp.replace(tzinfo=timezone.utc)
                if timestamp.tzinfo is None
                else timestamp.astimezone(timezone.utc)
            )
            return timestamp >= effective_cutoff

        retained = [review for review in self._review_history if is_retained(review)]
        deleted = len(self._review_history) - len(retained)
        if deleted and not dry_run:
            self._review_history = retained
            self._auto_persist()
        return deleted

    def reset_learning(self) -> None:
        """Reset learning data and restore default thresholds."""
        self._review_history = []
        self._threshold_history = []
        self.auto_send_threshold = PIPELINE_AUTO_APPROVE_THRESHOLD
        self.queue_high_threshold = PIPELINE_SPOT_CHECK_THRESHOLD
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

    def save_state(self, repository: Any) -> bool:
        """Save learning engine state to database via repository.

        Args:
            repository: KnowledgeCandidateRepository with save_learning_state method

        Returns:
            True if save succeeded, False otherwise (P5: error handling)
        """
        try:
            repository.save_learning_state(
                auto_send_threshold=self.auto_send_threshold,
                queue_high_threshold=self.queue_high_threshold,
                reject_threshold=self.reject_threshold,
                review_history=self.bounded_review_history(self._review_history),
                threshold_history=self._threshold_history,
            )
            logger.info(
                f"LearningEngine state saved: thresholds={self.get_current_thresholds()}, "
                f"reviews={len(self._review_history)}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save LearningEngine state: {e}")
            return False

    def load_state(self, repository: Any) -> None:
        """Load learning engine state from database via repository.

        Args:
            repository: KnowledgeCandidateRepository with get_learning_state method
        """
        state = repository.get_learning_state()
        if state is None:
            logger.info("No saved learning state found, using defaults")
            return

        # Preserve saved values, including those produced before cohort separation.
        # Excluding ambiguous history does not undo historical threshold changes.
        # Any reset/recalibration is a separate operator decision, never a load side effect.
        self.auto_send_threshold = state.get(
            "auto_send_threshold", self.auto_send_threshold
        )
        self.queue_high_threshold = state.get(
            "queue_high_threshold", self.queue_high_threshold
        )
        self.reject_threshold = state.get("reject_threshold", self.reject_threshold)

        # Load history
        self._review_history = state.get("review_history", [])
        self._threshold_history = state.get("threshold_history", [])

        logger.info(
            f"LearningEngine state loaded: thresholds={self.get_current_thresholds()}, "
            f"reviews={len(self._review_history)}"
        )


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
        metrics = self.learning_engine.get_calibration_metrics()
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
                "description": "Minimum distinct answer-quality reviews collected",
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
