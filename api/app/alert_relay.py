"""Minimal out-of-process Alertmanager-to-Matrix relay.

This app intentionally avoids the main API lifespan and its database/RAG startup.
It reuses only the password-authenticated Matrix alert lane and webhook contract.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from app.channels.plugins.matrix.services.alert_service import MatrixAlertService
from app.core.config import get_settings
from app.routes.alertmanager import router as alertmanager_router
from fastapi import FastAPI, HTTPException

logger = logging.getLogger(__name__)


matrix_alert_service = MatrixAlertService(get_settings())


@asynccontextmanager
async def lifespan(relay_app: FastAPI) -> AsyncIterator[None]:
    """Own the relay's Matrix client without starting the main API services."""
    relay_app.state.matrix_alert_service = matrix_alert_service
    relay_app.state.relay_configured = matrix_alert_service.is_configured()
    if relay_app.state.relay_configured:
        logger.info("Matrix alert relay configured")
    else:
        logger.error("Matrix alert relay is missing its alert-lane configuration")

    try:
        yield
    finally:
        await matrix_alert_service.close()


app = FastAPI(title="Bisq Matrix Alert Relay", lifespan=lifespan)
app.state.matrix_alert_service = matrix_alert_service
app.state.relay_configured = matrix_alert_service.is_configured()
app.include_router(alertmanager_router)


@app.get("/ready")
async def ready() -> dict[str, str]:
    """Fail readiness when the Matrix alert lane is not configured."""
    if not bool(getattr(app.state, "relay_configured", False)):
        raise HTTPException(status_code=503, detail="matrix_alert_relay_not_configured")
    return {"status": "ready"}
