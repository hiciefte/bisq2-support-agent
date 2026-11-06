"""Offline regressions for confirmed retrieval facts and auditable Staff holds."""

import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest
from app.channels.staff_assist.context_runtime import _SourceContextSnapshot
from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver

from tests.channels import test_context_runtime_integration as runtime_fixtures
from tests.channels.test_context_discussion import OWNER, event, source

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in runtime_fixtures.runtime_case.__wrapped__(tmp_path):
        yield bundle


@pytest.mark.asyncio
async def test_confirmed_requester_diagnostic_reaches_retriever_and_resolver(
    runtime_case,
):
    bundle = runtime_case
    question = "Yes, PeerHandshakeMismatch remains after restarting."
    prior = "My Bisq 2 client reports PeerHandshakeMismatch after reconnecting."
    source(bundle, question, before=[event("$diagnostic", prior, sender=OWNER)])
    original = StaffEvidenceResolver.resolve
    queries = []

    async def resolve(self, **kwargs):
        queries.append(kwargs["question"])
        return await original(self, **kwargs)

    with patch.object(StaffEvidenceResolver, "resolve", resolve):
        case = await runtime_fixtures.run(bundle)
    query = bundle.retrieve.call_args.args[0]
    assert query == question + "\n\nConfirmed requester context:\n" + prior
    assert queries == [query]
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert prompt["question"] == question
    assert prompt["recent_messages"][0]["content"] == prior
    assert case.channel_metadata["context_status"] == "delivered"
    assert len(case.channel_metadata["retrieval_query_version"]) == 64


@pytest.mark.asyncio
@pytest.mark.parametrize("sender", [OWNER, "@helper:example.org"])
async def test_unrelated_neighbor_never_becomes_retrieval_fact(runtime_case, sender):
    bundle = runtime_case
    question = "Where is the mediation entry point?"
    prior = "My client reports PeerHandshakeMismatch."
    source(bundle, question, before=[event("$neighbor", prior, sender=sender)])
    case = await runtime_fixtures.run(bundle)
    bundle.retrieve.assert_called_once_with(question)
    assert prior in json.dumps(case.channel_metadata["source_context_snapshot"])


@pytest.mark.asyncio
async def test_helper_diagnostic_is_prompt_context_not_requester_query(runtime_case):
    bundle = runtime_case
    question = "Yes, PeerHandshakeMismatch remains after restarting."
    source(
        bundle,
        question,
        before=[event("$helper", "Does PeerHandshakeMismatch appear?")],
    )
    await runtime_fixtures.run(bundle)
    bundle.retrieve.assert_called_once_with(question)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "neighbor",
    [
        "New issue: my wallet reports AnotherException.",
        "My Bisq 1 wallet reports AnotherException.",
    ],
)
async def test_explicit_native_new_issue_and_product_conflict_not_enriched(
    runtime_case, neighbor
):
    bundle = runtime_case
    source(
        bundle,
        "My Bisq 2 client reports PeerHandshakeMismatch.",
        after=[
            event(
                "$other",
                neighbor,
                sender=OWNER,
                relation={"m.in_reply_to": {"event_id": "$source"}},
            ),
        ],
    )
    snapshot = _SourceContextSnapshot()
    messages, reason = await bundle.engine._read_source(
        bundle.incoming, snapshot=snapshot
    )
    assert reason is None
    assert any(message.content == neighbor for message in messages)
    assert snapshot.confirmed_retrieval_messages == ()


@pytest.mark.asyncio
async def test_native_requester_fact_is_version_bound_but_helper_is_not_owned(
    runtime_case,
):
    bundle = runtime_case
    response = source(
        bundle,
        "My Bisq 2 wallet will not open.",
        after=[
            event(
                "$ack",
                "Thanks.",
                sender=OWNER,
                relation={"m.in_reply_to": {"event_id": "$source"}},
            ),
            event(
                "$own",
                "The wallet reports PeerHandshakeMismatch.",
                sender=OWNER,
                relation={"m.in_reply_to": {"event_id": "$ack"}},
            ),
            event(
                "$helper",
                "My wallet reports AnotherException.",
                relation={"m.in_reply_to": {"event_id": "$source"}},
            ),
        ],
    )
    snapshot = _SourceContextSnapshot()
    _, reason = await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert reason is None
    assert [message.content for message in snapshot.confirmed_retrieval_messages] == [
        response.events_after[1].body
    ]
    assert "$own" in snapshot.events
    response.events_after[1] = event("$own", "Edited diagnostic.", sender=OWNER)
    _, reason = await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert reason == "source_context_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["pre_generation", "pre_root", "pre_note"])
async def test_staff_hold_records_current_phase_and_relation_basis(runtime_case, phase):
    bundle = runtime_case
    response = source(bundle, "My wallet is unavailable; where can I check its status?")
    staff = event(
        "$staff",
        "Which error appears in the wallet?",
        sender="@staff:example.org",
        relation={"m.in_reply_to": {"event_id": "$source"}},
    )
    if phase == "pre_generation":
        response.events_after = [staff]
    elif phase == "pre_root":

        def after_model(*args, **kwargs):
            response.events_after = [staff]
            return bundle.llm.invoke.return_value

        bundle.llm.invoke.side_effect = after_model
    else:
        initial = bundle.sender.side_effect

        async def after_root(*args, **kwargs):
            response.events_after = [staff]
            return next(initial)

        bundle.sender.side_effect = after_root
    case = await runtime_fixtures.run(bundle)
    audit = case.channel_metadata["staff_activity_decision"]
    assert audit == {
        "version": 1,
        "phase": phase,
        "reason": "staff_active",
        "basis": "incident_member",
        "trigger_event_sha256": hashlib.sha256(b"$staff").hexdigest(),
        "trigger_in_snapshot": True,
        "discussion_reason": None,
        "final_route_reason": "staff_active",
        "coverage": "bounded_snapshot",
    }
    assert "$staff" not in json.dumps(audit)
    assert bundle.sender.await_count == (1 if phase == "pre_note" else 0)
    assert bundle.llm.invoke.call_count == (0 if phase == "pre_generation" else 1)
    if phase != "pre_generation":
        assert case.channel_metadata["source_context_snapshot"] == []


