"""
Prometheus metrics for scheduled background tasks.

This module provides metrics instrumentation for periodic tasks like:
- FAQ extraction from support chats
- Wiki content updates
- Feedback processing

Metrics are exposed via the /metrics endpoint and monitored by Prometheus
for alerting on task failures, staleness, and performance issues.

Persistence:
All Gauge metrics are automatically persisted to SQLite database to survive
container restarts, deployments, and crashes.
"""

import logging
import time
from functools import wraps
from typing import Any, Callable, Optional

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# =============================================================================
# FAQ Extraction Metrics
# =============================================================================

FAQ_EXTRACTION_RUNS = Counter(
    "faq_extraction_runs_total",
    "Total number of FAQ extraction runs",
    ["status"],  # success, failure, retry
)

FAQ_EXTRACTION_DURATION = Histogram(
    "faq_extraction_duration_seconds",
    "Duration of FAQ extraction process in seconds",
    buckets=(10, 30, 60, 120, 300, 600, 1200, 1800, 3600),  # 10s to 1h
)

FAQ_EXTRACTION_MESSAGES_PROCESSED = Gauge(
    "faq_extraction_messages_processed",
    "Number of messages processed in last FAQ extraction run",
)

FAQ_EXTRACTION_FAQS_GENERATED = Gauge(
    "faq_extraction_faqs_generated",
    "Number of FAQs generated in last extraction run",
)

FAQ_EXTRACTION_LAST_SUCCESS_TIMESTAMP = Gauge(
    "faq_extraction_last_success_timestamp",
    "Unix timestamp of last successful FAQ extraction",
)

FAQ_EXTRACTION_LAST_RUN_STATUS = Gauge(
    "faq_extraction_last_run_status",
    "Status of last FAQ extraction run (1=success, 0=failure)",
)

# =============================================================================
# Wiki Update Metrics
# =============================================================================

WIKI_UPDATE_RUNS = Counter(
    "wiki_update_runs_total",
    "Total number of wiki update runs",
    ["status"],  # success, failure
)

WIKI_UPDATE_DURATION = Histogram(
    "wiki_update_duration_seconds",
    "Duration of wiki update process in seconds",
    buckets=(10, 30, 60, 120, 300, 600, 1200, 1800, 3600),  # 10s to 1h
)

WIKI_UPDATE_PAGES_PROCESSED = Gauge(
    "wiki_update_pages_processed",
    "Number of wiki pages processed in last update run",
)

WIKI_UPDATE_LAST_SUCCESS_TIMESTAMP = Gauge(
    "wiki_update_last_success_timestamp",
    "Unix timestamp of last successful wiki update",
)

WIKI_UPDATE_LAST_RUN_STATUS = Gauge(
    "wiki_update_last_run_status",
    "Status of last wiki update run (1=success, 0=failure)",
)

# =============================================================================
# Feedback Processing Metrics
# =============================================================================

FEEDBACK_PROCESSING_RUNS = Counter(
    "feedback_processing_runs_total",
    "Total number of feedback processing runs",
    ["status"],  # success, failure
)

FEEDBACK_PROCESSING_DURATION = Histogram(
    "feedback_processing_duration_seconds",
    "Duration of feedback processing in seconds",
    buckets=(1, 5, 10, 30, 60, 120, 300),  # 1s to 5min
)

FEEDBACK_PROCESSING_ENTRIES = Gauge(
    "feedback_processing_entries_processed",
    "Number of feedback entries processed in last run",
)

FEEDBACK_PROCESSING_LAST_SUCCESS_TIMESTAMP = Gauge(
    "feedback_processing_last_success_timestamp",
    "Unix timestamp of last successful feedback processing",
)

FEEDBACK_PROCESSING_LAST_RUN_STATUS = Gauge(
    "feedback_processing_last_run_status",
    "Status of last feedback processing run (1=success, 0=failure)",
)

# =============================================================================
# Decorator Functions for Task Instrumentation
# =============================================================================


