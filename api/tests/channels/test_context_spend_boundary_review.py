"""Provider-free regressions for pre-call boundaries and rejected-output usage."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist import context_trial
from app.channels.staff_assist.context_trial import ContextTrialStore
from app.scripts import replay_staff_context as replay
from app.services.rag.openai_responses import (
    ResponsesGenerationError,
)

from tests.channels.test_context_spend import rows, spend_trial, wrapper

pytestmark = pytest.mark.unit


@pytest.fixture
def bounded(tmp_path, monkeypatch):
    now = datetime(2026, 11, 18, 23, 59, 59, tzinfo=timezone.utc)
    clock = [now]
    monkeypatch.setattr(context_trial, "utc_now", lambda: clock[0])
    trial = spend_trial(
        MATRIX_CONTEXT_TRIAL_START_AT=(now - timedelta(hours=1)).isoformat(),
        MATRIX_CONTEXT_TRIAL_END_AT=(now + timedelta(hours=1)).isoformat(),
        MATRIX_CONTEXT_TRIAL_BUDGET_USD="1",
        MATRIX_CONTEXT_TRIAL_DAILY_BUDGET_USD="1",
    )
    return ContextTrialStore(str(tmp_path / "trial.db"), trial), clock


@pytest.mark.parametrize("boundary", ["cutoff", "midnight", "exception"])
@pytest.mark.parametrize("hook_name", ["before_call", "before_provider"])
def test_pre_call_hook_never_starts_after_time_shift_or_error(
    bounded, boundary, hook_name
):
    store, clock = bounded
    if boundary == "cutoff":
        store.trial = replace(
            store.trial, end_at=clock[0] + timedelta(milliseconds=500)
        )
    audit = Mock()
    original = OSError("synthetic disk failure")

    def hook():
        if boundary == "exception":
            raise original
        clock[0] = (
            store.trial.end_at
            if boundary == "cutoff"
            else clock[0] + timedelta(seconds=2)
        )

    adapter = wrapper(store, **{hook_name: hook}, on_not_started=audit)
    with pytest.raises((RuntimeError, OSError)) as exc:
        adapter.invoke("request")
    if boundary == "exception":
        assert exc.value is original
    else:
        assert str(exc.value) == (
            "context_trial_expired"
            if boundary == "cutoff"
            else "context_trial_day_changed"
        )
    adapter.llm.invoke.assert_not_called()
    assert adapter.started is False
    assert rows(store)[0]["status"] == "not_started"
    assert rows(store)[0]["actual_nanodollars"] == 0
    audit.assert_called_once()


def test_cancellation_failure_preserves_refusal_and_held_reservation(
    bounded, monkeypatch
):
    store, _ = bounded
    original = RuntimeError("source_changed")
    audit = Mock()
    adapter = wrapper(
        store, before_provider=Mock(side_effect=original), on_not_started=audit
    )
    monkeypatch.setattr(
        store, "cancel_unstarted_call", Mock(side_effect=OSError("private detail"))
    )
    with pytest.raises(RuntimeError) as error:
        adapter.invoke("request")
    assert error.value is original
    assert adapter.unstarted_cleanup_error == "OSError"
    assert all("private detail" not in note for note in original.__notes__)
    adapter.llm.invoke.assert_not_called()
    assert rows(store)[0]["status"] == "uncertain"
    assert rows(store)[0]["actual_nanodollars"] is None
    audit.assert_called_once()


def test_replay_records_no_provider_call_without_claiming_zero_cost_on_cleanup_error(
    bounded, monkeypatch, tmp_path
):
    store, _ = bounded
    calls = replay.ReplayCalls(
        {
            "max_model_calls": 5,
            "maximum_elapsed_seconds": 10,
            "model": store.trial.model,
        },
        wrapper(store).llm,
        store,
        tmp_path,
    )
    adapter = calls.adapter(NS(case_id=1, version="v1"), kind="note", virtual_time_ms=1)
    adapter.before_provider = lambda: "stale_case"
    monkeypatch.setattr(store, "cancel_unstarted_call", Mock(side_effect=OSError()))
    with pytest.raises(RuntimeError, match="stale_case"):
        adapter.invoke("request")
    record = replay.read_jsonl(tmp_path / "calls-not-started.jsonl")[0]
    assert record["status"] == "provider_not_started_ledger_uncertain"
    assert record["cleanup_error_class"] == "OSError"
    assert calls.calls == 0
    assert rows(store)[0]["status"] == "uncertain"


def test_not_started_note_releases_kind_but_not_exact_attempt(bounded):
    store, _ = bounded
    adapter = wrapper(store, before_call=lambda: "stale_case")
    with pytest.raises(RuntimeError, match="stale_case"):
        adapter.invoke("request")
    with pytest.raises(RuntimeError, match="already_started"):
        wrapper(store).invoke("same cancelled attempt")
    again = wrapper(store, call_id="new_version")
    again.invoke("updated request")
    with pytest.raises(RuntimeError, match="already_started"):
        wrapper(store, call_id="third_version").invoke("third request")


@pytest.mark.parametrize("status", ["incomplete", "failed", "empty"])
def test_rejected_provider_response_settles_valid_usage_without_output(
    bounded, monkeypatch, status
):
    store, _ = bounded
    adapter = wrapper(store)
    # Exercise the actual wrapper, including contract rejection after usage.
    del adapter.llm.invoke
    raw = {
        "status": "completed" if status == "empty" else status,
        "usage": {"input_tokens": 8, "output_tokens": 5},
        "output": [],
    }
    adapter.llm.client.responses = NS(create=Mock(return_value=raw))
    monkeypatch.setattr(
        "app.services.rag.openai_responses.track_tokens_and_cost", Mock()
    )
    with pytest.raises(ResponsesGenerationError) as exc:
        adapter.invoke("request")
    assert exc.value.usage["prompt_tokens"] == 8
    assert not hasattr(exc.value, "content")
    receipt = rows(store)[0]
    assert receipt["status"] == "settled"
    assert receipt["actual_nanodollars"] == 18000
    assert adapter.started


def test_invalid_usage_on_rejected_response_keeps_full_uncertainty(
    bounded, monkeypatch
):
    store, _ = bounded
    adapter = wrapper(store)
    del adapter.llm.invoke
    adapter.llm.client.responses = NS(
        create=Mock(
            return_value={
                "status": "incomplete",
                "usage": {"input_tokens": True, "output_tokens": 5},
            }
        )
    )
    with pytest.raises(ResponsesGenerationError) as exc:
        adapter.invoke("request")
    assert exc.value.usage is None
    assert rows(store)[0]["status"] == "uncertain"
    assert rows(store)[0]["actual_nanodollars"] is None


def test_replay_sync_elapsed_limit_reconciles_intent_and_releases_charge(
    bounded, tmp_path, monkeypatch
):
    store, _ = bounded
    monotonic = [100.0]
    monkeypatch.setattr(replay.time, "monotonic", lambda: monotonic[0])
    calls = replay.ReplayCalls(
        {
            "max_model_calls": 5,
            "maximum_elapsed_seconds": 10,
            "model": store.trial.model,
        },
        wrapper(store).llm,
        store,
        tmp_path,
    )
    original = replay.append_private

    def slow_sync(path, item):
        original(path, item)
        monotonic[0] = 111.0

    monkeypatch.setattr(replay, "append_private", slow_sync)
    adapter = calls.adapter(NS(case_id=1, version="v1"), kind="note", virtual_time_ms=1)
    with pytest.raises(RuntimeError, match="elapsed_limit"):
        adapter.invoke("request")
    calls.llm.invoke.assert_not_called()
    assert calls.calls == 0
    assert rows(store)[0]["status"] == "not_started"
    assert replay.read_jsonl(tmp_path / "calls-not-started.jsonl")[0]["call_id"] == "v1"
