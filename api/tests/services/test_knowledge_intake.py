"""Offline integration regressions for durable, wiki-first knowledge intake."""

import json
import sqlite3
from contextlib import closing
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
from app.channels.plugins.matrix.client.polling_state import PollingStateManager
from app.services.knowledge.candidate_repository import KnowledgeExtractionHeldError
from app.services.knowledge.ingest.bisq2_sync_service import Bisq2SyncService
from app.services.knowledge.ingest.matrix_sync_service import (
    IncompleteKnowledgeContextError,
    MatrixSyncService,
)
from app.services.knowledge.knowledge_extractor import KnowledgeExtractor
from app.services.knowledge.knowledge_pipeline_service import (
    KnowledgeExtractionError,
    KnowledgePipelineService,
)
from nio import MessageDirection, RoomContextResponse

QUESTION = "Do buyers need reputation in Bisq Easy?"
ANSWER = "Buyers can buy BTC in Bisq Easy without reputation. Seller reputation is the safety signal."
ROOM = "!support:test"
STAFF = "@staff:test"


def event(event_id, sender, text, timestamp=1, reply=None):
    content = {"body": text, "msgtype": "m.text"}
    if reply:
        content["m.relates_to"] = {"m.in_reply_to": {"event_id": reply}}
    return {
        "type": "m.room.message",
        "event_id": event_id,
        "sender": sender,
        "origin_server_ts": timestamp,
        "content": content,
    }


def nio_event(value):
    return SimpleNamespace(source=value, event_id=value["event_id"])


def extraction_result(answer_id="$answer:test", question_id="$question:test"):
    return {
        "faq_pairs": [
            {
                "question_text": QUESTION,
                "answer_text": ANSWER,
                "question_msg_id": question_id,
                "answer_msg_id": answer_id,
                "original_question_text": QUESTION,
                "original_answer_text": ANSWER,
                "confidence": 0.95,
                "has_correction": False,
                "category": "Trading",
            }
        ]
    }


@pytest.fixture
def pipeline(tmp_path):
    settings = SimpleNamespace(
        LLM_WIKI_DIR_PATH=str(tmp_path / "wiki"),
        OPENAI_MODEL="test-model",
        LLM_TEMPERATURE=0,
        MAX_TOKENS=100,
        TRUSTED_STAFF_IDS=[STAFF],
    )
    return KnowledgePipelineService(
        settings=settings,
        rag_service=SimpleNamespace(query=AsyncMock()),
        faq_service=MagicMock(),
        db_path=str(tmp_path / "candidates.db"),
        aisuite_client=MagicMock(),
    )


@pytest.fixture
def qa():
    return [
        event("$question:test", "@user:test", QUESTION),
        event("$answer:test", STAFF, ANSWER, 2, "$question:test"),
    ]


@pytest.mark.asyncio
async def test_default_intake_persists_without_answer_generation(pipeline, qa):
    with patch.object(
        KnowledgeExtractor, "_call_llm", AsyncMock(return_value=extraction_result())
    ):
        results = await pipeline.extract_faqs_batch(
            qa,
            "matrix",
            [STAFF],
            source_scope=ROOM,
            eligible_answer_ids={"$answer:test"},
        )
    saved = pipeline.repository.get_by_id(results[0].candidate_id)
    assert saved.staff_answer == ANSWER
    assert saved.original_user_question == QUESTION
    assert saved.generated_answer is None
    assert saved.final_score is None
    assert saved.generation_confidence is None
    assert not saved.is_calibration_sample
    pipeline.rag_service.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_comparison_failure_keeps_candidate_and_blocks_automatic_retry(
    pipeline, qa
):
    pipeline.rag_service.query.return_value = {
        "answer": "Generated baseline",
        "confidence": 0.7,
    }
    pipeline._compare_answers = AsyncMock(
        side_effect=TimeoutError("private failure text")
    )
    extract = AsyncMock(return_value=extraction_result())
    with patch.object(KnowledgeExtractor, "_call_llm", extract):
        with pytest.raises(KnowledgeExtractionError):
            await pipeline.extract_faqs_batch(
                qa, "matrix", [STAFF], source_scope=ROOM, compare_answers=True
            )
        with pytest.raises(KnowledgeExtractionHeldError):
            await pipeline.extract_faqs_batch(
                [*qa, event("$later:test", STAFF, "More information")],
                "matrix",
                [STAFF],
                source_scope=ROOM,
            )
    assert pipeline.repository.count_pending() == 1
    assert pipeline.repository.get_pending()[0].staff_answer == ANSWER
    assert extract.await_count == 1
    assert pipeline.rag_service.query.await_count == 1
    with closing(sqlite3.connect(pipeline.repository.db_path)) as conn:
        assert (
            conn.execute("SELECT state FROM knowledge_extraction_attempts").fetchone()[
                0
            ]
            == "uncertain"
        )
        assert (
            conn.execute(
                "SELECT candidate_ids FROM knowledge_extraction_attempts"
            ).fetchone()[0]
            == "[1]"
        )
        receipt = str(
            conn.execute("SELECT * FROM knowledge_extraction_attempts").fetchone()
        )
        assert QUESTION not in receipt and "$question:test" not in receipt


