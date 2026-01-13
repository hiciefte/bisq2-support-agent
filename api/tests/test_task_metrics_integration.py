"""
Tests for task metrics persistence integration.

Tests the integration between Prometheus metrics and SQLite persistence.
"""

from unittest.mock import patch

import pytest
from app.core.config import Settings
from app.utils.task_metrics import (
    BISQ2_API_HEALTH_STATUS,
    BISQ2_API_LAST_CHECK_TIMESTAMP,
    BISQ2_API_RESPONSE_TIME,
    FAQ_EXTRACTION_FAQS_GENERATED,
    FAQ_EXTRACTION_LAST_RUN_STATUS,
    FAQ_EXTRACTION_MESSAGES_PROCESSED,
    FEEDBACK_PROCESSING_ENTRIES,
    FEEDBACK_PROCESSING_LAST_RUN_STATUS,
    WIKI_UPDATE_LAST_RUN_STATUS,
    WIKI_UPDATE_PAGES_PROCESSED,
    record_bisq2_api_health,
    record_faq_extraction_failure,
    record_faq_extraction_success,
    record_feedback_processing_failure,
    record_feedback_processing_success,
    record_wiki_update_failure,
    record_wiki_update_success,
    restore_metrics_from_database,
)
from app.utils.task_metrics_persistence import init_persistence


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide temporary database path for testing."""
    return tmp_path / "test_metrics.db"


@pytest.fixture
def test_settings(temp_db_path):
    """Provide test settings with temporary database."""
    settings = Settings()
    settings.DATA_DIR = str(temp_db_path.parent)  # Use uppercase DATA_DIR
    return settings


@pytest.fixture(autouse=True)
def setup_persistence(test_settings):
    """Initialize persistence before each test."""
    import os

    import app.utils.task_metrics_persistence as module

    # Clean up database file before test
    db_path = os.path.join(
        test_settings.DATA_DIR, "feedback.db"
    )  # Use uppercase DATA_DIR
    if os.path.exists(db_path):
        os.remove(db_path)

    init_persistence(test_settings)
    yield

    # Reset global instance and clean up after test
    module._persistence_instance = None
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset all Prometheus Gauge metrics before each test."""
    FAQ_EXTRACTION_LAST_RUN_STATUS.set(0)
    FAQ_EXTRACTION_MESSAGES_PROCESSED.set(0)
    FAQ_EXTRACTION_FAQS_GENERATED.set(0)
    WIKI_UPDATE_LAST_RUN_STATUS.set(0)
    WIKI_UPDATE_PAGES_PROCESSED.set(0)
    FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(0)
    FEEDBACK_PROCESSING_ENTRIES.set(0)
    BISQ2_API_HEALTH_STATUS.set(0)
    BISQ2_API_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_RESPONSE_TIME.set(0)


class TestFAQExtractionSuccess:
    """Test FAQ extraction success recording with persistence."""

    def test_records_success_status(self):
        """Should set success status gauge and persist to database."""
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)

        # Check Prometheus gauge
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 1

        # Check database persistence
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("faq_extraction_last_run_status") == 1.0

    def test_records_messages_processed(self):
        """Should set messages processed gauge and persist."""
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)

        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 42

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("faq_extraction_messages_processed") == 42.0

    def test_records_faqs_generated(self):
        """Should set FAQs generated gauge and persist."""
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)

        assert FAQ_EXTRACTION_FAQS_GENERATED._value.get() == 5

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("faq_extraction_faqs_generated") == 5.0

    def test_handles_zero_values(self):
        """Should correctly handle zero values."""
        record_faq_extraction_success(messages_processed=0, faqs_generated=0)

        # Gauges should still be set to 0
        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 0
        assert FAQ_EXTRACTION_FAQS_GENERATED._value.get() == 0

    def test_persists_all_metrics_atomically(self):
        """Should persist all FAQ metrics in single transaction."""
        record_faq_extraction_success(messages_processed=100, faqs_generated=10)

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        metrics = persistence.load_all_metrics()

        assert "faq_extraction_last_run_status" in metrics
        assert "faq_extraction_messages_processed" in metrics
        assert "faq_extraction_faqs_generated" in metrics


class TestFAQExtractionFailure:
    """Test FAQ extraction failure recording with persistence."""

    def test_records_failure_status(self):
        """Should set failure status and persist to database."""
        record_faq_extraction_failure()

        # Check Prometheus gauge
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 0

        # Check database persistence
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("faq_extraction_last_run_status") == 0.0

    def test_preserves_other_metrics_on_failure(self):
        """Should preserve messages/faqs metrics when failure occurs."""
        # First record success with metrics
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)

        # Then record failure
        record_faq_extraction_failure()

        # Status should be 0 (failure)
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 0

        # Other metrics should be preserved
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("faq_extraction_messages_processed") == 42.0
        assert persistence.load_metric("faq_extraction_faqs_generated") == 5.0


