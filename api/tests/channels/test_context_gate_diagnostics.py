"""Diagnostic length must not change the gate's authorization boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.context_conversation import (
    ConversationTurn,
    RequestSnapshot,
)
from app.channels.staff_assist.context_gate import RequestGateError, RequestGateService

pytestmark = pytest.mark.unit


def snapshot():
    return RequestSnapshot(
        case_id=1,
        room_id="!support:example.org",
        requester_id="@requester:example.org",
        revision=1,
        turns=(
            ConversationTurn(
                "!support:example.org",
                "$request",
                "@requester:example.org",
                1000,
                "The application will not connect.",
            ),
        ),
        last_requester_at_ms=1000,
    )


def gate(selected_ids, **overrides):
    response = {
        "category": "unanswered_support_request",
        "selected_event_ids": selected_ids,
        "request_summary": "The requester reports a connection problem.",
        "material_change": True,
        "request_resolved": False,
        "resolution_event_id": None,
        "reason": "Diagnostic explanation. " * 30,
    }
    response.update(overrides)
    llm = SimpleNamespace(
        invoke=Mock(
            return_value=SimpleNamespace(
                content=json.dumps(response),
                usage={"input_tokens": 100, "output_tokens": 100},
            )
        )
    )
    return RequestGateService(llm), response


def test_long_explanation_preserved_without_changing_decision():
    service, expected = gate(["$request"])
    decision = service.classify(snapshot())
    assert decision.reason == expected["reason"]
    assert decision.request_summary == expected["request_summary"]
    assert decision.category == expected["category"]
    assert decision.selected_event_ids == ["$request"]
    service.llm.invoke.assert_called_once()


@pytest.mark.parametrize("ids", [["$unknown"], ["$request", "$request"]])
def test_long_diagnostics_do_not_admit_unknown_or_duplicate_events(ids):
    service, _ = gate(ids)
    with pytest.raises(RequestGateError, match="invalid_conversation_gate"):
        service.classify(snapshot())


@pytest.mark.parametrize(
    "overrides",
    [
        {"category": "send_now"},
        {"reason": ""},
        {"request_summary": "x" * 1001},
        {"material_change": "true"},
    ],
)
def test_diagnostic_fix_preserves_other_schema_rejections(overrides):
    service, _ = gate(["$request"], **overrides)
    with pytest.raises(RequestGateError, match="invalid_conversation_gate"):
        service.classify(snapshot())
