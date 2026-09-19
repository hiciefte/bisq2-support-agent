"""Network-status answers require tool evidence, including with no Wiki match."""

import json
import time
from unittest.mock import MagicMock

import pytest
from app.prompts import error_messages
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.services.bisq_network_status_service import SCOPES, BisqNetworkStatusService
from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.llm_provider import (
    ToolCallResult,
    needs_live_data,
    needs_network_status,
)

from tests.services import test_rag_service_review_fixes as support_fixtures

pytestmark = pytest.mark.unit


@pytest.fixture
def service(test_settings):
    return support_fixtures.service.__wrapped__(test_settings)


def tool_call(status="observations_available"):
    report = BisqNetworkStatusService._summarize(
        "tor",
        SCOPES["tor"],
        [
            {
                "target": "bisq_v2.torNetwork.torStartupTime",
                "datapoints": [[1000, int(time.time() - 20)]],
            }
        ],
        None,
        time.time(),
    )
    report["status"] = status
    return {"tool": "get_bisq_network_status", "result": json.dumps(report)}


@pytest.mark.parametrize(
    "query",
    [
        "Is Tor down right now?",
        "Are the Bisq seed nodes reachable?",
        "Is there a Bisq network outage?",
        "Check price node status",
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
