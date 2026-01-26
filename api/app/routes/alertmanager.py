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
    Alertmanager -> POST /alertmanager/alerts -> API -> Matrix rooms
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Request
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
    # Get matrix service from app state
    matrix_service = getattr(request.app.state, "matrix_shadow_service", None)

    if not matrix_service:
        logger.warning(
            "Matrix shadow service not available, alerts will not be sent to Matrix"
        )
        return AlertResponse(
            status="ok",
            alerts_processed=0,
            warning="matrix_service_unavailable",
        )

    # Process each alert
    processed = 0
    for alert in payload.alerts:
        message = format_alert_message(alert, payload.status)

        try:
            await matrix_service.send_alert_message(message)
            processed += 1
            logger.info(
                f"Sent alert to Matrix: {alert.labels.get('alertname', 'Unknown')} "
                f"({payload.status})"
            )
        except Exception as e:
            logger.error(
                f"Failed to send alert to Matrix: {alert.labels.get('alertname', 'Unknown')}: {e}"
            )

    logger.info(
        f"Processed {processed}/{len(payload.alerts)} alerts from receiver '{payload.receiver}'"
    )

    return AlertResponse(status="ok", alerts_processed=processed)
