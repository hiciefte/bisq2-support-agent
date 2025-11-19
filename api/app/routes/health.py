import os
import time

import psutil  # type: ignore[import-untyped]
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Health check endpoint that monitors system resources and service status.
    Includes build metadata for cache invalidation troubleshooting.
    """
    # System metrics
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Service status
    rag_service_status = "healthy"  # TODO: Implement actual health check

    # Build metadata (for cache invalidation monitoring)
    # BUILD_ID is injected via Docker build arg from git commit hash
    # Format: build-{git-hash} (e.g., build-a3f2c1b)
    build_id = os.getenv("BUILD_ID", "unknown")

    return {
        "status": "healthy",
        "timestamp": int(time.time()),
        "build_id": build_id,
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "disk_percent": disk.percent,
        },
        "services": {"rag": rag_service_status},
    }


@router.get("/health/ready")
async def readiness_check():
    """
    Readiness probe that checks if the service is ready to handle requests.
    """
    return {"status": "ready"}


@router.get("/health/live")
async def liveness_check():
    """
    Liveness probe that checks if the service is running.
    """
    return {"status": "alive"}
