"""
Admin endpoints for vector store management.
"""

import logging
from typing import Any, Dict

from app.core.exceptions import BaseAppException
from app.core.security import verify_admin_access
from fastapi import APIRouter, Depends, status

logger = logging.getLogger(__name__)

# Create admin router with authentication
router = APIRouter(
    prefix="/admin/vectorstore",
    tags=["Admin Vector Store"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


@router.get("/status")
async def get_vectorstore_status(
    detailed: bool = False,
) -> Dict[str, Any]:
    """
    Get vector store rebuild status.

    Args:
        detailed: If True, include full change history. If False, return summary.

    Returns:
        Status dictionary with rebuild state and pending changes
    """
    logger.info(f"Vector store status requested (detailed={detailed})")

    try:
        # Import here to avoid circular dependency
        from app.main import rag_service

        if detailed:
            return rag_service.get_rebuild_status()
        else:
            return rag_service.get_rebuild_summary()

    except Exception as e:
        logger.error(f"Failed to get vector store status: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to retrieve vector store status",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="VECTORSTORE_STATUS_FAILED",
        ) from e


@router.post("/rebuild")
async def trigger_vectorstore_rebuild() -> Dict[str, Any]:
    """
    Manually trigger vector store rebuild.

    This endpoint executes a full rebuild of the vector store to incorporate
    all pending FAQ changes. The rebuild is asynchronous but this endpoint
    waits for completion before returning.

    Returns:
        Rebuild result with success status, duration, and changes applied
    """
    logger.info("Manual vector store rebuild triggered")

    try:
        from app.main import rag_service

        result = await rag_service.manual_rebuild()

        if result.get("success"):
            logger.info(
                f"Vector store rebuild completed: "
                f"{result.get('changes_applied', 0)} changes in "
                f"{result.get('rebuild_time', 0):.2f}s"
            )
        else:
            logger.warning(f"Vector store rebuild completed with issues: {result}")

        return result

    except Exception as e:
        logger.error(f"Vector store rebuild failed: {e}", exc_info=True)
        raise BaseAppException(
            detail="Vector store rebuild failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="VECTORSTORE_REBUILD_FAILED",
        ) from e
