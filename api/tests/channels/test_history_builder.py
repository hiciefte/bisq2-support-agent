"""Tests for shared channel chat-history builder."""

from app.channels.history_builder import ConversationMessage, build_channel_chat_history


def _msg(
    message_id: str,
    sender_id: str,
    text: str,
    ts: int,
    *,
    conversation_id: str = "support.support",
    sender_alias: str = "",
    citation_message_id: str | None = None,
) -> ConversationMessage:
    return ConversationMessage(
        message_id=message_id,
        conversation_id=conversation_id,
        sender_id=sender_id,
        sender_alias=sender_alias,
        text=text,
        timestamp_ms=ts,
        citation_message_id=citation_message_id,
    )


def test_build_history_filters_unrelated_users_and_keeps_staff_context() -> None:
    requester = "user-1"
    staff = "staff-1"
    other = "other-1"

    messages = [
        _msg("m1", requester, "What is Bisq Easy?", 1),
        _msg("m2", other, "How do I recover my account?", 2),
        _msg("m3", staff, "Bisq Easy is for simple BTC purchases.", 3),
        _msg("m4", requester, "And what about USD?", 4),
    ]

    history = build_channel_chat_history(
        messages,
        current_message_id="m4",
        requester_id=requester,
        is_staff_message=lambda msg: msg.sender_id == staff,
    )

    assert history is not None
    content = [entry["content"] for entry in history]
    assert "What is Bisq Easy?" in content
    assert "Bisq Easy is for simple BTC purchases." in content
    assert "And what about USD?" in content
    assert "How do I recover my account?" not in content


def test_build_history_keeps_citation_linked_non_staff_message() -> None:
    requester = "user-1"
    non_staff = "ai-bot-1"

    messages = [
        _msg("m1", requester, "Best EUR payment method?", 1),
        _msg(
            "m2",
            non_staff,
            "SEPA is commonly the best for EUR offers.",
            2,
            citation_message_id="m1",
        ),
        _msg("m3", requester, "And for USD?", 3),
    ]

    history = build_channel_chat_history(
        messages,
        current_message_id="m3",
        requester_id=requester,
        is_staff_message=lambda _msg: False,
    )

    assert history is not None
    content = [entry["content"] for entry in history]
    assert "Best EUR payment method?" in content
    assert "SEPA is commonly the best for EUR offers." in content
    assert "And for USD?" in content


def test_build_history_truncation_keeps_tail_context_for_version_hints() -> None:
    requester = "user-1"
    staff = "staff-1"
    long_prefix = "x" * 280
    long_staff_reply = (
        f"{long_prefix} Support note: this answer is specifically for Bisq 2 users."
    )
    messages = [
        _msg("m1", requester, "Why is the app slow?", 1),
        _msg("m2", staff, long_staff_reply, 2),
        _msg("m3", requester, "WTF?!", 3),
    ]

    history = build_channel_chat_history(
        messages,
        current_message_id="m3",
        requester_id=requester,
        is_staff_message=lambda msg: msg.sender_id == staff,
    )

    assert history is not None
    combined = " ".join(entry["content"].lower() for entry in history)
    assert "bisq 2" in combined
