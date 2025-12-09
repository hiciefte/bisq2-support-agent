"""Prometheus metrics for Matrix authentication and connection monitoring."""

from prometheus_client import Counter, Gauge, Histogram

# Authentication metrics
matrix_auth_total = Counter(
    "matrix_auth_total",
    "Total Matrix authentication attempts",
    ["result"],  # success, failure
)

matrix_auth_failures_total = Counter(
    "matrix_auth_failures_total",
    "Total Matrix authentication failures by error type",
    [
        "error_type"
    ],  # token_expired, network_error, invalid_password, session_load_failed
)

# Connection status
matrix_connection_status = Gauge(
    "matrix_connection_status",
    "Matrix connection status (1=connected, 0=disconnected)",
)

# Circuit breaker state
matrix_circuit_breaker_state = Gauge(
    "matrix_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
)

# Session metrics
matrix_session_restores_total = Counter(
    "matrix_session_restores_total",
    "Total Matrix session restoration attempts",
    ["result"],  # success, failure
)

matrix_fresh_logins_total = Counter(
    "matrix_fresh_logins_total",
    "Total Matrix fresh password-based login attempts",
    ["result"],  # success, failure
)

# API call metrics
matrix_api_calls_total = Counter(
    "matrix_api_calls_total",
    "Total Matrix API calls by method",
    ["method", "result"],  # method: room_messages, sync, etc.; result: success, failure
)

matrix_api_retry_total = Counter(
    "matrix_api_retry_total",
    "Total Matrix API retry attempts",
    ["method"],  # room_messages, sync, etc.
)

# Polling metrics (Phase 3: Matrix polling automation)
matrix_polls_total = Counter(
    "matrix_polls_total",
    "Total Matrix polling attempts",
    ["room_id", "status"],  # status: success, failure
)

matrix_questions_detected = Counter(
    "matrix_questions_detected",
    "Total support questions detected in Matrix polls",
    ["room_id"],
)

matrix_questions_processed = Counter(
    "matrix_questions_processed",
    "Total support questions successfully processed",
    ["room_id"],
)

matrix_poll_duration_seconds = Histogram(
    "matrix_poll_duration_seconds",
    "Duration of Matrix polling operations in seconds",
    ["room_id"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)
