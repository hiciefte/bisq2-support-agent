"""Authorization helpers for ChatOps commands."""

from __future__ import annotations

from app.channels.chatops.models import ChatOpsCommand, ChatOpsResult


class ChatOpsAuthorizer:
    """Authorize ChatOps commands by room and trusted actor identity."""

    def __init__(self, *, enabled: bool, allowed_room_ids: set[str], staff_resolver):
        self.enabled = bool(enabled)
        self.allowed_room_ids = {
            str(room_id or "").strip()
            for room_id in allowed_room_ids
            if str(room_id or "").strip()
        }
        self.staff_resolver = staff_resolver

    def authorize(self, command: ChatOpsCommand) -> ChatOpsResult | None:
        if not self.enabled:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message="Matrix ChatOps is disabled.",
                command_name=command.name.value,
                case_id=command.case_id,
            )
        if command.room_id not in self.allowed_room_ids:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message="This command is only allowed in the configured Matrix staff room.",
                command_name=command.name.value,
                case_id=command.case_id,
            )
        if self.staff_resolver is None or not self.staff_resolver.is_staff(
            command.actor_id
        ):
            return ChatOpsResult(
                handled=True,
                ok=False,
                message="You are not authorized to use support ChatOps commands.",
                command_name=command.name.value,
                case_id=command.case_id,
            )
        return None
