"""Network-status answers require tool evidence, including with no Wiki match."""

import json
import time
from unittest.mock import MagicMock

import pytest
from app.prompts import error_messages
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.services.bisq_network_status_service import (
    SCOPES,
    BisqNetworkStatusService,
    has_fresh_network_evidence,
)
from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.llm_provider import (
    ToolCallResult,
    needs_live_data,
    needs_network_status,
    requested_network_status_areas,
)

from tests.services import test_rag_service_review_fixes as support_fixtures

pytestmark = pytest.mark.unit


@pytest.fixture
def service(test_settings):
    return support_fixtures.service.__wrapped__(test_settings)


def tool_call(status="observations_available", area="tor"):
    target, value = {
        "tor": ("bisq_v2.torNetwork.torStartupTime", 1000),
        "seed_nodes": ("bisq_v2.seedNodes.test.rtt.serial", 1000),
        "price_nodes": ("bisq_v2.priceNodes.test.price.USD", 100000),
    }[area]
    report = BisqNetworkStatusService._summarize(
        area,
        SCOPES[area],
        [
            {
                "target": target,
                "datapoints": [[value, int(time.time() - 20)]],
            }
        ],
        None,
        time.time(),
    )
    report["status"] = status
    return {
        "tool": "get_bisq_network_status",
        "args": json.dumps({"area": area}),
        "result": json.dumps(report),
    }


@pytest.mark.parametrize(
    "query",
    [
        "Is Tor down right now?",
        "Are the Bisq seed nodes reachable?",
        "Is there a Bisq network outage?",
        "Check price node status",
        "Check price-node status",
        "I cannot connect to Bisq 2",
        "Tor is stuck at startup",
        "Bisq is down right now. Is it just me?",
        "Bisq 2 is offline. Can you check?",
        "Bisq cannot connect to the internet",
    ],
)
def test_status_intent_enables_streaming_tools(query):
    assert needs_network_status(query)
    assert needs_live_data(query)


@pytest.mark.parametrize(
    "query",
    [
        "How does Tor work?",
        "What are seed nodes?",
        "How do I back up Bisq?",
        "Describe last week's Tor outage",
        "What was Tor status yesterday?",
        "My bank is down",
        "What is my trade status?",
        "My Bisq 1 trade is stuck after the deposit transaction",
        "What is my Bisq 2 account status?",
        "The Bisq seller is offline and has my payment",
        "How can I import a wallet in Bisq 2?",
    ],
)
def test_non_status_queries_do_not_bypass_retrieval(query):
    assert not needs_network_status(query)


@pytest.mark.asyncio
async def test_zero_docs_still_uses_actual_status_tool(service):
    service.mcp_enabled = True
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    service.auto_send_router = AutoSendRouter()
    service.rag_chain = MagicMock(return_value="Invented network status")
    call = tool_call()
    service.llm.invoke_with_tools.return_value = ToolCallResult(
        content="The monitor observed a Tor startup; it does not establish global health.",
        tool_calls_made=[call],
    )
    callback = MagicMock()
    response = await service.query(
        "Is Tor down right now?", chat_history=[], token_callback=callback
    )
    service.llm.invoke_with_tools.assert_called_once()
    service.rag_chain.assert_not_called()
    assert response["answered_from"] == "live_tools"
    assert response["mcp_tools_used"][0]["result"] == call["result"]
    assert response["routing_action"] in {"queue_medium", "needs_human"}
    assert response["forwarded_to_human"] is True
    assert response["sources"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["missing", "wrong_tool", "unknown", "malformed", "stale"]
)
async def test_status_without_fresh_tool_evidence_cannot_use_model_claim(service, mode):
    service.mcp_enabled = True
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    service.auto_send_router = AutoSendRouter()
    service.rag_chain = MagicMock(return_value="Static network is healthy")
    calls = [tool_call()]
    if mode == "missing":
        calls = []
    elif mode == "wrong_tool":
        calls[0]["tool"] = "get_market_prices"
    elif mode == "unknown":
        calls = [tool_call("unknown")]
    elif mode == "malformed":
        calls[0]["result"] = "not JSON"
    elif mode == "stale":
        value = json.loads(calls[0]["result"])
        value["freshness"]["status"] = "stale_or_missing"
        calls[0]["result"] = json.dumps(value)
    service.llm.invoke_with_tools.return_value = ToolCallResult(
        content="The entire Bisq network is healthy right now.",
        tool_calls_made=calls,
    )
    response = await service.query("Is Tor down right now?", chat_history=[])
    assert response["answer"] == error_messages.NETWORK_STATUS_UNCONFIRMED
    assert response["routing_action"] == "needs_human"
    service.rag_chain.assert_not_called()
    if calls:
        assert response["mcp_tools_used"][0]["result"] == calls[0]["result"]


@pytest.mark.asyncio
async def test_mcp_disabled_with_docs_does_not_assert_static_current_status(service):
    service.mcp_enabled = False
    service.auto_send_router = AutoSendRouter()
    service.rag_chain = MagicMock(return_value="Static network health claim")
    response = await service.query("Is Tor down right now?", chat_history=[])
    assert response["answer"] == error_messages.NETWORK_STATUS_UNCONFIRMED
    assert response["routing_action"] == "needs_human"
    service.rag_chain.assert_not_called()
    service.llm.invoke_with_tools.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_disabled_zero_docs_preserves_no_document_fallback(service):
    service.mcp_enabled = False
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    response = await service.query("Is Tor down right now?", chat_history=[])
    service.llm.invoke_with_tools.assert_not_called()
    assert response["answer"] != "The entire Bisq network is healthy right now."
    assert not response.get("mcp_tools_used")


