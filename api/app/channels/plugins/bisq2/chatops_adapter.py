"""Bisq2 transport adapter for shared ChatOps commands."""

from __future__ import annotations

import logging
from typing import Any

from app.channels.chatops import ChatOpsAuthorizer, ChatOpsDispatcher, ChatOpsParser

logger = logging.getLogger(__name__)


class Bisq2ChatOpsAdapter:
    """Handle Bisq2 `!case` commands in configured staff channels."""

    def __init__(
        self,
        *,
        runtime: Any,
        enabled: bool,
        allowed_channel_ids: set[str],
        parser: ChatOpsParser | None = None,
        dispatcher: ChatOpsDispatcher | None = None,
    ) -> None:
        self.runtime = runtime
        self.enabled = bool(enabled)
        self.allowed_channel_ids = {
            str(channel_id or "").strip()
            for channel_id in allowed_channel_ids
            if str(channel_id or "").strip()
        }
        self.parser = parser or ChatOpsParser()
        self.dispatcher = dispatcher or ChatOpsDispatcher(
            escalation_service=runtime.resolve_optional("escalation_service"),
            arbitration_service=runtime.resolve_optional("arbitration_service"),
        )

    async def handle_message(self, payload: dict[str, Any]) -> bool:
        text = str(payload.get("message", "") or "").strip()
        channel_id = str(payload.get("channelId", "") or "").strip()
        conversation_id = str(payload.get("conversationId", channel_id) or "").strip()
        sender_profile_id = str(
            payload.get("senderUserProfileId", payload.get("authorId", "")) or ""
        ).strip()
        message_id = str(payload.get("messageId", "") or "").strip()

        parsed = self.parser.parse(
            text=text,
            actor_id=sender_profile_id,
            source_message_id=message_id,
            room_id=channel_id,
        )
        if not parsed.handled:
            return False

        if parsed.command is None:
            await self._send_notice(
                target=conversation_id or channel_id,
                body=parsed.error_message or "Invalid command.",
                citation=text or None,
            )
            return True

        authorizer = ChatOpsAuthorizer(
            enabled=self.enabled,
            allowed_room_ids=self.allowed_channel_ids,
            staff_resolver=self.runtime.resolve_optional("staff_resolver"),
            surface_label="Bisq2 ChatOps",
            allowed_scope_label="configured Bisq2 staff channel",
        )
        auth_result = authorizer.authorize(parsed.command)
        if auth_result is not None:
            await self._send_notice(
                target=conversation_id or channel_id,
                body=auth_result.message,
                citation=text or None,
            )
            return True

        try:
            result = await self.dispatcher.dispatch(parsed.command)
        except Exception:
            logger.exception(
                "Bisq2 ChatOps dispatch failed for channel=%s actor=%s",
                channel_id,
                sender_profile_id,
            )
            await self._send_notice(
                target=conversation_id or channel_id,
                body="Command failed to execute.",
                citation=text or None,
            )
            return True
        await self._send_notice(
            target=conversation_id or channel_id,
            body=result.message,
            citation=text or None,
        )
        return True

    async def _send_notice(
        self,
        *,
        target: str,
        body: str,
        citation: str | None = None,
    ) -> None:
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if bisq_api is None:
            return
        send_support_message = getattr(bisq_api, "send_support_message", None)
        if not callable(send_support_message):
            return
        await send_support_message(
            channel_id=str(target or "").strip(),
            text=str(body or "").strip(),
            citation=str(citation or "").strip() or None,
        )
