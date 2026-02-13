"""Tests for Bisq2API send methods.

Covers:
- send_support_message() REST call and response parsing
- send_reaction() REST call and response handling
- Error handling for failed requests
- Session setup and request delegation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.channels.plugins.bisq2.client.api import Bisq2API

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_settings():
    """Settings mock with Bisq2 API URL."""
    settings = MagicMock()
    settings.BISQ_API_URL = "http://localhost:8090"
    return settings


@pytest.fixture()
def api(mock_settings):
    """Bisq2API instance with mock settings."""
    return Bisq2API(settings=mock_settings)


# ---------------------------------------------------------------------------
# send_support_message
# ---------------------------------------------------------------------------


class TestSendSupportMessage:
    """Test send_support_message REST call."""

    @pytest.mark.asyncio
    async def test_sends_post_request(self, api):
        """Sends POST to correct endpoint with JSON body."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(
            return_value={"messageId": "msg-abc-123", "timestamp": 1700000000}
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_response)
        api._session = mock_session

        result = await api.send_support_message(
            channel_id="support.support",
            text="Hello from bot",
        )

        mock_session.request.assert_called_once()
        call_args = mock_session.request.call_args
        assert call_args[0][0] == "POST"
        assert "support.support/messages" in call_args[0][1]
        assert result["messageId"] == "msg-abc-123"

    @pytest.mark.asyncio
    async def test_includes_citation_when_provided(self, api):
        """Citation is included in JSON body when provided."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(
            return_value={"messageId": "msg-456", "timestamp": 1700000000}
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_response)
        api._session = mock_session

        result = await api.send_support_message(
            channel_id="support.support",
            text="Answer text",
            citation="Original question",
        )

        call_kwargs = mock_session.request.call_args[1]
        assert call_kwargs["json"]["citation"] == "Original question"
        assert result["messageId"] == "msg-456"

    @pytest.mark.asyncio
    async def test_no_citation_when_none(self, api):
        """Citation is omitted from body when None."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(
            return_value={"messageId": "msg-789", "timestamp": 1700000000}
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_response)
        api._session = mock_session

        await api.send_support_message(
            channel_id="support.support",
            text="Answer",
        )

        call_kwargs = mock_session.request.call_args[1]
        assert "citation" not in call_kwargs["json"]

    @pytest.mark.asyncio
    async def test_initializes_session_if_needed(self, api):
        """Session is created if not yet initialized."""
        assert api._session is None

        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"messageId": "msg-x", "timestamp": 0}
            result = await api.send_support_message("ch", "text")
            assert result["messageId"] == "msg-x"

    @pytest.mark.asyncio
    async def test_raises_on_client_error(self, api):
        """ClientError from HTTP request propagates."""
        import aiohttp

        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("Connection refused"),
        ):
            with pytest.raises(aiohttp.ClientError):
                await api.send_support_message("ch", "text")

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self, api):
        """404 response returns empty dict (endpoint not deployed yet)."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await api.send_support_message("ch", "text")
            assert result == {}


# ---------------------------------------------------------------------------
# send_reaction
# ---------------------------------------------------------------------------


class TestSendReaction:
    """Test send_reaction REST call."""

    @pytest.mark.asyncio
    async def test_sends_post_request(self, api):
        """Sends POST to reaction endpoint."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            return_value={"content": ""},
        ) as mock_req:
            await api.send_reaction(
                channel_id="support.support",
                message_id="msg-123",
                reaction_id=0,
            )

            mock_req.assert_called_once()
            call_args = mock_req.call_args
            assert call_args[0][0] == "POST"
            assert "msg-123/reactions" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_includes_reaction_id_in_body(self, api):
        """reaction_id is sent in JSON body."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_req:
            await api.send_reaction(
                channel_id="ch",
                message_id="msg-1",
                reaction_id=4,
            )

            call_kwargs = mock_req.call_args[1]
            assert call_kwargs["json"]["reactionId"] == 4

    @pytest.mark.asyncio
    async def test_is_removed_flag(self, api):
        """is_removed is sent when True."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_req:
            await api.send_reaction(
                channel_id="ch",
                message_id="msg-1",
                reaction_id=0,
                is_removed=True,
            )

            call_kwargs = mock_req.call_args[1]
            assert call_kwargs["json"]["isRemoved"] is True

    @pytest.mark.asyncio
    async def test_is_removed_defaults_false(self, api):
        """is_removed defaults to False."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_req:
            await api.send_reaction(
                channel_id="ch",
                message_id="msg-1",
                reaction_id=0,
            )

            call_kwargs = mock_req.call_args[1]
            assert call_kwargs["json"]["isRemoved"] is False

    @pytest.mark.asyncio
    async def test_raises_on_error(self, api):
        """Errors propagate to caller."""
        import aiohttp

        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("timeout"),
        ):
            with pytest.raises(aiohttp.ClientError):
                await api.send_reaction("ch", "msg", 0)
