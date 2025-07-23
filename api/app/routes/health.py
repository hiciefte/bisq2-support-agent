import time

import psutil
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Health check endpoint that monitors system resources and service status.
    """
    # System metrics
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Service status
    rag_service_status = "healthy"  # TODO: Implement actual health check

    return {
        "status": "healthy",
        "timestamp": int(time.time()),
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
