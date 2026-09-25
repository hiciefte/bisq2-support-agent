"""Read-only public projections and authenticated support-guide publication."""

from functools import partial

from app.core.security import verify_admin_access
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/public/knowledge", tags=["Support guides"])
admin_router = APIRouter(
    prefix="/admin/knowledge-updates/pages",
    tags=["Support guide review"],
    dependencies=[Depends(verify_admin_access)],
)


def _service(request: Request):
    service = getattr(request.app.state, "public_knowledge_service", None)
    if service is None:
        raise HTTPException(503, "Support guides unavailable")
    return service


class PublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(min_length=1, max_length=120)


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1, max_length=120)


@router.get("/{page_id}")
async def get_public_guide(page_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    projection = await run_in_threadpool(
        _service(request).get_public_projection, page_id
    )
    if projection is None:
        raise HTTPException(
            404, "Support guide not published", headers={"Cache-Control": "no-store"}
        )
    return projection


@admin_router.get("/{page_id}")
async def inspect_guide(page_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await run_in_threadpool(_service(request).get_internal_page, page_id)
    except ValueError:
        raise HTTPException(404, "Support guide unavailable") from None


@admin_router.post("/{page_id}/publish")
async def publish_guide(
    page_id: str, body: PublicationRequest, request: Request, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await run_in_threadpool(
            partial(
                _service(request).publish,
                page_id,
                body.revision,
                body.reviewer,
            )
        )
    except ValueError:
        raise HTTPException(
            409, "Support guide changed or is not reviewed; preview again"
        ) from None


@admin_router.post("/{page_id}/revoke")
async def revoke_guide(
    page_id: str, body: RevokeRequest, request: Request, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await run_in_threadpool(_service(request).revoke, page_id, body.reviewer)
    except ValueError:
        raise HTTPException(400, "Invalid support guide request") from None