@pytest.mark.asyncio
async def test_context_only_answer_cannot_create_candidate(pipeline, qa):
    with patch.object(
        KnowledgeExtractor, "_call_llm", AsyncMock(return_value=extraction_result())
    ):
        results = await pipeline.extract_faqs_batch(
            qa,
            "matrix",
            [STAFF],
            source_scope=ROOM,
            eligible_answer_ids={"$question:test"},
        )
    assert results == []
    assert pipeline.repository.count_pending() == 0


@pytest.mark.asyncio
async def test_successful_empty_extraction_is_not_repeated(pipeline, qa):
    extract = AsyncMock(return_value={"faq_pairs": []})
    with patch.object(KnowledgeExtractor, "_call_llm", extract):
        assert (
            await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
            == []
        )
        qa[0]["unsigned"] = {"age": 999}
        assert (
            await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
            == []
        )
    assert extract.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result", [TimeoutError("provider timeout"), "", "invalid-json", "{}"]
)
async def test_provider_failure_is_not_an_empty_success_or_retried(
    pipeline, qa, result
):
    client = MagicMock()
    client.is_fallback = False
    if isinstance(result, Exception):
        client.chat.completions.create.side_effect = result
    else:
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=result))]
        )
    pipeline.aisuite_client = client
    with pytest.raises(KnowledgeExtractionError):
        await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
    with pytest.raises(KnowledgeExtractionHeldError):
        await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
    assert client.chat.completions.create.call_count == 1


class Page:
    def __init__(self, messages, end):
        self.chunk = [nio_event(message) for message in messages]
        self.end = end
        self.start = "head-" + end


@pytest.fixture
def matrix_sync(pipeline, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge.ingest.matrix_sync_service.RoomMessagesResponse", Page
    )
    state = PollingStateManager(str(tmp_path / "matrix-state.json"))
    sync = MatrixSyncService(pipeline.settings, pipeline, state)
    sync._error_handler = SimpleNamespace(call_with_retry=AsyncMock())
    return sync


