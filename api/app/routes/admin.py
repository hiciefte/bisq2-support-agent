"""
Admin routes for the Bisq Support API.
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

from app.core.security import verify_admin_access
from app.services.simplified_rag_service import get_rag_service

# Create router with better documentation of admin security requirements
router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"}
    },
)

logger = logging.getLogger(__name__)

# Create Prometheus metrics
FEEDBACK_TOTAL = Gauge('bisq_feedback_total', 'Total number of feedback entries')
FEEDBACK_HELPFUL = Gauge('bisq_feedback_helpful', 'Number of helpful feedback entries')
FEEDBACK_UNHELPFUL = Gauge('bisq_feedback_unhelpful', 'Number of unhelpful feedback entries')
FEEDBACK_HELPFUL_RATE = Gauge('bisq_feedback_helpful_rate', 'Percentage of helpful feedback')

# Source effectiveness metrics
SOURCE_TOTAL = Gauge('bisq_source_total', 'Total usage count by source type', ['source_type'])
SOURCE_HELPFUL = Gauge('bisq_source_helpful', 'Helpful count by source type', ['source_type'])
SOURCE_HELPFUL_RATE = Gauge('bisq_source_helpful_rate', 'Helpful rate by source type', ['source_type'])

# Issue metrics
ISSUE_COUNT = Gauge('bisq_issue_count', 'Count of specific issues in feedback', ['issue_type'])


@router.get("/feedback", response_model=Dict[str, Any])
async def get_feedback_analytics(
        request: Request,
):
    """Get analytics about user feedback.
    
    This endpoint requires admin authentication via the API key.
    Authentication can be provided through:
    - Authorization header with Bearer token
    - api_key query parameter
    """
    rag_service = get_rag_service(request)
    feedback = rag_service.load_feedback()

    # Basic analytics
    total = len(feedback)

    if total == 0:
        return {
            "total_feedback": 0,
            "helpful_rate": 0,
            "source_effectiveness": {},
            "common_issues": {},
            "recent_negative": []
        }

    # Consider rating 1 as helpful, rating 0 as unhelpful
    helpful_count = sum(1 for item in feedback if item.get('rating', 0) == 1)
    unhelpful_count = total - helpful_count

    # Source effectiveness
    source_stats = {}
    for item in feedback:
        for source in item.get('sources_used', []):
            source_type = source.get('type', 'unknown')
            if source_type not in source_stats:
                source_stats[source_type] = {'total': 0, 'helpful': 0}

            source_stats[source_type]['total'] += 1
            if item.get('rating', 0) == 1:  # Consider rating 1 as helpful
                source_stats[source_type]['helpful'] += 1

    # Common issues in negative feedback
    common_issues = {}
    for item in feedback:
        if item.get('rating', 0) == 0:  # Consider rating 0 as unhelpful
            # Check specific issue fields
            for issue_key in ['too_verbose', 'too_technical', 'not_specific', 'inaccurate']:
                if item.get(issue_key):
                    common_issues[issue_key] = common_issues.get(issue_key, 0) + 1

            # Also check metadata.issues list if present
            if item.get('metadata') and item['metadata'].get('issues'):
                for issue in item['metadata']['issues']:
                    common_issues[issue] = common_issues.get(issue, 0) + 1

    return {
        "total_feedback": total,
        "helpful_rate": helpful_count / total if total > 0 else 0,
        "helpful_count": helpful_count,
        "unhelpful_count": unhelpful_count,
        "source_effectiveness": source_stats,
        "common_issues": common_issues,
        "recent_negative": [f for f in feedback if f.get('rating', 0) == 0][-5:]  # Include recent negative feedback
    }


@router.get("/metrics", response_class=Response)
async def get_metrics(
        request: Request,
):
    """Get feedback metrics in Prometheus format.
    
    This endpoint requires admin authentication via the API key.
    Authentication can be provided through:
    - Authorization header with Bearer token
    - api_key query parameter
    """
    # Get feedback analytics
    analytics = await get_feedback_analytics(request)

    # Update Prometheus metrics
    FEEDBACK_TOTAL.set(analytics["total_feedback"])
    FEEDBACK_HELPFUL.set(analytics["helpful_count"])
    FEEDBACK_UNHELPFUL.set(analytics["unhelpful_count"])
    FEEDBACK_HELPFUL_RATE.set(analytics["helpful_rate"] * 100)  # Convert to percentage

    # Update source metrics
    for source_type, stats in analytics["source_effectiveness"].items():
        SOURCE_TOTAL.labels(source_type=source_type).set(stats["total"])
        SOURCE_HELPFUL.labels(source_type=source_type).set(stats["helpful"])
        helpful_rate = stats["helpful"] / stats["total"] if stats["total"] > 0 else 0
        SOURCE_HELPFUL_RATE.labels(source_type=source_type).set(helpful_rate * 100)  # Convert to percentage

    # Update issue metrics
    for issue_type, count in analytics["common_issues"].items():
        ISSUE_COUNT.labels(issue_type=issue_type).set(count)

    # Return metrics in Prometheus format
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
