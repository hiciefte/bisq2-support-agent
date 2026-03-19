"""Authorization helpers for ChatOps commands."""

from __future__ import annotations

from app.channels.chatops.models import ChatOpsCommand, ChatOpsResult


class ChatOpsAuthorizer:
    """Authorize ChatOps commands by room and trusted actor identity."""

    def __init__(
        self,
        *,
        enabled: bool,
        allowed_room_ids: set[str],
        staff_resolver,
        surface_label: str = "ChatOps",
        allowed_scope_label: str = "configured staff channel",
    ):
        self.enabled = bool(enabled)
        self.allowed_room_ids = {
            str(room_id or "").strip()
            for room_id in allowed_room_ids
            if str(room_id or "").strip()
        }
        self.staff_resolver = staff_resolver
        self.surface_label = str(surface_label or "ChatOps").strip() or "ChatOps"
        self.allowed_scope_label = (
            str(allowed_scope_label or "configured staff channel").strip()
            or "configured staff channel"
        )

    def authorize(self, command: ChatOpsCommand) -> ChatOpsResult | None:
        if not self.enabled:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message=f"{self.surface_label} is disabled.",
                command_name=command.name.value,
                case_id=command.case_id,
            )
        if command.room_id not in self.allowed_room_ids:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message=(
                    "This command is only allowed in the "
                    f"{self.allowed_scope_label}."
                ),
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
