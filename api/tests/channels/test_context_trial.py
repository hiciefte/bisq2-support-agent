"""Offline admission, expiry and accounting tests for bounded staff trials."""

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist import context_trial
from app.channels.staff_assist.context_runtime import (
    ContextReviewStore,
    MatrixContextRuntime,
)
from app.channels.staff_assist.context_trial import ContextTrial, ContextTrialStore

from tests.channels.test_context_runtime_integration import (
    SOURCE_ROOM,
    STAFF_ROOM,
    context,
    run,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as existing_runtime_case,
)
from tests.channels.test_context_runtime_integration import (
    saved_case,
)

pytestmark = pytest.mark.unit


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in existing_runtime_case.__wrapped__(tmp_path):
        yield bundle


def trial_settings(**changes):
    now = datetime.now(timezone.utc)
    values = dict(
        MATRIX_CONTEXT_TRIAL_ID="staff-trial-1",
        MATRIX_CONTEXT_TRIAL_START_AT=(now - timedelta(minutes=1)).isoformat(),
        MATRIX_CONTEXT_TRIAL_END_AT=(now + timedelta(hours=1)).isoformat(),
        MATRIX_CONTEXT_TRIAL_MAX_CASES=10,
        MATRIX_CONTEXT_SOURCE_ROOMS=[SOURCE_ROOM],
        MATRIX_STAFF_ROOM=STAFF_ROOM,
    )
    values.update(changes)
    return NS(**values)


def enable_trial(bundle, **changes):
    settings = trial_settings(**changes)
    for key, value in vars(settings).items():
        setattr(bundle.runtime.settings, key, value)
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    return bundle.engine._trial


@pytest.mark.parametrize(
    "changes",
    [
        {"MATRIX_CONTEXT_TRIAL_ID": ""},
        {"MATRIX_CONTEXT_TRIAL_ID": "unsafe/id"},
        {"MATRIX_CONTEXT_TRIAL_START_AT": "2026-01-01T00:00:00"},
        {"MATRIX_CONTEXT_TRIAL_END_AT": "invalid"},
        {"MATRIX_CONTEXT_TRIAL_END_AT": "2030-01-01T00:00:00Z"},
        {"MATRIX_CONTEXT_TRIAL_MAX_CASES": 11},
        {"MATRIX_CONTEXT_TRIAL_MAX_CASES": 0},
        {"MATRIX_CONTEXT_SOURCE_ROOMS": []},
        {"MATRIX_STAFF_ROOM": SOURCE_ROOM},
    ],
)
def test_trial_settings_reject_unbounded_or_ambiguous_descriptors(changes):
    with pytest.raises(ValueError):
        ContextTrial.from_settings(trial_settings(**changes))


def test_no_trial_preserves_existing_settings():
    assert ContextTrial.from_settings(NS()) is None


def test_settings_model_validates_trial_configuration(tmp_path):
    from app.core.config import Settings

    values = vars(trial_settings())
    settings = Settings(DATA_DIR=str(tmp_path), _env_file=None, **values)
    assert settings.MATRIX_CONTEXT_TRIAL_MAX_CASES == 10
    values["MATRIX_CONTEXT_TRIAL_MAX_CASES"] = 11
    with pytest.raises(ValueError, match="between 1 and 10"):
        Settings(DATA_DIR=str(tmp_path), _env_file=None, **values)


@pytest.mark.asyncio
async def test_concurrent_reservations_and_restart_cannot_replenish_cap(tmp_path):
    trial = ContextTrial.from_settings(trial_settings())
    store = ContextTrialStore(str(tmp_path / "trial.db"), trial)
    results = await asyncio.gather(*(store.reserve(case_id) for case_id in range(30)))
    assert results.count(None) == 10
    assert results.count("context_trial_capacity_reached") == 20
    restarted = ContextTrialStore(store.db_path, trial)
    assert await restarted.reserve(100) == "context_trial_capacity_reached"
    admitted = results.index(None)
    assert await restarted.reserve(admitted) == "context_trial_case_already_reserved"
    assert await restarted.check(admitted) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("staff_room", "!other:example.org"),
        ("source_rooms", ("!other:example.org",)),
        ("max_cases", 9),
        ("start_at", datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ("end_at", datetime(2030, 1, 1, tzinfo=timezone.utc)),
    ],
)
async def test_restart_rejects_changed_trial_descriptor(tmp_path, field, value):
    trial = ContextTrial.from_settings(trial_settings())
    store = ContextTrialStore(str(tmp_path / "trial.db"), trial)
    assert await store.check() is None
    changed = ContextTrialStore(store.db_path, replace(trial, **{field: value}))
    assert await changed.reserve(1) == "context_trial_configuration_changed"