@pytest.mark.asyncio
async def test_snapshot_failure_preserves_original_staff_decision(runtime_case):
    bundle = runtime_case
    source(
        bundle,
        "Where is the mediation entry point?",
        after=[
            event(
                f"$staff-{index}",
                "Which trade are you asking about?",
                sender="@staff:example.org",
            )
            for index in range(11)
        ],
    )
    case = await runtime_fixtures.run(bundle)
    audit = case.channel_metadata["staff_activity_decision"]
    assert audit["reason"] == "staff_context_membership_unresolved"
    assert audit["discussion_reason"] == "source_discussion_capacity_reached"
    assert audit["final_route_reason"] == case.channel_metadata["context_reason"]
    assert audit["coverage"] == "discussion_unavailable"
    assert audit["trigger_in_snapshot"] is False
    assert case.channel_metadata["staff_activity_snapshot"] == []
    bundle.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_each_source_read_clears_audit_without_changing_frozen_context(
    runtime_case,
):
    bundle = runtime_case
    response = source(bundle, "Where is the mediation entry point?")
    snapshot = _SourceContextSnapshot()
    await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    frozen_events = snapshot.events.copy()
    response.events_after = [
        event(
            "$staff", "Which trade are you asking about?", sender="@staff:example.org"
        )
    ]
    await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert snapshot.staff_activity_decision is not None
    assert snapshot.events == frozen_events
    bundle.client.room_context = AsyncMock(return_value=None)
    _, reason = await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert reason == "source_unavailable"
    assert snapshot.staff_activity_decision is None
    assert snapshot.events == frozen_events


@pytest.mark.asyncio
async def test_read_only_native_chain_uses_relation_basis_without_intake(runtime_case):
    bundle = runtime_case
    source(
        bundle,
        "Where is the mediation entry point?",
        after=[
            event(
                "$ack", "Thanks.", relation={"m.in_reply_to": {"event_id": "$source"}}
            ),
            event(
                "$staff",
                "Which trade are you asking about?",
                sender="@staff:example.org",
                relation={"m.in_reply_to": {"event_id": "$ack"}},
            ),
        ],
    )
    snapshot = _SourceContextSnapshot()
    _, reason = await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert reason == "staff_active"
    assert snapshot.staff_activity_decision["basis"] == "native_relation"
    bundle.retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_active_staff_outside_prompt_window_has_explicit_omission(runtime_case):
    bundle = runtime_case
    bundle.policy.staff_active_cooldown_seconds = 3600
    response = source(bundle, "Where is the mediation entry point?")
    response.events_before = [
        event(
            "$staff",
            "Which trade are you asking about?",
            sender="@staff:example.org",
            timestamp=response.event.server_timestamp - 1200000,
        )
    ]
    case = await runtime_fixtures.run(bundle)
    audit = case.channel_metadata["staff_activity_decision"]
    assert audit["reason"] == "staff_context_membership_unresolved"
    assert audit["basis"] == "incident_membership_unresolved"
    assert audit["trigger_in_snapshot"] is False
    assert audit["coverage"] == "bounded_snapshot"
    assert audit["discussion_reason"] is None
    assert case.channel_metadata["staff_activity_snapshot"] == []


@pytest.mark.asyncio
async def test_unavailable_membership_service_is_not_identity_failure(runtime_case):
    bundle = runtime_case
    source(
        bundle,
        "Where is the mediation entry point?",
        after=[event("$staff", "Which trade?", sender="@staff:example.org")],
    )
    bundle.services.pop("escalation_service")
    snapshot = _SourceContextSnapshot()
    _, reason = await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert reason == "staff_context_membership_unresolved"
    assert snapshot.staff_activity_decision["basis"] == "escalation_service_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["relation", "author", "removed", "redacted"])
async def test_native_ack_proof_is_revalidated_without_prompt_text(
    runtime_case, change
):
    bundle = runtime_case
    ack = event("$ack", "Thanks.", relation={"m.in_reply_to": {"event_id": "$source"}})
    diagnostic = event(
        "$own",
        "The wallet reports PeerHandshakeMismatch.",
        sender=OWNER,
        relation={"m.in_reply_to": {"event_id": "$ack"}},
    )
    response = source(bundle, "My wallet will not open.", after=[ack, diagnostic])
    snapshot = _SourceContextSnapshot()
    messages, reason = await bundle.engine._read_source(
        bundle.incoming, snapshot=snapshot
    )
    assert reason is None
    assert "$ack" in snapshot.events
    assert all(message.content != "Thanks." for message in messages)
    if change == "relation":
        ack.source["content"]["m.relates_to"] = {
            "m.in_reply_to": {"event_id": "$different"}
        }
    elif change == "author":
        ack.sender = "@different:example.org"
    elif change == "redacted":
        ack.source["unsigned"] = {"redacted_because": {"type": "m.room.redaction"}}
    else:
        response.events_after = [diagnostic]
    _, reason = await bundle.engine._read_source(bundle.incoming, snapshot=snapshot)
    assert reason == "source_context_changed"
