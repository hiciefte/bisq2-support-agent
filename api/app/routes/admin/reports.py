"""Admin reporting routes for support-admin compensation summaries."""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.core.security import verify_admin_access
from app.services.admin_reporting_service import SupportReportingService
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/reports",
    tags=["Admin Reports"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


def get_support_reporting_service(request: Request) -> SupportReportingService:
    pipeline_service = getattr(request.app.state, "unified_pipeline_service", None)
    repository = getattr(pipeline_service, "repository", None)
    db_path = getattr(repository, "db_path", None)
    if not db_path:
        settings = getattr(request.app.state, "settings", None) or get_settings()
        db_path = os.path.join(settings.DATA_DIR, "unified_training.db")
    return SupportReportingService(db_path=db_path)


@router.get("/support-work")
async def get_support_work_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    reviewer: Optional[str] = Query(default=None),
    period_label: Optional[str] = Query(default=None),
    service: SupportReportingService = Depends(get_support_reporting_service),
) -> Dict[str, Any]:
    """Return support-admin work totals for an inclusive date range."""
    try:
        return await run_in_threadpool(
            lambda: service.build_support_work_report(
                start_date=start_date,
                end_date=end_date,
                reviewer=reviewer,
                period_label=period_label,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to build support work report")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build support work report",
        ) from exc
