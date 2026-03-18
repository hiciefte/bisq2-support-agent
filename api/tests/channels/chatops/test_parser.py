"""Tests for shared ChatOps command parsing."""

from app.channels.chatops import ChatOpsCommandName, ChatOpsParser


def test_parse_returns_unhandled_for_non_chatops_text() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="plain message",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is False
    assert result.command is None
    assert result.error_message is None


def test_parse_list_command_with_scope_and_options() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!case list mine channel=matrix limit=5",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is True
    assert result.error_message is None
    assert result.command is not None
    assert result.command.name is ChatOpsCommandName.LIST
    assert result.command.case_id is None
    assert result.command.options == {
        "scope": "mine",
        "channel": "matrix",
        "limit": "5",
    }


def test_parse_edit_send_command_extracts_message() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!case edit-send 241 :: Updated answer",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is True
    assert result.command is not None
    assert result.command.name is ChatOpsCommandName.EDIT_SEND
    assert result.command.case_id == 241
    assert result.command.message == "Updated answer"


def test_parse_marks_future_command_as_not_implemented_yet() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!case snooze 241 30m",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is True
    assert result.command is not None
    assert result.command.name is ChatOpsCommandName.SNOOZE
    assert result.command.options["duration"] == "30m"
    assert result.command.options["implemented"] == "false"


def test_parse_returns_helpful_error_for_unknown_command() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!case sent 241",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is True
    assert result.command is None
    assert result.error_message is not None
    assert "Unknown command `sent`." in result.error_message
    assert "Did you mean `!case send`?" in result.error_message


def test_parse_requires_case_id_for_send() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!case send",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is True
    assert result.command is None
    assert result.error_message is not None
    assert "`!case send` requires a case id." in result.error_message


def test_parse_rejects_prefix_without_boundary() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!casefoo 241",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is False
    assert result.command is None


def test_parse_rejects_zero_case_id() -> None:
    parser = ChatOpsParser()

    result = parser.parse(
        text="!case send 0",
        actor_id="@staff:server",
        source_message_id="$event",
        room_id="!staff:server",
    )

    assert result.handled is True
    assert result.command is None
    assert result.error_message is not None
    assert "positive integer" in result.error_message
