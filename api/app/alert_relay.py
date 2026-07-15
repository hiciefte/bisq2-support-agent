"""Minimal out-of-process Alertmanager-to-Matrix relay.

This app intentionally avoids the main API lifespan and its database/RAG startup.
It reuses only the password-authenticated Matrix alert lane and webhook contract.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.channels.plugins.matrix.services.alert_service import MatrixAlertService
from app.core.config import Settings, get_settings
from app.metrics.privacy_metrics import record_privacy_retention_failure
from app.routes.alertmanager import router as alertmanager_router
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = logging.getLogger(__name__)


matrix_alert_service = MatrixAlertService(get_settings())


async def _session_retention_loop(
    service: MatrixAlertService,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            deleted = await service.rotate_expired_session()
            if deleted:
                logger.info("Rotated expired Matrix alert session generation")
        except Exception:
            record_privacy_retention_failure()
            logger.exception("Matrix alert session retention failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3600)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(relay_app: FastAPI) -> AsyncIterator[None]:
    """Own the relay's Matrix client without starting the main API services."""
    relay_app.state.matrix_alert_service = matrix_alert_service
    if matrix_alert_service.is_configured():
        logger.info("Matrix alert relay configured")
    else:
        logger.error("Matrix alert relay is missing its alert-lane configuration")

    stop_event = asyncio.Event()
    retention_task = asyncio.create_task(
        _session_retention_loop(matrix_alert_service, stop_event)
    )
    try:
        yield
    finally:
        stop_event.set()
        await retention_task
        await matrix_alert_service.close()


app = FastAPI(title="Bisq Matrix Alert Relay", lifespan=lifespan)
app.state.matrix_alert_service = matrix_alert_service
app.include_router(alertmanager_router)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Expose relay-process retention health to Prometheus."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready")
async def ready(
    request: Request, settings: Settings = Depends(get_settings)
) -> dict[str, str]:
    """Fail readiness when authentication or the Matrix lane is not configured."""
    if not settings.ALERTMANAGER_WEBHOOK_SECRET.strip():
        raise HTTPException(
            status_code=503,
            detail="alertmanager_webhook_not_configured",
        )

    service = getattr(request.app.state, "matrix_alert_service", None)
    is_configured = getattr(service, "is_configured", None)
    try:
        configured = bool(is_configured()) if callable(is_configured) else False
    except Exception:
        logger.warning(
            "Failed to check Matrix alert relay configuration", exc_info=True
        )
        configured = False
    if not configured:
        raise HTTPException(status_code=503, detail="matrix_alert_relay_not_configured")
    return {"status": "ready"}