@pytest.mark.asyncio
async def test_matrix_cross_page_answer_uses_native_context(pipeline, matrix_sync, qa):
    client = SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock())
    context = RoomContextResponse(ROOM, None, None, nio_event(qa[0]), [], [], [])
    matrix_sync._error_handler.call_with_retry.side_effect = [
        Page([qa[0]], "cursor-one"),
        Page([qa[1]], "cursor-two"),
        context,
    ]
    extract = AsyncMock(return_value=extraction_result())
    with patch.object(KnowledgeExtractor, "_call_llm", extract):
        assert await matrix_sync._sync_single_room(client, ROOM) == 0
        assert extract.await_count == 0
        assert matrix_sync.polling_state.get_room_token(ROOM) == "head-cursor-one"
        initial_call = matrix_sync._error_handler.call_with_retry.call_args
        assert initial_call.kwargs["direction"] == MessageDirection.back
        assert await matrix_sync._sync_single_room(client, ROOM) == 1
        forward_call = matrix_sync._error_handler.call_with_retry.call_args_list[1]
        assert forward_call.kwargs["direction"] == MessageDirection.front
        assert forward_call.kwargs["start"] == "head-cursor-one"
    assert QUESTION in extract.call_args.kwargs["messages_text"]
    assert matrix_sync.polling_state.get_room_token(ROOM) == "cursor-two"
    assert matrix_sync.polling_state.is_processed("$answer:test")
    context_call = matrix_sync._error_handler.call_with_retry.call_args
    assert context_call.args[1:3] == (ROOM, "$question:test")
    assert context_call.kwargs["limit"] == 20
    pipeline.rag_service.query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_room", [False, True])
async def test_matrix_context_failure_retains_cursor_and_input(
    matrix_sync, qa, wrong_room
):
    client = SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock())
    context = (
        RoomContextResponse("!other:test", None, None, nio_event(qa[0]), [], [], [])
        if wrong_room
        else SimpleNamespace(error="unavailable")
    )
    matrix_sync._error_handler.call_with_retry.side_effect = [
        Page([qa[1]], "next"),
        context,
    ]
    with pytest.raises(IncompleteKnowledgeContextError):
        await matrix_sync._sync_single_room(client, ROOM)
    assert matrix_sync.polling_state.get_room_token(ROOM) is None
    assert not matrix_sync.polling_state.is_processed("$answer:test")


@pytest.mark.asyncio
async def test_matrix_extraction_failure_never_consumes_events(
    pipeline, matrix_sync, qa
):
    client = SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock())
    matrix_sync._error_handler.call_with_retry.return_value = Page(qa, "next")
    with patch.object(
        KnowledgeExtractor, "_call_llm", AsyncMock(side_effect=TimeoutError())
    ):
        with pytest.raises(KnowledgeExtractionError):
            await matrix_sync._sync_single_room(client, ROOM)
    assert matrix_sync.polling_state.get_room_token(ROOM) is None
    assert not matrix_sync.polling_state.is_processed("$question:test")
    assert not matrix_sync.polling_state.is_processed("$answer:test")


@pytest.mark.asyncio
async def test_bisq_cross_batch_question_is_context_only_with_bounded_lookback(
    pipeline, tmp_path
):
    settings = pipeline.settings
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-a"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["user", "staff"]
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_STAFF_PROFILE_IDS = ["staff"]
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
    state = BisqSyncStateManager(str(tmp_path / "bisq-state.json"))
    question = {
        "messageId": "question-original",
        "message": QUESTION,
        "author": "user",
        "senderUserProfileId": "user",
        "channelId": "channel-a",
        "date": "2026-09-25T10:00:00Z",
    }
    answer = {
        "messageId": "answer-original",
        "message": ANSWER,
        "author": "staff",
        "senderUserProfileId": "staff",
        "channelId": "channel-a",
        "date": "2026-09-25T10:01:00Z",
    }
    api = SimpleNamespace(
        export_chat_messages=AsyncMock(
            side_effect=[{"messages": [question]}, {"messages": [question, answer]}]
        )
    )
    sync = Bisq2SyncService(settings, pipeline, api, state)
    extract = AsyncMock(
        return_value=extraction_result("answer-original", "question-original")
    )
    with patch.object(KnowledgeExtractor, "_call_llm", extract):
        assert await sync.sync_conversations() == 0
        last_sync = state.last_sync_timestamp
        assert await sync.sync_conversations() == 1
    assert api.export_chat_messages.call_args.kwargs["since"] == last_sync - timedelta(
        hours=1
    )
    assert extract.await_count == 1
    candidate = pipeline.repository.get_pending()[0]
    assert candidate.source_event_id == "bisq2:channel-a:answer-original"
    assert candidate.original_user_question == QUESTION


