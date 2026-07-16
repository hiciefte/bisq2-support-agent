"""Shared dispatch logic for channel AI responses.

Handles auto-send vs review-queue escalation in a channel-agnostic way.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Mapping
from copy import deepcopy
from enum import Enum
from typing import Any

from app.channels.constants import REVIEW_QUEUE_ACTIONS
from app.channels.delivery_planner import DeliveryMode, DeliveryPlanner
from app.channels.escalation_localization import render_escalation_notice
from app.channels.policy import (
    get_escalation_notification_channel,
    get_escalation_user_notice_mode,
    get_escalation_user_notice_template,
    is_public_escalation_notice_enabled,
)
from app.channels.streaming import deliver_buffered_stream, deliver_native_stream
from app.models.escalation import EscalationCreate
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.services.channel_launch_control_service import LAUNCH_CONTROLLED_CHANNELS

logger = logging.getLogger(__name__)

_DIRECT_DELIVERY_ACTIONS = frozenset({"auto_send", "needs_clarification"})


class DispatchOutcome(str, Enum):
    """Terminal outcome of one channel response dispatch attempt."""

    SENT = "sent"
    QUEUED = "queued"
    FAILED = "failed"

    @classmethod
    def coerce(cls, value: Any) -> "DispatchOutcome":
        """Normalize legacy bool callbacks while preserving typed outcomes."""
        if isinstance(value, cls):
            return value
        return cls.SENT if value is True else cls.FAILED


def _formatter_accepts_kwarg(formatter: Any, name: str) -> bool:
    """Return True when formatter can accept the named keyword argument."""
    try:
        signature = inspect.signature(formatter)
    except (TypeError, ValueError):
        return False

    params = signature.parameters
    if name in params:
        return True

    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in params.values()
    )


def _call_escalation_formatter(
    formatter: Any,
    *,
    username: str,
    escalation_id: int,
    support_handle: str,
    language_code: str | None,
) -> Any:
    """Invoke channel formatter with supported kwargs only."""
    kwargs: dict[str, Any] = {
        "username": username,
        "escalation_id": escalation_id,
        "support_handle": support_handle,
    }
    if language_code is not None and _formatter_accepts_kwarg(
        formatter, "language_code"
    ):
        kwargs["language_code"] = language_code
    return formatter(**kwargs)


def format_escalation_notice(
    *,
    channel_id: str,
    username: str,
    escalation_id: int,
    support_handle: str = "support",
    language_code: str | None = None,
    channel: Any | None = None,
    channel_registry: Any | None = None,
) -> str:
    """Render channel-specific queued-review notice with generic fallback."""
    formatter = getattr(channel, "format_escalation_message", None) if channel else None
    if callable(formatter):
        try:
            rendered = _call_escalation_formatter(
                formatter,
                username=username,
                escalation_id=escalation_id,
                support_handle=support_handle,
                language_code=language_code,
            )
            if isinstance(rendered, str) and rendered.strip():
                return rendered
        except Exception:
            logger.debug(
                "Channel escalation formatter failed for channel=%s",
                channel_id,
                exc_info=True,
            )

    if channel_registry is not None:
        try:
            adapter = channel_registry.get(channel_id)
        except Exception:
            logger.debug(
                "Failed to resolve adapter for channel=%s from registry",
                channel_id,
                exc_info=True,
            )
            adapter = None

        registry_formatter = (
            getattr(adapter, "format_escalation_message", None) if adapter else None
        )
        if callable(registry_formatter):
            try:
                rendered = _call_escalation_formatter(
                    registry_formatter,
                    username=username,
                    escalation_id=escalation_id,
                    support_handle=support_handle,
                    language_code=language_code,
                )
                if isinstance(rendered, str) and rendered.strip():
                    return rendered
            except Exception:
                logger.debug(
                    "Adapter escalation formatter failed for channel=%s",
                    channel_id,
                    exc_info=True,
                )

    return render_escalation_notice(
        channel_id=channel_id,
        escalation_id=escalation_id,
        support_handle=support_handle,
        language_code=language_code,
    )


def preserve_static_safety_warning(
    original_answer: str | None,
    replacement_answer: str,
) -> str:
    """Keep the required safety prefix when replacing a review-routed answer."""
    if not str(original_answer or "").startswith(SAFETY_REFLEX_WARNING):
        return replacement_answer

    replacement_without_warning = replacement_answer.replace(
        SAFETY_REFLEX_WARNING, ""
    ).strip()
    if not replacement_without_warning:
        return SAFETY_REFLEX_WARNING
    return f"{SAFETY_REFLEX_WARNING}\n\n{replacement_without_warning}"


class ChannelResponseDispatcher:
    """Dispatch channel responses with shared auto-send/escalation semantics."""

    def __init__(
        self,
        channel: Any,
        channel_id: str,
        escalation_service: Any | None = None,
        delivery_planner: DeliveryPlanner | None = None,
        launch_control_service: Any | None = None,
    ) -> None:
        self.channel = channel
        self.channel_id = channel_id
        self.escalation_service = escalation_service
        self.delivery_planner = delivery_planner or DeliveryPlanner()
        self.launch_control_service = launch_control_service

    async def dispatch(self, incoming: Any, response: Any) -> DispatchOutcome:
        """Dispatch one response.

        Returns:
            SENT when delivered, QUEUED when persisted for staff review, and
            FAILED when neither action completed.
        """
        should_autosend = self.should_autosend_response(response)
        review_only_reason: str | None = None
        if should_autosend:
            allowed, launch_reason = self._authorize_autonomous_delivery(incoming)
            if not allowed:
                return await self._queue_launch_review(
                    incoming,
                    response,
                    reason=launch_reason,
                )
        else:
            review_only_reason = self._secondary_delivery_block_reason()

        if should_autosend:
            if self.channel is None:
                logger.debug(
                    "Skipping %s message %s because channel instance is unavailable",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                )
                return DispatchOutcome.FAILED
            target = self.channel.get_delivery_target(
                getattr(incoming, "channel_metadata", {})
            )
            if not target:
                logger.debug(
                    "Skipping %s message %s without delivery target",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                )
                return DispatchOutcome.FAILED
            try:
                plan = self.delivery_planner.plan(
                    channel=self.channel,
                    response=response,
                )
                if plan.mode == DeliveryMode.STREAM_NATIVE:
                    try:
                        if await deliver_native_stream(self.channel, target, response):
                            return DispatchOutcome.SENT
                    except Exception:
                        logger.debug(
                            (
                                "Native stream failed for %s message_id=%s; "
                                "falling back to buffered stream"
                            ),
                            self.channel_id,
                            getattr(incoming, "message_id", "<unknown>"),
                            exc_info=True,
                        )
                    buffered = await deliver_buffered_stream(
                        self.channel, target, response
                    )
                    return DispatchOutcome.SENT if buffered else DispatchOutcome.FAILED
                if plan.mode == DeliveryMode.STREAM_BUFFERED:
                    buffered = await deliver_buffered_stream(
                        self.channel, target, response
                    )
                    return DispatchOutcome.SENT if buffered else DispatchOutcome.FAILED
                sent = bool(await self.channel.send_message(target, response))
                return DispatchOutcome.SENT if sent else DispatchOutcome.FAILED
            except Exception:
                logger.exception(
                    "Failed sending %s message_id=%s",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                )
                return DispatchOutcome.FAILED

        if self.should_create_escalation(response):
            escalation = await self.create_escalation_for_review(incoming, response)
            if escalation is None:
                return DispatchOutcome.FAILED
            if review_only_reason is None:
                await self._notify_review_queued(incoming, response, escalation)
            else:
                logger.warning(
                    "Suppressed %s review notification message_id=%s launch_control=%s",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                    review_only_reason,
                )
            logger.debug(
                "Queued %s message_id=%s for support review (routing_action=%s)",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
                str(
                    getattr(getattr(response, "metadata", None), "routing_action", "")
                    or ""
                )
                .strip()
                .lower()
                or "<empty>",
            )
            return DispatchOutcome.QUEUED
        return DispatchOutcome.FAILED

    @staticmethod
    def should_autosend_response(response: Any) -> bool:
        metadata = getattr(response, "metadata", None)
        routing_action = (
            str(getattr(metadata, "routing_action", "") or "").strip().lower()
        )
        requires_human_raw = getattr(response, "requires_human", False)
        requires_human = (
            requires_human_raw if isinstance(requires_human_raw, bool) else False
        )
        if requires_human:
            return False
        if routing_action in _DIRECT_DELIVERY_ACTIONS:
            return True
        if not routing_action:
            logger.error(
                "Missing routing_action for channel dispatcher; routing to review queue"
            )
        elif routing_action not in REVIEW_QUEUE_ACTIONS:
            logger.error(
                "Unknown routing_action=%r for channel dispatcher; routing to review queue",
                routing_action,
            )
        return False

    @staticmethod
    def should_create_escalation(response: Any) -> bool:
        metadata = getattr(response, "metadata", None)
        routing_action = (
            str(getattr(metadata, "routing_action", "") or "").strip().lower()
        )
        requires_human_raw = getattr(response, "requires_human", False)
        requires_human = (
            requires_human_raw if isinstance(requires_human_raw, bool) else False
        )
        return requires_human or routing_action not in _DIRECT_DELIVERY_ACTIONS

    def _resolve_escalation_service(self) -> Any | None:
        if self.escalation_service is not None:
            return self.escalation_service

        runtime = getattr(self.channel, "runtime", None)
        resolve_optional = (
            getattr(runtime, "resolve_optional", None) if runtime else None
        )
        if callable(resolve_optional):
            try:
                return resolve_optional("escalation_service")
            except Exception:
                logger.exception(
                    "Failed to resolve escalation_service from runtime for channel=%s",
                    self.channel_id,
                )
        return None

    async def create_escalation_for_review(
        self,
        incoming: Any,
        response: Any,
        *,
        routing_action_override: str | None = None,
        routing_reason_override: str | None = None,
    ) -> Any | None:
        escalation_service = self._resolve_escalation_service()
        if escalation_service is None:
            logger.debug(
                "Skipping escalation creation for %s message_id=%s because escalation_service is unavailable",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return None

        metadata = getattr(response, "metadata", None)
        routing_action = (
            str(
                routing_action_override
                if routing_action_override is not None
                else getattr(metadata, "routing_action", "") or ""
            )
            .strip()
            .lower()
        )
        routing_action = routing_action or "needs_human"
        confidence = getattr(metadata, "confidence_score", None)
        if isinstance(confidence, (int, float)):
            confidence_score = max(0.0, min(1.0, float(confidence)))
        else:
            confidence_score = 0.0

        message_id = str(getattr(incoming, "message_id", "") or "").strip()
        localized_question = str(getattr(incoming, "question", "") or "").strip()
        raw_canonical_question = getattr(metadata, "canonical_question_en", None)
        canonical_question = (
            raw_canonical_question.strip()
            if isinstance(raw_canonical_question, str)
            else ""
        )
        question = (
            canonical_question
            or str(getattr(response, "original_question", "") or "").strip()
            or localized_question
        )
        if not message_id or not question:
            logger.warning(
                "Skipping %s escalation creation due to missing message_id/question (message_id=%s)",
                self.channel_id,
                message_id or "<empty>",
            )
            return None

        user = getattr(incoming, "user", None)
        user_id = str(getattr(user, "user_id", "") or "").strip() or "unknown"
        username = str(getattr(user, "channel_user_id", "") or "").strip() or user_id
        routing_reason = (
            routing_reason_override
            if routing_reason_override is not None
            else getattr(metadata, "routing_reason", None)
        )
        localized_answer = str(getattr(response, "answer", "") or "").strip()
        raw_canonical_answer = getattr(metadata, "canonical_answer_en", None)
        canonical_answer = (
            raw_canonical_answer.strip()
            if isinstance(raw_canonical_answer, str)
            else ""
        )
        ai_draft_answer = canonical_answer or localized_answer
        if not ai_draft_answer:
            ai_draft_answer = "Escalated for staff review."
        raw_language_code = getattr(metadata, "original_language", None)
        language_code = (
            raw_language_code.strip().lower()
            if isinstance(raw_language_code, str)
            else ""
        )
        if len(language_code) > 8:
            language_code = ""
        translation_applied = bool(getattr(metadata, "translation_applied", False))

        source_docs = []
        for source in list(getattr(response, "sources", []) or []):
            if hasattr(source, "model_dump"):
                source_docs.append(source.model_dump())
            elif isinstance(source, dict):
                source_docs.append(source)

        try:
            escalation = await escalation_service.create_escalation(
                EscalationCreate(
                    message_id=message_id,
                    channel=self.channel_id,
                    user_id=user_id,
                    username=username,
                    channel_metadata=getattr(incoming, "channel_metadata", None)
                    or None,
                    question_original=localized_question or None,
                    question=question,
                    ai_draft_answer_original=localized_answer or None,
                    ai_draft_answer=ai_draft_answer,
                    user_language=language_code or None,
                    translation_applied=translation_applied,
                    confidence_score=confidence_score,
                    routing_action=routing_action,
                    routing_reason=routing_reason,
                    sources=source_docs or None,
                )
            )
            logger.info(
                "Created escalation for channel=%s message_id=%s (routing_action=%s)",
                self.channel_id,
                message_id,
                routing_action,
            )
            return escalation
        except Exception:
            logger.exception(
                "Failed to create escalation for channel=%s message_id=%s",
                self.channel_id,
                message_id,
            )
            return None

    async def _queue_launch_review(
        self,
        incoming: Any,
        response: Any,
        *,
        reason: str,
    ) -> DispatchOutcome:
        metadata = getattr(response, "metadata", None)
        would_have_sent = (
            str(getattr(metadata, "routing_action", "") or "").strip().lower()
            or "unknown"
        )
        routing_reason = f"launch_control={reason}; would_have_sent={would_have_sent}"
        escalation = await self.create_escalation_for_review(
            incoming,
            response,
            routing_action_override=would_have_sent,
            routing_reason_override=routing_reason,
        )
        if escalation is None:
            return DispatchOutcome.FAILED
        logger.warning(
            "Queued autonomous %s response message_id=%s launch_control=%s would_have_sent=%s",
            self.channel_id,
            getattr(incoming, "message_id", "<unknown>"),
            reason,
            would_have_sent,
        )
        return DispatchOutcome.QUEUED

    def _authorize_autonomous_delivery(self, incoming: Any) -> tuple[bool, str]:
        if not self._launch_control_applies():
            return True, "launch_control_not_applicable"
        service = self._resolve_launch_control_service()
        if service is None:
            reason = (
                "launch_control_unavailable"
                if self.launch_control_service is None
                else "launch_control_invalid_service"
            )
            logger.error(
                "Autonomous delivery blocked because launch control is %s channel=%s",
                reason,
                self.channel_id,
            )
            return False, reason
        try:
            decision = service.authorize_autonomous_delivery(
                self.channel_id,
                str(getattr(incoming, "message_id", "") or ""),
            )
            allowed = getattr(decision, "allowed", None)
            reason = getattr(decision, "reason", None)
            if not isinstance(allowed, bool) or not isinstance(reason, str):
                logger.error(
                    "Autonomous delivery blocked because launch control returned "
                    "an invalid result channel=%s",
                    self.channel_id,
                )
                return False, "launch_control_invalid_result"
            normalized_reason = reason.strip()
            if not normalized_reason:
                logger.error(
                    "Autonomous delivery blocked because launch control returned "
                    "an empty reason channel=%s",
                    self.channel_id,
                )
                return False, "launch_control_invalid_result"
            return allowed, normalized_reason
        except Exception:
            logger.exception(
                "Autonomous delivery blocked because launch control failed channel=%s",
                self.channel_id,
            )
            return False, "launch_control_error"

    def _secondary_delivery_block_reason(self) -> str | None:
        if not self._launch_control_applies():
            return None
        service = self._resolve_launch_control_service()
        if service is None:
            reason = (
                "launch_control_unavailable"
                if self.launch_control_service is None
                else "launch_control_invalid_service"
            )
            logger.error(
                "Automatic review notification blocked because launch control is "
                "%s channel=%s",
                reason,
                self.channel_id,
            )
            return reason
        guard = getattr(service, "secondary_delivery_block_reason", None)
        if not callable(guard):
            logger.error(
                "Secondary automatic delivery blocked because launch control is "
                "malformed channel=%s",
                self.channel_id,
            )
            return "launch_control_invalid_service"
        try:
            reason = guard(self.channel_id)
        except Exception:
            logger.exception(
                "Review notification blocked because launch control failed channel=%s",
                self.channel_id,
            )
            return "launch_control_error"
        if reason is None:
            return None
        if not isinstance(reason, str) or not reason.strip():
            logger.error(
                "Automatic review notification blocked because launch control "
                "returned an invalid guard result channel=%s",
                self.channel_id,
            )
            return "launch_control_invalid_result"
        return reason.strip()

    def _resolve_launch_control_service(self) -> Any | None:
        candidate = self.launch_control_service
        if candidate is None:
            return None
        if not callable(getattr(candidate, "authorize_autonomous_delivery", None)):
            return None
        if not callable(getattr(candidate, "review_only_reason", None)):
            return None
        return candidate

    def _launch_control_applies(self) -> bool:
        return str(self.channel_id or "").strip().lower() in LAUNCH_CONTROLLED_CHANNELS

    async def _notify_review_queued(
        self,
        incoming: Any,
        response: Any,
        escalation: Any,
    ) -> bool:
        if self.channel is None:
            return False

        notification_channel = self._notification_channel_mode()
        sent_public = False
        if notification_channel == "public_room" and self._is_public_notice_enabled():
            sent_public = await self._send_public_escalation_notice(
                incoming=incoming,
                response=response,
                escalation=escalation,
            )
            if notification_channel == "public_room":
                return sent_public

        # For non-public routing, user-room notice behavior is controlled by policy.
        user_notice_sent = await self._send_user_escalation_notice(incoming, response)
        staff_notice_sent = False
        if notification_channel == "staff_room":
            staff_notice_sent = await self._send_staff_room_escalation_notice(
                incoming=incoming,
                response=response,
                escalation=escalation,
            )
        return sent_public or user_notice_sent or staff_notice_sent

    async def notify_review_queued(
        self,
        incoming: Any,
        response: Any,
        escalation: Any,
    ) -> bool:
        """Public wrapper for sending escalation notices after queueing."""
        reason = self._secondary_delivery_block_reason()
        if reason is not None:
            logger.warning(
                "Suppressed %s review notification message_id=%s launch_control=%s",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
                reason,
            )
            return False
        return await self._notify_review_queued(incoming, response, escalation)

    async def _send_public_escalation_notice(
        self,
        *,
        incoming: Any,
        response: Any,
        escalation: Any,
    ) -> bool:
        if self.channel is None:
            return False

        target = self.channel.get_delivery_target(
            getattr(incoming, "channel_metadata", {})
        )
        if not target:
            logger.debug(
                "Skipping queued-review notification for %s message %s without delivery target",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return False
        notice = self._build_escalation_notice_response(incoming, response, escalation)
        try:
            sent = bool(await self.channel.send_message(target, notice))
            if sent:
                logger.info(
                    "Sent queued-review notification for channel=%s message_id=%s escalation_id=%s",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                    getattr(escalation, "id", "<unknown>"),
                )
            return sent
        except Exception:
            logger.exception(
                "Failed to send queued-review notification for channel=%s message_id=%s",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return False

    async def _send_staff_room_escalation_notice(
        self,
        *,
        incoming: Any,
        response: Any,
        escalation: Any,
    ) -> bool:
        if self.channel is None:
            return False
        target = self._resolve_staff_notification_target(incoming)
        if not target:
            return False
        notice = self._build_staff_room_escalation_notice_response(
            incoming=incoming,
            response=response,
            escalation=escalation,
        )
        try:
            sent = bool(await self.channel.send_message(target, notice))
            if sent:
                logger.info(
                    "Sent staff-room escalation notice for channel=%s message_id=%s escalation_id=%s target=%s",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                    getattr(escalation, "id", "<unknown>"),
                    target,
                )
            return sent
        except Exception:
            logger.exception(
                "Failed to send staff-room escalation notice for channel=%s message_id=%s",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return False

    async def _send_user_escalation_notice(self, incoming: Any, response: Any) -> bool:
        if self.channel is None:
            return False
        mode = self._user_notice_mode()
        if mode == "none":
            return False
        target = self.channel.get_delivery_target(
            getattr(incoming, "channel_metadata", {})
        )
        if not target:
            return False
        notice = self._build_user_escalation_notice_response(incoming, response)
        try:
            return bool(await self.channel.send_message(target, notice))
        except Exception:
            logger.exception(
                "Failed to send user escalation notice for channel=%s message_id=%s",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return False

    def _build_escalation_notice_response(
        self,
        incoming: Any,
        response: Any,
        escalation: Any,
    ) -> Any:
        escalation_id = getattr(escalation, "id", None)
        if not isinstance(escalation_id, int):
            escalation_id = 0
        username = (
            str(
                getattr(getattr(incoming, "user", None), "channel_user_id", "") or ""
            ).strip()
            or str(
                getattr(getattr(incoming, "user", None), "user_id", "") or ""
            ).strip()
            or "user"
        )
        metadata = getattr(response, "metadata", None)
        raw_language = getattr(metadata, "original_language", None)
        original_language = (
            raw_language.strip().lower() if isinstance(raw_language, str) else None
        )
        if isinstance(original_language, str) and len(original_language) > 8:
            original_language = None
        notice_text = self._format_escalation_notice(
            username=username,
            escalation_id=escalation_id,
            support_handle="support",
            language_code=original_language,
        )
        notice_text = preserve_static_safety_warning(
            getattr(response, "answer", None),
            notice_text,
        )

        notice = (
            response.model_copy(deep=True)
            if hasattr(response, "model_copy")
            else response
        )
        try:
            setattr(notice, "answer", notice_text)
            setattr(notice, "requires_human", True)
            if hasattr(notice, "sources"):
                setattr(notice, "sources", [])
            metadata = getattr(notice, "metadata", None)
            if metadata is not None:
                if hasattr(metadata, "confidence_score"):
                    setattr(metadata, "confidence_score", None)
                if hasattr(metadata, "routing_action"):
                    # Reactions to queue-notice messages should not feed learning.
                    setattr(metadata, "routing_action", "escalation_notice")
        except Exception:
            logger.debug(
                "Failed to shape queued-review notification payload", exc_info=True
            )
        return notice

    def _format_escalation_notice(
        self,
        username: str,
        escalation_id: int,
        support_handle: str,
        language_code: str | None = None,
    ) -> str:
        return format_escalation_notice(
            channel_id=self.channel_id,
            username=username,
            escalation_id=escalation_id,
            support_handle=support_handle,
            language_code=language_code,
            channel=self.channel,
            channel_registry=None,
        )

    def _resolve_policy_service(self) -> Any | None:
        runtime = getattr(self.channel, "runtime", None)
        resolve_optional = (
            getattr(runtime, "resolve_optional", None) if runtime is not None else None
        )
        if not callable(resolve_optional):
            return None
        try:
            return resolve_optional("channel_autoresponse_policy_service")
        except Exception:
            logger.debug(
                "Failed resolving channel_autoresponse_policy_service for channel=%s",
                self.channel_id,
                exc_info=True,
            )
            return None

    def _is_public_notice_enabled(self) -> bool:
        return is_public_escalation_notice_enabled(
            self._resolve_policy_service(),
            self.channel_id,
        )

    def _notification_channel_mode(self) -> str:
        return get_escalation_notification_channel(
            self._resolve_policy_service(),
            self.channel_id,
        )

    def _user_notice_mode(self) -> str:
        return get_escalation_user_notice_mode(
            self._resolve_policy_service(),
            self.channel_id,
        )

    def _resolve_staff_notification_target(self, incoming: Any) -> str:
        if self.channel is None:
            return ""

        metadata = getattr(incoming, "channel_metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}

        static_target = None
        try:
            static_target = inspect.getattr_static(
                self.channel, "get_staff_notification_target"
            )
        except AttributeError:
            static_target = None

        get_target = getattr(self.channel, "get_staff_notification_target", None)
        if static_target is not None and callable(get_target):
            try:
                target = str(get_target(metadata) or "").strip()
                if target:
                    return target
            except Exception:
                logger.debug(
                    "Channel-specific staff notification target resolution failed for channel=%s",
                    self.channel_id,
                    exc_info=True,
                )

        target = str(metadata.get("staff_room_id", "") or "").strip()
        return target

    def _build_user_escalation_notice_response(
        self, incoming: Any, response: Any
    ) -> Any:
        notice = (
            response.model_copy(deep=True)
            if hasattr(response, "model_copy")
            else deepcopy(response)
        )
        template = get_escalation_user_notice_template(
            self._resolve_policy_service(),
            self.channel_id,
        )
        template = preserve_static_safety_warning(
            getattr(response, "answer", None),
            template,
        )
        try:
            setattr(notice, "answer", template)
            setattr(notice, "requires_human", True)
            if hasattr(notice, "sources"):
                setattr(notice, "sources", [])
            metadata = getattr(notice, "metadata", None)
            if metadata is not None and hasattr(metadata, "routing_action"):
                setattr(metadata, "routing_action", "escalation_notice")
        except Exception:
            logger.debug("Failed shaping user escalation notice payload", exc_info=True)
        return notice

    def _build_staff_room_escalation_notice_response(
        self,
        *,
        incoming: Any,
        response: Any,
        escalation: Any,
    ) -> Any:
        notice = (
            response.model_copy(deep=True)
            if hasattr(response, "model_copy")
            else deepcopy(response)
        )
        user = getattr(incoming, "user", None)
        username = (
            str(getattr(user, "channel_user_id", "") or "").strip()
            or str(getattr(user, "user_id", "") or "").strip()
            or "unknown"
        )
        escalation_id = getattr(escalation, "id", None)
        question = self._truncate_notice_text(
            str(getattr(incoming, "question", "") or "").strip(),
            limit=220,
        )
        ai_draft_answer = self._truncate_notice_text(
            str(getattr(response, "answer", "") or "").strip(),
            limit=3000,
        )
        response_metadata = getattr(response, "metadata", None)
        routing_reason = str(
            getattr(response_metadata, "routing_reason", "") or ""
        ).strip()
        confidence_value = getattr(response_metadata, "confidence_score", None)
        confidence_text = ""
        try:
            if confidence_value is not None:
                confidence_text = f"{int(round(float(confidence_value) * 100))}%"
        except Exception:
            confidence_text = ""

        source_lines = self._build_staff_notice_source_lines(
            getattr(response, "sources", None),
            limit=3,
        )
        admin_link = (
            f"/admin/escalations?search={escalation_id}"
            if isinstance(escalation_id, int) and escalation_id > 0
            else "/admin/escalations"
        )
        source_block = (
            "\n".join(source_lines) if source_lines else "- No source links available."
        )
        routing_line = routing_reason or "n/a"
        confidence_line = confidence_text or "n/a"
        draft_block = ai_draft_answer or "_No AI draft answer available._"
        staff_enriched_answer = self._truncate_notice_text(
            str(getattr(response_metadata, "staff_enriched_answer", "") or "").strip(),
            limit=4000,
        )
        if draft_block.startswith(SAFETY_REFLEX_WARNING):
            staff_enriched_answer = staff_enriched_answer.replace(
                SAFETY_REFLEX_WARNING, ""
            ).strip()
        internal_enrichment_block = ""
        if staff_enriched_answer and staff_enriched_answer != draft_block:
            internal_enrichment_block = (
                "\n\n"
                "Codebase-enriched staff context (internal; not sent by reactions or `/send`):\n"
                f"{staff_enriched_answer}"
            )

        text = (
            f"Escalation #{escalation_id or '?'} for {self.channel_id}\n\n"
            f"User: {username}\n"
            f"Question: {question}\n\n"
            "Reply to user (copy-ready):\n"
            f"{draft_block}"
            f"{internal_enrichment_block}\n\n"
            "Sources to copy:\n"
            f"{source_block}\n\n"
            "Review context:\n"
            f"- Routing reason: {routing_line}\n"
            f"- Confidence: {confidence_line}\n"
            f"- Admin review: {admin_link}\n\n"
            "How to review in this room:\n"
            "- React `👍` to send only the copy-ready reply to the user.\n"
            "- React `👎` to dismiss with no reply.\n"
            "- Reply in thread with `/send` to send only the copy-ready reply unchanged.\n"
            "- Reply in thread with `/send <edited reply>` to send an edited reply.\n"
            "- Reply in thread with `/dismiss` to close without reply."
        )
        try:
            setattr(notice, "answer", text)
            if isinstance(escalation_id, int) and escalation_id > 0:
                setattr(notice, "message_id", f"staff-escalation-{escalation_id}")
            setattr(notice, "requires_human", True)
            if hasattr(notice, "sources"):
                setattr(notice, "sources", [])
            metadata = getattr(notice, "metadata", None)
            if metadata is not None and hasattr(metadata, "routing_action"):
                setattr(metadata, "routing_action", "staff_escalation_notice")
        except Exception:
            logger.debug(
                "Failed shaping staff-room escalation notice payload", exc_info=True
            )
        return notice

    @staticmethod
    def _truncate_notice_text(text: str, *, limit: int) -> str:
        value = str(text or "").strip()
        if limit <= 3 or len(value) <= limit:
            return value
        return f"{value[: limit - 3].rstrip()}..."

    @staticmethod
    def _build_staff_notice_source_lines(
        sources: Any,
        *,
        limit: int,
    ) -> list[str]:
        lines: list[str] = []
        if not isinstance(limit, int) or limit <= 0:
            return lines

        iterable = sources if isinstance(sources, list) else []
        for source in iterable[:limit]:
            if isinstance(source, Mapping):
                raw_title = source.get("title", "")
                raw_url = source.get("url", "")
            else:
                raw_title = getattr(source, "title", "")
                raw_url = getattr(source, "url", "")
            title = str(raw_title or "").strip() or "Source"
            url = str(raw_url or "").strip()
            if url:
                lines.append(f"- {title}: {url}")
            else:
                lines.append(f"- {title}")
        return lines