def instrument_faq_extraction(func: Callable) -> Callable:
    """
    Decorator to instrument FAQ extraction tasks with Prometheus metrics.

    Tracks:
    - Run count (success/failure)
    - Duration
    - Messages processed
    - FAQs generated
    - Last success timestamp
    - Last run status

    Example:
        @instrument_faq_extraction
        async def extract_faqs():
            # extraction logic
            return {"messages_processed": 100, "faqs_generated": 15}
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        result = None

        try:
            # Execute the task
            result = await func(*args, **kwargs)

            # Calculate duration
            duration = time.time() - start_time
            FAQ_EXTRACTION_DURATION.observe(duration)

            # Update success metrics
            FAQ_EXTRACTION_RUNS.labels(status="success").inc()
            FAQ_EXTRACTION_LAST_RUN_STATUS.set(1)
            FAQ_EXTRACTION_LAST_SUCCESS_TIMESTAMP.set(time.time())

            # Update task-specific metrics if result contains them
            if isinstance(result, dict):
                if "messages_processed" in result:
                    FAQ_EXTRACTION_MESSAGES_PROCESSED.set(result["messages_processed"])
                if "faqs_generated" in result:
                    FAQ_EXTRACTION_FAQS_GENERATED.set(result["faqs_generated"])

            return result

        except Exception:
            # Calculate duration even on failure
            duration = time.time() - start_time
            FAQ_EXTRACTION_DURATION.observe(duration)

            # Update failure metrics
            FAQ_EXTRACTION_RUNS.labels(status="failure").inc()
            FAQ_EXTRACTION_LAST_RUN_STATUS.set(0)

            # Re-raise the exception
            raise

    return wrapper


def instrument_wiki_update(func: Callable) -> Callable:
    """
    Decorator to instrument wiki update tasks with Prometheus metrics.

    Tracks:
    - Run count (success/failure)
    - Duration
    - Pages processed
    - Last success timestamp
    - Last run status

    Example:
        @instrument_wiki_update
        async def update_wiki():
            # update logic
            return {"pages_processed": 50}
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        result = None

        try:
            # Execute the task
            result = await func(*args, **kwargs)

            # Calculate duration
            duration = time.time() - start_time
            WIKI_UPDATE_DURATION.observe(duration)

            # Update success metrics
            WIKI_UPDATE_RUNS.labels(status="success").inc()
            WIKI_UPDATE_LAST_RUN_STATUS.set(1)
            WIKI_UPDATE_LAST_SUCCESS_TIMESTAMP.set(time.time())

            # Update task-specific metrics if result contains them
            if isinstance(result, dict):
                if "pages_processed" in result:
                    WIKI_UPDATE_PAGES_PROCESSED.set(result["pages_processed"])

            return result

        except Exception:
            # Calculate duration even on failure
            duration = time.time() - start_time
            WIKI_UPDATE_DURATION.observe(duration)

            # Update failure metrics
            WIKI_UPDATE_RUNS.labels(status="failure").inc()
            WIKI_UPDATE_LAST_RUN_STATUS.set(0)

            # Re-raise the exception
            raise

    return wrapper


