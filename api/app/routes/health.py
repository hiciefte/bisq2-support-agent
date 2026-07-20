import asyncio
import logging
import os
import time
from typing import Any

import psutil
from app.channels.plugins.bisq2.test_scope import (
    Bisq2TestScope,
    resolve_bisq2_test_scope,
)
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bisq API readiness check failed (%s)", type(exc).__name__)
        return False


def _bisq_test_scope_ready(
    request: Request,
    configured_scope: Bisq2TestScope,
) -> bool:
    """Verify every active Bisq boundary shares the configured test scope."""
    if not configured_scope.ready:
        return False
    try:
        registry = getattr(request.app.state, "channel_registry", None)
        get_channel = getattr(registry, "get", None)
        channel = get_channel("bisq2") if callable(get_channel) else None
        if channel is None or getattr(channel, "is_connected", False) is not True:
            return False
        if getattr(channel, "test_scope_rebaseline_complete", False) is not True:
            return False
        if getattr(channel, "test_scope_persistence_capable", False) is not True:
            return False
        if getattr(channel, "test_scope_persistence_healthy", False) is not True:
            return False
        if getattr(channel, "test_scope_websocket_ready", False) is not True:
            return False

        channel_scope = getattr(channel, "_test_scope", None)
        runtime = getattr(channel, "runtime", None)
        resolve_optional = getattr(runtime, "resolve_optional", None)
        bisq_api = resolve_optional("bisq2_api") if callable(resolve_optional) else None
        api_scope = getattr(bisq_api, "_test_scope", None)
        reaction_handler = (
            resolve_optional("bisq2_reaction_handler")
            if callable(resolve_optional)
            else None
        )
        if reaction_handler is None:
            return False
        if getattr(reaction_handler, "is_listening", False) is not True:
            return False
        chatops_adapter = (
            resolve_optional("bisq2_chatops_adapter")
            if callable(resolve_optional)
            else None
        )
        settings = getattr(request.app.state, "settings", None)
        if (
            getattr(settings, "BISQ2_CHATOPS_ENABLED", False) is True
            and chatops_adapter is None
        ):
            return False
        active_scopes = [
            channel_scope,
            api_scope,
            getattr(reaction_handler, "_test_scope", None),
        ]
        if chatops_adapter is not None:
            active_scopes.append(getattr(chatops_adapter, "_test_scope", None))
        for active_scope in active_scopes:
            if not isinstance(active_scope, Bisq2TestScope):
                return False
            if not active_scope.ready:
                return False
            if active_scope.allowed_channel_ids != configured_scope.allowed_channel_ids:
                return False
            if (
                active_scope.allowed_sender_profile_ids
                != configured_scope.allowed_sender_profile_ids
            ):
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Bisq production-test scope readiness check failed (%s)",
            type(exc).__name__,
        )
        return False


def _channel_launch_control_ready(request: Request) -> bool:
    """Check persistent delivery controls without exposing their state."""
    service = getattr(request.app.state, "channel_launch_control_service", None)
    check_readiness = getattr(service, "check_readiness", None)
    if not callable(check_readiness):
        return False
    try:
        return check_readiness() is True
    except Exception:
        logger.warning("Channel launch-control readiness check failed", exc_info=True)
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
    launch_control_ready = _channel_launch_control_ready(request)
    launch_control_required = bool(
        getattr(settings, "AUTONOMOUS_DELIVERY_ENABLED", False)
    )

    matrix_required = bool(getattr(settings, "MATRIX_SYNC_ENABLED", False))
    matrix_ready = _matrix_session_ready(request) if matrix_required else False

    bisq_channel_required = bool(getattr(settings, "BISQ2_CHANNEL_ENABLED", False))
    bisq_scope = resolve_bisq2_test_scope(settings)
    bisq_export_required = bool(bisq_channel_required or bisq_scope.ready)
    bisq_required = bool(
        bisq_export_required or getattr(settings, "ENABLE_BISQ_MCP_INTEGRATION", False)
    )
    bisq_scope_ready = bool(
        _bisq_test_scope_ready(request, bisq_scope)
        if bisq_channel_required
        else bisq_scope.ready
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
        "channel_launch_control": {
            "status": "ready" if launch_control_ready else "unavailable",
            "required": launch_control_required,
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
        "bisq2_test_scope": {
            "status": (
                "ready"
                if bisq_export_required and bisq_scope_ready
                else "unavailable" if bisq_export_required else "disabled"
            ),
            "required": bisq_export_required,
            "channel_count": bisq_scope.channel_count,
            "sender_profile_count": bisq_scope.sender_profile_count,
        },
    }
    ready = bool(
        rag_ready
        and vector_ready
        and (not launch_control_required or launch_control_ready)
        and (not matrix_required or matrix_ready)
        and (not bisq_required or bisq_ready)
        and (not bisq_export_required or bisq_scope_ready)
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
