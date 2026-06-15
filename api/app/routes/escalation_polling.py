"""
User-facing polling endpoint for escalation responses.
"""

import asyncio
import json
import logging
from typing import AsyncIterator

from app.channels.escalation_localization import normalize_language_code
from app.channels.plugins.web.identity import derive_web_user_context
from app.core.config import get_settings
from app.models.escalation import (
    EscalationStatus,
    RateStaffAnswerRequest,
    UserPollResponse,
)
from app.routes.admin.escalations import get_escalation_service
from app.services.escalation.rating_token import (
    generate_rating_token,
    verify_rating_token,
)
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import StreamingResponse

# Setup logging
logger = logging.getLogger(__name__)

# Create public router (no authentication required)
router = APIRouter()

# Message ID pattern: optional channel prefix + UUID v4
# Examples: "160541ae-..." (plain UUID) or "web_160541ae-..." (channel-prefixed)
MESSAGE_ID_PATH_PATTERN = (
    r"^(?:[a-z]+_)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _derive_user_resolution(escalation) -> str | None:
    """Map internal escalation state to user-visible resolution semantics.

    If a staff answer exists, this must be surfaced as "responded" even when
    the escalation lifecycle status is already "closed" after response handling.
    """
    if escalation.staff_answer:
        return "responded"
    if escalation.status == EscalationStatus.CLOSED:
        return "closed"
    if escalation.status == EscalationStatus.RESPONDED:
        return "responded"
    return None


def _derive_rater_id(request: Request) -> str:
    """Derive stable anonymous rater identity for token binding."""
    user_id, _ = derive_web_user_context(request)
    return user_id


def _get_rating_signing_key(settings) -> str:
    key = (getattr(settings, "ESCALATION_RATING_TOKEN_SECRET", "") or "").strip()
    if key:
        return key
    # Backward-compatible fallback in test/dev environments.
    return settings.ADMIN_API_KEY


def _build_rate_token_for_escalation(
    escalation,
    message_id: str,
    rater_id: str,
    signing_key: str,
    settings,
) -> str | None:
    if not escalation.staff_answer or not signing_key:
        return None
    return generate_rating_token(
        message_id=message_id,
        rater_id=rater_id,
        signing_key=signing_key,
        ttl_seconds=getattr(settings, "ESCALATION_RATING_TOKEN_TTL_SECONDS", 3600),
    )


async def _localize_staff_answer(
    *,
    request: Request,
    escalation,
) -> str | None:
    """Translate canonical staff answer for user-facing polling payloads."""
    answer = str(getattr(escalation, "staff_answer", "") or "").strip()
    if not answer:
        return None

    target_lang = normalize_language_code(getattr(escalation, "user_language", None))
    if target_lang == "en":
        return answer

    translation_service = getattr(request.app.state, "translation_service", None)
    if translation_service is None:
        return answer

    try:
        translated = await translation_service.translate_response(
            answer,
            target_lang=target_lang,
            source_lang="en",
        )
        raw_translated_text = (
            translated.get("translated_text") if isinstance(translated, dict) else None
        )
        if isinstance(raw_translated_text, str):
            translated_text = raw_translated_text.strip()
            if translated_text:
                return translated_text
    except Exception:
        logger.warning(
            "Failed to localize polled staff answer for message_id=%s (lang=%s)",
            getattr(escalation, "message_id", "<unknown>"),
            target_lang,
            exc_info=True,
        )

    return answer


async def _get_escalation_or_404(service, message_id: str):
    escalation = await service.repository.get_by_message_id(message_id)

    if not escalation:
        logger.debug(f"Message ID not found: {message_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found"},
        )
    return escalation


async def _build_user_poll_response(
    *,
    request: Request,
    escalation,
    message_id: str,
    settings,
) -> UserPollResponse:
    signing_key = _get_rating_signing_key(settings)
    rater_id = _derive_rater_id(request)
    localized_staff_answer = await _localize_staff_answer(
        request=request,
        escalation=escalation,
    )

    if escalation.status in (
        EscalationStatus.PENDING,
        EscalationStatus.IN_REVIEW,
    ):
        return UserPollResponse(
            status="pending",
            staff_answer=None,
            responded_at=None,
            resolution=None,
            closed_at=None,
            user_language=escalation.user_language,
        )

    if escalation.status == EscalationStatus.RESPONDED:
        rate_token = _build_rate_token_for_escalation(
            escalation=escalation,
            message_id=message_id,
            rater_id=rater_id,
            signing_key=signing_key,
            settings=settings,
        )
        return UserPollResponse(
            status="resolved",
            staff_answer=localized_staff_answer,
            responded_at=escalation.responded_at,
            resolution="responded",
            closed_at=None,
            staff_answer_rating=escalation.staff_answer_rating,
            rate_token=rate_token,
            user_language=escalation.user_language,
        )

    if escalation.status == EscalationStatus.CLOSED:
        rate_token = _build_rate_token_for_escalation(
            escalation=escalation,
            message_id=message_id,
            rater_id=rater_id,
            signing_key=signing_key,
            settings=settings,
        )
        return UserPollResponse(
            status="resolved",
            staff_answer=localized_staff_answer,
            responded_at=escalation.responded_at,
            resolution=_derive_user_resolution(escalation),
            closed_at=escalation.closed_at,
            staff_answer_rating=escalation.staff_answer_rating,
            rate_token=rate_token,
            user_language=escalation.user_language,
        )

    return UserPollResponse(
        status="pending",
        staff_answer=None,
        responded_at=None,
        resolution=None,
        closed_at=None,
        user_language=escalation.user_language,
    )


