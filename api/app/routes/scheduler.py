"""Internal, least-privilege endpoints for scheduled application jobs."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings, get_settings
from app.core.security import verify_scheduler_access
from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal/scheduler",
    tags=["Internal Scheduler"],
    dependencies=[Depends(verify_scheduler_access)],
    responses={
        401: {"description": "Scheduler authentication required"},
        403: {"description": "Invalid scheduler credentials"},
        503: {"description": "Scheduler dependency unavailable"},
    },
)


async def process_feedback_task() -> Any:
    """Load and run feedback processing only when the job is invoked."""
    from app.scripts.process_feedback import main

    return await main()


async def update_wiki_task() -> Any:
    """Load optional wiki-download dependencies only for the weekly job."""
    from app.scripts.update_wiki import main

    return await main()


def run_reconciliation(**kwargs: Any) -> dict[str, Any]:
    """Run the synchronous reconciliation implementation."""
    from app.scripts.reconcile_llm_wiki_coverage import run_reconciliation as run

    return run(**kwargs)


async def trigger_bisq_sync(*, request: Request, pipeline_service: Any) -> Any:
    """Invoke the existing Bisq training sync without widening its auth."""
    from app.routes.admin.training import trigger_bisq_sync as handler

    return await handler(request=request, pipeline_service=pipeline_service)


async def trigger_matrix_sync(*, request: Request, pipeline_service: Any) -> Any:
    """Invoke the existing Matrix training sync without widening its auth."""
    from app.routes.admin.training import trigger_matrix_sync as handler

    return await handler(request=request, pipeline_service=pipeline_service)


def _task_failure(task_name: str, error: Exception) -> HTTPException:
    logger.exception("Scheduled %s task failed", task_name, exc_info=error)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Scheduled task failed",
    )


def _require_app_service(request: Request, state_name: str) -> Any:
    service = getattr(request.app.state, state_name, None)
    if service is None:
        logger.error("Scheduler dependency is unavailable: %s", state_name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduled task dependency unavailable",
        )
    return service


@router.post("/process-feedback")
async def process_feedback() -> dict[str, Any]:
    """Apply persisted feedback learning inside the API process."""
    try:
        result = await process_feedback_task()
    except Exception as error:
        raise _task_failure("feedback processing", error) from error

    entries_processed = (
        int(result.get("entries_processed", 0)) if isinstance(result, dict) else 0
    )
    return {
        "status": "completed",
        "entries_processed": entries_processed,
    }


@router.post("/update-wiki")
async def update_wiki(request: Request) -> dict[str, Any]:
    """Refresh wiki data and rebuild the live retrieval index."""
    rag_service = _require_app_service(request, "rag_service")

    try:
        result = await update_wiki_task()
        rebuilt = await rag_service.rebuild_live_index(force_rebuild=True)
        if not rebuilt:
            raise RuntimeError("RAG index rebuild did not complete")
    except Exception as error:
        raise _task_failure("wiki update", error) from error

    pages_processed = (
        int(result.get("pages_processed", 0)) if isinstance(result, dict) else 0
    )
    return {
        "status": "completed",
        "pages_processed": pages_processed,
    }


@router.post("/reconcile-llm-wiki-coverage")
async def reconcile_llm_wiki_coverage(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Reconcile reviewed LLM-Wiki coverage against pending candidates."""
    pipeline_service = _require_app_service(request, "unified_pipeline_service")

    try:
        result = await run_in_threadpool(
            run_reconciliation,
            settings=settings,
            db_path=pipeline_service.repository.db_path,
            apply=True,
        )
    except Exception as error:
        raise _task_failure("LLM-Wiki coverage reconciliation", error) from error

    return {"status": "completed", "result": result}


async def _run_training_sync(
    *,
    source: str,
    request: Request,
) -> dict[str, Any]:
    pipeline_service = _require_app_service(request, "unified_pipeline_service")
    handler = trigger_bisq_sync if source == "bisq" else trigger_matrix_sync

    try:
        result = await handler(
            request=request,
            pipeline_service=pipeline_service,
        )
        if result.status == "error":
            raise RuntimeError(f"{source} training sync reported an error")
    except Exception as error:
        raise _task_failure(f"{source} training sync", error) from error

    return {
        "status": result.status,
        "processed": result.processed,
        "message": result.message,
    }


@router.post("/training-sync/bisq")
async def sync_bisq_training(request: Request) -> dict[str, Any]:
    """Run the scheduled Bisq conversation sync."""
    return await _run_training_sync(source="bisq", request=request)


@router.post("/training-sync/matrix")
async def sync_matrix_training(request: Request) -> dict[str, Any]:
    """Run the scheduled Matrix conversation sync."""
    return await _run_training_sync(source="matrix", request=request)
