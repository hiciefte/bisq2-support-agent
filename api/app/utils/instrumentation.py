"""
RAG Pipeline Instrumentation for Prometheus Monitoring.

This module provides metrics and decorators for monitoring the RAG pipeline:
- Request rate and error tracking
- Stage-level latency measurement (retrieval, generation)
- Token usage and cost tracking
- Error categorization by stage and type

Metrics follow the Unified Monitoring Plan (docs/requirements/unified-monitoring-plan.md).
"""

import functools
import logging
import time
from typing import Callable

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# =============================================================================
# RAG Pipeline Metrics
# =============================================================================

# Request tracking
RAG_REQUEST_RATE = Counter(
    "rag_requests_total",
    "Total number of RAG requests processed",
)

RAG_ERROR_RATE = Gauge(
    "rag_error_rate",
    "Current error rate (errors / total requests)",
)

# Stage-level latency
RAG_LATENCY = Histogram(
    "rag_stage_latency_seconds",
    "Latency of RAG pipeline stages",
    ["stage_name"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Token usage
RAG_TOKENS = Histogram(
    "rag_tokens_per_request",
    "Tokens per request (input and output)",
    ["type"],  # input, output
    buckets=[100, 500, 1000, 2000, 3000, 5000, 10000, 20000],
)

# Cost tracking (GPT-4o-mini pricing)
RAG_COST = Histogram(
    "rag_cost_per_request_usd",
    "Cost per request in USD (GPT-4o-mini pricing)",
    buckets=[0.0001, 0.0005, 0.001, 0.0015, 0.002, 0.003, 0.005, 0.01],
)

# Error tracking
RAG_ERRORS = Counter(
    "rag_errors_total",
    "Total RAG errors by stage and type",
    ["stage_name", "error_type"],
)

# P95 latency gauge for easier alerting
RAG_P95_LATENCY = Gauge(
    "rag_p95_latency_seconds",
    "95th percentile latency across all stages",
)

# =============================================================================
# Request/Error Rate Tracking
# =============================================================================

# Simple counters for rate calculation
_total_requests = 0
_total_errors = 0
_error_rate_lock = None


def update_error_rate(is_error: bool = False):
    """
    Update the error rate metric.

    Args:
        is_error: Whether the request resulted in an error
    """
    global _total_requests, _total_errors

    _total_requests += 1

    if is_error:
        _total_errors += 1

    # Calculate and update error rate
    if _total_requests > 0:
        error_rate = _total_errors / _total_requests
        RAG_ERROR_RATE.set(error_rate)


# =============================================================================
# Instrumentation Decorator
# =============================================================================


def instrument_stage(stage_name: str):
    """
    Decorator to instrument RAG pipeline stages with metrics.

    Tracks:
    - Latency of the stage
    - Errors by type
    - Success/failure status

    Args:
        stage_name: Name of the stage (e.g., "retrieval", "generation")

    Example:
        @instrument_stage("retrieval")
        async def retrieve_documents(self, query: str):
            # Your retrieval logic here
            return documents
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                # Execute the wrapped function
                result = await func(*args, **kwargs)

                # Record success latency
                latency = time.time() - start_time
                RAG_LATENCY.labels(stage_name=stage_name).observe(latency)

                logger.debug(f"Stage '{stage_name}' completed in {latency:.3f}s")

                return result

            except Exception as e:
                # Record error
                error_type = type(e).__name__
                RAG_ERRORS.labels(stage_name=stage_name, error_type=error_type).inc()

                logger.error(f"Stage '{stage_name}' failed with {error_type}: {str(e)}")

                # Re-raise the exception
                raise

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                # Execute the wrapped function
                result = func(*args, **kwargs)

                # Record success latency
                latency = time.time() - start_time
                RAG_LATENCY.labels(stage_name=stage_name).observe(latency)

                logger.debug(f"Stage '{stage_name}' completed in {latency:.3f}s")

                return result

            except Exception as e:
                # Record error
                error_type = type(e).__name__
                RAG_ERRORS.labels(stage_name=stage_name, error_type=error_type).inc()

                logger.error(f"Stage '{stage_name}' failed with {error_type}: {str(e)}")

                # Re-raise the exception
                raise

        # Return the appropriate wrapper based on whether the function is async
        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


# =============================================================================
# Token and Cost Tracking
# =============================================================================


def track_tokens_and_cost(
    input_tokens: int,
    output_tokens: int,
    input_cost_per_token: float,
    output_cost_per_token: float,
):
    """
    Track token usage and calculate cost based on configured pricing.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        input_cost_per_token: Cost per input token (e.g., 0.00000015 for $0.15/1M tokens)
        output_cost_per_token: Cost per output token (e.g., 0.0000006 for $0.60/1M tokens)
    """
    # Calculate total tokens
    total_tokens = input_tokens + output_tokens

    # Emit token metrics
    RAG_TOKENS.labels(type="input").observe(input_tokens)
    RAG_TOKENS.labels(type="output").observe(output_tokens)

    # Calculate total cost
    cost = (input_tokens * input_cost_per_token) + (
        output_tokens * output_cost_per_token
    )

    # Emit cost metric
    RAG_COST.observe(cost)

    logger.debug(
        f"Token usage: {input_tokens} input + {output_tokens} output = {total_tokens} total (${cost:.6f})"
    )


# =============================================================================
# Utility Functions
# =============================================================================


def reset_metrics():
    """
    Reset all metrics to zero.

    WARNING: This is primarily for testing. Use with caution in production.
    """
    global _total_requests, _total_errors

    _total_requests = 0
    _total_errors = 0

    RAG_REQUEST_RATE._value.set(0)
    RAG_ERROR_RATE.set(0)
    RAG_P95_LATENCY.set(0)

    logger.warning("Metrics have been reset to zero")
