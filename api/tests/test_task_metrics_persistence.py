"""
Tests for task metrics persistence layer.

Following TDD approach - these tests drive the implementation requirements.
"""

import sqlite3
import time
from pathlib import Path

import pytest
from app.core.config import Settings
from app.metrics.task_metrics import (
    FAQ_EXTRACTION_FAQS_GENERATED,
    FAQ_EXTRACTION_LAST_RUN_STATUS,
    FAQ_EXTRACTION_MESSAGES_PROCESSED,
    FEEDBACK_PROCESSING_ENTRIES,
    FEEDBACK_PROCESSING_LAST_RUN_STATUS,
    WIKI_UPDATE_LAST_RUN_STATUS,
    WIKI_UPDATE_PAGES_PROCESSED,
)
from app.utils.task_metrics_persistence import (
    TaskMetricsPersistence,
    get_persistence,
    init_persistence,
)


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


@pytest.fixture
def persistence(test_settings):
    """Provide initialized persistence instance."""
    return TaskMetricsPersistence(test_settings)


@pytest.fixture(autouse=True)
def reset_global_instance(test_settings):
    """Reset global persistence instance and clean database before each test."""
    import os

    import app.utils.task_metrics_persistence as module

    module._persistence_instance = None

    # Clean up database file if it exists
    db_path = os.path.join(
        test_settings.DATA_DIR, "feedback.db"
    )  # Use uppercase DATA_DIR
    if os.path.exists(db_path):
        os.remove(db_path)

    yield

    # Clean up after test
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


class TestTableCreation:
    """Test database table initialization."""

    def test_table_created_on_init(self, persistence, test_settings):  # noqa: ARG002
        """Table should be created automatically on first init."""
        db_path = Path(test_settings.DATA_DIR) / "feedback.db"
        assert db_path.exists()

        # Verify table exists with correct schema
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='task_metrics'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_table_schema(self, persistence, test_settings):  # noqa: ARG002
        """Table should have correct columns and types."""
        db_path = Path(test_settings.DATA_DIR) / "feedback.db"
        conn = sqlite3.connect(db_path)

        cursor = conn.execute("PRAGMA table_info(task_metrics)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        assert columns == {
            "metric_name": "TEXT",
            "metric_value": "REAL",
            "last_updated": "REAL",
        }
        conn.close()

    def test_table_primary_key(self, persistence, test_settings):  # noqa: ARG002
        """metric_name should be primary key."""
        db_path = Path(test_settings.DATA_DIR) / "feedback.db"
        conn = sqlite3.connect(db_path)

        cursor = conn.execute("PRAGMA table_info(task_metrics)")
        pk_columns = [row[1] for row in cursor.fetchall() if row[5] > 0]

        assert pk_columns == ["metric_name"]
        conn.close()


class TestSaveMetric:
    """Test single metric persistence."""

    def test_save_new_metric(self, persistence):
        """Should save new metric to database."""
        persistence.save_metric("test_metric", 42.0)

        value = persistence.load_metric("test_metric")
        assert value == 42.0

    def test_update_existing_metric(self, persistence):
        """Should update existing metric value."""
        persistence.save_metric("test_metric", 42.0)
        persistence.save_metric("test_metric", 100.0)

        value = persistence.load_metric("test_metric")
        assert value == 100.0

    def test_save_zero_value(self, persistence):
        """Should correctly save zero values."""
        persistence.save_metric("test_metric", 0.0)

        value = persistence.load_metric("test_metric")
        assert value == 0.0

    def test_save_negative_value(self, persistence):
        """Should correctly save negative values."""
        persistence.save_metric("test_metric", -1.0)

        value = persistence.load_metric("test_metric")
        assert value == -1.0

    def test_save_updates_timestamp(self, persistence):
        """Should update last_updated timestamp."""
        before = time.time()
        persistence.save_metric("test_metric", 42.0)
        after = time.time()

        # Verify timestamp is within expected range
        conn = sqlite3.connect(Path(persistence.db_path))
        cursor = conn.execute(
            "SELECT last_updated FROM task_metrics WHERE metric_name = ?",
            ("test_metric",),
        )
        timestamp = cursor.fetchone()[0]
        conn.close()

        assert before <= timestamp <= after