class TestWikiUpdateSuccess:
    """Test wiki update success recording with persistence."""

    def test_records_success_status(self):
        """Should set success status and persist."""
        record_wiki_update_success(pages_processed=150)

        assert WIKI_UPDATE_LAST_RUN_STATUS._value.get() == 1

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("wiki_update_last_run_status") == 1.0

    def test_records_pages_processed(self):
        """Should set pages processed and persist."""
        record_wiki_update_success(pages_processed=150)

        assert WIKI_UPDATE_PAGES_PROCESSED._value.get() == 150

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("wiki_update_pages_processed") == 150.0


class TestWikiUpdateFailure:
    """Test wiki update failure recording with persistence."""

    def test_records_failure_status(self):
        """Should set failure status and persist."""
        record_wiki_update_failure()

        assert WIKI_UPDATE_LAST_RUN_STATUS._value.get() == 0

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("wiki_update_last_run_status") == 0.0


class TestFeedbackProcessingSuccess:
    """Test feedback processing success recording with persistence."""

    def test_records_success_status(self):
        """Should set success status and persist."""
        record_feedback_processing_success(entries_processed=25)

        assert FEEDBACK_PROCESSING_LAST_RUN_STATUS._value.get() == 1

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("feedback_processing_last_run_status") == 1.0

    def test_records_entries_processed(self):
        """Should set entries processed and persist."""
        record_feedback_processing_success(entries_processed=25)

        assert FEEDBACK_PROCESSING_ENTRIES._value.get() == 25

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("feedback_processing_entries_processed") == 25.0


class TestFeedbackProcessingFailure:
    """Test feedback processing failure recording with persistence."""

    def test_records_failure_status(self):
        """Should set failure status and persist."""
        record_feedback_processing_failure()

        assert FEEDBACK_PROCESSING_LAST_RUN_STATUS._value.get() == 0

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("feedback_processing_last_run_status") == 0.0


class TestRestoreMetrics:
    """Test metrics restoration on application startup."""

    def test_restores_all_persisted_metrics(self):
        """Should restore all metrics from database on startup."""
        # Simulate previous run with metrics
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)
        record_wiki_update_success(pages_processed=150)
        record_feedback_processing_success(entries_processed=25)

        # Reset gauges to simulate container restart
        FAQ_EXTRACTION_LAST_RUN_STATUS.set(0)
        FAQ_EXTRACTION_MESSAGES_PROCESSED.set(0)
        FAQ_EXTRACTION_FAQS_GENERATED.set(0)
        WIKI_UPDATE_LAST_RUN_STATUS.set(0)
        WIKI_UPDATE_PAGES_PROCESSED.set(0)
        FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(0)
        FEEDBACK_PROCESSING_ENTRIES.set(0)

        # Restore from database
        restore_metrics_from_database()

        # Verify all metrics restored
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 1
        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 42
        assert FAQ_EXTRACTION_FAQS_GENERATED._value.get() == 5
        assert WIKI_UPDATE_LAST_RUN_STATUS._value.get() == 1
        assert WIKI_UPDATE_PAGES_PROCESSED._value.get() == 150
        assert FEEDBACK_PROCESSING_LAST_RUN_STATUS._value.get() == 1
        assert FEEDBACK_PROCESSING_ENTRIES._value.get() == 25

    def test_handles_empty_database(self):
        """Should handle restoration from empty database gracefully."""
        restore_metrics_from_database()  # Should not raise

        # Gauges should remain at default values
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 0
        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 0

    def test_handles_partial_metrics(self):
        """Should restore only available metrics."""
        # Save only FAQ metrics
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)

        # Reset all gauges
        FAQ_EXTRACTION_LAST_RUN_STATUS.set(0)
        FAQ_EXTRACTION_MESSAGES_PROCESSED.set(0)
        FAQ_EXTRACTION_FAQS_GENERATED.set(0)
        WIKI_UPDATE_LAST_RUN_STATUS.set(0)

        # Restore
        restore_metrics_from_database()

        # FAQ metrics should be restored
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 1
        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 42

        # Wiki metrics should remain at default
        assert WIKI_UPDATE_LAST_RUN_STATUS._value.get() == 0

    def test_restoration_is_idempotent(self):
        """Should safely restore multiple times without errors."""
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)

        restore_metrics_from_database()
        restore_metrics_from_database()  # Second call should not fail

        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 42


class TestPersistenceErrorHandling:
    """Test error handling in persistence operations."""

    def test_continues_on_persistence_failure(self):
        """Should not raise if persistence fails."""
        # Mock persistence to raise error
        with patch(
            "app.utils.task_metrics_persistence.get_persistence"
        ) as mock_get_persistence:
            mock_get_persistence.side_effect = Exception("Database error")

            # Should not raise - error should be logged
            record_faq_extraction_success(messages_processed=42, faqs_generated=5)

            # Prometheus gauges should still be updated
            assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 1
            assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 42

    def test_continues_on_restoration_failure(self):
        """Should not raise if restoration fails."""
        with patch(
            "app.utils.task_metrics_persistence.get_persistence"
        ) as mock_get_persistence:
            mock_get_persistence.side_effect = Exception("Database error")

            # Should not raise - warning should be logged
            restore_metrics_from_database()


