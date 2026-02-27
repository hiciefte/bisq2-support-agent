"""Shared dispatch logic for channel AI responses.

Handles auto-send vs review-queue escalation in a channel-agnostic way.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.escalation import EscalationCreate

logger = logging.getLogger(__name__)

_GENERIC_ESCALATION_MSG = (
    "Your question has been forwarded to our support team. "
    "A staff member will review and respond shortly. "
    "(Reference: #{escalation_id})"
)

_DIRECT_DELIVERY_ACTIONS = frozenset({"auto_send", "needs_clarification"})
_REVIEW_QUEUE_ACTIONS = frozenset({"queue_medium", "needs_human"})


def format_escalation_notice(
    *,
    channel_id: str,
    username: str,
    escalation_id: int,
    support_handle: str = "support",
    channel: Any | None = None,
    channel_registry: Any | None = None,
) -> str:
    """Render channel-specific queued-review notice with generic fallback."""
    formatter = getattr(channel, "format_escalation_message", None) if channel else None
    if callable(formatter):
        try:
            rendered = formatter(
                username=username,
                escalation_id=escalation_id,
                support_handle=support_handle,
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
                rendered = registry_formatter(
                    username=username,
                    escalation_id=escalation_id,
                    support_handle=support_handle,
                )
                if isinstance(rendered, str) and rendered.strip():
                    return rendered
            except Exception:
                logger.debug(
                    "Adapter escalation formatter failed for channel=%s",
                    channel_id,
                    exc_info=True,
                )

    return _GENERIC_ESCALATION_MSG.format(escalation_id=escalation_id)


class ChannelResponseDispatcher:
    """Dispatch channel responses with shared auto-send/escalation semantics."""

    def __init__(
        self,
        channel: Any,
        channel_id: str,
        escalation_service: Any | None = None,
    ) -> None:
        self.channel = channel
        self.channel_id = channel_id
        self.escalation_service = escalation_service

    async def dispatch(self, incoming: Any, response: Any) -> bool:
        """Dispatch one response.

        Returns:
            True when a response was sent to the channel.
            False when not sent (e.g. queued for review, missing target, filtered).
        """
        if self.should_autosend_response(response):
            if self.channel is None:
                logger.debug(
                    "Skipping %s message %s because channel instance is unavailable",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                )
                return False
            target = self.channel.get_delivery_target(
                getattr(incoming, "channel_metadata", {})
            )
            if not target:
                logger.debug(
                    "Skipping %s message %s without delivery target",
                    self.channel_id,
                    getattr(incoming, "message_id", "<unknown>"),
                )
                return False
            return bool(await self.channel.send_message(target, response))

        if self.should_create_escalation(response):
            escalation = await self.create_escalation_for_review(incoming, response)
            if escalation is not None:
                await self._notify_review_queued(incoming, response, escalation)
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
        return False

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
        # Fail-open for unknown legacy actions to avoid silent user drops.
        if routing_action and routing_action not in _REVIEW_QUEUE_ACTIONS:
            logger.warning(
                "Unknown routing_action=%r for channel dispatcher; defaulting to autosend",
                routing_action,
            )
        return routing_action not in _REVIEW_QUEUE_ACTIONS

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
        return requires_human or routing_action in _REVIEW_QUEUE_ACTIONS

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
        self, incoming: Any, response: Any
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
            str(getattr(metadata, "routing_action", "") or "").strip().lower()
        )
        routing_action = routing_action or "needs_human"
        confidence = getattr(metadata, "confidence_score", None)
        if isinstance(confidence, (int, float)):
            confidence_score = max(0.0, min(1.0, float(confidence)))
        else:
            confidence_score = 0.0

        message_id = str(getattr(incoming, "message_id", "") or "").strip()
        question = str(getattr(incoming, "question", "") or "").strip()
        if not question:
            question = str(getattr(response, "original_question", "") or "").strip()
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
        routing_reason = getattr(metadata, "routing_reason", None)
        ai_draft_answer = str(getattr(response, "answer", "") or "").strip()
        if not ai_draft_answer:
            ai_draft_answer = "Escalated for staff review."

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
                    question=question,
                    ai_draft_answer=ai_draft_answer,
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

    async def _notify_review_queued(
        self,
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
        notice_text = self._format_escalation_notice(
            username=username,
            escalation_id=escalation_id,
            support_handle="support",
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
    ) -> str:
        return format_escalation_notice(
            channel_id=self.channel_id,
            username=username,
            escalation_id=escalation_id,
            support_handle=support_handle,
            channel=self.channel,
            channel_registry=None,
        )