def test_attempt_guard_is_durable_and_success_can_be_reconciled(pipeline):
    repo = pipeline.repository
    assert (
        repo.begin_knowledge_extraction(
            source="matrix", scope_digest="a", input_digest="one"
        )
        is None
    )
    with pytest.raises(KnowledgeExtractionHeldError):
        repo.begin_knowledge_extraction(
            source="matrix", scope_digest="a", input_digest="two"
        )
    repo.finish_knowledge_extraction("one", candidate_ids=[], succeeded=True)
    assert (
        repo.begin_knowledge_extraction(
            source="matrix", scope_digest="a", input_digest="one"
        )
        == []
    )


@pytest.mark.asyncio
async def test_already_reviewed_source_evidence_never_generates_another_baseline(
    pipeline,
):
    candidate = pipeline.repository.create(
        source="matrix",
        source_event_id="$answer:test",
        source_timestamp="2026-09-25T10:00:00Z",
        question_text=QUESTION,
        staff_answer=ANSWER,
        is_calibration_sample=False,
    )
    pipeline.repository.approve_pending(candidate.id, "reviewer", "llm_wiki:reputation")
    result = await pipeline._process_extracted_faq(
        QUESTION,
        ANSWER,
        "matrix",
        "$answer:test",
        compare_answer=True,
    )
    assert result.skipped_reason == "duplicate"
    pipeline.rag_service.query.assert_not_awaited()
    assert pipeline.repository.get_by_id(candidate.id).faq_id == "llm_wiki:reputation"


@pytest.mark.asyncio
async def test_lexical_wiki_similarity_does_not_auto_approve_staff_claim(
    pipeline, tmp_path
):
    root = tmp_path / "wiki"
    root.mkdir()
    (root / "reputation.md").write_text(
        "---\nid: reputation\ntitle: Bisq Easy reputation\ntype: llm_wiki\n"
        "page_type: support_playbook\nstatus: reviewed\nprotocol: bisq_easy\n"
        "reviewed_by: reviewer\nreviewed_at: '2026-09-25'\nrisk_level: low\n"
        "source_refs:\n  - wiki:Reputation\n---\n## Canonical Support Answer\n\n"
        + ANSWER
        + "\n\n## Applies When\n\n"
        + QUESTION,
        encoding="utf-8",
    )
    result = await pipeline._process_extracted_faq(
        QUESTION, ANSWER, "matrix", "$novel:test"
    )
    candidate = pipeline.repository.get_by_id(result.candidate_id)
    assert candidate.review_status == "pending"
    assert candidate.generated_answer_sources is None
    pipeline.rag_service.query.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value",
    [
        ("confidence", "bad"),
        ("confidence", True),
        ("answer_msg_id", ""),
        ("answer_text", 123),
    ],
)
async def test_malformed_nonempty_candidate_preserves_matrix_inputs(
    pipeline, matrix_sync, qa, key, value
):
    result = extraction_result()
    result["faq_pairs"][0][key] = value
    client = MagicMock()
    client.is_fallback = False
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))]
    )
    pipeline.aisuite_client = client
    matrix_sync._error_handler.call_with_retry.return_value = Page(qa, "next")
    with pytest.raises(KnowledgeExtractionError):
        await matrix_sync._sync_single_room(
            SimpleNamespace(room_messages=AsyncMock()), ROOM
        )
    assert matrix_sync.polling_state.get_room_token(ROOM) is None
    assert not matrix_sync.polling_state.is_processed("$answer:test")
    assert client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["user_answer", "unknown_question", "duplicate_id"]
)
async def test_matrix_extracted_pair_requires_unique_trusted_source_events(
    pipeline, qa, mutation
):
    if mutation == "user_answer":
        qa[1]["sender"] = "@another-user:test"
        qa.append(event("$staff-other:test", STAFF, "Unrelated staff message", 3))
    elif mutation == "unknown_question":
        qa[0]["event_id"] = "$different-question:test"
    else:
        qa.append(dict(qa[1]))
    with patch.object(
        KnowledgeExtractor, "_call_llm", AsyncMock(return_value=extraction_result())
    ):
        results = await pipeline.extract_faqs_batch(
            qa,
            "matrix",
            [STAFF],
            source_scope=ROOM,
            eligible_answer_ids={"$answer:test"},
        )
    assert results == []
    assert pipeline.repository.count_pending() == 0
    pipeline.rag_service.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_matrix_cursor_catches_up_forward_without_reset(matrix_sync, qa):
    matrix_sync.polling_state.update_room_token(ROOM, "legacy-backward-token")
    for message in qa:
        matrix_sync.polling_state.mark_processed(message["event_id"])
    matrix_sync._error_handler.call_with_retry.side_effect = [
        Page(qa, "forward-catchup"),
        Page([], "forward-head"),
    ]
    client = SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock())
    assert await matrix_sync._sync_single_room(client, ROOM) == 0
    call = matrix_sync._error_handler.call_with_retry.call_args
    assert call.kwargs["start"] == "legacy-backward-token"
    assert call.kwargs["direction"] == MessageDirection.front
    assert matrix_sync.polling_state.get_room_token(ROOM) == "forward-catchup"
    assert await matrix_sync._sync_single_room(client, ROOM) == 0
    assert matrix_sync.polling_state.get_room_token(ROOM) == "forward-head"