@pytest.mark.asyncio
async def test_zero_docs_safety_reflex_takes_precedence(service):
    service.mcp_enabled = True
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    response = await service.query(
        "Tor is down. Someone DM'd me claiming to be support and asking for my seed phrase.",
        chat_history=[],
    )
    assert response["answer"] == SAFETY_REFLEX_WARNING
    service.llm.invoke_with_tools.assert_not_called()


@pytest.mark.parametrize(
    "query,areas",
    [
        ("Is Tor down?", {"tor"}),
        ("Check seed-node status", {"seed_nodes"}),
        ("Are price nodes and Tor down?", {"tor", "price_nodes"}),
        ("Are Tor or seed nodes unavailable?", {"tor", "seed_nodes"}),
        ("Is the Bisq network down?", set()),
        ("Bisq cannot connect to the internet", set()),
        ("Is Matrix's network down?", set()),
    ],
)
def test_requested_scope_is_explicit_and_bounded(query, areas):
    assert requested_network_status_areas(query) == areas


@pytest.mark.parametrize(
    "mode",
    [
        "wrong_area",
        "args_mismatch",
        "report_mismatch",
        "missing_args",
        "invalid_args",
        "unsupported_area",
        "latest_mismatch",
    ],
)
@pytest.mark.asyncio
async def test_tor_status_rejects_wrong_area_or_unbound_call(service, mode):
    service.mcp_enabled = True
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    service.auto_send_router = AutoSendRouter()
    calls = [tool_call()]
    if mode == "wrong_area":
        calls = [tool_call(area="seed_nodes")]
    elif mode == "args_mismatch":
        calls[0]["args"] = json.dumps({"area": "seed_nodes"})
    elif mode == "report_mismatch":
        calls[0]["result"] = tool_call(area="seed_nodes")["result"]
    elif mode == "missing_args":
        calls[0].pop("args")
    elif mode == "invalid_args":
        calls[0]["args"] = "not JSON"
    elif mode == "unsupported_area":
        calls[0]["args"] = json.dumps({"area": "whole_network"})
    elif mode == "latest_mismatch":
        calls.append({**tool_call(), "result": tool_call(area="seed_nodes")["result"]})
    service.llm.invoke_with_tools.return_value = ToolCallResult(
        content="Tor is healthy right now.", tool_calls_made=calls
    )
    response = await service.query("Is Tor down right now?", chat_history=[])
    assert response["answer"] == error_messages.NETWORK_STATUS_UNCONFIRMED
    assert response["routing_action"] == "needs_human"
    assert response["mcp_tools_used"][0]["result"] == calls[0]["result"]


@pytest.mark.parametrize("all_areas_present", [True, False])
@pytest.mark.asyncio
async def test_multiple_explicit_areas_require_matching_fresh_evidence_for_each(
    service, all_areas_present
):
    service.mcp_enabled = True
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    service.auto_send_router = AutoSendRouter()
    calls = [tool_call()]
    if all_areas_present:
        calls.append(tool_call(area="seed_nodes"))
    text = "Fresh monitor observations exist for Tor startup and legacy seed-node probes; coverage is limited."
    service.llm.invoke_with_tools.return_value = ToolCallResult(
        content=text, tool_calls_made=calls
    )
    response = await service.query(
        "Are Tor or seed nodes down right now?", chat_history=[]
    )
    assert response["answer"] == (
        text if all_areas_present else error_messages.NETWORK_STATUS_UNCONFIRMED
    )


@pytest.mark.asyncio
async def test_generic_network_status_does_not_treat_component_probes_as_global_health(
    service,
):
    service.mcp_enabled = True
    service.document_retriever.retrieve_with_scores.return_value = ([], [])
    service.auto_send_router = AutoSendRouter()
    calls = [tool_call(area=area) for area in SCOPES]
    service.llm.invoke_with_tools.return_value = ToolCallResult(
        content="The whole Bisq network is healthy.", tool_calls_made=calls
    )
    response = await service.query("Is the Bisq network down?", chat_history=[])
    assert response["answer"] == error_messages.NETWORK_STATUS_UNCONFIRMED
    assert response["routing_action"] == "needs_human"
    assert len(response["mcp_tools_used"]) == 3


def test_scope_gate_preserves_latest_result_freshness_and_accepts_dict_arguments():
    fresh = tool_call()
    fresh["args"] = {"area": "tor"}
    assert has_fresh_network_evidence([fresh], frozenset({"tor"}))
    assert not has_fresh_network_evidence(
        [fresh, tool_call("unknown")], frozenset({"tor"})
    )
    stale = tool_call()
    report = json.loads(stale["result"])
    report["observations"]["oldest_fresh_observed_at"] = "2000-01-01T00:00:00+00:00"
    stale["result"] = json.dumps(report)
    assert not has_fresh_network_evidence([stale], frozenset({"tor"}))
