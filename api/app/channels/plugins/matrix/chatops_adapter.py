"""Matrix transport adapter for shared ChatOps commands."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.channels.chatops import ChatOpsAuthorizer, ChatOpsDispatcher, ChatOpsParser
from app.metrics.operator_metrics import record_chatops_auth, record_chatops_parse


class MatrixChatOpsAdapter:
    """Handle Matrix `!case` commands in staff rooms."""

    def __init__(
        self,
        *,
        runtime: Any,
        enabled: bool,
        allowed_room_ids: set[str],
        parser: ChatOpsParser | None = None,
        dispatcher: ChatOpsDispatcher | None = None,
    ) -> None:
        self.runtime = runtime
        self.enabled = bool(enabled)
        self.allowed_room_ids = {
            str(room_id or "").strip()
            for room_id in allowed_room_ids
            if str(room_id or "").strip()
        }
        self.parser = parser or ChatOpsParser()
        self.dispatcher = dispatcher or ChatOpsDispatcher(
            escalation_service=runtime.resolve_optional("escalation_service"),
            arbitration_service=runtime.resolve_optional("arbitration_service"),
            audit_store=runtime.resolve_optional("chatops_audit_store"),
        )

    async def handle_event(
        self,
        *,
        room_id: str,
        event_id: str,
        sender: str,
        text: str,
    ) -> bool:
        parsed = self.parser.parse(
            text=text,
            actor_id=sender,
            source_message_id=event_id,
            room_id=room_id,
            channel_id="matrix",
        )
        if not parsed.handled:
            record_chatops_parse(channel="matrix", result="ignored")
            return False

        if parsed.command is None:
            record_chatops_parse(channel="matrix", result="invalid")
            audit_store = self.runtime.resolve_optional("chatops_audit_store")
            if audit_store is not None:
                audit_store.add_entry(
                    channel_id="matrix",
                    room_id=room_id,
                    actor_id=sender,
                    command_name="invalid",
                    case_id=None,
                    source_message_id=event_id,
                    ok=False,
                    idempotent=False,
                    metadata={"result": "invalid_command"},
                    created_at=datetime.now(timezone.utc),
                )
            await self._send_notice(
                room_id=room_id,
                root_event_id=event_id,
                body=parsed.error_message or "Invalid command.",
            )
            return True
        record_chatops_parse(channel="matrix", result="parsed")

        authorizer = ChatOpsAuthorizer(
            enabled=self.enabled,
            allowed_room_ids=self.allowed_room_ids,
            staff_resolver=self.runtime.resolve_optional("staff_resolver"),
            surface_label="Matrix ChatOps",
            allowed_scope_label="configured Matrix staff room",
        )
        auth_result = authorizer.authorize(parsed.command)
        if auth_result is not None:
            record_chatops_auth(channel="matrix", result="rejected")
            audit_store = self.runtime.resolve_optional("chatops_audit_store")
            if audit_store is not None:
                audit_store.add_entry(
                    channel_id="matrix",
                    room_id=room_id,
                    actor_id=sender,
                    command_name=parsed.command.name.value,
                    case_id=parsed.command.case_id,
                    source_message_id=event_id,
                    ok=False,
                    idempotent=False,
                    metadata={"result": "auth_rejected"},
                    created_at=datetime.now(timezone.utc),
                )
            await self._send_notice(
                room_id=room_id,
                root_event_id=event_id,
                body=auth_result.message,
            )
            return True
        record_chatops_auth(channel="matrix", result="authorized")

        result = await self.dispatcher.dispatch(parsed.command)
        await self._send_notice(
            room_id=room_id,
            root_event_id=event_id,
            body=result.message,
        )
        return True

    async def _send_notice(
        self, *, room_id: str, root_event_id: str, body: str
    ) -> None:
        client = self.runtime.resolve_optional("matrix_client")
        if client is None:
            return
        settings = getattr(self.runtime, "settings", None)
        ignore_unverified_devices = bool(
            getattr(settings, "MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES", True)
        )
        await client.room_send(
            room_id=str(room_id or "").strip(),
            message_type="m.room.message",
            content={
                "msgtype": "m.notice",
                "body": str(body or "").strip(),
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": str(root_event_id or "").strip(),
                    "is_falling_back": True,
                    "m.in_reply_to": {"event_id": str(root_event_id or "").strip()},
                },
            },
            ignore_unverified_devices=ignore_unverified_devices,
        )