@pytest.mark.asyncio
async def test_bisq_completed_channel_survives_later_channel_failure(
    pipeline, tmp_path
):
    settings = pipeline.settings
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-a", "channel-b"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["user", "staff"]
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_STAFF_PROFILE_IDS = ["staff"]
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
    state = BisqSyncStateManager(str(tmp_path / "partial-sync.json"))
    messages = [
        {
            "messageId": f"{role}-{channel}",
            "message": QUESTION if role == "question" else ANSWER,
            "author": "user" if role == "question" else "staff",
            "senderUserProfileId": "user" if role == "question" else "staff",
            "channelId": channel,
        }
        for channel in ["channel-a", "channel-b"]
        for role in ["question", "answer"]
    ]
    api = SimpleNamespace(
        export_chat_messages=AsyncMock(return_value={"messages": messages})
    )
    pipeline.extract_faqs_batch = AsyncMock(
        side_effect=[[], KnowledgeExtractionHeldError("held")]
    )
    sync = Bisq2SyncService(settings, pipeline, api, state)
    with pytest.raises(KnowledgeExtractionHeldError):
        await sync.sync_conversations()
    restored = BisqSyncStateManager(str(state.state_file))
    assert restored.is_processed("answer-channel-a")
    assert not restored.is_processed("answer-channel-b")
    assert restored.last_sync_timestamp is None
    pipeline.extract_faqs_batch.reset_mock(side_effect=True)
    pipeline.extract_faqs_batch.side_effect = KnowledgeExtractionHeldError("held")
    sync.state_manager = restored
    with pytest.raises(KnowledgeExtractionHeldError):
        await sync.sync_conversations()
    assert pipeline.extract_faqs_batch.await_count == 1
    assert pipeline.extract_faqs_batch.call_args.kwargs["source_scope"] == "channel-b"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["server_error", "read_timeout"])
async def test_openai_extraction_transport_dispatches_only_once(
    pipeline, qa, monkeypatch, failure
):
    import httpx
    import openai
    from app.services.knowledge.knowledge_extractor import (
        create_knowledge_extraction_client,
    )

    calls = []

    def send(request):
        calls.append(request)
        if failure == "read_timeout":
            raise httpx.ReadTimeout("simulated timeout", request=request)
        return httpx.Response(503, json={"error": {"message": "simulated failure"}})

    transport_client = httpx.Client(transport=httpx.MockTransport(send))
    original = openai.OpenAI
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: original(http_client=transport_client, **kwargs),
    )
    pipeline.settings.OPENAI_API_KEY = "test-only-not-a-real-key"
    pipeline.aisuite_client = create_knowledge_extraction_client(pipeline.settings)
    try:
        with pytest.raises(KnowledgeExtractionError):
            await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
        with pytest.raises(KnowledgeExtractionHeldError):
            await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
        assert len(calls) == 1
    finally:
        transport_client.close()


