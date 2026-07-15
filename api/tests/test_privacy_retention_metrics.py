from __future__ import annotations

from dataclasses import dataclass

from app.metrics.privacy_metrics import (
    record_privacy_retention_failure,
    record_privacy_retention_run,
)
from prometheus_client import REGISTRY


@dataclass(frozen=True)
class _StoreResult:
    deleted_rows: int
    anonymized_rows: int
    oldest_age_seconds: float | None
    window_seconds: float


def test_retention_success_is_recorded_per_store_group() -> None:
    run_at = 1_800_000_000.0

    record_privacy_retention_run(
        stores={
            "fixture_records": _StoreResult(
                deleted_rows=2,
                anonymized_rows=1,
                oldest_age_seconds=60.0,
                window_seconds=120.0,
            )
        },
        successful_store_groups=("fixture_group_a", "fixture_group_b"),
        run_at=run_at,
    )

    for store_group in ("fixture_group_a", "fixture_group_b"):
        assert (
            REGISTRY.get_sample_value(
                "privacy_retention_last_success_timestamp_seconds",
                {"store": store_group},
            )
            == run_at
        )
    assert (
        REGISTRY.get_sample_value(
            "privacy_retention_deleted_last",
            {"store": "fixture_records"},
        )
        == 2
    )


def test_retention_failure_is_recorded_once_per_failed_store_group() -> None:
    labels = {"store": "fixture_failed_group"}
    before = REGISTRY.get_sample_value("privacy_retention_failures_total", labels) or 0

    record_privacy_retention_failure(
        failed_store_groups=("fixture_failed_group", "fixture_failed_group")
    )

    assert (
        REGISTRY.get_sample_value("privacy_retention_failures_total", labels)
        == before + 1
    )
