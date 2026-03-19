"""Bisq2 transport adapter for shared ChatOps commands."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.channels.chatops import ChatOpsAuthorizer, ChatOpsDispatcher, ChatOpsParser
from app.metrics.operator_metrics import record_chatops_auth, record_chatops_parse

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
            audit_store=runtime.resolve_optional("chatops_audit_store"),
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
            channel_id="bisq2",
        )
        if not parsed.handled:
            record_chatops_parse(channel="bisq2", result="ignored")
            return False

        if parsed.command is None:
            record_chatops_parse(channel="bisq2", result="invalid")
            audit_store = self.runtime.resolve_optional("chatops_audit_store")
            if audit_store is not None:
                audit_store.add_entry(
                    channel_id="bisq2",
                    room_id=channel_id,
                    actor_id=sender_profile_id,
                    command_name="invalid",
                    case_id=None,
                    source_message_id=message_id,
                    ok=False,
                    idempotent=False,
                    metadata={"result": "invalid_command"},
                    created_at=datetime.now(timezone.utc),
                )
            await self._send_notice(
                target=conversation_id or channel_id,
                body=parsed.error_message or "Invalid command.",
                citation=text or None,
            )
            return True
        record_chatops_parse(channel="bisq2", result="parsed")

        authorizer = ChatOpsAuthorizer(
            enabled=self.enabled,
            allowed_room_ids=self.allowed_channel_ids,
            staff_resolver=self.runtime.resolve_optional("staff_resolver"),
            surface_label="Bisq2 ChatOps",
            allowed_scope_label="configured Bisq2 staff channel",
        )
        auth_result = authorizer.authorize(parsed.command)
        if auth_result is not None:
            record_chatops_auth(channel="bisq2", result="rejected")
            audit_store = self.runtime.resolve_optional("chatops_audit_store")
            if audit_store is not None:
                audit_store.add_entry(
                    channel_id="bisq2",
                    room_id=channel_id,
                    actor_id=sender_profile_id,
                    command_name=parsed.command.name.value,
                    case_id=parsed.command.case_id,
                    source_message_id=message_id,
                    ok=False,
                    idempotent=False,
                    metadata={"result": "auth_rejected"},
                    created_at=datetime.now(timezone.utc),
                )
            await self._send_notice(
                target=conversation_id or channel_id,
                body=auth_result.message,
                citation=text or None,
            )
            return True
        record_chatops_auth(channel="bisq2", result="authorized")

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