def instrument_feedback_processing(func: Callable) -> Callable:
    """
    Decorator to instrument feedback processing tasks with Prometheus metrics.

    Tracks:
    - Run count (success/failure)
    - Duration
    - Entries processed
    - Last success timestamp
    - Last run status

    Example:
        @instrument_feedback_processing
        async def process_feedback():
            # processing logic
            return {"entries_processed": 25}
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.time()
        result = None

        try:
            # Execute the task
            result = await func(*args, **kwargs)

            # Calculate duration
            duration = time.time() - start_time
            FEEDBACK_PROCESSING_DURATION.observe(duration)

            # Update success metrics
            FEEDBACK_PROCESSING_RUNS.labels(status="success").inc()
            FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(1)
            FEEDBACK_PROCESSING_LAST_SUCCESS_TIMESTAMP.set(time.time())

            # Update task-specific metrics if result contains them
            if isinstance(result, dict):
                if "entries_processed" in result:
                    FEEDBACK_PROCESSING_ENTRIES.set(result["entries_processed"])

            return result

        except Exception:
            # Calculate duration even on failure
            duration = time.time() - start_time
            FEEDBACK_PROCESSING_DURATION.observe(duration)

            # Update failure metrics
            FEEDBACK_PROCESSING_RUNS.labels(status="failure").inc()
            FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(0)

            # Re-raise the exception
            raise

    return wrapper


# =============================================================================
# Manual Metric Update Functions (for shell script wrappers)
# =============================================================================


def record_faq_extraction_success(
    messages_processed: int = 0,
    faqs_generated: int = 0,
    duration: Optional[float] = None,
) -> None:
    """
    Manually record successful FAQ extraction metrics.

    Useful when calling from shell scripts that wrap the Python extraction process.

    Args:
        messages_processed: Number of messages processed
        faqs_generated: Number of FAQs generated
        duration: Task duration in seconds (optional)
    """
    FAQ_EXTRACTION_RUNS.labels(status="success").inc()
    FAQ_EXTRACTION_LAST_RUN_STATUS.set(1)
    FAQ_EXTRACTION_LAST_SUCCESS_TIMESTAMP.set(time.time())

    if messages_processed > 0:
        FAQ_EXTRACTION_MESSAGES_PROCESSED.set(messages_processed)
    if faqs_generated > 0:
        FAQ_EXTRACTION_FAQS_GENERATED.set(faqs_generated)
    if duration is not None:
        FAQ_EXTRACTION_DURATION.observe(duration)

    # Persist Gauge values to database
    _persist_faq_metrics()


def record_faq_extraction_failure(duration: Optional[float] = None) -> None:
    """
    Manually record failed FAQ extraction metrics.

    Args:
        duration: Task duration in seconds (optional)
    """
    FAQ_EXTRACTION_RUNS.labels(status="failure").inc()
    FAQ_EXTRACTION_LAST_RUN_STATUS.set(0)

    if duration is not None:
        FAQ_EXTRACTION_DURATION.observe(duration)

    # Persist failure status to database
    _persist_faq_metrics()


def record_wiki_update_success(
    pages_processed: int = 0, duration: Optional[float] = None
) -> None:
    """
    Manually record successful wiki update metrics.

    Args:
        pages_processed: Number of wiki pages processed
        duration: Task duration in seconds (optional)
    """
    WIKI_UPDATE_RUNS.labels(status="success").inc()
    WIKI_UPDATE_LAST_RUN_STATUS.set(1)
    WIKI_UPDATE_LAST_SUCCESS_TIMESTAMP.set(time.time())

    if pages_processed > 0:
        WIKI_UPDATE_PAGES_PROCESSED.set(pages_processed)
    if duration is not None:
        WIKI_UPDATE_DURATION.observe(duration)

    # Persist Gauge values to database
    _persist_wiki_metrics()


def record_wiki_update_failure(duration: Optional[float] = None) -> None:
    """
    Manually record failed wiki update metrics.

    Args:
        duration: Task duration in seconds (optional)
    """
    WIKI_UPDATE_RUNS.labels(status="failure").inc()
    WIKI_UPDATE_LAST_RUN_STATUS.set(0)

    if duration is not None:
        WIKI_UPDATE_DURATION.observe(duration)

    # Persist failure status to database
    _persist_wiki_metrics()


def record_feedback_processing_success(
    entries_processed: int = 0, duration: Optional[float] = None
) -> None:
    """
    Manually record successful feedback processing metrics.

    Args:
        entries_processed: Number of feedback entries processed
        duration: Task duration in seconds (optional)
    """
    FEEDBACK_PROCESSING_RUNS.labels(status="success").inc()
    FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(1)
    FEEDBACK_PROCESSING_LAST_SUCCESS_TIMESTAMP.set(time.time())

    if entries_processed > 0:
        FEEDBACK_PROCESSING_ENTRIES.set(entries_processed)
    if duration is not None:
        FEEDBACK_PROCESSING_DURATION.observe(duration)

    # Persist Gauge values to database
    _persist_feedback_metrics()


def record_feedback_processing_failure(duration: Optional[float] = None) -> None:
    """
    Manually record failed feedback processing metrics.

    Args:
        duration: Task duration in seconds (optional)
    """
    FEEDBACK_PROCESSING_RUNS.labels(status="failure").inc()
    FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(0)

    if duration is not None:
        FEEDBACK_PROCESSING_DURATION.observe(duration)

    # Persist failure status to database
    _persist_feedback_metrics()


# =============================================================================
# Persistence Helper Functions
# =============================================================================


def _persist_faq_metrics() -> None:
    """Persist FAQ extraction Gauge metrics to database."""
    try:
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        persistence.save_metrics(
            {
                "faq_extraction_last_run_status": FAQ_EXTRACTION_LAST_RUN_STATUS._value.get(),
                "faq_extraction_messages_processed": FAQ_EXTRACTION_MESSAGES_PROCESSED._value.get(),
                "faq_extraction_faqs_generated": FAQ_EXTRACTION_FAQS_GENERATED._value.get(),
            }
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist FAQ metrics")


def _persist_wiki_metrics() -> None:
    """Persist wiki update Gauge metrics to database."""
    try:
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        persistence.save_metrics(
            {
                "wiki_update_last_run_status": WIKI_UPDATE_LAST_RUN_STATUS._value.get(),
                "wiki_update_pages_processed": WIKI_UPDATE_PAGES_PROCESSED._value.get(),
            }
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist wiki metrics")


def _persist_feedback_metrics() -> None:
    """Persist feedback processing Gauge metrics to database."""
    try:
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        persistence.save_metrics(
            {
                "feedback_processing_last_run_status": FEEDBACK_PROCESSING_LAST_RUN_STATUS._value.get(),
                "feedback_processing_entries_processed": FEEDBACK_PROCESSING_ENTRIES._value.get(),
            }
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist feedback metrics")


def restore_metrics_from_database() -> None:
    """
    Restore Prometheus Gauge metrics from database on application startup.

    Called from main.py lifespan to recover persisted metric values after
    container restarts, deployments, or crashes.
    """
    try:
        from app.utils.task_metrics_persistence import get_persistence

        persistence = get_persistence()
        metrics = persistence.load_all_metrics()

        # Restore FAQ extraction metrics
        if "faq_extraction_last_run_status" in metrics:
            FAQ_EXTRACTION_LAST_RUN_STATUS.set(
                metrics["faq_extraction_last_run_status"]
            )
        if "faq_extraction_messages_processed" in metrics:
            FAQ_EXTRACTION_MESSAGES_PROCESSED.set(
                metrics["faq_extraction_messages_processed"]
            )
        if "faq_extraction_faqs_generated" in metrics:
            FAQ_EXTRACTION_FAQS_GENERATED.set(metrics["faq_extraction_faqs_generated"])

        # Restore wiki update metrics
        if "wiki_update_last_run_status" in metrics:
            WIKI_UPDATE_LAST_RUN_STATUS.set(metrics["wiki_update_last_run_status"])
        if "wiki_update_pages_processed" in metrics:
            WIKI_UPDATE_PAGES_PROCESSED.set(metrics["wiki_update_pages_processed"])

        # Restore feedback processing metrics
        if "feedback_processing_last_run_status" in metrics:
            FEEDBACK_PROCESSING_LAST_RUN_STATUS.set(
                metrics["feedback_processing_last_run_status"]
            )
        if "feedback_processing_entries_processed" in metrics:
            FEEDBACK_PROCESSING_ENTRIES.set(
                metrics["feedback_processing_entries_processed"]
            )

        logger.info(f"Restored {len(metrics)} metrics from database")

    except Exception:  # noqa: BLE001
        logger.exception("Failed to restore metrics from database")
