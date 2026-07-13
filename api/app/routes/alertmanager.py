"""Alertmanager webhook endpoint for Matrix notifications.

Phase 9: Replace token-based Matrix auth with password-based auth.

This module provides a webhook endpoint that receives alerts from Alertmanager
and forwards them to Matrix rooms using the same reliable authentication
infrastructure as the Matrix Shadow Mode service.

Benefits over the old matrix-alertmanager-webhook container:
- Uses password-based auth with session persistence (no token timeouts)
- Automatic token refresh on auth failures
- Circuit breaker protection to prevent account lockout
- Unified auth system with chat polling

Architecture:
    Alertmanager -> POST /alerts -> isolated relay -> Matrix rooms

The main API also mounts this router under ``/alertmanager`` for backward
compatibility, but production Alertmanager delivery targets the isolated relay.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================


class Alert(BaseModel):
    """Single alert from Alertmanager.

    Attributes:
        status: Alert status ("firing" or "resolved")
        labels: Alert labels (alertname, severity, component, etc.)
        annotations: Alert annotations (summary, description, etc.)
        startsAt: ISO timestamp when alert started
        endsAt: ISO timestamp when alert ended (or "0001-01-01T00:00:00Z" if still firing)
        generatorURL: URL to the generator (Prometheus graph)
        fingerprint: Unique identifier for the alert
    """

    status: str
    labels: dict
    annotations: dict
    startsAt: Optional[str] = None
    endsAt: Optional[str] = None
    generatorURL: Optional[str] = None
    fingerprint: Optional[str] = None


class AlertmanagerPayload(BaseModel):
    """Alertmanager webhook payload.

    See: https://prometheus.io/docs/alerting/latest/configuration/#webhook_config

    Attributes:
        receiver: Name of the receiver that matched
        status: Overall status ("firing" or "resolved")
        alerts: List of alerts in this notification
        groupLabels: Labels that caused the alerts to be grouped
        commonLabels: Labels common to all alerts
        commonAnnotations: Annotations common to all alerts
        externalURL: Alertmanager external URL
        version: Webhook payload version
        groupKey: Key identifying the group
    """

    receiver: str
    status: str
    alerts: List[Alert]
    groupLabels: Optional[dict] = {}
    commonLabels: Optional[dict] = {}
    commonAnnotations: Optional[dict] = {}
    externalURL: Optional[str] = None
    version: Optional[str] = None
    groupKey: Optional[str] = None


class AlertResponse(BaseModel):
    """Response from the alerts endpoint."""

    status: str
    alerts_processed: int
    warning: Optional[str] = None


class HealthResponse(BaseModel):
    """Response from the health endpoint."""

    status: str


# =============================================================================
# Message Formatting
# =============================================================================


def format_alert_message(alert: Alert, status: str) -> str:
    """Format an alert as a Matrix message.

    Args:
        alert: The alert to format
        status: Overall status from the payload ("firing" or "resolved")

    Returns:
        Formatted message string with emoji, severity, name, and details
    """
    # Emoji based on status
    emoji = "🔥" if status == "firing" else "✅"

    # Extract key fields with defaults
    severity = alert.labels.get("severity", "unknown").upper()
    alertname = alert.labels.get("alertname", "Unknown")
    summary = alert.annotations.get("summary", "No summary")
    description = alert.annotations.get("description", "")
    component = alert.labels.get("component", "")

    # Build message
    lines = [f"{emoji} **{severity}**: {alertname}"]

    if component:
        lines[0] += f" ({component})"

    lines.append(summary)

    if description:
        lines.append("")
        lines.append(description)

    return "\n".join(lines)


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint for the alertmanager webhook.

    Returns:
        HealthResponse with status "healthy"
    """
    return HealthResponse(status="healthy")


@router.post("/alerts", response_model=AlertResponse)
async def receive_alerts(
    payload: AlertmanagerPayload, request: Request
) -> AlertResponse:
    """Receive alerts from Alertmanager and forward to Matrix.

    This endpoint receives webhook payloads from Alertmanager and forwards
    each alert as a formatted message to the configured Matrix rooms.

    Uses the same reliable authentication infrastructure as chat polling:
    - Password-based auth with session persistence
    - Automatic token refresh on auth failures
    - Circuit breaker protection

    Args:
        payload: Alertmanager webhook payload
        request: FastAPI request (for accessing app state)

    Returns:
        AlertResponse with status and count of processed alerts
    """
    # Get matrix alert service from app state
    matrix_service = getattr(request.app.state, "matrix_alert_service", None)

    if not matrix_service:
        logger.error(
            "Matrix alert service not available; returning a retryable webhook failure"
        )
        raise HTTPException(status_code=503, detail="matrix_service_unavailable")

    is_configured = getattr(matrix_service, "is_configured", None)
    try:
        configured = bool(is_configured()) if callable(is_configured) else False
    except Exception as exc:
        logger.error("Failed to check Matrix alert service configuration: %s", exc)
        configured = False
    if not configured:
        logger.error(
            "Matrix alert service is not configured; rejecting webhook before delivery"
        )
        raise HTTPException(status_code=503, detail="matrix_service_not_configured")

    if not payload.alerts:
        return AlertResponse(status="ok", alerts_processed=0)

    # Alertmanager retries a whole webhook group after any non-2xx response.
    # Deliver the group as one Matrix event so a later per-alert failure cannot
    # cause already-delivered alerts in the same group to be duplicated.
    message = "\n\n---\n\n".join(
        format_alert_message(alert, payload.status) for alert in payload.alerts
    )
    try:
        sent = await matrix_service.send_alert_message(message)
    except Exception as exc:
        logger.error(
            "Failed to send alert group from receiver '%s': %s",
            payload.receiver,
            exc,
        )
        raise HTTPException(status_code=503, detail="matrix_delivery_failed") from exc

    if not sent:
        logger.error(
            "Matrix delivery returned false for alert group from receiver '%s'",
            payload.receiver,
        )
        raise HTTPException(status_code=503, detail="matrix_delivery_failed")

    processed = len(payload.alerts)
    logger.info(
        "Processed %s/%s alerts from receiver '%s' in one Matrix event",
        processed,
        processed,
        payload.receiver,
    )
    return AlertResponse(status="ok", alerts_processed=processed)