@pytest.mark.asyncio
async def test_unverified_provider_fails_only_intake_before_reservation(pipeline, qa):
    from app.services.knowledge.knowledge_extractor import (
        create_knowledge_extraction_client,
    )

    pipeline.settings.LLM_EXTRACTION_MODEL = "unverified:test-model"
    pipeline.settings.OPENAI_API_KEY = "test-only-not-a-real-key"
    pipeline.aisuite_client = create_knowledge_extraction_client(pipeline.settings)
    with pytest.raises(ValueError, match="verified no-retry transport"):
        await pipeline.extract_faqs_batch(qa, "matrix", [STAFF], source_scope=ROOM)
    with closing(sqlite3.connect(pipeline.repository.db_path)) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM knowledge_extraction_attempts"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_matrix_resolves_multiple_distinct_old_reply_targets(
    pipeline, matrix_sync
):
    questions = [
        event(f"$old-{i}:test", f"@user-{i}:test", QUESTION, i + 1) for i in range(2)
    ]
    answers = [
        event(f"$answer-{i}:test", STAFF, ANSWER, 100 + i, question["event_id"])
        for i, question in enumerate(questions)
    ]
    contexts = [
        RoomContextResponse(ROOM, None, None, nio_event(question), [], [], [])
        for question in questions
    ]
    matrix_sync._error_handler.call_with_retry.side_effect = [
        Page(answers, "next"),
        *contexts,
    ]
    pairs = [
        extraction_result(answer["event_id"], question["event_id"])["faq_pairs"][0]
        for question, answer in zip(questions, answers)
    ]
    with patch.object(
        KnowledgeExtractor, "_call_llm", AsyncMock(return_value={"faq_pairs": pairs})
    ) as extract:
        assert (
            await matrix_sync._sync_single_room(
                SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock()),
                ROOM,
            )
            == 2
        )
    assert extract.await_count == 1
    assert [
        call.args[2]
        for call in matrix_sync._error_handler.call_with_retry.call_args_list
        if call.kwargs["method_name"] == "room_context"
    ] == [question["event_id"] for question in questions]
    assert all(
        matrix_sync.polling_state.is_processed(answer["event_id"]) for answer in answers
    )


@pytest.mark.asyncio
async def test_matrix_too_many_reply_targets_defers_before_context_or_extraction(
    pipeline, matrix_sync
):
    answers = [
        event(f"$answer-{i}:test", STAFF, ANSWER, 100 + i, f"$old-{i}:test")
        for i in range(11)
    ]
    matrix_sync._error_handler.call_with_retry.return_value = Page(answers, "next")
    with patch.object(KnowledgeExtractor, "_call_llm", AsyncMock()) as extract:
        with pytest.raises(
            IncompleteKnowledgeContextError, match="bounded context reads"
        ):
            await matrix_sync._sync_single_room(
                SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock()),
                ROOM,
            )
    assert matrix_sync._error_handler.call_with_retry.await_count == 1
    extract.assert_not_awaited()
    assert matrix_sync.polling_state.get_room_token(ROOM) is None
    assert not any(
        matrix_sync.polling_state.is_processed(answer["event_id"]) for answer in answers
    )


