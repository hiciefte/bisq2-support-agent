"""Pinned nio callback lifecycle and local projection failure boundaries."""

import asyncio
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.plugins.matrix.message_handler import AttachmentEventTypes
from nio import RoomEncryptedImage

from tests.channels.test_context_feedback import feedback as base_feedback
from tests.channels.test_context_feedback import proposal
from tests.channels.test_context_runtime_integration import SOURCE_ROOM
from tests.channels.test_matrix_review_regressions import (
    ROOM,
    STAFF,
    message_handler,
    reaction_runtime,
)
from tests.channels.test_matrix_review_regressions import (
    runtime_case as base_runtime_case,
)
from tests.channels.test_matrix_review_regressions import (
    sync_response,
)

pytestmark = pytest.mark.unit
runtime_case = base_runtime_case
feedback = base_feedback


async def test_real_nio_stop_start_removes_only_own_callbacks():
    client, store, observer, handler, _ = reaction_runtime()
    unrelated = AsyncMock()
    client.add_event_callback(unrelated, object)
    await handler.start_listening()
    await handler.stop_listening()
    assert [c.func for c in client.event_callbacks] == [unrelated]
    await handler.start_listening()
    await handler.start_listening()
    try:
        await client.receive_response(
            sync_response(
                [
                    dict(
                        type="m.room.redaction",
                        event_id="$redact",
                        sender=STAFF,
                        origin_server_ts=1234,
                        content={"redacts": "$reaction"},
                    )
                ]
            )
        )
    finally:
        await handler.stop_listening()
        await client.close()
    store.redact_verdict.assert_awaited_once_with(ROOM, "$reaction")
    observer.observe_source_event.assert_awaited_once()
    assert [c.func for c in client.event_callbacks] == [unrelated]


async def test_transient_staff_redaction_write_retries_locally_once():
    client, store, _, handler, processor = reaction_runtime()
    store.redact_verdict.side_effect = [sqlite3.OperationalError("locked"), None]
    await handler._on_redaction_event(
        NS(room_id=ROOM), NS(redacts="$reaction", sender=STAFF)
    )
    assert store.redact_verdict.await_count == 2
    processor.revoke_reaction.assert_awaited_once_with(
        channel_id="matrix",
        external_message_id="$original",
        reactor_id=STAFF,
        raw_reaction="👍",
    )
    await client.close()


async def test_persistent_redaction_failure_is_bounded_and_ordinary_revocation_independent():
    client, store, _, handler, processor = reaction_runtime()
    store.redact_verdict.side_effect = sqlite3.OperationalError("locked")
    await handler._on_redaction_event(
        NS(room_id=ROOM), NS(redacts="$reaction", sender=STAFF)
    )
    assert store.redact_verdict.await_count == 3
    processor.revoke_reaction.assert_awaited_once()
    await client.close()


async def test_identified_ordinary_escalation_does_not_depend_on_note_lookup():
    client, store, _, handler, processor = reaction_runtime()
    store.has_note = AsyncMock(side_effect=sqlite3.OperationalError("locked"))
    handler._lookup_staff_escalation_record = Mock(
        return_value=NS(routing_action="staff_escalation_notice")
    )
    handler._handle_staff_room_escalation_action = AsyncMock(return_value=True)
    event = NS(
        event_id="$approve",
        sender=STAFF,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$notice",
                    "key": "👍",
                }
            }
        },
    )
    await handler._on_reaction_event(NS(room_id=ROOM), event)
    store.has_note.assert_not_awaited()
    handler._handle_staff_room_escalation_action.assert_awaited_once_with(
        room_id=ROOM, target_event_id="$notice", key="👍", sender=STAFF
    )
    processor.process.assert_not_awaited()
    await client.close()


async def test_unknown_target_lookup_failure_never_falls_through_to_approval_or_learning():
    client, store, _, handler, processor = reaction_runtime()
    store.has_note = AsyncMock(side_effect=sqlite3.OperationalError("locked"))
    handler._lookup_staff_escalation_record = Mock(return_value=None)
    handler._handle_staff_room_escalation_action = AsyncMock()
    event = NS(
        event_id="$unknown",
        sender=STAFF,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": "$unknown-note",
                    "key": "👍",
                }
            }
        },
    )
    await handler._on_reaction_event(NS(room_id=ROOM), event)
    handler._handle_staff_room_escalation_action.assert_not_awaited()
    processor.process.assert_not_awaited()
    await client.close()


@pytest.mark.parametrize("encrypted", [False, True])
async def test_attachment_failure_does_not_abort_later_event_in_same_sync(
    runtime_case, encrypted
):
    bundle = runtime_case
    observer = AsyncMock(side_effect=sqlite3.OperationalError("locked"))
    bundle.services["matrix_context_runtime"] = NS(observe_source_event=observer)
    handler = message_handler(bundle)
    from nio import AsyncClient, RoomMessageText

    client = AsyncClient("https://offline.invalid", "@bot:example.org")
    text_callback = AsyncMock()
    client.add_event_callback(handler._on_context_attachment, AttachmentEventTypes)
    client.add_event_callback(text_callback, RoomMessageText)
    response = sync_response(
        [
            dict(
                type="m.room.message",
                event_id="$image",
                sender="@requester:example.org",
                origin_server_ts=1000,
                content=dict(
                    msgtype="m.image", body="image", url="mxc://example.org/not-fetched"
                ),
            ),
            dict(
                type="m.room.message",
                event_id="$later",
                sender="@requester:example.org",
                origin_server_ts=1001,
                content=dict(msgtype="m.text", body="The later event"),
            ),
        ]
    )
    if encrypted:
        original = response.rooms.join[ROOM].timeline.events[0]
        response.rooms.join[ROOM].timeline.events[0] = RoomEncryptedImage(
            original.source,
            "mxc://example.org/not-fetched",
            "image",
            {"kty": "oct", "k": "synthetic-never-used"},
            {"sha256": "synthetic"},
            "synthetic-iv",
            "image/png",
        )
    joined = response.rooms.join.pop(ROOM)
    response.rooms.join[SOURCE_ROOM] = joined
    try:
        await client.receive_response(response)
    finally:
        await client.close()
    observer.assert_awaited_once()
    if encrypted:
        assert isinstance(observer.await_args.args[1], RoomEncryptedImage)
    assert text_callback.await_args.args[1].event_id == "$later"


async def test_attachment_cancellation_propagates(runtime_case):
    bundle = runtime_case
    bundle.services["matrix_context_runtime"] = NS(
        observe_source_event=AsyncMock(side_effect=asyncio.CancelledError())
    )
    with pytest.raises(asyncio.CancelledError):
        await message_handler(bundle)._on_context_attachment(
            NS(room_id=SOURCE_ROOM), NS(sender="@requester:example.org")
        )


def test_encrypted_image_presence_has_subscription_filter():
    assert RoomEncryptedImage in AttachmentEventTypes


@pytest.mark.parametrize("fallback", [True, False, "true"])
async def test_only_explicit_thread_reply_identifies_published_draft(
    feedback, fallback
):
    event = NS(
        event_id="$fallback-check",
        server_timestamp=5000,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root",
                    "is_falling_back": fallback,
                    "m.in_reply_to": {"event_id": "$oldnote"},
                }
            }
        },
    )
    assert await feedback.handler.handle_context_thread_answer(
        room_id=ROOM, event=event, sender=STAFF, answer="Check your network."
    )
    saved = proposal(await feedback.repository.get_by_id(feedback.case.id))
    assert saved["draft_version_known"] is (fallback is False)
    assert saved["edit_distance"] == (0.0 if fallback is False else None)