class TestContainerRestartScenario:
    """Test complete container restart scenario."""

    def test_metrics_survive_restart(self):
        """Should preserve metrics across simulated container restart."""
        # Step 1: Initial run - record metrics
        record_faq_extraction_success(messages_processed=42, faqs_generated=5)
        record_wiki_update_success(pages_processed=150)

        # Verify metrics persisted to database
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        db_metrics = persistence.load_all_metrics()
        assert len(db_metrics) >= 5  # At least 5 FAQ/wiki metrics

        # Step 2: Simulate container restart - reset gauges to 0
        FAQ_EXTRACTION_LAST_RUN_STATUS.set(0)
        FAQ_EXTRACTION_MESSAGES_PROCESSED.set(0)
        FAQ_EXTRACTION_FAQS_GENERATED.set(0)
        WIKI_UPDATE_LAST_RUN_STATUS.set(0)
        WIKI_UPDATE_PAGES_PROCESSED.set(0)

        # Verify gauges are reset
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 0
        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 0

        # Step 3: Application startup - restore from database
        restore_metrics_from_database()

        # Step 4: Verify metrics restored
        assert FAQ_EXTRACTION_LAST_RUN_STATUS._value.get() == 1
        assert FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get() == 42
        assert FAQ_EXTRACTION_FAQS_GENERATED._value.get() == 5
        assert WIKI_UPDATE_LAST_RUN_STATUS._value.get() == 1
        assert WIKI_UPDATE_PAGES_PROCESSED._value.get() == 150


class TestBisq2APIHealthMetrics:
    """Test bisq2 API health recording with persistence.

    This test class ensures that bisq2_api health metrics are properly
    persisted when the persistence layer is initialized. This addresses
    the bug where extract_faqs.py didn't initialize persistence, causing
    bisq2_api metrics to silently fail to persist.
    """

    def test_records_healthy_status(self):
        """Should set healthy status (1) and persist to database."""
        record_bisq2_api_health(is_healthy=True, response_time=0.5)

        # Check Prometheus gauge
        assert BISQ2_API_HEALTH_STATUS._value.get() == 1

        # Check database persistence
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("bisq2_api_health_status") == 1.0

    def test_records_unhealthy_status(self):
        """Should set unhealthy status (0) and persist to database."""
        record_bisq2_api_health(is_healthy=False)

        # Check Prometheus gauge
        assert BISQ2_API_HEALTH_STATUS._value.get() == 0

        # Check database persistence
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("bisq2_api_health_status") == 0.0

    def test_records_response_time(self):
        """Should set response time gauge and persist."""
        record_bisq2_api_health(is_healthy=True, response_time=0.123)

        assert BISQ2_API_RESPONSE_TIME._value.get() == 0.123

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        # Metric name includes _seconds suffix in database
        assert persistence.load_metric("bisq2_api_response_time_seconds") == 0.123

    def test_records_timestamp(self):
        """Should set timestamp gauge and persist."""
        import time

        before_time = time.time()
        record_bisq2_api_health(is_healthy=True, response_time=0.5)
        after_time = time.time()

        # Timestamp should be between before and after
        timestamp = BISQ2_API_LAST_CHECK_TIMESTAMP._value.get()
        assert before_time <= timestamp <= after_time

        # Check persistence
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        persisted_timestamp = persistence.load_metric("bisq2_api_last_check_timestamp")
        assert before_time <= persisted_timestamp <= after_time

    def test_persists_all_metrics_atomically(self):
        """Should persist all bisq2_api metrics together."""
        record_bisq2_api_health(is_healthy=True, response_time=0.25)

        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        metrics = persistence.load_all_metrics()

        assert "bisq2_api_health_status" in metrics
        # Metric name includes _seconds suffix in database
        assert "bisq2_api_response_time_seconds" in metrics
        assert "bisq2_api_last_check_timestamp" in metrics

    def test_handles_none_response_time(self):
        """Should handle None response time gracefully."""
        record_bisq2_api_health(is_healthy=False, response_time=None)

        # Status should be set
        assert BISQ2_API_HEALTH_STATUS._value.get() == 0

        # Response time should remain at 0 (not updated)
        # Note: The function only updates response_time if it's not None
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("bisq2_api_health_status") == 0.0

    def test_health_metrics_survive_restart(self):
        """Should preserve bisq2_api metrics across simulated container restart."""
        # Step 1: Record healthy status
        record_bisq2_api_health(is_healthy=True, response_time=0.5)

        # Verify persisted
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        assert persistence.load_metric("bisq2_api_health_status") == 1.0

        # Step 2: Simulate container restart - reset gauges
        BISQ2_API_HEALTH_STATUS.set(0)
        BISQ2_API_RESPONSE_TIME.set(0)
        BISQ2_API_LAST_CHECK_TIMESTAMP.set(0)

        assert BISQ2_API_HEALTH_STATUS._value.get() == 0

        # Step 3: Restore from database
        restore_metrics_from_database()

        # Step 4: Verify metrics restored
        assert BISQ2_API_HEALTH_STATUS._value.get() == 1
        assert BISQ2_API_RESPONSE_TIME._value.get() == 0.5