@pytest.mark.asyncio
async def test_time_boundaries_before_admission_and_publication(tmp_path, monkeypatch):
    trial = ContextTrial.from_settings(trial_settings())
    store = ContextTrialStore(str(tmp_path / "trial.db"), trial)
    monkeypatch.setattr(
        context_trial, "utc_now", lambda: trial.start_at - timedelta(microseconds=1)
    )
    assert await store.reserve(1) == "context_trial_not_started"
    monkeypatch.setattr(context_trial, "utc_now", lambda: trial.start_at)
    assert await store.reserve(1) is None
    monkeypatch.setattr(context_trial, "utc_now", lambda: trial.end_at)
    assert await store.check(1) == "context_trial_expired"
    assert await store.reserve(2) == "context_trial_expired"


@pytest.mark.asyncio
async def test_before_activation_source_is_reviewable_without_paid_work(runtime_case):
    bundle = runtime_case
    trial = enable_trial(bundle)
    snapshot = context()
    snapshot.event.server_timestamp = int(
        (trial.start_at - timedelta(seconds=1)).timestamp() * 1000
    )
    bundle.client.room_context.return_value = snapshot
    bundle.client.room_context.side_effect = None
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_before_activation"
    assert case.channel_metadata["model_called"] is False
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_expiry_after_retrieval_prevents_model(runtime_case, monkeypatch):
    bundle = runtime_case
    trial = enable_trial(bundle)
    original = bundle.rag._run_retriever_call.side_effect

    async def retrieval(*args, **kwargs):
        result = await original(*args, **kwargs)
        monkeypatch.setattr(context_trial, "utc_now", lambda: trial.end_at)
        return result

    bundle.rag._run_retriever_call.side_effect = retrieval
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_expired"
    assert case.channel_metadata["model_called"] is False
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_retrieval_cannot_start_after_expiry(runtime_case, monkeypatch):
    bundle = runtime_case
    trial = enable_trial(bundle)

    async def delayed_retrieval(_retriever, method, *args):
        monkeypatch.setattr(context_trial, "utc_now", lambda: trial.end_at)
        return method(*args)

    bundle.rag._run_retriever_call.side_effect = delayed_retrieval
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_expired"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_generation_cannot_start_after_expiry(runtime_case, monkeypatch):
    bundle = runtime_case
    trial = enable_trial(bundle)

    async def delayed_thread(method, *args):
        monkeypatch.setattr(context_trial, "utc_now", lambda: trial.end_at)
        return method(*args)

    monkeypatch.setattr(asyncio, "to_thread", delayed_thread)
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_expired"
    assert case.channel_metadata["model_called"] is False
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,sends", [("staff_root_reserved", 0), ("staff_note_reserved", 1)]
)
async def test_expiry_before_each_send_keeps_exact_ledger(
    runtime_case, monkeypatch, stage, sends
):
    bundle = runtime_case
    trial = enable_trial(bundle)
    update = ContextReviewStore.update

    async def expire_after_reservation(store, case_id, **kwargs):
        await update(store, case_id, **kwargs)
        if kwargs.get("reason") == stage:
            monkeypatch.setattr(context_trial, "utc_now", lambda: trial.end_at)

    monkeypatch.setattr(ContextReviewStore, "update", expire_after_reservation)
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_expired"
    assert case.channel_metadata["context_status"] == "deferred"
    assert bundle.sender.await_count == sends
    assert bool(case.channel_metadata.get("staff_root_event_id")) == bool(sends)


@pytest.mark.asyncio
async def test_silence_keeps_usage_and_spends_trial_reservation(runtime_case):
    bundle = runtime_case
    trial = enable_trial(bundle, MATRIX_CONTEXT_TRIAL_MAX_CASES=1)
    bundle.llm.invoke.return_value = NS(
        content=json.dumps(
            dict(action="silence", text="", source_ids=[], reason="adds_no_evidence")
        ),
        usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    )
    case = await run(bundle)
    metadata = case.channel_metadata
    assert metadata["model_called"] is True
    assert metadata["model_decision"]["action"] == "silence"
    assert metadata["model_usage"]["total_tokens"] == 20
    bundle.sender.assert_not_awaited()
    store = ContextTrialStore(bundle.repository.db_path, trial)
    assert await store.reserve(999) == "context_trial_capacity_reached"


