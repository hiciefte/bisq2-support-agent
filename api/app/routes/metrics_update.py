"""
HTTP endpoints for updating background task metrics from cron jobs.

Since cron jobs run as separate processes in the scheduler container,
they can't directly update the API's prometheus metrics (different memory space).
This API provides HTTP endpoints that cron scripts can call to record task outcomes.
"""

from typing import Literal, Optional

from app.core.security import verify_admin_key
from app.utils.task_metrics import (
    record_faq_extraction_failure,
    record_faq_extraction_success,
    record_feedback_processing_failure,
    record_feedback_processing_success,
    record_wiki_update_failure,
    record_wiki_update_success,
)
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

router = APIRouter(
    prefix="/admin/metrics",
    tags=["Metrics"],
    dependencies=[Depends(verify_admin_key)],
)


class FAQExtractionMetrics(BaseModel):
    """Metrics for FAQ extraction task."""

    status: Literal["success", "failure"]
    messages_processed: int = Field(ge=0, default=0)
    faqs_generated: int = Field(ge=0, default=0)
    duration: Optional[float] = Field(ge=0, default=None)


class WikiUpdateMetrics(BaseModel):
    """Metrics for wiki update task."""

    status: Literal["success", "failure"]
    pages_processed: int = Field(ge=0, default=0)
    duration: Optional[float] = Field(ge=0, default=None)


class FeedbackProcessingMetrics(BaseModel):
    """Metrics for feedback processing task."""

    status: Literal["success", "failure"]
    entries_processed: int = Field(ge=0, default=0)
    duration: Optional[float] = Field(ge=0, default=None)


@router.post("/faq-extraction", status_code=status.HTTP_204_NO_CONTENT)
async def update_faq_extraction_metrics(metrics: FAQExtractionMetrics):
    """
    Update FAQ extraction metrics from cron job.

    Called by the scheduler's FAQ extraction script to record task outcomes.

    Example curl from scheduler container:
        curl -X POST http://api:8000/admin/metrics/faq-extraction \\
          -H "X-API-Key: $ADMIN_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"status":"success","messages_processed":42,"faqs_generated":5,"duration":123.45}'
    """
    if metrics.status == "success":
        record_faq_extraction_success(
            messages_processed=metrics.messages_processed,
            faqs_generated=metrics.faqs_generated,
            duration=metrics.duration,
        )
    else:
        record_faq_extraction_failure(duration=metrics.duration)


@router.post("/wiki-update", status_code=status.HTTP_204_NO_CONTENT)
async def update_wiki_update_metrics(metrics: WikiUpdateMetrics):
    """
    Update wiki update metrics from cron job.

    Called by the scheduler's wiki update script to record task outcomes.

    Example curl from scheduler container:
        curl -X POST http://api:8000/admin/metrics/wiki-update \\
          -H "X-API-Key: $ADMIN_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"status":"success","pages_processed":150,"duration":89.12}'
    """
    if metrics.status == "success":
        record_wiki_update_success(
            pages_processed=metrics.pages_processed,
            duration=metrics.duration,
        )
    else:
        record_wiki_update_failure(duration=metrics.duration)


@router.post("/feedback-processing", status_code=status.HTTP_204_NO_CONTENT)
async def update_feedback_processing_metrics(metrics: FeedbackProcessingMetrics):
    """
    Update feedback processing metrics from cron job.

    Called by the scheduler's feedback processing script to record task outcomes.

    Example curl from scheduler container:
        curl -X POST http://api:8000/admin/metrics/feedback-processing \\
          -H "X-API-Key: $ADMIN_API_KEY" \\
          -H "Content-Type: application/json" \\
          -d '{"status":"success","entries_processed":25,"duration":15.67}'
    """
    if metrics.status == "success":
        record_feedback_processing_success(
            entries_processed=metrics.entries_processed,
            duration=metrics.duration,
        )
    else:
        record_feedback_processing_failure(duration=metrics.duration)
