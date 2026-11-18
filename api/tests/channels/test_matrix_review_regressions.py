"""Real parser and callback failure boundaries; no Matrix requests."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.plugins.matrix.message_handler import MatrixMessageHandler
from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler
from nio import AsyncClient, BadEvent, SyncResponse

from tests.channels.test_context_conversation_runtime import (
    runtime_case as base_runtime_case,
)
from tests.channels.test_context_runtime_integration import SOURCE_ROOM

runtime_case = base_runtime_case

pytestmark = pytest.mark.unit
ROOM = "!staff:example.org"
STAFF = "@staff:example.org"


def reaction_runtime():
    client = AsyncClient("https://offline.invalid", "@bot:example.org")
    store = NS(redact_verdict=AsyncMock(), record_answer=AsyncMock())
    observer = NS(observe_source_event=AsyncMock())
    services = {"matrix_client": client, "matrix_context_runtime": observer}
    runtime = NS(
        settings=NS(MATRIX_STAFF_ROOM=ROOM, MATRIX_RESPONDER_ROOMS=[ROOM]),
        resolve=lambda key: services[key],
        resolve_optional=lambda key: services.get(key),
    )
    processor = NS(revoke_reaction=AsyncMock(), process=AsyncMock())
    handler = MatrixReactionHandler(runtime, processor, allowed_room_ids=[ROOM])
    handler._context_feedback_store = Mock(return_value=store)
    handler._is_staff_sender = Mock(return_value=True)
    handler._reaction_to_message["$reaction"] = "$original"
    handler._reaction_to_sender["$reaction"] = STAFF
    return client, store, observer, handler, processor


def sync_response(events):
    return SyncResponse.from_dict(
        {
            "next_batch": "fixture-1",
            "rooms": {
                "join": {
                    ROOM: {
                        "timeline": {
                            "events": events,
                            "limited": False,
                            "prev_batch": "x",
                        },
                        "state": {"events": []},
                        "ephemeral": {"events": []},
                        "account_data": {"events": []},
                        "unread_notifications": {},
                    }
                }
            },
        }
    )


async def test_room_v11_content_redaction_reaches_callback_through_real_sync_parser():
    client, store, observer, handler, processor = reaction_runtime()
    response = sync_response(
        [
            {
                "type": "m.room.redaction",
                "event_id": "$redact",
                "sender": STAFF,
                "origin_server_ts": 1234,
                "content": {"redacts": "$reaction"},
            }
        ]
    )
    assert isinstance(response.rooms.join[ROOM].timeline.events[0], BadEvent)
    await handler.start_listening()
    try:
        await client._handle_sync(response)
    finally:
        await handler.stop_listening()
        await client.close()
    store.redact_verdict.assert_awaited_once_with(ROOM, "$reaction")
    processor.revoke_reaction.assert_awaited_once()
    observer.observe_source_event.assert_awaited_once()
    assert "$reaction" not in handler._reaction_to_message


@pytest.mark.parametrize("failed_component", ["observer", "store"])
async def test_context_redaction_failure_does_not_block_ordinary_revocation(
    failed_component,
):
    client, store, observer, handler, processor = reaction_runtime()
    failing = (
        observer.observe_source_event
        if failed_component == "observer"
        else store.redact_verdict
    )
    failing.side_effect = RuntimeError("fixture storage failure")
    await handler._on_redaction_event(
        NS(room_id=ROOM), NS(redacts="$reaction", sender=STAFF)
    )
    processor.revoke_reaction.assert_awaited_once()
    await client.close()


@pytest.mark.parametrize("target", [{}, [], None, "", 3])
@pytest.mark.parametrize("kind", ["m.replace", "m.thread"])
async def test_malformed_thread_or_edit_target_never_queries_store(target, kind):
    client, store, _, handler, _ = reaction_runtime()
    event = NS(
        event_id="$answer",
        server_timestamp=1000,
        source={"content": {"m.relates_to": {"rel_type": kind, "event_id": target}}},
    )
    assert not await handler.handle_context_thread_answer(
        room_id=ROOM, event=event, sender=STAFF, answer="Check the network."
    )
    handler._context_feedback_store.assert_not_called()
    store.record_answer.assert_not_awaited()
    await client.close()


def message_handler(bundle):
    handler = MatrixMessageHandler(
        client=bundle.client,
        connection_manager=NS(room_state_ready=True),
        channel=bundle.channel,
        autoresponse_policy_service=bundle.services[
            "channel_autoresponse_policy_service"
        ],
    )
    handler._record_trust_event = AsyncMock()
    handler._record_staff_activity = AsyncMock()
    handler._maybe_handle_staff_command = AsyncMock()
    handler._get_orchestrator = Mock(return_value=NS(process_incoming=AsyncMock()))
    return handler


async def test_failed_internal_answer_capture_does_not_escape_or_fall_through(
    runtime_case,
):
    bundle = runtime_case
    bundle.runtime.settings.MATRIX_STAFF_ROOM = ROOM
    bundle.runtime.settings.MATRIX_RESPONDER_ROOMS = [ROOM]
    capture = AsyncMock(side_effect=RuntimeError("database busy"))
    bundle.services["matrix_reaction_handler"] = NS(
        handle_context_thread_answer=capture
    )
    handler = message_handler(bundle)
    body = "A proposed reply"
    event = NS(
        event_id="$answer",
        sender=STAFF,
        body=body,
        server_timestamp=1000,
        source={
            "content": {
                "body": body,
                "m.relates_to": {"rel_type": "m.thread", "event_id": "$root"},
            }
        },
    )
    await handler._on_message(NS(room_id=ROOM), event)
    capture.assert_awaited_once()
    handler._record_staff_activity.assert_not_awaited()
    handler._maybe_handle_staff_command.assert_not_awaited()
    handler._get_orchestrator.assert_not_called()
    # A later event still reaches this callback; one failure cannot abort sync.
    capture.side_effect = None
    capture.return_value = True
    await handler._on_message(NS(room_id=ROOM), event)
    assert capture.await_count == 2


async def test_rejected_context_observation_preserves_staff_activity_and_commands(
    runtime_case,
):
    bundle = runtime_case
    observation = AsyncMock(side_effect=ValueError("Future event"))
    bundle.services["matrix_context_runtime"] = NS(observe_source_event=observation)
    handler = message_handler(bundle)
    body = "/status"
    event = NS(
        event_id="$future",
        sender=STAFF,
        body=body,
        server_timestamp=9999999999999,
        source={"content": {"body": body}},
    )
    await handler._on_message(NS(room_id=SOURCE_ROOM), event)
    observation.assert_awaited_once()
    handler._record_staff_activity.assert_awaited_once()
    handler._maybe_handle_staff_command.assert_awaited_once()
