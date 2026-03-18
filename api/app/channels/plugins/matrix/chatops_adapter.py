"""Matrix transport adapter for shared ChatOps commands."""

from __future__ import annotations

from typing import Any

from app.channels.chatops import ChatOpsAuthorizer, ChatOpsDispatcher, ChatOpsParser


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
        )
        if not parsed.handled:
            return False

        if parsed.command is None:
            await self._send_notice(
                room_id=room_id,
                root_event_id=event_id,
                body=parsed.error_message or "Invalid command.",
            )
            return True

        authorizer = ChatOpsAuthorizer(
            enabled=self.enabled,
            allowed_room_ids=self.allowed_room_ids,
            staff_resolver=self.runtime.resolve_optional("staff_resolver"),
            surface_label="Matrix ChatOps",
            allowed_scope_label="configured Matrix staff room",
        )
        auth_result = authorizer.authorize(parsed.command)
        if auth_result is not None:
            await self._send_notice(
                room_id=room_id,
                root_event_id=event_id,
                body=auth_result.message,
            )
            return True

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