def non_question_event(kind):
    if kind == "later_user":
        return event(
            "$later-user:test", "@other:test", "An unrelated later question?", 101
        )
    return {
        "event_id": "$reaction:test",
        "sender": "@other:test",
        "type": "m.reaction",
        "origin_server_ts": 101,
        "content": {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": "$question:test",
                "key": "+1",
            }
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", ["reaction", "later_user"])
@pytest.mark.parametrize("recoverable", [True, False])
async def test_matrix_requires_real_prior_question_context(
    pipeline, matrix_sync, extra, recoverable
):
    question = event("$question:test", "@user:test", QUESTION, 1)
    answer = event("$answer:test", STAFF, ANSWER, 100)
    context = RoomContextResponse(
        ROOM,
        None,
        None,
        nio_event(answer),
        [nio_event(question)] if recoverable else [],
        [],
        [],
    )
    matrix_sync._error_handler.call_with_retry.side_effect = [
        Page([answer, non_question_event(extra)], "next"),
        context,
    ]
    with patch.object(
        KnowledgeExtractor, "_call_llm", AsyncMock(return_value=extraction_result())
    ) as extract:
        if recoverable:
            assert (
                await matrix_sync._sync_single_room(
                    SimpleNamespace(
                        room_messages=AsyncMock(), room_context=AsyncMock()
                    ),
                    ROOM,
                )
                == 1
            )
            assert QUESTION in extract.call_args.kwargs["messages_text"]
            assert matrix_sync.polling_state.is_processed(answer["event_id"])
        else:
            with pytest.raises(IncompleteKnowledgeContextError, match="prior question"):
                await matrix_sync._sync_single_room(
                    SimpleNamespace(
                        room_messages=AsyncMock(), room_context=AsyncMock()
                    ),
                    ROOM,
                )
            extract.assert_not_awaited()
            assert matrix_sync.polling_state.get_room_token(ROOM) is None
            assert not matrix_sync.polling_state.is_processed(answer["event_id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reaction", "member", "image", "empty", "whitespace"])
async def test_matrix_noncontent_events_cannot_enable_paid_extraction(pipeline, kind):
    user = event("$noncontent:test", "@user:test", QUESTION)
    if kind == "reaction":
        user = non_question_event("reaction")
    elif kind == "member":
        user.update(type="m.room.member", content={"membership": "join"})
    elif kind == "image":
        user["content"]["msgtype"] = "m.image"
    else:
        user["content"]["body"] = "" if kind == "empty" else "   "
    with patch.object(KnowledgeExtractor, "_call_llm", AsyncMock()) as extract:
        assert (
            await pipeline.extract_faqs_batch(
                [user, event("$answer:test", STAFF, ANSWER, 100)],
                "matrix",
                [STAFF],
                source_scope=ROOM,
            )
            == []
        )
    extract.assert_not_awaited()


def late_bisq_sync(pipeline, tmp_path, *, cited=True):
    from datetime import datetime, timezone

    settings = pipeline.settings
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-a"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["user", "staff"]
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_STAFF_PROFILE_IDS = ["staff"]
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
    now = datetime.now(timezone.utc)
    question = {
        "messageId": "question-old",
        "message": QUESTION,
        "author": "user",
        "senderUserProfileId": "user",
        "channelId": "channel-a",
        "date": (now - timedelta(hours=2)).isoformat(),
    }
    answer = {
        "messageId": "answer-late",
        "message": ANSWER,
        "author": "staff",
        "senderUserProfileId": "staff",
        "channelId": "channel-a",
        "date": now.isoformat(),
    }
    if cited:
        answer.update(
            citationMessageId=question["messageId"], citationAuthorUserProfileId="user"
        )
    state = BisqSyncStateManager(str(tmp_path / "bisq-late.json"))
    state.mark_processed(question["messageId"])
    state.update_last_sync(now - timedelta(minutes=10))
    state.save_state()
    api = SimpleNamespace(export_chat_messages=AsyncMock())
    return Bisq2SyncService(settings, pipeline, api, state), question, answer


@pytest.mark.asyncio
@pytest.mark.parametrize("cited", [True, False])
async def test_bisq_late_answer_recovers_question_older_than_hour(
    pipeline, tmp_path, cited
):
    sync, question, answer = late_bisq_sync(pipeline, tmp_path, cited=cited)
    sync.bisq_api.export_chat_messages.side_effect = [
        {"messages": [answer]},
        {"messages": [question, answer]},
    ]
    with patch.object(
        KnowledgeExtractor,
        "_call_llm",
        AsyncMock(return_value=extraction_result("answer-late", "question-old")),
    ) as extract:
        assert await sync.sync_conversations() == 1
    assert sync.bisq_api.export_chat_messages.await_count == 2
    assert QUESTION in extract.call_args.kwargs["messages_text"]
    assert extract.await_count == 1
    assert sync.state_manager.is_processed("answer-late")
    assert pipeline.repository.get_pending()[0].original_user_question == QUESTION
    assert sync.bisq_api.export_chat_messages.call_args.kwargs["max_retries"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "oversize", "wrong_channel"])