def _is_terminal_user_response(response: UserPollResponse) -> bool:
    return response.status == "resolved" and (
        bool(response.staff_answer) or response.resolution == "closed"
    )


def _format_sse_event(event: str, payload: UserPollResponse) -> str:
    data = payload.model_dump(mode="json")
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n"


def _get_event_broker(request: Request, service):
    broker = getattr(service, "event_broker", None)
    if broker is not None:
        return broker
    return getattr(request.app.state, "escalation_event_broker", None)


@router.get("/escalations/{message_id}/response", response_model=UserPollResponse)
async def poll_escalation_response(
    request: Request,
    message_id: str = Path(
        ...,
        description="Message ID from the original question (UUID with optional channel prefix)",
        pattern=MESSAGE_ID_PATH_PATTERN,
    ),
    service=Depends(get_escalation_service),
    settings=Depends(get_settings),
) -> UserPollResponse:
    """Poll for escalation response by message ID.

    Public endpoint - no authentication required.

    Args:
        message_id: UUID from the original question
        service: Escalation service dependency

    Returns:
        UserPollResponse with status and optional staff_answer

    Raises:
        HTTPException: 404 if message_id not found, 422 if invalid UUID
    """
    logger.debug(f"User polling for escalation response: {message_id}")

    try:
        escalation = await _get_escalation_or_404(service, message_id)
        return await _build_user_poll_response(
            request=request,
            escalation=escalation,
            message_id=message_id,
            settings=settings,
        )

    except HTTPException:
        # Re-raise HTTP exceptions without wrapping
        raise
    except Exception as e:
        logger.error(
            f"Failed to poll escalation response for {message_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve escalation status",
        ) from e


@router.get("/escalations/{message_id}/events")
async def stream_escalation_events(
    request: Request,
    message_id: str = Path(
        ...,
        description="Message ID from the original question (UUID with optional channel prefix)",
        pattern=MESSAGE_ID_PATH_PATTERN,
    ),
    service=Depends(get_escalation_service),
    settings=Depends(get_settings),
) -> StreamingResponse:
    """Stream escalation response updates via Server-Sent Events."""
    logger.debug(f"User streaming escalation response: {message_id}")

    try:
        await _get_escalation_or_404(service, message_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to open escalation event stream for {message_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to open escalation event stream",
        ) from e

    async def event_stream() -> AsyncIterator[str]:
        broker = _get_event_broker(request, service)
        if broker is None:
            escalation = await service.repository.get_by_message_id(message_id)
            if escalation is None:
                return
            response = await _build_user_poll_response(
                request=request,
                escalation=escalation,
                message_id=message_id,
                settings=settings,
            )
            yield _format_sse_event("escalation", response)
            return

        async with broker.subscribe(message_id) as queue:
            escalation = await service.repository.get_by_message_id(message_id)
            if escalation is None:
                return

            response = await _build_user_poll_response(
                request=request,
                escalation=escalation,
                message_id=message_id,
                settings=settings,
            )
            yield _format_sse_event("escalation", response)
            if _is_terminal_user_response(response):
                return

            while True:
                if await request.is_disconnected():
                    return
                try:
                    escalation = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                response = await _build_user_poll_response(
                    request=request,
                    escalation=escalation,
                    message_id=message_id,
                    settings=settings,
                )
                yield _format_sse_event("escalation", response)
                if _is_terminal_user_response(response):
                    return

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/escalations/{message_id}/rate",
    response_model=UserPollResponse,
)
async def rate_staff_answer(
    body: RateStaffAnswerRequest,
    request: Request,
    message_id: str = Path(
        ...,
        description="Message ID from the original question",
        pattern=MESSAGE_ID_PATH_PATTERN,
    ),
    service=Depends(get_escalation_service),
    settings=Depends(get_settings),
) -> UserPollResponse:
    """Rate a staff answer as helpful or unhelpful.

    Public endpoint - no authentication required. Idempotent: re-rating overwrites.

    Returns:
        Updated UserPollResponse on success.

    Raises:
        HTTPException: 404 if message_id not found,
                       400 if escalation has no staff_answer yet.
    """
    try:
        escalation = await service.repository.get_by_message_id(message_id)

        if not escalation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escalation not found",
            )

        trusted = False
        rating_token_jti = None
        if body.rate_token:
            payload = verify_rating_token(
                token=body.rate_token,
                message_id=message_id,
                rater_id=_derive_rater_id(request),
                signing_key=_get_rating_signing_key(settings),
            )
            if payload is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired rating token",
                )
            trusted = True
            rating_token_jti = payload.jti

        if trusted and rating_token_jti:
            if not await service.repository.consume_rating_token_jti(
                message_id=message_id,
                token_jti=rating_token_jti,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Rating token already used",
                )

        updated = await service.record_staff_answer_rating(
            escalation=escalation,
            rating=body.rating,
            rater_id=_derive_rater_id(request),
            trusted=trusted,
        )

        if not updated:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot rate: no staff answer yet",
            )
        localized_staff_answer = await _localize_staff_answer(
            request=request,
            escalation=escalation,
        )

        return UserPollResponse(
            status="resolved",
            staff_answer=localized_staff_answer,
            responded_at=escalation.responded_at,
            resolution=_derive_user_resolution(escalation),
            closed_at=escalation.closed_at,
            staff_answer_rating=body.rating,
            user_language=escalation.user_language,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to rate staff answer for {message_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit rating",
        ) from e
