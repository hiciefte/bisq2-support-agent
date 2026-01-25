"""
TDD Tests for Training Pipeline Metrics.

Tests for LearningEngine metrics, duplicate detection metrics,
and post-approval correction metrics.
"""


class TestLearningEngineMetrics:
    """Tests for LearningEngine threshold update metrics."""

    def test_threshold_update_counter_exists(self):
        """Metric for threshold updates should exist."""
        from app.metrics.training_metrics import learning_threshold_updates

        assert learning_threshold_updates is not None
        # Counter should have labels for threshold type
        assert "threshold_type" in [
            label for label in learning_threshold_updates._labelnames
        ]

    def test_threshold_update_is_recorded(self):
        """Threshold updates should increment the counter."""
        from app.metrics.training_metrics import learning_threshold_updates

        # Get initial value
        initial_value = learning_threshold_updates.labels(
            threshold_type="auto_send"
        )._value.get()

        # Increment
        learning_threshold_updates.labels(threshold_type="auto_send").inc()

        # Verify increment
        new_value = learning_threshold_updates.labels(
            threshold_type="auto_send"
        )._value.get()
        assert new_value == initial_value + 1

    def test_threshold_value_gauge_exists(self):
        """Gauge for current threshold values should exist."""
        from app.metrics.training_metrics import learning_current_thresholds

        assert learning_current_thresholds is not None
        # Gauge should have labels for threshold type
        assert "threshold_type" in [
            label for label in learning_current_thresholds._labelnames
        ]

    def test_learning_reviews_counter_exists(self):
        """Counter for learning reviews should exist."""
        from app.metrics.training_metrics import learning_reviews_total

        assert learning_reviews_total is not None
        # Counter should have labels for admin_action
        assert "admin_action" in [label for label in learning_reviews_total._labelnames]


class TestDuplicateDetectionMetrics:
    """Tests for duplicate FAQ detection metrics."""

    def test_duplicate_detection_counter_exists(self):
        """Counter for duplicate detections should exist."""
        from app.metrics.training_metrics import training_duplicate_detections

        assert training_duplicate_detections is not None

    def test_duplicate_detection_increments(self):
        """Duplicate detection should increment counter."""
        from app.metrics.training_metrics import training_duplicate_detections

        initial = training_duplicate_detections._value.get()
        training_duplicate_detections.inc()
        assert training_duplicate_detections._value.get() == initial + 1

    def test_duplicate_similarity_histogram_exists(self):
        """Histogram for duplicate similarity scores should exist."""
        from app.metrics.training_metrics import training_duplicate_similarity_scores

        assert training_duplicate_similarity_scores is not None


class TestPostApprovalCorrectionMetrics:
    """Tests for post-approval correction metrics."""

    def test_post_approval_correction_counter_exists(self):
        """Counter for post-approval corrections should exist."""
        from app.metrics.training_metrics import training_post_approval_corrections

        assert training_post_approval_corrections is not None

    def test_correction_resolution_counter_exists(self):
        """Counter for correction resolutions should exist."""
        from app.metrics.training_metrics import training_correction_resolutions

        assert training_correction_resolutions is not None
        # Should have action label (update, confirm, delete)
        assert "action" in [
            label for label in training_correction_resolutions._labelnames
        ]


class TestMetricsHelperFunctions:
    """Tests for metrics helper functions."""

    def test_update_learning_thresholds_function_exists(self):
        """Helper function to update learning thresholds should exist."""
        from app.metrics.training_metrics import update_learning_thresholds

        assert callable(update_learning_thresholds)

    def test_update_learning_thresholds_sets_gauges(self):
        """update_learning_thresholds should set gauge values."""
        from app.metrics.training_metrics import (
            learning_current_thresholds,
            update_learning_thresholds,
        )

        # Update thresholds
        update_learning_thresholds(
            auto_send=0.92,
            queue_high=0.78,
            reject=0.45,
        )

        # Verify gauges are set
        assert (
            learning_current_thresholds.labels(threshold_type="auto_send")._value.get()
            == 0.92
        )
        assert (
            learning_current_thresholds.labels(threshold_type="queue_high")._value.get()
            == 0.78
        )
        assert (
            learning_current_thresholds.labels(threshold_type="reject")._value.get()
            == 0.45
        )

    def test_record_duplicate_detection_function_exists(self):
        """Helper function to record duplicate detection should exist."""
        from app.metrics.training_metrics import record_duplicate_detection

        assert callable(record_duplicate_detection)
