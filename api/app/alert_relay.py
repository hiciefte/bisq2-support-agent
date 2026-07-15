"""Minimal out-of-process Alertmanager-to-Matrix relay.

This app intentionally avoids the main API lifespan and its database/RAG startup.
It reuses only the password-authenticated Matrix alert lane and webhook contract.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.channels.plugins.matrix.services.alert_service import (
    ALERT_RELAY_RETENTION_STORE,
    MatrixAlertService,
)
from app.core.config import Settings, get_settings
from app.metrics.privacy_metrics import record_privacy_retention_failure
from app.routes.alertmanager import router as alertmanager_router
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = logging.getLogger(__name__)
SESSION_ROTATION_TIMEOUT_SECONDS = 60.0
SESSION_ROTATION_CANCEL_TIMEOUT_SECONDS = 1.0
SESSION_CLOSE_TIMEOUT_SECONDS = 10.0
matrix_alert_service = MatrixAlertService(get_settings())


def _consume_task_result(task: asyncio.Task[Any]) -> None:
    """Retrieve a detached task result without surfacing cancellation noise."""
    try:
        task.result()
    except BaseException:
        pass


async def _cancel_tasks_bounded(
    tasks: list[asyncio.Task[Any]],
    *,
    label: str,
) -> None:
    """Request cancellation without allowing a resistant task to block."""
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        task.cancel()
    if not pending:
        return
    done, still_pending = await asyncio.wait(
        pending,
        timeout=SESSION_ROTATION_CANCEL_TIMEOUT_SECONDS,
    )
    for task in done:
        _consume_task_result(task)
    for task in still_pending:
        logger.error("%s task ignored cancellation", label)
        task.add_done_callback(_consume_task_result)


async def _close_service_bounded(service: MatrixAlertService) -> None:
    """Close the Matrix client without allowing shutdown to hang."""
    close_task = asyncio.create_task(service.close())
    done, _ = await asyncio.wait(
        {close_task},
        timeout=SESSION_CLOSE_TIMEOUT_SECONDS,
    )
    if close_task in done:
        await close_task
        return
    logger.error("Matrix alert relay close timed out")
    await _cancel_tasks_bounded([close_task], label="Matrix alert relay close")


async def _rotate_session_or_stop(
    service: MatrixAlertService,
    stop_event: asyncio.Event,
) -> int | None:
    """Run one rotation with bounded shutdown and execution time."""
    rotation_task = asyncio.create_task(service.rotate_expired_session())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            {rotation_task, stop_task},
            timeout=SESSION_ROTATION_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if rotation_task in done:
            return await rotation_task
        if stop_task in done:
            return None
        raise TimeoutError("Matrix alert session retention timed out")
    finally:
        await _cancel_tasks_bounded(
            [rotation_task, stop_task],
            label="Matrix alert retention",
        )


async def _session_retention_loop(
    service: MatrixAlertService,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            deleted = await _rotate_session_or_stop(service, stop_event)
            if deleted is None:
                break
            if deleted:
                logger.info("Rotated expired Matrix alert session generation")
        except Exception:
            record_privacy_retention_failure(
                failed_store_groups=(ALERT_RELAY_RETENTION_STORE,)
            )
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
        await _close_service_bounded(matrix_alert_service)


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