class TestSaveMetrics:
    """Test batch metric persistence."""

    def test_save_multiple_metrics(self, persistence):
        """Should save multiple metrics in one transaction."""
        metrics = {
            "metric1": 10.0,
            "metric2": 20.0,
            "metric3": 30.0,
        }
        persistence.save_metrics(metrics)

        for name, expected_value in metrics.items():
            actual_value = persistence.load_metric(name)
            assert actual_value == expected_value

    def test_save_empty_dict(self, persistence):
        """Should handle empty metrics dict gracefully."""
        persistence.save_metrics({})  # Should not raise

    def test_batch_update_existing_metrics(self, persistence):
        """Should update multiple existing metrics."""
        persistence.save_metrics({"m1": 10.0, "m2": 20.0})
        persistence.save_metrics({"m1": 100.0, "m2": 200.0})

        assert persistence.load_metric("m1") == 100.0
        assert persistence.load_metric("m2") == 200.0

    def test_batch_mixed_new_and_existing(self, persistence):
        """Should handle mix of new and existing metrics."""
        persistence.save_metric("existing", 50.0)
        persistence.save_metrics({"existing": 100.0, "new": 200.0})

        assert persistence.load_metric("existing") == 100.0
        assert persistence.load_metric("new") == 200.0


class TestLoadMetric:
    """Test single metric retrieval."""

    def test_load_existing_metric(self, persistence):
        """Should load existing metric value."""
        persistence.save_metric("test", 42.0)
        assert persistence.load_metric("test") == 42.0

    def test_load_nonexistent_metric(self, persistence):
        """Should return None for nonexistent metric."""
        assert persistence.load_metric("nonexistent") is None

    def test_load_after_update(self, persistence):
        """Should load most recent value after update."""
        persistence.save_metric("test", 10.0)
        persistence.save_metric("test", 20.0)
        assert persistence.load_metric("test") == 20.0


class TestLoadAllMetrics:
    """Test batch metric retrieval."""

    def test_load_all_empty_database(self, persistence):
        """Should return empty dict for empty database."""
        metrics = persistence.load_all_metrics()
        assert metrics == {}

    def test_load_all_multiple_metrics(self, persistence):
        """Should load all metrics from database."""
        expected = {
            "faq_extraction_last_run_status": 1.0,
            "wiki_update_pages_processed": 150.0,
            "feedback_processing_entries_processed": 25.0,
        }
        persistence.save_metrics(expected)

        actual = persistence.load_all_metrics()
        assert actual == expected

    def test_load_all_after_updates(self, persistence):
        """Should reflect latest values after updates."""
        persistence.save_metrics({"m1": 10.0, "m2": 20.0})
        persistence.save_metric("m1", 100.0)

        metrics = persistence.load_all_metrics()
        assert metrics == {"m1": 100.0, "m2": 20.0}


class TestDeleteMetric:
    """Test metric deletion."""

    def test_delete_existing_metric(self, persistence):
        """Should delete existing metric."""
        persistence.save_metric("test", 42.0)
        persistence.delete_metric("test")

        assert persistence.load_metric("test") is None

    def test_delete_nonexistent_metric(self, persistence):
        """Should handle deletion of nonexistent metric gracefully."""
        persistence.delete_metric("nonexistent")  # Should not raise

    def test_delete_one_of_many(self, persistence):
        """Should delete only specified metric."""
        persistence.save_metrics({"m1": 10.0, "m2": 20.0, "m3": 30.0})
        persistence.delete_metric("m2")

        assert persistence.load_metric("m1") == 10.0
        assert persistence.load_metric("m2") is None
        assert persistence.load_metric("m3") == 30.0


