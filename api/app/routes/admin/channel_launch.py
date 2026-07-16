"""Admin endpoints for autonomous channel launch controls."""

from __future__ import annotations

from app.core.security import verify_admin_access
from app.services.channel_launch_control_service import (
    ChannelLaunchControlService,
    ChannelLaunchPolicy,
    GlobalLaunchControl,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter(
    prefix="/admin/channels/launch-control",
    tags=["Admin Channel Launch Control"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


class GlobalLaunchControlResponse(BaseModel):
    autonomous_delivery_enabled: bool
    updated_at: str


class UpdateGlobalLaunchControlRequest(BaseModel):
    autonomous_delivery_enabled: bool


class ChannelLaunchPolicyResponse(BaseModel):
    channel_id: str
    shadow_mode: bool
    canary_enabled: bool
    canary_hourly_limit: int
    canary_daily_limit: int
    canary_reservation_count: int
    updated_at: str


class UpdateChannelLaunchPolicyRequest(BaseModel):
    shadow_mode: bool | None = None
    canary_enabled: bool | None = None
    canary_hourly_limit: int | None = None
    canary_daily_limit: int | None = None


def _service_from_app(request: Request) -> ChannelLaunchControlService:
    service = getattr(request.app.state, "channel_launch_control_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel launch control service is not available",
        )
    return service


def _global_response(control: GlobalLaunchControl) -> GlobalLaunchControlResponse:
    return GlobalLaunchControlResponse(
        autonomous_delivery_enabled=control.autonomous_delivery_enabled,
        updated_at=control.updated_at,
    )


def _channel_response(
    service: ChannelLaunchControlService,
    policy: ChannelLaunchPolicy,
) -> ChannelLaunchPolicyResponse:
    return ChannelLaunchPolicyResponse(
        channel_id=policy.channel_id,
        shadow_mode=policy.shadow_mode,
        canary_enabled=policy.canary_enabled,
        canary_hourly_limit=policy.canary_hourly_limit,
        canary_daily_limit=policy.canary_daily_limit,
        canary_reservation_count=service.reservation_count(policy.channel_id),
        updated_at=policy.updated_at,
    )


@router.get("/global", response_model=GlobalLaunchControlResponse)
def get_global_launch_control(request: Request) -> GlobalLaunchControlResponse:
    return _global_response(_service_from_app(request).get_global_control())


@router.put("/global", response_model=GlobalLaunchControlResponse)
def update_global_launch_control(
    payload: UpdateGlobalLaunchControlRequest,
    request: Request,
) -> GlobalLaunchControlResponse:
    try:
        control = _service_from_app(request).set_autonomous_delivery_enabled(
            payload.autonomous_delivery_enabled
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    return _global_response(control)


@router.get("", response_model=list[ChannelLaunchPolicyResponse])
def list_channel_launch_policies(
    request: Request,
) -> list[ChannelLaunchPolicyResponse]:
    service = _service_from_app(request)
    return [
        _channel_response(service, policy) for policy in service.list_channel_policies()
    ]


@router.get("/{channel_id}", response_model=ChannelLaunchPolicyResponse)
def get_channel_launch_policy(
    channel_id: str,
    request: Request,
) -> ChannelLaunchPolicyResponse:
    service = _service_from_app(request)
    try:
        return _channel_response(service, service.get_channel_policy(channel_id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None


@router.put("/{channel_id}", response_model=ChannelLaunchPolicyResponse)
def update_channel_launch_policy(
    channel_id: str,
    payload: UpdateChannelLaunchPolicyRequest,
    request: Request,
) -> ChannelLaunchPolicyResponse:
    if all(
        value is None
        for value in (
            payload.shadow_mode,
            payload.canary_enabled,
            payload.canary_hourly_limit,
            payload.canary_daily_limit,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one launch policy field must be provided",
        )
    try:
        service = _service_from_app(request)
        policy = service.set_channel_policy(
            channel_id,
            shadow_mode=payload.shadow_mode,
            canary_enabled=payload.canary_enabled,
            canary_hourly_limit=payload.canary_hourly_limit,
            canary_daily_limit=payload.canary_daily_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None
    return _channel_response(service, policy)
