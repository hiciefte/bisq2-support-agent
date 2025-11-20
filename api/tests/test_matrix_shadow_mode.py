"""Tests for Matrix Shadow Mode Integration - TDD approach."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock nio module before importing
mock_nio = MagicMock()
mock_nio.AsyncClient = MagicMock
mock_nio.RoomMessagesError = Exception
sys.modules["nio"] = mock_nio


class TestMatrixShadowModeService:
    """Test suite for Matrix shadow mode integration."""

    @pytest.fixture
    def mock_matrix_client(self):
        """Create mock matrix-nio client."""
        mock = MagicMock()
        mock.login = AsyncMock(return_value=MagicMock(error=None))
        mock.sync = AsyncMock(return_value=MagicMock())
        mock.room_messages = AsyncMock(
            return_value=MagicMock(
                chunk=[
                    MagicMock(
                        event_id="$event1",
                        sender="@user:matrix.org",
                        body="What is the trade limit?",
                        server_timestamp=1234567890000,
                    )
                ]
            )
        )
        mock.close = AsyncMock()
        return mock

    @pytest.fixture
    def shadow_service(self, mock_matrix_client):
        """Create shadow mode service with mocked Matrix client."""
        with patch("app.integrations.matrix_shadow_mode.AsyncClient") as mock_client:
            mock_client.return_value = mock_matrix_client
            from app.integrations.matrix_shadow_mode import MatrixShadowModeService

            service = MatrixShadowModeService(
                homeserver="https://matrix.org",
                user_id="@bot:matrix.org",
                access_token="test_token",
                room_id="!support:matrix.org",
            )
            return service

    @pytest.mark.asyncio
    async def test_connect(self, shadow_service, mock_matrix_client):
        """Service can connect to Matrix homeserver."""
        await shadow_service.connect()
        mock_matrix_client.login.assert_not_called()  # Using access token

    @pytest.mark.asyncio
    async def test_fetch_messages(self, shadow_service, mock_matrix_client):
        """Service can fetch messages from room."""
        messages = await shadow_service.fetch_messages(limit=10)
        assert isinstance(messages, list)
        mock_matrix_client.room_messages.assert_called()

    @pytest.mark.asyncio
    async def test_detect_support_questions(self, shadow_service):
        """Service detects support questions in messages."""
        messages = [
            {"body": "What is the trade limit?", "event_id": "$1"},
            {"body": "Thanks for the help!", "event_id": "$2"},
            {"body": "How do I start a trade?", "event_id": "$3"},
        ]

        questions = shadow_service.filter_support_questions(messages)

        # Should detect 2 questions
        assert len(questions) == 2
        assert questions[0]["event_id"] == "$1"
        assert questions[1]["event_id"] == "$3"

    @pytest.mark.asyncio
    async def test_track_processed_messages(self, shadow_service):
        """Service tracks processed message IDs."""
        # Process a message
        shadow_service.mark_as_processed("$event1")

        # Check it's tracked
        assert shadow_service.is_processed("$event1")
        assert not shadow_service.is_processed("$event2")

    @pytest.mark.asyncio
    async def test_disconnect(self, shadow_service, mock_matrix_client):
        """Service disconnects cleanly."""
        await shadow_service.disconnect()
        mock_matrix_client.close.assert_called_once()

    def test_configuration(self):
        """Service requires proper configuration."""
        with patch("app.integrations.matrix_shadow_mode.AsyncClient"):
            from app.integrations.matrix_shadow_mode import MatrixShadowModeService

            service = MatrixShadowModeService(
                homeserver="https://matrix.org",
                user_id="@bot:matrix.org",
                access_token="token",
                room_id="!room:matrix.org",
            )

            assert service.homeserver == "https://matrix.org"
            assert service.room_id == "!room:matrix.org"

    @pytest.mark.asyncio
    async def test_poll_for_questions(self, shadow_service, mock_matrix_client):
        """Service can poll for new questions."""
        # Mock returning messages
        mock_matrix_client.room_messages.return_value = MagicMock(
            chunk=[
                MagicMock(
                    event_id="$event1",
                    sender="@user:matrix.org",
                    body="What is Bisq?",
                    server_timestamp=1234567890000,
                )
            ]
        )

        questions = await shadow_service.poll_for_questions()

        assert isinstance(questions, list)
