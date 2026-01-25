"""Centralized metrics module for Prometheus instrumentation.

This package consolidates all Prometheus metrics definitions:
- tor_metrics: Tor connection and hidden service metrics
- matrix_metrics: Matrix authentication and polling metrics
- training_metrics: Training pipeline and calibration metrics
- task_metrics: Scheduled task metrics with decorators
- llm_extraction_metrics: LLM extraction pipeline metrics

Usage:
    # Import individual metrics directly from submodules:
    from app.metrics.tor_metrics import tor_connection_status
    from app.metrics.matrix_metrics import matrix_auth_total
    from app.metrics.training_metrics import training_pairs_processed
    from app.metrics.task_metrics import instrument_faq_extraction
    from app.metrics.llm_extraction_metrics import messages_filtered_total
"""

# Import submodules for convenience access
from app.metrics import (
    llm_extraction_metrics,
    matrix_metrics,
    task_metrics,
    tor_metrics,
    training_metrics,
)

__all__ = [
    "tor_metrics",
    "matrix_metrics",
    "training_metrics",
    "task_metrics",
    "llm_extraction_metrics",
]
