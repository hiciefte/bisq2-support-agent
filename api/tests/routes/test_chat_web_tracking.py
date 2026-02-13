"""
TDD tests for SentMessageTracker integration in chat.py.

The goal: After a successful gateway response, chat.py should call
tracker.track() so that web feedback can later be correlated via
ReactionProcessor (same pipeline as Matrix/Bisq2).
"""

from unittest.mock import AsyncMock, MagicMock

from app.channels.models import (
    ChannelType,
    ErrorCode,
    GatewayError,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)


def _make_outgoing(message_id: str = "web_test-uuid") -> OutgoingMessage:
    """Minimal OutgoingMessage for mocking."""
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


class TestWebMessageTracking:
    """Tests that chat.py calls tracker.track() after a successful gateway response."""

    def test_successful_response_tracks_message(self, test_client):
        """tracker.track() should be called on successful gateway response."""
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(return_value=_make_outgoing())
        test_client.app.state.channel_gateway = mock_gateway

        mock_tracker = MagicMock()
        test_client.app.state.sent_message_tracker = mock_tracker

        response = test_client.post(
            "/chat/query",
            json={"question": "How do I use Bisq?"},
        )

        assert response.status_code == 200
        mock_tracker.track.assert_called_once()

    def test_tracked_message_has_web_channel_id(self, test_client):
        """tracker.track() should be called with channel_id='web'."""
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(return_value=_make_outgoing())
        test_client.app.state.channel_gateway = mock_gateway

        mock_tracker = MagicMock()
        test_client.app.state.sent_message_tracker = mock_tracker

        test_client.post(
            "/chat/query",
            json={"question": "What is the trading fee?"},
        )

        call_kwargs = mock_tracker.track.call_args
        assert call_kwargs.kwargs.get("channel_id") == "web" or (
            call_kwargs.args and call_kwargs.args[0] == "web"
        )

    def test_tracked_message_uses_incoming_message_id(self, test_client):
        """external_message_id should be the incoming message's web_<uuid> ID."""
        captured = {}

        async def capture_incoming(incoming):
            captured["message_id"] = incoming.message_id
            return _make_outgoing()

        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(side_effect=capture_incoming)
        test_client.app.state.channel_gateway = mock_gateway

        mock_tracker = MagicMock()
        test_client.app.state.sent_message_tracker = mock_tracker

        test_client.post(
            "/chat/query",
            json={"question": "Test question"},
        )

        call_kwargs = mock_tracker.track.call_args.kwargs
        assert call_kwargs["external_message_id"] == captured["message_id"]
        assert call_kwargs["internal_message_id"] == captured["message_id"]

    def test_gateway_error_does_not_track(self, test_client):
        """tracker.track() should NOT be called when gateway returns an error."""
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(
            return_value=GatewayError(
                error_code=ErrorCode.RAG_SERVICE_ERROR,
                error_message="Service unavailable",
            )
        )
        test_client.app.state.channel_gateway = mock_gateway

        mock_tracker = MagicMock()
        test_client.app.state.sent_message_tracker = mock_tracker

        response = test_client.post(
            "/chat/query",
            json={"question": "Will this fail?"},
        )

        assert response.status_code == 500
        mock_tracker.track.assert_not_called()

    def test_tracker_unavailable_does_not_break_response(self, test_client):
        """If sent_message_tracker is not on app.state, response still works."""
        mock_gateway = MagicMock()
        mock_gateway.process_message = AsyncMock(return_value=_make_outgoing())
        test_client.app.state.channel_gateway = mock_gateway

        # Explicitly ensure no tracker
        if hasattr(test_client.app.state, "sent_message_tracker"):
            delattr(test_client.app.state, "sent_message_tracker")

        response = test_client.post(
            "/chat/query",
            json={"question": "No tracker here"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
