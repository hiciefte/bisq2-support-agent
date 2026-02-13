"""
TDD tests for message_id in chat query response.

The goal: POST /chat/query should return a message_id field in the response
so the frontend can correlate feedback with the exact message.
"""

from unittest.mock import AsyncMock, MagicMock

from app.channels.models import (
    ChannelType,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


def _make_outgoing_message(message_id: str = "web_test-uuid") -> OutgoingMessage:
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
