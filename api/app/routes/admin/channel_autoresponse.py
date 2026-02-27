"""Admin endpoints for channel autoresponse policy."""

from __future__ import annotations

from typing import List

from app.core.security import verify_admin_access
from app.services.channel_autoresponse_policy_service import (
    ChannelAutoResponsePolicy,
    ChannelAutoResponsePolicyService,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter(
    prefix="/admin/channels/autoresponse",
    tags=["Admin Channel Autoresponse"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


class ChannelAutoResponsePolicyResponse(BaseModel):
    channel_id: str
    enabled: bool
    generation_enabled: bool
    updated_at: str


class UpdateChannelAutoResponsePolicyRequest(BaseModel):
    enabled: bool | None = None
    generation_enabled: bool | None = None


def _service_from_app(request: Request) -> ChannelAutoResponsePolicyService:
    service = getattr(request.app.state, "channel_autoresponse_policy_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel autoresponse policy service is not available",
        )
    return service


def _to_response(
    policy: ChannelAutoResponsePolicy,
) -> ChannelAutoResponsePolicyResponse:
    return ChannelAutoResponsePolicyResponse(
        channel_id=policy.channel_id,
        enabled=policy.enabled,
        generation_enabled=policy.generation_enabled,
        updated_at=policy.updated_at,
    )


@router.get(
    "",
    response_model=List[ChannelAutoResponsePolicyResponse],
)
def list_channel_autoresponse_policies(
    request: Request,
) -> List[ChannelAutoResponsePolicyResponse]:
    service = _service_from_app(request)
    return [_to_response(policy) for policy in service.list_policies()]


@router.get(
    "/{channel_id}",
    response_model=ChannelAutoResponsePolicyResponse,
)
def get_channel_autoresponse_policy(
    channel_id: str,
    request: Request,
) -> ChannelAutoResponsePolicyResponse:
    service = _service_from_app(request)
    try:
        return _to_response(service.get_policy(channel_id))
    except ValueError:
        supported = ", ".join(service.supported_channels)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel_id '{channel_id}'. Supported channels: {supported}",
        ) from None
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No policy found for channel_id '{channel_id}'",
        ) from None


@router.put(
    "/{channel_id}",
    response_model=ChannelAutoResponsePolicyResponse,
)
def update_channel_autoresponse_policy(
    channel_id: str,
    payload: UpdateChannelAutoResponsePolicyRequest,
    request: Request,
) -> ChannelAutoResponsePolicyResponse:
    service = _service_from_app(request)
    if payload.enabled is None and payload.generation_enabled is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of enabled or generation_enabled must be provided",
        )
    try:
        updated = service.set_policy(
            channel_id=channel_id,
            enabled=payload.enabled,
            generation_enabled=payload.generation_enabled,
        )
    except ValueError:
        supported = ", ".join(service.supported_channels)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported channel_id '{channel_id}'. Supported channels: {supported}",
        ) from None
    return _to_response(updated)
