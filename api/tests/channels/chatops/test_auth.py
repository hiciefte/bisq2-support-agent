"""Tests for ChatOps authorization."""

from app.channels.chatops import ChatOpsAuthorizer, ChatOpsCommand, ChatOpsCommandName
from app.channels.staff import StaffResolver


def _command(
    *,
    actor_id: str = "@staff:server",
    room_id: str = "!staff:server",
) -> ChatOpsCommand:
    return ChatOpsCommand(
        name=ChatOpsCommandName.HELP,
        actor_id=actor_id,
        source_message_id="$event",
        room_id=room_id,
        raw_text="!case help",
    )


def test_authorize_rejects_disabled_feature() -> None:
    authorizer = ChatOpsAuthorizer(
        enabled=False,
        allowed_room_ids={"!staff:server"},
        staff_resolver=StaffResolver(["@staff:server"]),
    )

    result = authorizer.authorize(_command())

    assert result is not None
    assert result.ok is False
    assert result.message == "ChatOps is disabled."


def test_authorize_rejects_wrong_room() -> None:
    authorizer = ChatOpsAuthorizer(
        enabled=True,
        allowed_room_ids={"!staff:server"},
        staff_resolver=StaffResolver(["@staff:server"]),
    )

    result = authorizer.authorize(_command(room_id="!public:server"))

    assert result is not None
    assert result.ok is False
    assert "configured staff channel" in result.message


def test_authorize_supports_transport_specific_labels() -> None:
    authorizer = ChatOpsAuthorizer(
        enabled=False,
        allowed_room_ids={"support.staff"},
        staff_resolver=StaffResolver(["staff-1"]),
        surface_label="Bisq2 ChatOps",
        allowed_scope_label="configured Bisq2 staff channel",
    )

    disabled = authorizer.authorize(
        _command(actor_id="staff-1", room_id="support.staff")
    )
    wrong_scope = ChatOpsAuthorizer(
        enabled=True,
        allowed_room_ids={"support.staff"},
        staff_resolver=StaffResolver(["staff-1"]),
        surface_label="Bisq2 ChatOps",
        allowed_scope_label="configured Bisq2 staff channel",
    ).authorize(_command(actor_id="staff-1", room_id="public"))

    assert disabled is not None
    assert disabled.message == "Bisq2 ChatOps is disabled."
    assert wrong_scope is not None
    assert wrong_scope.message.endswith("configured Bisq2 staff channel.")


def test_authorize_rejects_non_staff_sender() -> None:
    authorizer = ChatOpsAuthorizer(
        enabled=True,
        allowed_room_ids={"!staff:server"},
        staff_resolver=StaffResolver(["@trusted:server"]),
    )

    result = authorizer.authorize(_command(actor_id="@intruder:server"))

    assert result is not None
    assert result.ok is False
    assert result.message == "You are not authorized to use support ChatOps commands."


def test_authorize_allows_trusted_staff_in_allowed_room() -> None:
    authorizer = ChatOpsAuthorizer(
        enabled=True,
        allowed_room_ids={"!staff:server"},
        staff_resolver=StaffResolver(["@staff:server"]),
    )

    result = authorizer.authorize(_command())

    assert result is None
