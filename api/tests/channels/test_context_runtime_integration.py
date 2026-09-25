"""Restart and publication boundaries for the durable Matrix context runtime."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.models import ChannelType, IncomingMessage, SendResult, UserContext
from app.channels.staff import StaffResolver
from app.channels.staff_assist.context_runtime import (
    ContextReviewStore,
    MatrixContextRuntime,
)
from app.models.escalation import EscalationFilters, EscalationStatus
from app.services.escalation.escalation_repository import EscalationRepository
from app.services.escalation.escalation_service import EscalationService
from app.services.faq.slug_manager import SlugManager
from langchain_core.documents import Document

pytestmark = pytest.mark.unit
SOURCE_ROOM = "!support:example.org"
STAFF_ROOM = "!staff:example.org"
QUESTION = "Where can I open mediation after the trade period?"


def context(*, body=QUESTION, after=None):
    return NS(
        event=NS(
            event_id="$source",
            body=body,
            server_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        ),
        events_before=[],
        events_after=after or [],
    )


def public_doc(**overrides):
    metadata = {
        "type": "wiki",
        "title": "Dispute resolution",
        "url": "https://bisq.wiki/Dispute_resolution",
    }
    metadata.update(overrides)
    return Document(
        page_content="The trade screen provides a mediation entry point after the trade period expires.",
        metadata=metadata,
    )


@pytest.fixture
async def runtime_case(tmp_path):
    repository = EscalationRepository(str(tmp_path / "escalations.db"))
    await repository.initialize()
    service = EscalationService(
        repository, None, None, None, NS(ESCALATION_CLAIM_TTL_MINUTES=30)
    )
    policy = NS(
        channel_id="matrix",
        response_kind="public_context",
        delivery_audience="staff_room",
        ai_response_mode="hitl",
        generation_enabled=True,
        first_response_delay_seconds=0,
    )
    policy_service = NS(get_policy=lambda _: policy)
    client = NS(
        room_context=AsyncMock(side_effect=lambda *a, **kw: context()),
        user_id="@agent:example.org",
    )
    retrieve = Mock(return_value=([public_doc()], [0.9]))

    async def run_retriever(_retriever, method, *args, **kwargs):
        return method(*args, **kwargs)

    llm = NS(
        invoke=Mock(
            return_value=NS(
                content=json.dumps(
                    {
                        "action": "note",
                        "text": "The trade screen provides a mediation entry point after the trade period expires.",
                        "source_ids": ["e1"],
                        "reason": "documented_mediation_entry_point",
                    }
                )
            )
        )
    )
    rag = NS(
        document_retriever=NS(retrieve_with_scores=retrieve),
        retriever=object(),
        _run_retriever_call=AsyncMock(side_effect=run_retriever),
        llm=llm,
    )
    services = {
        "escalation_service": service,
        "channel_autoresponse_policy_service": policy_service,
        "matrix_client": client,
        "staff_resolver:matrix": StaffResolver(["@staff:example.org"]),
    }
    runtime = NS(
        resolve_optional=services.get,
        rag_service=rag,
        settings=NS(
            MATRIX_CONTEXT_SOURCE_ROOMS=[SOURCE_ROOM],
            MATRIX_STAFF_ROOM=STAFF_ROOM,
            OPENAI_MODEL="openai:test-model",
        ),
    )
    incoming = IncomingMessage(
        message_id="$source",
        channel=ChannelType.MATRIX,
        question=QUESTION,
        user=UserContext(user_id="@user:example.org"),
        channel_metadata={"room_id": SOURCE_ROOM},
    )
    sender = AsyncMock(
        side_effect=[SendResult(True, "$staff-root"), SendResult(True, "$staff-note")]
    )
    channel = NS(
        send_staff_context=sender,
        runtime=runtime,
        handle_incoming=AsyncMock(),
        send_message=AsyncMock(),
    )
    engine = MatrixContextRuntime(runtime)
    bundle = NS(
        repository=repository,
        service=service,
        policy=policy,
        services=services,
        client=client,
        rag=rag,
        llm=llm,
        retrieve=retrieve,
        runtime=runtime,
        incoming=incoming,
        channel=channel,
        sender=sender,
        engine=engine,
    )
    yield bundle
    await engine.close()


async def saved_case(bundle):
    rows, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 1
    return rows[0]


async def run(bundle):
    assert await bundle.engine.process(bundle.incoming, bundle.channel) is False
    await bundle.engine.drain()
    return await saved_case(bundle)


def no_public_delivery(bundle):
    bundle.channel.handle_incoming.assert_not_awaited()
    bundle.channel.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reservation,expected_sends",
    [("staff_root_reserved", 0), ("staff_note_reserved", 1)],
)
async def test_rejection_after_send_reservation_prevents_transport(
    runtime_case, monkeypatch, reservation, expected_sends
):
    bundle = runtime_case
    update = ContextReviewStore.update

    async def close_after_reservation(store, case_id, **kwargs):
        await update(store, case_id, **kwargs)
        if kwargs.get("reason") == reservation:
            await bundle.service.close_escalation(case_id)

    monkeypatch.setattr(ContextReviewStore, "update", close_after_reservation)
    case = await run(bundle)
    assert case.status == EscalationStatus.CLOSED
    assert case.channel_metadata["context_status"] == "deferred"
    assert bundle.sender.await_count == expected_sends
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_case_is_durable_before_generation_and_each_send(runtime_case):
    bundle = runtime_case
    release = asyncio.Event()

    async def read(*args, **kwargs):
        await release.wait()
        return context()

    bundle.client.room_context.side_effect = read
    assert await bundle.engine.process(bundle.incoming, bundle.channel) is False
    fresh_repository = EscalationRepository(bundle.repository.db_path)
    rows, count = await fresh_repository.list_escalations(EscalationFilters())
    assert count == 1 and rows[0].status == EscalationStatus.PENDING
    assert rows[0].channel_metadata["delivery_audience"] == "staff_room"
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    snapshots = []

    async def send(markdown, **kwargs):
        case = await saved_case(bundle)
        snapshots.append(case)
        assert case.ai_draft_answer.startswith("AI context · ")
        assert case.channel_metadata["evidence_snapshot"]
        assert kwargs["expected_room_id"] == STAFF_ROOM
        if len(snapshots) == 1:
            assert markdown == case.channel_metadata["staff_root_content"]
            assert (
                kwargs["transaction_id"]
                == case.channel_metadata["staff_root_transaction_id"]
            )
            assert case.channel_metadata["context_reason"] == "staff_root_reserved"
            assert "thread_root_event_id" not in kwargs
            return SendResult(True, "$staff-root")
        assert markdown == case.channel_metadata["staff_note_content"]
        assert (
            kwargs["transaction_id"]
            == case.channel_metadata["staff_note_transaction_id"]
        )
        assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
        assert case.channel_metadata["context_reason"] == "staff_note_reserved"
        assert kwargs["thread_root_event_id"] == "$staff-root"
        return SendResult(True, "$staff-note")

    bundle.sender.side_effect = send
    release.set()
    await bundle.engine.drain()
    final = await saved_case(bundle)
    assert final.channel_metadata["context_status"] == "delivered"
    assert final.channel_metadata["staff_note_event_id"] == "$staff-note"
    assert final.channel_metadata["staff_thread_url"].endswith("/$staff-root")
    bundle.llm.invoke.assert_called_once()
    assert len(snapshots) == 2
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_duplicate_after_restart_never_regenerates_or_resends(runtime_case):
    bundle = runtime_case
    original = await run(bundle)
    assert original.channel_metadata["context_status"] == "delivered"
    restarted_repo = EscalationRepository(bundle.repository.db_path)
    bundle.services["escalation_service"] = EscalationService(
        restarted_repo, None, None, None, NS()
    )
    restarted = MatrixContextRuntime(bundle.runtime)
    assert await restarted.process(bundle.incoming, bundle.channel) is False
    await restarted.drain()
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2
    assert (await saved_case(bundle)).id == original.id
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_only_public_wiki_evidence_enters_actual_context_prompt(runtime_case):
    bundle = runtime_case
    excluded = [
        public_doc(type="faq"),
        public_doc(type="llm_wiki"),
        public_doc(private=True),
        public_doc(audience="staff"),
        public_doc(url="https://private.invalid/guide"),
    ]
    for index, document in enumerate(excluded):
        document.page_content = f"PRIVATE_BODY_{index}"
    bundle.retrieve.return_value = ([*excluded, public_doc()], [0.9] * 6)
    case = await run(bundle)
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert len(prompt["evidence"]) == 1
    assert "PRIVATE_BODY" not in json.dumps(prompt)
    assert "PRIVATE_BODY" not in json.dumps(case.sources)
    assert len(case.channel_metadata["evidence_snapshot"]) == 1
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_no_public_evidence_retains_case_without_model_or_send(runtime_case):
    bundle = runtime_case
    bundle.retrieve.return_value = ([public_doc(type="faq")], [0.9])
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "needs_human"
    assert case.channel_metadata["context_reason"] == "no_eligible_evidence"
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_code_grounding_is_supplied_before_context_generation(runtime_case):
    bundle = runtime_case
    calls = []
    fact = {
        "id": "code-example",
        "audience": "staff_only",
        "claim": "The source release documents a mediation entry point.",
        "support_use": "Check the installed release before applying this detail.",
        "source_refs": ["code:bisq2@abcdef123456:support/Service.java:10-12"],
        "freshness_class": "release_bound",
        "applies_to_versions": ["2.1.13"],
        "protocol": "bisq_easy",
    }

    def ground(**kwargs):
        calls.append("grounding")
        return {
            "evidence": [fact],
            "uncertainties": [
                "User release is unconfirmed; this does not diagnose the case."
            ],
        }

    def generate(payload, **kwargs):
        calls.append("generation")
        prompt = json.loads(payload)
        assert prompt["audience"] == "staff_only"
        code = next(
            source for source in prompt["evidence"] if source["kind"] == "code_fact"
        )
        assert json.loads(code["content"])["source_releases"] == ["2.1.13"]
        return NS(
            content=json.dumps(
                {
                    "action": "note",
                    "text": "The Bisq 2 source release documents a mediation entry point; the user's installed release remains unconfirmed.",
                    "source_ids": [code["id"]],
                    "reason": "Scoped staff investigation evidence.",
                }
            )
        )

    bundle.services["staff_grounding_brief_service"] = NS(build=ground)
    bundle.llm.invoke.side_effect = generate
    case = await run(bundle)
    assert calls == ["grounding", "generation"]
    assert case.sources[0]["type"] == "code_fact"
    assert case.sources[0]["audience"] == "staff_only"
    assert "Staff code evidence" in case.ai_draft_answer
    assert "Service.java" not in case.ai_draft_answer
    assert (
        case.channel_metadata["staff_grounding_brief"]["evidence"][0]["id"]
        == "code-example"
    )
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_verified_faq_enters_context_generation_with_real_source_kind(
    runtime_case,
):
    bundle = runtime_case
    bundle.rag.faq_service = NS(
        get_faq_by_id=lambda _: NS(
            id="42",
            verified=True,
            question="How does mediation work?",
            answer="The trade screen provides an entry point.",
            protocol="multisig_v1",
        )
    )
    published = {
        "id": "42",
        "question": "How does mediation work?",
        "answer": "The trade screen provides an entry point.",
        "slug": SlugManager().generate_slug("How does mediation work?", "42"),
    }
    bundle.services["public_faq_service"] = NS(
        get_faq_by_id=lambda _: published,
        get_faq_by_slug=lambda _: published,
    )
    bundle.retrieve.return_value = ([public_doc(type="faq", id="42")], [0.9])
    case = await run(bundle)
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert prompt["evidence"][0]["kind"] == "faq"
    assert prompt["evidence"][0]["url"].endswith(
        "/faq/" + SlugManager().generate_slug("How does mediation work?", "42")
    )
    assert case.sources[0]["type"] == "faq"
    assert (
        case.channel_metadata["evidence_snapshot"][0]["provenance"]["verified"] is True
    )
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_staff_activity_defers_durable_case_before_model(runtime_case):
    bundle = runtime_case
    staff_reply = NS(
        sender="@staff:example.org", body="I can help with this.", source={}
    )
    bundle.client.room_context.side_effect = lambda *a, **kw: context(
        after=[staff_reply]
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "staff_active"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_change_during_generation_preserves_note_but_suppresses_send(
    runtime_case,
):
    bundle = runtime_case
    bundle.client.room_context.side_effect = [
        context(),
        context(body="The original question was edited."),
    ]
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "source_changed_or_redacted"
    assert case.ai_draft_answer.startswith("AI context · ")
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "root_false",
        "root_timeout",
        "root_delivery_failed",
        "note_false",
        "note_timeout",
        "note_delivery_failed",
    ],
)
async def test_uncertain_or_partial_delivery_is_durable_and_never_retried(
    runtime_case, failure
):
    bundle = runtime_case
    if failure.endswith("timeout"):
        failed = TimeoutError("Ambiguous remote send")
    elif failure.endswith("delivery_failed"):
        failed = SendResult(False, error="staff_context_delivery_failed")
    else:
        failed = SendResult(False)
    bundle.sender.side_effect = (
        [SendResult(True, "$staff-root"), failed]
        if failure.startswith("note")
        else [failed]
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivery_uncertain"
    expected_sends = 2 if failure.startswith("note") else 1
    assert bundle.sender.await_count == expected_sends
    if expected_sends == 2:
        assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    restarted = MatrixContextRuntime(bundle.runtime)
    assert await restarted.process(bundle.incoming, bundle.channel) is False
    await restarted.drain()
    assert bundle.sender.await_count == expected_sends
    bundle.llm.invoke.assert_called_once()
    no_public_delivery(bundle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination",
    [
        None,
        "",
        "   ",
        "!missing-server",
        "@user:example.org",
        "!bad room:example.org",
        SOURCE_ROOM,
    ],
)
async def test_invalid_staff_destination_defers_before_retrieval_or_provider(
    runtime_case, destination
):
    bundle = runtime_case
    bundle.runtime.settings.MATRIX_STAFF_ROOM = destination
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert (
        case.channel_metadata["context_reason"] == "staff_context_destination_invalid"
    )
    bundle.client.room_context.assert_not_awaited()
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["root", "note"])
@pytest.mark.parametrize(
    "reason",
    [
        "matrix_channel_inactive",
        "staff_context_disabled",
        "staff_context_destination_changed",
        "staff_context_destination_invalid",
        "staff_context_content_invalid",
        "staff_context_thread_invalid",
        "matrix_client_unavailable",
    ],
)
async def test_known_staff_send_refusal_is_deferred_and_preserves_partial_root(
    runtime_case, phase, reason
):
    bundle = runtime_case
    refused = SendResult(False, error=reason)
    bundle.sender.side_effect = (
        [SendResult(True, "$staff-root"), refused] if phase == "note" else [refused]
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == reason
    assert case.ai_draft_answer.startswith("AI context · ")
    assert (
        case.channel_metadata["staff_root_transaction_id"] == f"context-{case.id}-root"
    )
    assert (
        case.channel_metadata["staff_note_transaction_id"] == f"context-{case.id}-note"
    )
    assert "staff_note_event_id" not in case.channel_metadata
    expected_sends = 2 if phase == "note" else 1
    if phase == "note":
        assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
        assert case.channel_metadata["staff_thread_url"].endswith("/$staff-root")
    else:
        assert "staff_root_event_id" not in case.channel_metadata
    restarted = MatrixContextRuntime(bundle.runtime)
    assert await restarted.process(bundle.incoming, bundle.channel) is False
    await restarted.drain()
    assert bundle.sender.await_count == expected_sends
    bundle.llm.invoke.assert_called_once()
    no_public_delivery(bundle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["missing_service", "create_failure", "reservation_failure"]
)
async def test_missing_durability_never_starts_model_or_send(
    runtime_case, monkeypatch, failure
):
    bundle = runtime_case
    if failure == "missing_service":
        bundle.services.pop("escalation_service")
        assert await bundle.engine.process(bundle.incoming, bundle.channel) is False
    else:
        error = AsyncMock(side_effect=RuntimeError("Persistence unavailable"))
        if failure == "create_failure":
            monkeypatch.setattr(bundle.service, "create_escalation", error)
        else:
            monkeypatch.setattr(ContextReviewStore, "reserve", error)
        with pytest.raises(RuntimeError, match="Persistence unavailable"):
            await bundle.engine.process(bundle.incoming, bundle.channel)
    await bundle.engine.drain()
    bundle.client.room_context.assert_not_awaited()
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_policy_revoked_after_reservation_stops_before_model(runtime_case):
    bundle = runtime_case
    assert await bundle.engine.process(bundle.incoming, bundle.channel) is False
    bundle.policy.generation_enabled = False
    await bundle.engine.drain()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "policy_changed"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_rejection_during_model_work_prevents_publication(runtime_case):
    bundle = runtime_case
    reads = 0

    async def read(*args, **kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            case = await saved_case(bundle)
            await bundle.service.close_escalation(case.id)
        return context()

    bundle.client.room_context.side_effect = read
    case = await run(bundle)
    assert case.status == EscalationStatus.CLOSED
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_shutdown_preserves_interrupted_case_without_restart_replay(runtime_case):
    bundle = runtime_case
    reading = asyncio.Event()
    never_finish = asyncio.Event()

    async def read(*args, **kwargs):
        reading.set()
        await never_finish.wait()
        return context()

    bundle.client.room_context.side_effect = read
    assert await bundle.engine.process(bundle.incoming, bundle.channel) is False
    await reading.wait()
    await bundle.engine.close()
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "delivery_uncertain"
    assert (
        case.channel_metadata["context_reason"]
        == "processing_interrupted_review_required"
    )
    restarted = MatrixContextRuntime(bundle.runtime)
    assert await restarted.process(bundle.incoming, bundle.channel) is False
    await restarted.drain()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_identity_is_scoped_by_room_and_event(runtime_case):
    bundle = runtime_case
    other_room = "!other-support:example.org"
    bundle.runtime.settings.MATRIX_CONTEXT_SOURCE_ROOMS.append(other_room)
    bundle.sender.side_effect = lambda *a, **kw: SendResult(
        True, "$" + kw["transaction_id"]
    )
    await run(bundle)
    incoming = bundle.incoming.model_copy(
        update={"channel_metadata": {"room_id": other_room}}
    )
    assert await bundle.engine.process(incoming, bundle.channel) is False
    await bundle.engine.drain()
    rows, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2 and len({case.message_id for case in rows}) == 2
    assert {case.channel_metadata["room_id"] for case in rows} == {
        SOURCE_ROOM,
        other_room,
    }
    assert bundle.llm.invoke.call_count == 2 and bundle.sender.await_count == 4


@pytest.mark.asyncio
async def test_concurrent_runtime_instances_claim_one_generation_and_send(runtime_case):
    bundle = runtime_case
    other = MatrixContextRuntime(bundle.runtime)
    results = await asyncio.gather(
        bundle.engine.process(bundle.incoming, bundle.channel),
        other.process(bundle.incoming, bundle.channel),
    )
    assert results == [False, False]
    await asyncio.gather(bundle.engine.drain(), other.drain())
    case = await saved_case(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2


@pytest.mark.asyncio
async def test_trusted_high_risk_classification_defers_before_retrieval(runtime_case):
    from app.channels.models import ClassificationDecision

    bundle = runtime_case
    bundle.incoming.classification = ClassificationDecision(topic_risk="high")
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "needs_human"
    assert case.channel_metadata["context_reason"] == "high_risk_action"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_removed_source_during_generation_suppresses_send(runtime_case):
    bundle = runtime_case
    bundle.client.room_context.side_effect = [context(), NS(event=None)]
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "source_unavailable"
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_closed_runtime_accepts_no_new_work(runtime_case):
    bundle = runtime_case
    await bundle.engine.close()
    assert await bundle.engine.process(bundle.incoming, bundle.channel) is False
    await bundle.engine.drain()
    rows, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 0 and rows == []
    bundle.client.room_context.assert_not_awaited()
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_reopened_runtime_processes_new_event_without_retrying_interruption(
    runtime_case,
):
    bundle = runtime_case
    reading = asyncio.Event()

    async def interrupted_read(*args, **kwargs):
        reading.set()
        await asyncio.Event().wait()

    bundle.client.room_context.side_effect = interrupted_read
    await bundle.engine.process(bundle.incoming, bundle.channel)
    await reading.wait()
    await bundle.engine.close()
    interrupted = await saved_case(bundle)

    bundle.engine.start()
    await bundle.engine.process(bundle.incoming, bundle.channel)
    await bundle.engine.drain()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()

    def next_context(_room, event_id, **kwargs):
        response = context()
        response.event.event_id = event_id
        return response

    bundle.client.room_context.side_effect = next_context
    new_event = bundle.incoming.model_copy(update={"message_id": "$next"})
    await bundle.engine.process(new_event, bundle.channel)
    await bundle.engine.drain()
    rows, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == 2
    old = next(row for row in rows if row.id == interrupted.id)
    new = next(row for row in rows if row.id != interrupted.id)
    assert old.channel_metadata["context_status"] == "delivery_uncertain"
    assert new.channel_metadata["context_status"] == "delivered"
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_reopen_rejects_workers_still_shutting_down(runtime_case):
    bundle = runtime_case
    started = asyncio.Event()
    stopping = asyncio.Event()
    allow_stop = asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            stopping.set()
            await allow_stop.wait()
            raise

    task = asyncio.create_task(worker())
    bundle.engine._tasks.add(task)
    await started.wait()
    close = asyncio.create_task(bundle.engine.close())
    await stopping.wait()
    with pytest.raises(RuntimeError, match="not finished stopping"):
        bundle.engine.start()
    allow_stop.set()
    await close
    bundle.engine.start()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_nearest_staff_event_defers_generation_in_reverse_context(runtime_case):
    bundle = runtime_case
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    before = [
        NS(
            sender="@staff:example.org" if i == 0 else "@user:example.org",
            body=f"Earlier message {i}",
            server_timestamp=now_ms - 1000 * (i + 1),
            source={},
        )
        for i in range(20)
    ]
    response = context()
    response.events_before = before
    bundle.client.room_context.side_effect = None
    bundle.client.room_context.return_value = response
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "staff_active"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_unassociated_room_history_is_not_incident_evidence(runtime_case):
    bundle = runtime_case
    before = [
        NS(sender="@user:example.org", body=f"Earlier message {i}", source={})
        for i in range(12)
    ]
    response = context(
        after=[NS(sender="@user:example.org", body="Later message", source={})]
    )
    response.events_before = before
    bundle.client.room_context.side_effect = None
    bundle.client.room_context.return_value = response
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert messages == []


@pytest.mark.asyncio
async def test_source_context_timeout_remains_durable_without_model_or_delivery(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    cancelled = asyncio.Event()

    async def read_forever(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(bundle.engine, "CONTEXT_READ_TIMEOUT_SECONDS", 0.01)
    bundle.client.room_context.side_effect = read_forever
    case = await run(bundle)
    assert cancelled.is_set()
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "source_context_timeout"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    no_public_delivery(bundle)
