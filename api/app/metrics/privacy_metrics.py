"""Prometheus metrics for privacy-retention enforcement."""

from __future__ import annotations

from typing import Mapping, Protocol

from prometheus_client import Counter, Gauge


class _StoreResult(Protocol):
    @property
    def deleted_rows(self) -> int: ...

    @property
    def anonymized_rows(self) -> int: ...

    @property
    def oldest_age_seconds(self) -> float | None: ...

    @property
    def window_seconds(self) -> float: ...


PRIVACY_RETENTION_ROWS_DELETED_TOTAL = Counter(
    "privacy_retention_rows_deleted_total",
    "Rows or file artifacts deleted by privacy retention",
    ["store"],
)

PRIVACY_RETENTION_DELETED_LAST = Gauge(
    "privacy_retention_deleted_last",
    "Rows or file artifacts deleted by the latest retention run",
    ["store"],
)

PRIVACY_RETENTION_ANONYMIZED_TOTAL = Counter(
    "privacy_retention_rows_anonymized_total",
    "Rows anonymized by privacy retention",
    ["store"],
)

PRIVACY_RETENTION_ANONYMIZED_LAST = Gauge(
    "privacy_retention_anonymized_last",
    "Rows anonymized by the latest retention run",
    ["store"],
)

PRIVACY_RETENTION_OLDEST_AGE_SECONDS = Gauge(
    "privacy_retention_oldest_age_seconds",
    "Age of the oldest retained personal-data record",
    ["store"],
)

PRIVACY_RETENTION_WINDOW_SECONDS = Gauge(
    "privacy_retention_window_seconds",
    "Maximum configured age for a personal-data store",
    ["store"],
)

PRIVACY_RETENTION_LAST_SUCCESS_TIMESTAMP_SECONDS = Gauge(
    "privacy_retention_last_success_timestamp_seconds",
    "Unix timestamp of the last successful privacy-retention run",
)

PRIVACY_RETENTION_FAILURES_TOTAL = Counter(
    "privacy_retention_failures_total",
    "Failed privacy-retention runs",
)


def record_privacy_retention_run(
    *, stores: Mapping[str, _StoreResult], run_at: float
) -> None:
    """Publish a bounded per-store snapshot after a successful run."""
    for store, result in stores.items():
        PRIVACY_RETENTION_ROWS_DELETED_TOTAL.labels(store=store).inc(
            result.deleted_rows
        )
        PRIVACY_RETENTION_DELETED_LAST.labels(store=store).set(result.deleted_rows)
        PRIVACY_RETENTION_ANONYMIZED_TOTAL.labels(store=store).inc(
            result.anonymized_rows
        )
        PRIVACY_RETENTION_ANONYMIZED_LAST.labels(store=store).set(
            result.anonymized_rows
        )
        PRIVACY_RETENTION_OLDEST_AGE_SECONDS.labels(store=store).set(
            0.0
            if result.oldest_age_seconds is None
            else float(result.oldest_age_seconds)
        )
        PRIVACY_RETENTION_WINDOW_SECONDS.labels(store=store).set(result.window_seconds)
    PRIVACY_RETENTION_LAST_SUCCESS_TIMESTAMP_SECONDS.set(run_at)


def record_privacy_retention_failure() -> None:
    """Count a failed retention pass without advancing last-success state."""
    PRIVACY_RETENTION_FAILURES_TOTAL.inc()
