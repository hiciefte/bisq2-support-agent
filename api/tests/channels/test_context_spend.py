"""Atomic, fail-closed spend accounting without provider or Matrix calls."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist import context_trial
from app.channels.staff_assist.context_trial import (
    BudgetedContextLLM,
    ContextTrial,
    ContextTrialStore,
)
from app.services.rag.openai_responses import OpenAIResponsesLLMWrapper

from tests.channels.test_context_trial import trial_settings

pytestmark = pytest.mark.unit


def spend_trial(**changes):
    values = dict(
        MATRIX_CONTEXT_TRIAL_BUDGET_USD="0.001",
        MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="0.0006",
        MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION="1",
        MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION="2",
        OPENAI_MODEL="openai:gpt-6-astra",
        MAX_TOKENS=50,
    )
    values.update(changes)
    return ContextTrial.from_settings(trial_settings(**values))


def call(store, case_id, *, kind="note", call_id="initial", bound=100):
    return store.reserve_call(
        case_id, kind=kind, call_id=call_id, input_tokens_bound=bound
    )


def rows(store):
    with closing(sqlite3.connect(store.db_path)) as db, db:
        db.row_factory = sqlite3.Row
        return [
            dict(row) for row in db.execute("SELECT * FROM matrix_context_trial_spend")
        ]


def wrapper(store, case_id=1, **kwargs):
    llm = OpenAIResponsesLLMWrapper(
        client=NS(max_retries=0),
        model=store.trial.model,
        max_tokens=store.trial.max_output_tokens,
        reasoning_effort="low",
        mcp_url="",
        input_cost_per_token=0.000001,
        cached_input_cost_per_token=0.0000001,
        cache_write_cost_per_token=0.000001,
        output_cost_per_token=0.000002,
    )
    llm.invoke = Mock(
        return_value=NS(
            content="draft", usage={"input_tokens": 80, "output_tokens": 20}
        )
    )
    return BudgetedContextLLM(store, llm, case_id, **kwargs)


def test_30_days_and_legacy_descriptor_bytes():
    legacy = ContextTrial.from_settings(
        trial_settings(
            MATRIX_CONTEXT_TRIAL_START_AT="2026-01-01T00:00:00+00:00",
            MATRIX_CONTEXT_TRIAL_END_AT="2026-01-02T00:00:00+00:00",
        )
    )
    # Literal historical shape, independent of the dataclass field collection.
    expected = (
        '{"end_at": "2026-01-02T00:00:00+00:00", "max_cases": 10, '
        '"source_rooms": ["!support:example.org"], '
        '"staff_room": "!staff:example.org", '
        '"start_at": "2026-01-01T00:00:00+00:00", "trial_id": "staff-trial-1"}'
    )
    assert legacy.descriptor() == expected
    start = datetime.now(timezone.utc)
    assert spend_trial(
        MATRIX_CONTEXT_TRIAL_START_AT=start.isoformat(),
        MATRIX_CONTEXT_TRIAL_END_AT=(start + timedelta(days=30)).isoformat(),
    ).spend_bounded
    with pytest.raises(ValueError, match="at most 30 days"):
        spend_trial(
            MATRIX_CONTEXT_TRIAL_START_AT=start.isoformat(),
            MATRIX_CONTEXT_TRIAL_END_AT=(
                start + timedelta(days=30, microseconds=1)
            ).isoformat(),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("MATRIX_CONTEXT_TRIAL_BUDGET_USD", ""),
        ("MATRIX_CONTEXT_TRIAL_BUDGET_USD", "nan"),
        ("MATRIX_CONTEXT_TRIAL_BUDGET_USD", "-1"),
        ("MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD", "1"),
        ("MATRIX_CONTEXT_TRIAL_INPUT_USD_PER_MILLION", "0"),
        ("MATRIX_CONTEXT_TRIAL_OUTPUT_USD_PER_MILLION", "Infinity"),
        ("MAX_TOKENS", 0),
    ],
)
def test_explicit_finite_settings_required(field, value):
    with pytest.raises(ValueError):
        spend_trial(**{field: value})


@pytest.mark.asyncio
async def test_new_legacy_descriptor_cannot_enable_count_only_pilot(tmp_path):
    store = ContextTrialStore(
        str(tmp_path / "trial.db"), ContextTrial.from_settings(trial_settings())
    )
    assert await store.check() == "context_trial_budget_required"
    assert await store.reserve(1) == "context_trial_budget_required"


@pytest.mark.asyncio
async def test_atomic_daily_bound_and_restart(tmp_path, monkeypatch):
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(context_trial, "utc_now", lambda: now)
    trial = spend_trial(
        MATRIX_CONTEXT_TRIAL_START_AT=(now - timedelta(hours=1)).isoformat(),
        MATRIX_CONTEXT_TRIAL_END_AT=(now + timedelta(days=1)).isoformat(),
    )
    store = ContextTrialStore(str(tmp_path / "trial.db"), trial)
    results = await asyncio.gather(
        *(asyncio.to_thread(call, store, index) for index in range(20))
    )
    assert results.count(None) == 3
    assert results.count("context_trial_daily_budget_exhausted") == 17
    assert len(rows(store)) == 3
    restarted = ContextTrialStore(store.db_path, store.trial)
    assert call(restarted, 21) == "context_trial_daily_budget_exhausted"
    assert (
        call(restarted, rows(store)[0]["escalation_id"])
        == "context_trial_call_already_started"
    )


def test_utc_day_rollover_keeps_total_spend(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).replace(hour=23, minute=59)
    store = ContextTrialStore(
        str(tmp_path / "trial.db"),
        spend_trial(MATRIX_CONTEXT_TRIAL_END_AT=(now + timedelta(days=2)).isoformat()),
    )
    monkeypatch.setattr(context_trial, "utc_now", lambda: now)
    for index in range(3):
        assert call(store, index) is None
    assert call(store, 3) == "context_trial_daily_budget_exhausted"
    now += timedelta(days=1)
    assert call(store, 3) is None
    assert call(store, 4) is None
    assert call(store, 5) == "context_trial_budget_exhausted"


def test_unknown_usage_keeps_hold_and_settlement_is_once(tmp_path):
    store = ContextTrialStore(str(tmp_path / "trial.db"), spend_trial())
    assert call(store, 1) is None
    for usage in [
        None,
        {},
        {"input_tokens": True, "output_tokens": 1},
        {"input_tokens": 1},
    ]:
        assert not store.settle_call(1, kind="note", call_id="initial", usage=usage)
    assert rows(store)[0]["actual_nanodollars"] is None
    assert store.settle_call(
        1,
        kind="note",
        call_id="initial",
        usage={"input_tokens": 80, "output_tokens": 20},
    )
    assert rows(store)[0]["actual_nanodollars"] == 120000
    assert not store.settle_call(
        1, kind="note", call_id="initial", usage={"input_tokens": 0, "output_tokens": 0}
    )


@pytest.mark.asyncio
async def test_gate_separate_from_note_and_one_update(tmp_path):
    store = ContextTrialStore(
        str(tmp_path / "trial.db"),
        spend_trial(MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="0.001"),
    )
    assert call(store, 1, kind="gate", call_id="source-v1") is None
    assert await store.check(1) == "context_trial_case_not_reserved"
    assert call(store, 1) is None
    assert await store.check(1) is None
    assert call(store, 1, kind="update", call_id="source-v2") is None
    assert (
        call(store, 1, kind="update", call_id="source-v3")
        == "context_trial_call_already_started"
    )
    assert [row["kind"] for row in rows(store)] == ["gate", "note", "update"]


def test_changed_descriptor_or_usage_overrun_halts_new_calls(tmp_path):
    store = ContextTrialStore(str(tmp_path / "trial.db"), spend_trial())
    assert call(store, 1) is None
    changed = ContextTrialStore(
        store.db_path, replace(store.trial, budget_nanodollars=10000000)
    )
    assert call(changed, 2) == "context_trial_configuration_changed"
    assert not store.settle_call(
        1,
        kind="note",
        call_id="initial",
        usage={"input_tokens": 200, "output_tokens": 100},
    )
    assert rows(store)[0]["status"] == "overrun"
    assert rows(store)[0]["actual_nanodollars"] == 400000
    assert call(store, 2) == "context_trial_usage_bound_violated"


def test_only_invoke_spends_and_timeout_is_not_refunded(tmp_path):
    store = ContextTrialStore(
        str(tmp_path / "trial.db"),
        spend_trial(
            MATRIX_CONTEXT_TRIAL_BUDGET_USD="1",
            MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="1",
        ),
    )
    adapter = wrapper(store)
    with closing(sqlite3.connect(store.db_path)) as db, db:
        assert (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='matrix_context_trial_spend'"
            ).fetchone()
            is None
        )
    adapter.llm.invoke.side_effect = TimeoutError("unknown result")
    with pytest.raises(TimeoutError):
        adapter.invoke("request", system_content="system")
    assert adapter.started
    assert rows(store)[0]["actual_nanodollars"] is None
    with pytest.raises(RuntimeError, match="already_started"):
        adapter.invoke("request", system_content="system")
    adapter.llm.invoke.assert_called_once()


@pytest.mark.parametrize("change", ["retry", "rate", "limit", "model"])
def test_unbounded_or_changed_adapter_never_spends(tmp_path, change):
    adapter = wrapper(ContextTrialStore(str(tmp_path / "trial.db"), spend_trial()))
    if change == "retry":
        adapter.llm.client.max_retries = 1
    elif change == "rate":
        adapter.llm.write_rate = 1
    elif change == "limit":
        adapter.llm.max_tokens += 1
    else:
        adapter.llm.model_id = "openai:another-model"
    with pytest.raises(RuntimeError, match="unbounded_model"):
        adapter.invoke("request")
    assert not adapter.started
    adapter.llm.invoke.assert_not_called()


def test_cutoff_during_admission_is_zero_charge(tmp_path, monkeypatch):
    store = ContextTrialStore(
        str(tmp_path / "trial.db"),
        spend_trial(
            MATRIX_CONTEXT_TRIAL_BUDGET_USD="1",
            MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="1",
        ),
    )
    reserve = store.reserve_call

    def cross_cutoff(*args, **kwargs):
        result = reserve(*args, **kwargs)
        monkeypatch.setattr(context_trial, "utc_now", lambda: store.trial.end_at)
        return result

    monkeypatch.setattr(store, "reserve_call", cross_cutoff)
    adapter = wrapper(store)
    with pytest.raises(RuntimeError, match="expired"):
        adapter.invoke("request")
    assert not adapter.started
    assert rows(store)[0]["status"] == "not_started"
    assert rows(store)[0]["actual_nanodollars"] == 0
    adapter.llm.invoke.assert_not_called()


def test_utc_midnight_during_admission_is_zero_charge(tmp_path, monkeypatch):
    before = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59)
    store = ContextTrialStore(
        str(tmp_path / "trial.db"),
        spend_trial(
            MATRIX_CONTEXT_TRIAL_START_AT=(before - timedelta(hours=1)).isoformat(),
            MATRIX_CONTEXT_TRIAL_END_AT=(before + timedelta(days=1)).isoformat(),
            MATRIX_CONTEXT_TRIAL_BUDGET_USD="1",
            MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="1",
        ),
    )
    monkeypatch.setattr(context_trial, "utc_now", lambda: before)
    reserve = store.reserve_call

    def cross_midnight(*args, **kwargs):
        result = reserve(*args, **kwargs)
        monkeypatch.setattr(
            context_trial, "utc_now", lambda: before + timedelta(seconds=2)
        )
        return result

    monkeypatch.setattr(store, "reserve_call", cross_midnight)
    adapter = wrapper(store)
    with pytest.raises(RuntimeError, match="day_changed"):
        adapter.invoke("request")
    assert not adapter.started
    assert rows(store)[0]["status"] == "not_started"
    assert rows(store)[0]["actual_nanodollars"] == 0
    adapter.llm.invoke.assert_not_called()


@pytest.fixture
async def runtime_case(tmp_path):
    from tests.channels.test_context_runtime_integration import runtime_case as original

    async for bundle in original.__wrapped__(tmp_path):
        yield bundle


@pytest.mark.asyncio
async def test_runtime_without_trial_refuses_before_retrieval(runtime_case):
    from app.channels.staff_assist.context_runtime import MatrixContextRuntime

    from tests.channels.test_context_runtime_integration import run

    bundle = runtime_case
    for name in (
        "MATRIX_CONTEXT_TRIAL_ID",
        "MATRIX_CONTEXT_TRIAL_START_AT",
        "MATRIX_CONTEXT_TRIAL_END_AT",
    ):
        setattr(bundle.runtime.settings, name, "")
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "context_trial_budget_required"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_refusal_does_not_spend_note_reservation(runtime_case):
    from tests.channels.test_context_conversation_runtime import gate, setup

    bundle = runtime_case
    bundle.retrieve.return_value = ([], [])
    case = await setup(bundle, [gate(["$source"], category="not_a_request")])
    assert case.channel_metadata.get("conversation_generation_count", 0) == 0
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM matrix_context_trial_cases WHERE trial_id='conversation-fixture'"
            ).fetchone()[0]
            == 0
        )
        receipts = db.execute(
            "SELECT kind, status FROM matrix_context_trial_spend WHERE trial_id='conversation-fixture'"
        ).fetchall()
    assert receipts == [("gate", "settled")]
    bundle.llm.invoke.assert_called_once()
    bundle.retrieve.assert_not_called()
    bundle.sender.assert_not_awaited()