@pytest.mark.asyncio
async def test_provider_failure_keeps_unknown_usage_and_spent_reservation(runtime_case):
    bundle = runtime_case
    trial = enable_trial(bundle, MATRIX_CONTEXT_TRIAL_MAX_CASES=1)
    bundle.llm.invoke.side_effect = TimeoutError("provider result unavailable")
    case = await run(bundle)
    assert case.channel_metadata["model_called"] is True
    assert case.channel_metadata["model_call_status"] == "outcome_unknown"
    assert case.channel_metadata["model_usage"] is None
    assert (
        await ContextTrialStore(bundle.repository.db_path, trial).reserve(999)
        == "context_trial_capacity_reached"
    )
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_trial_delivery_requires_reserved_case(runtime_case):
    bundle = runtime_case
    enable_trial(bundle)
    assert (
        await bundle.engine.check_trial_delivery("arbitrary")
        == "context_trial_case_not_reserved"
    )
    assert (
        await bundle.engine.check_trial_delivery("context-999-root")
        == "context_trial_case_not_reserved"
    )


@pytest.mark.asyncio
async def test_expiry_task_disables_policy_and_closes_pending_workers(runtime_case):
    bundle = runtime_case
    now = datetime.now(timezone.utc)
    enable_trial(
        bundle,
        MATRIX_CONTEXT_TRIAL_END_AT=(now + timedelta(milliseconds=100)).isoformat(),
    )
    policy = bundle.services["channel_autoresponse_policy_service"]
    policy.set_policy = Mock()
    bundle.policy.first_response_delay_seconds = 10
    await bundle.engine.process(bundle.incoming, bundle.channel)
    await asyncio.wait_for(bundle.engine._expiry_task, timeout=2)
    policy.set_policy.assert_called_once_with(
        "matrix", generation_enabled=False, enabled=False
    )
    assert bundle.engine._closed
    case = await saved_case(bundle)
    assert (
        case.channel_metadata["context_reason"]
        == "processing_interrupted_review_required"
    )
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy_off", "case_closed"])
async def test_live_read_policy_or_review_change_prevents_generation(
    runtime_case, change
):
    bundle = runtime_case
    trial = enable_trial(bundle, MATRIX_CONTEXT_TRIAL_MAX_CASES=1)
    bundle.incoming.question = "What is the current BTC price in EUR?"
    bundle.client.room_context.side_effect = lambda *a, **kw: context(
        body=bundle.incoming.question
    )
    calls = []

    async def prices(**kwargs):
        calls.append(kwargs)
        if change == "policy_off":
            bundle.policy.generation_enabled = False
        else:
            case = await saved_case(bundle)
            await bundle.service.close_escalation(case.id)
        return {"success": True, "prices": {"EUR": 1}, "timestamp": "synthetic"}

    bundle.rag.mcp_enabled = True
    bundle.rag.bisq_mcp_service = NS(get_market_prices=prices)
    case = await run(bundle)
    assert len(calls) == 1
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "review_or_policy_changed"
    assert case.channel_metadata["model_called"] is False
    assert case.channel_metadata["model_call_status"] == "not_started"
    if change == "case_closed":
        assert case.status.value == "closed"
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    assert (
        await ContextTrialStore(bundle.repository.db_path, trial).reserve(999)
        == "context_trial_capacity_reached"
    )


@pytest.mark.asyncio
async def test_queued_generation_rechecks_policy_before_model(
    runtime_case, monkeypatch
):
    bundle = runtime_case
    trial = enable_trial(bundle, MATRIX_CONTEXT_TRIAL_MAX_CASES=1)

    async def delayed_thread(method, *args):
        bundle.policy.generation_enabled = False
        return method(*args)

    monkeypatch.setattr(asyncio, "to_thread", delayed_thread)
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "review_or_policy_changed"
    assert case.channel_metadata["model_called"] is False
    assert case.channel_metadata["model_call_status"] == "not_started"
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    assert (
        await ContextTrialStore(bundle.repository.db_path, trial).reserve(999)
        == "context_trial_capacity_reached"
    )
