"""Staff-context judgments must never use delivery or calibration paths."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler
from app.channels.staff import StaffResolver
from app.channels.staff_assist.context_feedback import ContextFeedbackStore
from app.models.escalation import EscalationCreate
from app.scripts.summarize_staff_context import summarize
from app.services.escalation.escalation_repository import EscalationRepository

pytestmark = pytest.mark.unit


def proposal(case):
    return case.channel_metadata.get("staff_context_proposed_answer")


@pytest.fixture
async def feedback(tmp_path):
    repository = EscalationRepository(str(tmp_path / "cases.db"))
    await repository.initialize()
    case = await repository.create(
        EscalationCreate(
            message_id="$question",
            channel="matrix",
            user_id="@user:example.org",
            question="Which setting?",
            ai_draft_answer="Envelope must not be compared",
            confidence_score=0,
            routing_action="needs_human",
            channel_metadata={
                "delivery_audience": "staff_room",
                "response_kind": "public_context",
                "staff_room_id": "!staff:example.org",
                "staff_root_event_id": "$root",
                "staff_note_event_id": "$note",
                "context_status": "delivered",
                "context_reason": "staff_context_delivered",
                "context_trial_id": "test-trial",
                "staff_reply": "Check Settings > Network.",
                "staff_note_history": [
                    {
                        "event_id": "$oldnote",
                        "reply": "Check your network.",
                        "version": 0,
                        "acknowledged_at_ms": 100,
                    },
                    {
                        "event_id": "$note",
                        "reply": "Check Settings > Network.",
                        "version": 1,
                        "acknowledged_at_ms": 200,
                    },
                ],
            },
        )
    )
    service = SimpleNamespace(
        repository=repository, respond_to_escalation=AsyncMock(), learning_engine=Mock()
    )
    client = SimpleNamespace(room_send=AsyncMock())
    processor = SimpleNamespace(process=AsyncMock(), revoke_reaction=AsyncMock())
    registry = {
        "escalation_service": service,
        "staff_resolver:matrix": StaffResolver(
            ["@staff:example.org", "@second:example.org"]
        ),
        "matrix_client": client,
    }
    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            MATRIX_STAFF_ROOM="!staff:example.org",
            MATRIX_RESPONDER_ROOMS=[],
            MATRIX_GENERATION_ENABLED=False,
        ),
        resolve_optional=lambda key: registry.get(key),
    )
    handler = MatrixReactionHandler(runtime, processor, allowed_room_ids=[])
    return SimpleNamespace(
        repository=repository,
        case=case,
        handler=handler,
        service=service,
        client=client,
        processor=processor,
        store=ContextFeedbackStore(repository.db_path),
    )


def reaction(event_id, key, timestamp, *, sender="@staff:example.org", target="$note"):
    return SimpleNamespace(
        event_id=event_id,
        sender=sender,
        server_timestamp=timestamp,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.annotation",
                    "event_id": target,
                    "key": key,
                }
            }
        },
    )


@pytest.mark.asyncio
async def test_only_trusted_latest_per_person_with_restart_and_redaction(feedback):
    room = SimpleNamespace(room_id="!staff:example.org")
    handler = feedback.handler
    await handler._on_reaction_event(
        room, reaction("$untrusted", "👍", 9000, sender="@outsider:example.org")
    )
    assert (
        await feedback.repository.get_by_id(feedback.case.id)
    ).staff_context_verdicts == []
    await handler._on_reaction_event(room, reaction("$first", "👍", 1000))
    await handler._on_reaction_event(room, reaction("$newer", "✏️", 3000))
    await handler._on_reaction_event(room, reaction("$outoforder", "❌", 2000))
    await handler._on_reaction_event(
        room, reaction("$second", "🚫", 1500, sender="@second:example.org")
    )
    handler = MatrixReactionHandler(
        handler.runtime, feedback.processor, allowed_room_ids=[]
    )
    await handler._on_reaction_event(room, reaction("$newer", "✏️", 3000))
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert len(case.staff_context_verdicts) == 2
    assert {v.reviewer: v.verdict for v in case.staff_context_verdicts} == {
        "@staff:example.org": "would_send_after_edit",
        "@second:example.org": "not_needed",
    }
    await handler._on_redaction_event(
        room, SimpleNamespace(redacts="$newer", sender="@staff:example.org")
    )
    await handler._on_reaction_event(room, reaction("$newer", "✏️", 3000))
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert {v.reviewer: v.verdict for v in case.staff_context_verdicts}[
        "@staff:example.org"
    ] == "wrong"
    feedback.client.room_send.assert_not_awaited()
    feedback.processor.process.assert_not_awaited()
    feedback.processor.revoke_reaction.assert_not_awaited()
    feedback.service.respond_to_escalation.assert_not_awaited()
    assert feedback.service.learning_engine.mock_calls == []


@pytest.mark.asyncio
async def test_wrong_room_target_unknown_emoji_and_bad_timestamp_are_not_verdicts(
    feedback,
):
    await feedback.handler._on_reaction_event(
        SimpleNamespace(room_id="!source:example.org"), reaction("$x", "👍", 1000)
    )
    room = SimpleNamespace(room_id="!staff:example.org")
    await feedback.handler._on_reaction_event(
        room, reaction("$x", "👍", 1000, target="$unrelated")
    )
    await feedback.handler._on_reaction_event(room, reaction("$y", "❤️", 1000))
    await feedback.handler._on_reaction_event(room, reaction("$z", "👍", None))
    assert (
        await feedback.repository.get_by_id(feedback.case.id)
    ).staff_context_verdicts == []
    feedback.client.room_send.assert_not_awaited()
    feedback.processor.process.assert_not_awaited()


@pytest.mark.asyncio
async def test_redaction_before_reaction_is_not_resurrected(feedback):
    room = SimpleNamespace(room_id="!staff:example.org")
    await feedback.handler._on_redaction_event(
        room, SimpleNamespace(redacts="$later", sender="@staff:example.org")
    )
    await feedback.handler._on_reaction_event(room, reaction("$later", "❌", 1000))
    assert (
        await feedback.repository.get_by_id(feedback.case.id)
    ).staff_context_verdicts == []


@pytest.mark.asyncio
async def test_native_staff_thread_answer_stored_without_send_or_learning(feedback):
    event = SimpleNamespace(
        event_id="$answer",
        server_timestamp=5000,
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root",
                    "m.in_reply_to": {"event_id": "$note"},
                }
            }
        },
    )
    args = dict(
        room_id="!staff:example.org", event=event, answer="Check Settings > Network."
    )
    assert not await feedback.handler.handle_context_thread_answer(
        sender="@outsider:example.org", **args
    )
    assert await feedback.handler.handle_context_thread_answer(
        sender="@staff:example.org", **args
    )
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert proposal(case)["answer"] == "Check Settings > Network."
    assert proposal(case)["edit_distance"] == 0
    assert proposal(case)["reviewer"] == "@staff:example.org"
    assert proposal(case)["timestamp_ms"] == 5000
    assert case.staff_id is None and case.responded_at is None
    assert case.staff_answer is None and case.edit_distance is None
    assert case.delivery_status == feedback.case.delivery_status
    assert case.status.value == "pending"
    assert not await feedback.handler.handle_context_thread_answer(
        sender="@staff:example.org", **{**args, "answer": "/send"}
    )
    event.source["content"]["m.relates_to"]["event_id"] = "$otherroot"
    assert not await feedback.handler.handle_context_thread_answer(
        sender="@staff:example.org", **args
    )
    event.source["content"]["m.relates_to"] = {"m.in_reply_to": {"event_id": "$root"}}
    assert not await feedback.handler.handle_context_thread_answer(
        sender="@staff:example.org", **args
    )
    feedback.service.respond_to_escalation.assert_not_awaited()
    feedback.client.room_send.assert_not_awaited()
    feedback.processor.process.assert_not_awaited()
    assert feedback.service.learning_engine.mock_calls == []


@pytest.mark.asyncio
async def test_history_verdict_retains_exact_draft_target(feedback):
    await feedback.handler._on_reaction_event(
        SimpleNamespace(room_id="!staff:example.org"),
        reaction("$vote", "👍", 1000, target="$oldnote"),
    )
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert case.staff_context_verdicts[0].target_event_id == "$oldnote"


@pytest.mark.asyncio
async def test_summary_counts_reviewers_and_unique_covered_notes(feedback):
    room = SimpleNamespace(room_id="!staff:example.org")
    await feedback.handler._on_reaction_event(room, reaction("$a", "👍", 1000))
    await feedback.handler._on_reaction_event(room, reaction("$b", "✏️", 2000))
    await feedback.handler._on_reaction_event(
        room, reaction("$c", "❌", 2000, sender="@second:example.org")
    )
    report = summarize(Path(feedback.repository.db_path))[0]
    assert report["notes_posted"] == 2
    assert report["posted_notes_with_verdict"] == 1
    assert report["share_of_posted_notes_with_verdict"] == 0.5
    assert report["verdict_counts"] == {
        "would_send_as_is": 0,
        "would_send_after_edit": 1,
        "wrong": 1,
        "not_needed": 0,
    }
    assert report["outcome_counts_by_reason"] == {"staff_context_delivered": 1}


@pytest.mark.asyncio
async def test_callback_captures_staff_answer_with_generation_and_responder_off(
    feedback,
):
    from app.channels.plugins.matrix.message_handler import MatrixMessageHandler

    runtime = feedback.handler.runtime
    original_resolve = runtime.resolve_optional
    runtime.resolve_optional = lambda key: (
        feedback.handler if key == "matrix_reaction_handler" else original_resolve(key)
    )
    channel = SimpleNamespace(runtime=runtime, handle_incoming=AsyncMock())
    listener = MatrixMessageHandler(
        client=SimpleNamespace(user_id="@bot:example.org"),
        connection_manager=SimpleNamespace(room_state_ready=True),
        channel=channel,
        allowed_room_ids=[],
        staff_command_room_ids=[],
    )
    event = SimpleNamespace(
        event_id="$answer",
        sender="@staff:example.org",
        server_timestamp=6000,
        body="Check Settings > Network.",
        source={
            "content": {
                "body": "Check Settings > Network.",
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root",
                    "m.in_reply_to": {"event_id": "$note"},
                },
            }
        },
    )
    await listener._on_message(SimpleNamespace(room_id="!staff:example.org"), event)
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert proposal(case)["answer"] == "Check Settings > Network."
    assert proposal(case)["edit_distance"] == 0
    channel.handle_incoming.assert_not_awaited()
    feedback.client.room_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_note_versions_retain_independent_latest_verdict(feedback):
    room = SimpleNamespace(room_id="!staff:example.org")
    await feedback.handler._on_reaction_event(
        room, reaction("$oldvote", "❌", 1000, target="$oldnote")
    )
    await feedback.handler._on_reaction_event(
        room, reaction("$currentvote", "👍", 2000)
    )
    await feedback.repository.initialize()  # additive migration is idempotent
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert {(v.target_event_id, v.verdict) for v in case.staff_context_verdicts} == {
        ("$oldnote", "wrong"),
        ("$note", "would_send_as_is"),
    }
    report = summarize(Path(feedback.repository.db_path))[0]
    assert report["notes_posted"] == report["posted_notes_with_verdict"] == 2
    assert report["share_of_posted_notes_with_verdict"] == 1


@pytest.mark.asyncio
async def test_answer_edit_distance_uses_explicit_older_note_version(feedback):
    assert await feedback.store.record_answer(
        room_id="!staff:example.org",
        root_event_id="$root",
        event_id="$a",
        reviewer="@staff:example.org",
        answer="Check your network.",
        timestamp_ms=2000,
        reply_to_event_id="$oldnote",
    )
    assert (
        proposal(await feedback.repository.get_by_id(feedback.case.id))["edit_distance"]
        == 0
    )
    assert await feedback.store.record_answer(
        room_id="!staff:example.org",
        root_event_id="$root",
        event_id="$older",
        reviewer="@staff:example.org",
        answer="An older response",
        timestamp_ms=1000,
    )
    assert (
        proposal(await feedback.repository.get_by_id(feedback.case.id))["answer"]
        == "Check your network."
    )


@pytest.mark.asyncio
async def test_staff_answer_edit_and_redaction_reproject_without_network(feedback):
    args = dict(
        room_id="!staff:example.org",
        root_event_id="$root",
        reviewer="@staff:example.org",
    )
    assert await feedback.store.record_answer(
        **args,
        event_id="$answer",
        answer="Original answer",
        timestamp_ms=1000,
        reply_to_event_id="$note",
    )
    event = SimpleNamespace(
        event_id="$edit",
        server_timestamp=2000,
        source={
            "content": {
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$answer"},
                "m.new_content": {"body": "Check Settings > Network."},
            }
        },
    )
    assert not await feedback.handler.handle_context_thread_answer(
        room_id=args["room_id"],
        event=event,
        sender="@second:example.org",
        answer="Forged edit",
    )
    assert await feedback.handler.handle_context_thread_answer(
        room_id=args["room_id"],
        event=event,
        sender=args["reviewer"],
        answer="Check Settings > Network.",
    )
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert (
        proposal(case)["answer"] == "Check Settings > Network."
        and proposal(case)["edit_distance"] == 0
    )
    room = SimpleNamespace(room_id=args["room_id"])
    await feedback.handler._on_redaction_event(
        room, SimpleNamespace(redacts="$edit", sender=args["reviewer"])
    )
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert proposal(case)["answer"] == "Original answer"
    assert proposal(case)["edit_distance"] > 0
    await feedback.handler._on_redaction_event(
        room, SimpleNamespace(redacts="$answer", sender=args["reviewer"])
    )
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert proposal(case) is None
    assert case.staff_answer is None and case.edit_distance is None
    assert await feedback.store.record_answer(
        **args, event_id="$answer", answer="Original answer", timestamp_ms=1000
    )
    assert proposal(await feedback.repository.get_by_id(feedback.case.id)) is None
    feedback.client.room_send.assert_not_awaited()
    assert feedback.service.learning_engine.mock_calls == []


@pytest.mark.asyncio
async def test_summary_keeps_acknowledged_note_after_later_deferral(feedback):
    import json

    import aiosqlite

    case = await feedback.repository.get_by_id(feedback.case.id)
    metadata = case.channel_metadata
    metadata.update(
        context_status="deferred",
        staff_note_history=[],
        staff_note_delivery={
            "reason_category": "acknowledged",
            "response_received": True,
            "response_event_id": "$note",
        },
    )
    async with aiosqlite.connect(feedback.repository.db_path) as db:
        await db.execute(
            "UPDATE escalations SET channel_metadata=? WHERE id=?",
            (json.dumps(metadata), case.id),
        )
        await db.commit()
    assert summarize(Path(feedback.repository.db_path))[0]["notes_posted"] == 1
    metadata["context_status"] = "delivery_uncertain"
    async with aiosqlite.connect(feedback.repository.db_path) as db:
        await db.execute(
            "UPDATE escalations SET channel_metadata=? WHERE id=?",
            (json.dumps(metadata), case.id),
        )
        await db.commit()
    report = summarize(Path(feedback.repository.db_path))[0]
    assert report["notes_posted"] == 1 and report["notes_delivery_uncertain"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["in_review", "responded"])
async def test_matrix_proposal_preserves_admin_claim_and_completed_response(
    feedback, status
):
    import aiosqlite

    async with aiosqlite.connect(feedback.repository.db_path) as db:
        await db.execute(
            "UPDATE escalations SET status=?, staff_id='alice', claimed_at='2026-01-01T00:00:00+00:00', staff_answer='Admin response', responded_at='2026-01-01T01:00:00+00:00', edit_distance=0.3, delivery_status='delivered' WHERE id=?",
            (status, feedback.case.id),
        )
        await db.commit()
        before = await (
            await db.execute(
                "SELECT status,staff_id,claimed_at,staff_answer,responded_at,edit_distance,delivery_status FROM escalations WHERE id=?",
                (feedback.case.id,),
            )
        ).fetchone()
    assert await feedback.store.record_answer(
        room_id="!staff:example.org",
        root_event_id="$root",
        event_id="$bob",
        reviewer="bob",
        answer="Proposed text",
        timestamp_ms=5000,
    )
    case = await feedback.repository.get_by_id(feedback.case.id)
    assert proposal(case)["reviewer"] == "bob"
    async with aiosqlite.connect(feedback.repository.db_path) as db:
        active = await (
            await db.execute(
                "SELECT status,staff_id,claimed_at,staff_answer,responded_at,edit_distance,delivery_status FROM escalations WHERE id=?",
                (feedback.case.id,),
            )
        ).fetchone()
    assert active == before
    await feedback.store.redact_verdict("!staff:example.org", "$bob")
    async with aiosqlite.connect(feedback.repository.db_path) as db:
        after = await (
            await db.execute(
                "SELECT status,staff_id,claimed_at,staff_answer,responded_at,edit_distance,delivery_status FROM escalations WHERE id=?",
                (feedback.case.id,),
            )
        ).fetchone()
    assert after == before
    assert proposal(await feedback.repository.get_by_id(feedback.case.id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history,expected",
    [
        (
            [
                {"event_id": "$a", "reply": "Published A", "acknowledged_at_ms": 100},
                {"event_id": "$b", "reply": "Published B", "acknowledged_at_ms": 3000},
            ],
            None,
        ),
        ([{"event_id": "$a", "reply": "Published A"}], None),
        (
            [
                {"event_id": "$a", "reply": "Published A", "acknowledged_at_ms": 100},
                {"event_id": "$b", "reply": "Published B", "acknowledged_at_ms": 100},
            ],
            None,
        ),
    ],
)
async def test_general_thread_answer_compares_only_identified_published_version(
    feedback, history, expected
):
    import json

    import aiosqlite

    metadata = dict(
        feedback.case.channel_metadata,
        staff_note_history=history,
        staff_reply="Unpublished or later B",
    )
    async with aiosqlite.connect(feedback.repository.db_path) as db:
        await db.execute(
            "UPDATE escalations SET channel_metadata=? WHERE id=?",
            (json.dumps(metadata), feedback.case.id),
        )
        await db.commit()
    assert await feedback.store.record_answer(
        room_id="!staff:example.org",
        root_event_id="$root",
        event_id="$answer",
        reviewer="bob",
        answer="Published A",
        timestamp_ms=2000,
    )
    assert (
        proposal(await feedback.repository.get_by_id(feedback.case.id))["edit_distance"]
        == expected
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,expected", [("$oldnote", 0), ("$unresolved", None), ("", None)]
)
@pytest.mark.parametrize("timestamp_ms", [50, 5000])
async def test_explicit_note_identity_wins_over_local_ack_clock(
    feedback, target, expected, timestamp_ms
):
    assert await feedback.store.record_answer(
        room_id="!staff:example.org",
        root_event_id="$root",
        event_id="$answer",
        reviewer="bob",
        answer="Check your network.",
        timestamp_ms=timestamp_ms,
        reply_to_event_id=target,
    )
    saved = proposal(await feedback.repository.get_by_id(feedback.case.id))
    assert saved["edit_distance"] == expected
    assert saved["draft_version_known"] is (expected is not None)
