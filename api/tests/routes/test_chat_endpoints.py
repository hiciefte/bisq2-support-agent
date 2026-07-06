"""
TDD tests for message_id in chat query response.

The goal: POST /chat/query should return a message_id field in the response
so the frontend can correlate feedback with the exact message.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from app.channels.models import (
    ChannelType,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


def _make_outgoing_message(
    message_id: str = "web_test-uuid",
    *,
    original_language: str = "de",
    mcp_tools_used=None,
) -> OutgoingMessage:
    """Create a minimal OutgoingMessage for mocking gateway responses."""
    return OutgoingMessage(
        message_id=message_id,
        in_reply_to="web_incoming-uuid",
        channel=ChannelType.WEB,
        answer="Test answer about Bisq.",
        sources=[],
        user=UserContext(
            user_id="user_test",
            session_id="web_test-session",
            channel_user_id=None,
            auth_token=None,
        ),
        metadata=ResponseMetadata(
            confidence_score=0.85,
            processing_time_ms=150.0,
            routing_action="auto_send",
            rag_strategy="retrieval",
            model_name="test-model",
            original_language=original_language,
            version_confidence=None,
            mcp_tools_used=mcp_tools_used,
        ),
    )


class TestChatEndpointMessageId:
    """Tests for message_id in /chat/query response."""

    def test_query_response_includes_message_id(self, test_client):
        """POST /chat/query response should contain message_id field."""
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(return_value=_make_outgoing_message())
        test_client.app.state.channel_gateway = mock_gateway

        response = test_client.post(
            "/chat/query",
            json={"question": "How do I use Bisq?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "message_id" in data, "Response must include message_id field"
        assert data["message_id"] is not None
        assert data["user_language"] == "de"
        assert data["ui_labels"]["staff_response_label"]

    def test_message_id_starts_with_web_prefix(self, test_client):
        """message_id should start with 'web_' for web channel requests."""
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(return_value=_make_outgoing_message())
        test_client.app.state.channel_gateway = mock_gateway

        response = test_client.post(
            "/chat/query",
            json={"question": "What is the trading fee?"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message_id"].startswith(
            "web_"
        ), f"Web channel message_id must start with 'web_', got: {data['message_id']}"

    def test_message_id_matches_incoming_message_id(self, test_client):
        """The returned message_id should be the incoming message's ID (web_ + UUID)."""
        captured_incoming = {}

        async def capture_incoming(incoming):
            captured_incoming["message_id"] = incoming.message_id
            return _make_outgoing_message(message_id="resp_id")

        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(side_effect=capture_incoming)
        test_client.app.state.channel_gateway = mock_gateway

        response = test_client.post(
            "/chat/query",
            json={"question": "Test question"},
        )

        assert response.status_code == 200
        data = response.json()
        # message_id in response should be the INCOMING message_id (not the outgoing)
        assert data["message_id"] == captured_incoming["message_id"]

    def test_query_response_includes_mcp_tools_used(self, test_client):
        """MCP tool metadata should survive gateway-to-route conversion."""
        tool_usage = [
            {
                "tool": "get_market_prices",
                "timestamp": "2026-07-06T10:00:00+00:00",
                "result": '{"BTC":"100000"}',
            }
        ]
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(
            return_value=_make_outgoing_message(mcp_tools_used=tool_usage)
        )
        test_client.app.state.channel_gateway = mock_gateway

        response = test_client.post(
            "/chat/query",
            json={"question": "What is the BTC price in Bisq Easy?"},
        )

        assert response.status_code == 200
        assert response.json()["mcp_tools_used"] == tool_usage


def _parse_sse_events(body: str):
    """Parse the small SSE payloads emitted by the test route."""
    events = []
    for raw_event in body.strip().split("\n\n"):
        event_name = None
        data = None
        for line in raw_event.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = json.loads(line.removeprefix("data:").strip())
        if event_name and data is not None:
            events.append((event_name, data))
    return events


class TestChatStreamEndpoint:
    """Tests for /chat/query/stream SSE responses."""

    def test_stream_response_includes_tokens_and_final_metadata(self, test_client):
        """POST /chat/query/stream should emit token events before final data."""
        captured_incoming = {}

        async def stream_message(incoming):
            captured_incoming["message_id"] = incoming.message_id
            yield {"event": "token", "data": "Test "}
            yield {"event": "token", "data": "answer"}
            yield {"event": "final", "data": _make_outgoing_message()}

        mock_gateway = MagicMock()
        mock_gateway.stream_message = stream_message
        test_client.app.state.channel_gateway = mock_gateway

        response = test_client.post(
            "/chat/query/stream",
            json={"question": "How do I use Bisq?"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse_events(response.text)
        assert [event_name for event_name, _data in events] == [
            "token",
            "token",
            "final",
        ]
        assert events[0][1] == {"content": "Test "}
        assert events[1][1] == {"content": "answer"}
        final_data = events[2][1]
        assert final_data["message_id"] == captured_incoming["message_id"]
        assert final_data["message_id"].startswith("web_")
        assert final_data["answer"] == "Test answer about Bisq."
        assert final_data["user_language"] == "de"
        assert final_data["ui_labels"]["staff_response_label"]
