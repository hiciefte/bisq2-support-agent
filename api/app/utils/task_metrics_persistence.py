"""
SQLite persistence layer for Prometheus task metrics.

This module provides database persistence for Prometheus Gauge metrics to survive
container restarts, deployments, and crashes. Each metric value is stored in a
database row and automatically restored on application startup.

Architecture:
- Single table with 7 rows (one per metric)
- Atomic transactions for data integrity
- Automatic restoration on startup via main.py lifespan
- Reuses existing feedback.db database

Database Schema:
    CREATE TABLE task_metrics (
        metric_name TEXT PRIMARY KEY,
        metric_value REAL NOT NULL,
        last_updated REAL NOT NULL
    )

Metrics persisted:
- faq_extraction_last_run_status (1=success, 0=failure)
- faq_extraction_messages_processed
- faq_extraction_faqs_generated
- wiki_update_last_run_status (1=success, 0=failure)
- wiki_update_pages_processed
- feedback_processing_last_run_status (1=success, 0=failure)
- feedback_processing_entries_processed
"""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, Optional

from app.core.config import Settings


class TaskMetricsPersistence:
    """Manages SQLite persistence for Prometheus task metrics."""

    def __init__(self, settings: Settings):
        """
        Initialize persistence layer.

        Args:
            settings: Application settings containing data directory path
        """
        self.db_path = Path(settings.DATA_DIR) / "feedback.db"
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create task_metrics table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_metrics (
                    metric_name TEXT PRIMARY KEY,
                    metric_value REAL NOT NULL,
                    last_updated REAL NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.

        Handles connection lifecycle and automatic commit/close.

        Yields:
            Active database connection

        Raises:
            sqlite3.Error: If database operation fails
        """
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save_metric(self, metric_name: str, metric_value: float) -> None:
        """
        Save a single metric value to database.

        Uses UPSERT (INSERT OR REPLACE) for atomic updates.

        Args:
            metric_name: Unique identifier for the metric
            metric_value: Numeric value to persist

        Raises:
            sqlite3.Error: If database operation fails
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_metrics (metric_name, metric_value, last_updated)
                VALUES (?, ?, ?)
                """,
                (metric_name, metric_value, time.time()),
            )

    def save_metrics(self, metrics: Dict[str, float]) -> None:
        """
        Save multiple metric values in a single transaction.

        More efficient than multiple save_metric() calls.

        Args:
            metrics: Dictionary mapping metric names to values

        Raises:
            sqlite3.Error: If database operation fails
        """
        if not metrics:
            return

        with self._get_connection() as conn:
            timestamp = time.time()
            conn.executemany(
                """
                INSERT OR REPLACE INTO task_metrics (metric_name, metric_value, last_updated)
                VALUES (?, ?, ?)
                """,
                [(name, value, timestamp) for name, value in metrics.items()],
            )

    def load_metric(self, metric_name: str) -> Optional[float]:
        """
        Load a single metric value from database.

        Args:
            metric_name: Unique identifier for the metric

        Returns:
            Metric value if found, None otherwise

        Raises:
            sqlite3.Error: If database operation fails
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT metric_value FROM task_metrics WHERE metric_name = ?",
                (metric_name,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def load_all_metrics(self) -> Dict[str, float]:
        """
        Load all persisted metric values.

        Returns:
            Dictionary mapping metric names to values

        Raises:
            sqlite3.Error: If database operation fails
        """
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT metric_name, metric_value FROM task_metrics")
            return {row[0]: row[1] for row in cursor.fetchall()}

    def delete_metric(self, metric_name: str) -> None:
        """
        Delete a metric from database.

        Args:
            metric_name: Unique identifier for the metric

        Raises:
            sqlite3.Error: If database operation fails
        """
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM task_metrics WHERE metric_name = ?", (metric_name,)
            )

    def clear_all_metrics(self) -> None:
        """
        Clear all metrics from database.

        Useful for testing and manual resets.

        Raises:
            sqlite3.Error: If database operation fails
        """
        with self._get_connection() as conn:
            conn.execute("DELETE FROM task_metrics")


# Global instance - initialized in main.py
_persistence_instance: Optional[TaskMetricsPersistence] = None


def init_persistence(settings: Settings) -> None:
    """
    Initialize the global persistence instance.

    Called from main.py on application startup.

    Args:
        settings: Application settings
    """
    global _persistence_instance
    _persistence_instance = TaskMetricsPersistence(settings)


_PERSISTENCE_NOT_INITIALIZED = (
    "TaskMetricsPersistence not initialized. Call init_persistence() first."
)


def get_persistence() -> TaskMetricsPersistence:
    """
    Get the global persistence instance.

    Returns:
        TaskMetricsPersistence instance

    Raises:
        RuntimeError: If persistence not initialized
    """
    if _persistence_instance is None:
        raise RuntimeError(_PERSISTENCE_NOT_INITIALIZED)
    return _persistence_instance
