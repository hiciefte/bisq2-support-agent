import asyncio
import logging
import os
import time
from typing import Any

import psutil
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)

READINESS_DEPENDENCY_TIMEOUT_SECONDS = 3.0


def _rag_initialized(rag_service: Any) -> bool:
    """Return whether the complete live RAG reader state is available."""
    return bool(
        rag_service is not None
        and getattr(rag_service, "rag_chain", None) is not None
        and getattr(rag_service, "document_retriever", None) is not None
        and getattr(rag_service, "retriever", None) is not None
    )


async def _vector_store_ready(rag_service: Any) -> bool:
    """Run the RAG-owned vector check with a prompt timeout."""
    check_readiness = getattr(rag_service, "check_readiness", None)
    if not callable(check_readiness):
        return False
    try:
        return bool(
            await asyncio.wait_for(
                check_readiness(),
                timeout=READINESS_DEPENDENCY_TIMEOUT_SECONDS,
            )
        )
    except Exception:
        logger.warning("Vector-store readiness check failed", exc_info=True)
        return False


def _matrix_session_ready(request: Request) -> bool:
    """Check the authenticated Matrix session without exposing its details."""
    channel = getattr(request.app.state, "matrix_channel", None)
    if channel is None:
        return False
    try:
        runtime = getattr(channel, "runtime", None)
        resolve_optional = getattr(runtime, "resolve_optional", None)
        connection_manager = (
            resolve_optional("matrix_connection_manager")
            if callable(resolve_optional)
            else None
        )
        health_check = getattr(connection_manager, "health_check", None)
        if callable(health_check):
            return bool(health_check())
        return False
    except Exception:
        logger.warning("Matrix session readiness check failed", exc_info=True)
        return False


async def _bisq_api_ready(request: Request) -> bool:
    """Check enabled Bisq lanes using their shared readiness snapshot."""
    service = getattr(request.app.state, "bisq_mcp_service", None)
    health_check = getattr(service, "health_check", None)
    if not callable(health_check):
        return False
    try:
        health = await asyncio.wait_for(
            health_check(),
            timeout=READINESS_DEPENDENCY_TIMEOUT_SECONDS,
        )
        readiness = health.get("readiness", {}) if isinstance(health, dict) else {}
        return bool(
            health.get("api_available") is True
            and isinstance(readiness, dict)
            and readiness.get("status") == "healthy"
        )
    except Exception:
        logger.warning("Bisq API readiness check failed", exc_info=True)
        return False


@router.get("/health")
async def health_check(request: Request):
    """
    Health check endpoint that monitors system resources and service status.
    Includes build metadata for cache invalidation troubleshooting.

    Returns "initializing" status until RAG service is fully loaded.
    This prevents deployment validation from testing endpoints before they're ready.
    """
    # System metrics
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Check if RAG service is initialized and ready
    rag_service_status = "initializing"
    if hasattr(request.app.state, "rag_service") and request.app.state.rag_service:
        rag_service_status = "healthy"

    bisq_status = {"status": "unknown"}
    bisq_service = getattr(request.app.state, "bisq_mcp_service", None)
    mcp_enabled = False
    if bisq_service is not None:
        mcp_enabled = bool(getattr(bisq_service, "enabled", False))
        try:
            bisq_health = await bisq_service.health_check()
            bisq_status = bisq_health.get("readiness", {"status": "unknown"})
        except Exception:  # noqa: BLE001
            bisq_status = {"status": "unhealthy"}
    else:
        app_settings = getattr(request.app.state, "settings", None)
        mcp_enabled = bool(getattr(app_settings, "ENABLE_BISQ_MCP_INTEGRATION", False))

    # Overall status depends on RAG readiness
    overall_status = "healthy" if rag_service_status == "healthy" else "initializing"

    # Build metadata (for cache invalidation monitoring)
    # BUILD_ID is injected via Docker build arg from git commit hash
    # Format: build-{git-hash} (e.g., build-a3f2c1b)
    build_id = os.getenv("BUILD_ID", "unknown")

    return {
        "status": overall_status,
        "timestamp": int(time.time()),
        "build_id": build_id,
        "mcp_enabled": mcp_enabled,
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_percent": disk.percent,
        },
        "services": {"rag": rag_service_status, "bisq2_api": bisq_status},
    }


@router.get("/health/ready")
async def readiness_check(request: Request) -> JSONResponse:
    """Report required dependency readiness and fail with HTTP 503."""
    settings = getattr(request.app.state, "settings", None)
    rag_service = getattr(request.app.state, "rag_service", None)
    rag_ready = _rag_initialized(rag_service)

    matrix_required = bool(getattr(settings, "MATRIX_SYNC_ENABLED", False))
    matrix_ready = _matrix_session_ready(request) if matrix_required else False

    bisq_required = bool(
        getattr(settings, "BISQ2_CHANNEL_ENABLED", False)
        or getattr(settings, "ENABLE_BISQ_MCP_INTEGRATION", False)
    )
    vector_task = (
        asyncio.create_task(_vector_store_ready(rag_service)) if rag_ready else None
    )
    bisq_task = asyncio.create_task(_bisq_api_ready(request)) if bisq_required else None
    vector_ready = await vector_task if vector_task is not None else False
    bisq_ready = await bisq_task if bisq_task is not None else False

    components = {
        "rag": {
            "status": "ready" if rag_ready else "unavailable",
            "required": True,
        },
        "vector_store": {
            "status": "ready" if vector_ready else "unavailable",
            "required": True,
        },
        "matrix": {
            "status": (
                "ready"
                if matrix_required and matrix_ready
                else "unavailable" if matrix_required else "disabled"
            ),
            "required": matrix_required,
        },
        "bisq2_api": {
            "status": (
                "ready"
                if bisq_required and bisq_ready
                else "unavailable" if bisq_required else "disabled"
            ),
            "required": bisq_required,
        },
    }
    ready = bool(
        rag_ready
        and vector_ready
        and (not matrix_required or matrix_ready)
        and (not bisq_required or bisq_ready)
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "degraded",
            "components": components,
        },
    )


@router.get("/health/live")
async def liveness_check():
    """
    Liveness probe that checks if the service is running.
    """
    return {"status": "alive"}