async def test_bisq_unrecoverable_boundary_preserves_source_and_has_no_paid_attempt(
    pipeline, tmp_path, failure
):
    from app.services.knowledge.ingest.bisq2_sync_service import (
        IncompleteBisqKnowledgeContextError,
    )

    sync, question, answer = late_bisq_sync(pipeline, tmp_path)
    before = sync.state_manager.last_sync_timestamp
    history = {
        "missing": [answer],
        "oversize": [question] * 1001,
        "wrong_channel": [{**question, "channelId": "other"}, answer],
    }[failure]
    sync.bisq_api.export_chat_messages.side_effect = [
        {"messages": [answer]},
        {"messages": history},
    ]
    with patch.object(KnowledgeExtractor, "_call_llm", AsyncMock()) as extract:
        with pytest.raises(IncompleteBisqKnowledgeContextError):
            await sync.sync_conversations()
    extract.assert_not_awaited()
    restored = BisqSyncStateManager(str(sync.state_manager.state_file))
    assert not restored.is_processed("answer-late")
    assert restored.last_sync_timestamp == before
    with closing(sqlite3.connect(pipeline.repository.db_path)) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM knowledge_extraction_attempts"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.asyncio
async def test_bisq_explicit_root_survives_recent_context_limit(pipeline, tmp_path):
    from datetime import datetime

    sync, question, answer = late_bisq_sync(pipeline, tmp_path)
    answered_at = datetime.fromisoformat(answer["date"])
    newer_context = [
        {
            **question,
            "messageId": f"context-{i}",
            "message": "Other support discussion",
            "date": (answered_at - timedelta(minutes=60 - i)).isoformat(),
        }
        for i in range(51)
    ]
    sync.bisq_api.export_chat_messages.side_effect = [
        {"messages": [answer]},
        {"messages": [question, *newer_context, answer]},
    ]
    with patch.object(
        KnowledgeExtractor,
        "_call_llm",
        AsyncMock(return_value=extraction_result("answer-late", "question-old")),
    ) as extract:
        assert await sync.sync_conversations() == 1
    transcript = extract.call_args.kwargs["messages_text"]
    assert QUESTION in transcript
    assert transcript.count("[Msg #") == 53  # 52 events plus the citation marker.
    assert pipeline.repository.count_pending() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_matrix_context_provenance_changes_defer_before_paid_work(
    pipeline, matrix_sync, duplicate
):
    question = event("$question:test", "@user:test", QUESTION, 1)
    answer = event("$answer:test", STAFF, ANSWER, 100)
    if duplicate:
        matrix_sync._error_handler.call_with_retry.return_value = Page(
            [question, answer, answer], "next"
        )
    else:
        # Readback can reveal a redaction after the source snapshot. Do not keep
        # the earlier readable body merely because the newer event has no text.
        redacted = {**answer, "content": {}}
        context = RoomContextResponse(
            ROOM, None, None, nio_event(redacted), [nio_event(question)], [], []
        )
        matrix_sync._error_handler.call_with_retry.side_effect = [
            Page([answer], "next"),
            context,
        ]
    with patch.object(KnowledgeExtractor, "_call_llm", AsyncMock()) as extract:
        with pytest.raises(IncompleteKnowledgeContextError, match="provenance"):
            await matrix_sync._sync_single_room(
                SimpleNamespace(room_messages=AsyncMock(), room_context=AsyncMock()),
                ROOM,
            )
    extract.assert_not_awaited()
    assert matrix_sync.polling_state.get_room_token(ROOM) is None
