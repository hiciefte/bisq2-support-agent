"""Prometheus metrics for operator-facing security and ChatOps workflows."""

from __future__ import annotations

import time

from prometheus_client import Counter, Gauge, Histogram

CHATOPS_PARSE_TOTAL = Counter(
    "chatops_parse_total",
    "Total number of ChatOps parse attempts by outcome",
    ["channel", "result"],
)

CHATOPS_AUTH_TOTAL = Counter(
    "chatops_auth_total",
    "Total number of ChatOps authorization checks by outcome",
    ["channel", "result"],
)

CHATOPS_DISPATCH_TOTAL = Counter(
    "chatops_dispatch_total",
    "Total number of ChatOps dispatch attempts by command and outcome",
    ["channel", "command", "result"],
)

CHATOPS_AUDIT_WRITES_TOTAL = Counter(
    "chatops_audit_writes_total",
    "Total number of ChatOps audit entries written",
    ["channel", "result"],
)

CHATOPS_DISPATCH_LATENCY_SECONDS = Histogram(
    "chatops_dispatch_latency_seconds",
    "ChatOps dispatch latency in seconds by channel, command, and outcome",
    ["channel", "command", "result"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

TRUST_MONITOR_EVENTS_TOTAL = Counter(
    "trust_monitor_events_total",
    "Total number of trust-monitor events by channel, type, and outcome",
    ["channel", "event_type", "result"],
)

TRUST_MONITOR_FINDINGS_TOTAL = Counter(
    "trust_monitor_findings_total",
    "Total number of trust-monitor findings by detector and action",
    ["detector", "action", "surface"],
)

TRUST_MONITOR_FEEDBACK_TOTAL = Counter(
    "trust_monitor_feedback_total",
    "Total number of trust-monitor feedback actions",
    ["action"],
)

TRUST_MONITOR_RETENTION_LAST_RUN_TIMESTAMP = Gauge(
    "trust_monitor_retention_last_run_timestamp",
    "Unix timestamp of the last trust-monitor retention run",
)

TRUST_MONITOR_RETENTION_DELETED_LAST = Gauge(
    "trust_monitor_retention_deleted_last",
    "Number of rows deleted by the latest trust-monitor retention run",
    ["table_name"],
)

TRUST_MONITOR_OLDEST_RECORD_AGE_SECONDS = Gauge(
    "trust_monitor_oldest_record_age_seconds",
    "Age in seconds of the oldest retained trust-monitor record",
    ["table_name"],
)

TRUST_MONITOR_TABLE_ROWS = Gauge(
    "trust_monitor_table_rows",
    "Current number of retained trust-monitor rows by table",
    ["table_name"],
)


def record_chatops_parse(*, channel: str, result: str) -> None:
    CHATOPS_PARSE_TOTAL.labels(channel=channel, result=result).inc()


def record_chatops_auth(*, channel: str, result: str) -> None:
    CHATOPS_AUTH_TOTAL.labels(channel=channel, result=result).inc()


def record_chatops_dispatch(*, channel: str, command: str, result: str) -> None:
    CHATOPS_DISPATCH_TOTAL.labels(
        channel=channel,
        command=command,
        result=result,
    ).inc()


def record_chatops_audit_write(*, channel: str, result: str) -> None:
    CHATOPS_AUDIT_WRITES_TOTAL.labels(channel=channel, result=result).inc()


def record_chatops_dispatch_latency(
    *,
    channel: str,
    command: str,
    result: str,
    duration_seconds: float,
) -> None:
    CHATOPS_DISPATCH_LATENCY_SECONDS.labels(
        channel=channel,
        command=command,
        result=result,
    ).observe(max(0.0, float(duration_seconds)))


def record_trust_event(*, channel: str, event_type: str, result: str) -> None:
    TRUST_MONITOR_EVENTS_TOTAL.labels(
        channel=channel,
        event_type=event_type,
        result=result,
    ).inc()


def record_trust_finding(*, detector: str, action: str, surface: str) -> None:
    TRUST_MONITOR_FINDINGS_TOTAL.labels(
        detector=detector,
        action=action,
        surface=surface,
    ).inc()


def record_trust_feedback(*, action: str) -> None:
    TRUST_MONITOR_FEEDBACK_TOTAL.labels(action=action).inc()


def set_trust_retention_snapshot(
    *,
    deleted_by_table: dict[str, int],
    row_counts: dict[str, int],
    oldest_ages_seconds: dict[str, float | None],
    run_at: float | None = None,
) -> None:
    TRUST_MONITOR_RETENTION_LAST_RUN_TIMESTAMP.set(run_at or time.time())
    for table_name, deleted in deleted_by_table.items():
        TRUST_MONITOR_RETENTION_DELETED_LAST.labels(table_name=table_name).set(deleted)
    for table_name, count in row_counts.items():
        TRUST_MONITOR_TABLE_ROWS.labels(table_name=table_name).set(count)
    for table_name, age in oldest_ages_seconds.items():
        TRUST_MONITOR_OLDEST_RECORD_AGE_SECONDS.labels(table_name=table_name).set(
            0.0 if age is None else float(age)
        )