class TestClearAllMetrics:
    """Test clearing all metrics."""

    def test_clear_empty_database(self, persistence):
        """Should handle clearing empty database."""
        persistence.clear_all_metrics()  # Should not raise
        assert persistence.load_all_metrics() == {}

    def test_clear_multiple_metrics(self, persistence):
        """Should delete all metrics."""
        persistence.save_metrics({"m1": 10.0, "m2": 20.0, "m3": 30.0})
        persistence.clear_all_metrics()

        assert persistence.load_all_metrics() == {}

    def test_save_after_clear(self, persistence):
        """Should allow saving after clearing."""
        persistence.save_metric("test", 42.0)
        persistence.clear_all_metrics()
        persistence.save_metric("new", 100.0)

        assert persistence.load_metric("new") == 100.0


class TestGlobalInstance:
    """Test global instance management."""

    def test_init_persistence(self, test_settings):
        """Should initialize global instance."""
        init_persistence(test_settings)
        instance = get_persistence()

        assert instance is not None
        assert isinstance(instance, TaskMetricsPersistence)

    def test_get_persistence_before_init(self):
        """Should raise error if accessed before initialization."""
        with pytest.raises(RuntimeError, match="not initialized"):
            get_persistence()

    def test_get_persistence_returns_same_instance(self, test_settings):
        """Should return same instance on multiple calls."""
        init_persistence(test_settings)
        instance1 = get_persistence()
        instance2 = get_persistence()

        assert instance1 is instance2


class TestConcurrency:
    """Test thread safety and race conditions."""

    def test_concurrent_updates_same_metric(self, persistence):
        """Should handle concurrent updates to same metric."""
        import threading

        def update_metric():
            for i in range(10):
                persistence.save_metric("counter", i)

        threads = [threading.Thread(target=update_metric) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify database is not corrupted
        value = persistence.load_metric("counter")
        assert value is not None
        assert 0 <= value <= 9

    def test_concurrent_different_metrics(self, persistence):
        """Should handle concurrent writes to different metrics."""
        import threading

        def update_metric(name, value):
            persistence.save_metric(name, value)

        threads = [
            threading.Thread(target=update_metric, args=(f"m{i}", i)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all metrics saved correctly
        metrics = persistence.load_all_metrics()
        assert len(metrics) == 20


class TestErrorHandling:
    """Test error handling and recovery."""

    def test_corrupted_database_path(self):
        """Should raise error for invalid database path."""
        settings = Settings()
        settings.DATA_DIR = "/nonexistent/path"

        with pytest.raises(sqlite3.OperationalError):
            persistence = TaskMetricsPersistence(settings)
            persistence.save_metric("test", 42.0)

    def test_readonly_database(self, persistence, test_settings):
        """Should handle readonly database appropriately."""
        import os

        persistence.save_metric("test", 42.0)

        # Make database readonly
        db_path = Path(test_settings.DATA_DIR) / "feedback.db"
        os.chmod(db_path, 0o444)

        try:
            with pytest.raises(sqlite3.OperationalError):
                persistence.save_metric("test2", 100.0)
        finally:
            # Restore permissions
            os.chmod(db_path, 0o644)


class TestPrometheusIntegration:
    """Test integration with Prometheus metrics."""

    def test_production_metric_names(self, persistence):
        """Should handle actual production metric names."""
        production_metrics = {
            "faq_extraction_last_run_status": 1.0,
            "faq_extraction_messages_processed": 42.0,
            "faq_extraction_faqs_generated": 5.0,
            "wiki_update_last_run_status": 1.0,
            "wiki_update_pages_processed": 150.0,
            "feedback_processing_last_run_status": 1.0,
            "feedback_processing_entries_processed": 25.0,
        }

        persistence.save_metrics(production_metrics)
        loaded = persistence.load_all_metrics()

        assert loaded == production_metrics

    def test_status_values(self, persistence):
        """Should correctly store success (1) and failure (0) status."""
        persistence.save_metric("task_status", 1.0)
        assert persistence.load_metric("task_status") == 1.0

        persistence.save_metric("task_status", 0.0)
        assert persistence.load_metric("task_status") == 0.0
