"""Tests for Bisq2API send methods.

Covers:
- send_support_message() REST call and response parsing
- send_reaction() REST call and response handling
- Error handling for failed requests
- Session setup and request delegation
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
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
        mock_response.raise_for_status = MagicMock()
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
        mock_response.raise_for_status = MagicMock()
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
        mock_response.raise_for_status = MagicMock()
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

    @pytest.mark.asyncio
    async def test_bootstraps_identity_and_retries_when_send_returns_empty(self, api):
        """When first send returns empty, bootstrap identity and retry once."""
        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [
                {},  # initial support send (404/no selected identity)
                {},  # selected profile check -> none
                [],  # existing identity ids -> none
                {  # key material for identity creation
                    "keyPair": {"privateKey": "priv", "publicKey": "pub"},
                    "id": "id-1",
                    "nym": "nym-1",
                    "proofOfWork": {"counter": 1},
                },
                {"userProfile": {"nickName": "Bisq Support Agent"}},  # created identity
                {"nickName": "Bisq Support Agent"},  # selected profile after create
                {
                    "messageId": "msg-after-bootstrap",
                    "timestamp": 1700000000,
                },  # retry send
            ]

            result = await api.send_support_message("support.support", "hello")

            assert result["messageId"] == "msg-after-bootstrap"
            assert mock_req.call_count == 7
            assert mock_req.call_args_list[0].args == (
                "POST",
                "/api/v1/support/channels/support.support/messages",
            )
            assert mock_req.call_args_list[-1].args == (
                "POST",
                "/api/v1/support/channels/support.support/messages",
            )

    @pytest.mark.asyncio
    async def test_falls_back_to_host_docker_internal_on_connection_error(self):
        """Retries request on host fallback URL when first URL is unreachable."""
        settings = MagicMock()
        settings.BISQ_API_URL = "http://bisq2-api:8090"
        api = Bisq2API(settings=settings)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(return_value={"messageId": "msg-fallback"})
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(
            side_effect=[aiohttp.ClientConnectionError("dns"), mock_response]
        )
        api._session = mock_session

        result = await api.send_support_message("support.support", "hello")

        assert result == {"messageId": "msg-fallback"}
        assert mock_session.request.call_count == 2
        urls = [call.args[1] for call in mock_session.request.call_args_list]
        assert urls == [
            "http://bisq2-api:8090/api/v1/support/channels/support.support/messages",
            "http://host.docker.internal:8090/api/v1/support/channels/support.support/messages",
        ]


class TestBaseUrlCandidates:
    """Test base URL candidate generation used for failover."""

    def test_adds_host_fallback_for_bisq_service_name(self):
        settings = MagicMock()
        settings.BISQ_API_URL = "http://bisq2-api:8090"

        api = Bisq2API(settings=settings)

        assert api.base_urls == [
            "http://bisq2-api:8090",
            "http://host.docker.internal:8090",
        ]

    def test_adds_host_fallback_for_localhost(self):
        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"

        api = Bisq2API(settings=settings)

        assert api.base_urls == [
            "http://localhost:8090",
            "http://host.docker.internal:8090",
        ]


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


class TestBisqApiAuth:
    """Test Bisq2 API authentication and pairing helpers."""

    @staticmethod
    def _json_response(payload: dict) -> AsyncMock:
        response = AsyncMock()
        response.status = 200
        response.headers = {"content-type": "application/json"}
        response.json = AsyncMock(return_value=payload)
        response.raise_for_status = MagicMock()
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)
        return response

    @pytest.mark.asyncio
    async def test_make_request_includes_auth_headers_when_enabled(self):
        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = "client-1"
        settings.BISQ_API_CLIENT_SECRET = "secret-1"
        settings.BISQ_API_SESSION_ID = "session-1"
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = ""

        api = Bisq2API(settings=settings)
        mock_session = AsyncMock()
        mock_session.request = MagicMock(
            return_value=self._json_response({"messages": []})
        )
        api._session = mock_session

        await api._make_request(
            "GET",
            "/api/v1/support/export",
            headers={"Accept": "application/json"},
        )

        headers = mock_session.request.call_args.kwargs["headers"]
        assert headers["Accept"] == "application/json"
        assert headers["Bisq-Client-Id"] == "client-1"
        assert headers["Bisq-Session-Id"] == "session-1"

    def test_decode_pairing_code_id_from_qr_payload(self):
        pairing_qr = (
            "AQBbAQAkMWQyN2ZiZTAtY2U1Ny00NzE1LWE1NTItNGUwMzQzOWFiMjk2AAABnJUUjRAAAAAK"
            "AAAAAAAAAAEAAAACAAAAAwAAAAQAAAAFAAAABgAAAAcAAAAIAAAACQATd3M6Ly8xMjcuMC4wLjE6ODA5MAA"
        )
        pairing_id = Bisq2API._decode_pairing_code_id_from_qr(pairing_qr)
        assert pairing_id == "1d27fbe0-ce57-4715-a552-4e03439ab296"

    @pytest.mark.asyncio
    async def test_pairs_client_when_enabled_and_credentials_missing(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = ""
        settings.BISQ_API_CLIENT_SECRET = ""
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = "pairing-code-id-1"
        settings.BISQ_API_PAIRING_CLIENT_NAME = "support-agent-test"
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)

        api = Bisq2API(settings=settings)

        with patch.object(
            api, "_request_access", new_callable=AsyncMock
        ) as mock_access:
            mock_access.return_value = {
                "clientId": "client-paired",
                "clientSecret": "secret-paired",
                "sessionId": "session-paired",
            }

            mock_session = AsyncMock()
            mock_session.request = MagicMock(
                return_value=self._json_response({"messages": []})
            )
            api._session = mock_session

            await api._make_request("GET", "/api/v1/support/export")

            assert mock_access.call_count == 1
            assert mock_access.call_args.args[1] == "/api/v1/access/pairing"
            headers = mock_session.request.call_args.kwargs["headers"]
            assert headers["Bisq-Client-Id"] == "client-paired"
            assert headers["Bisq-Session-Id"] == "session-paired"
            saved = json.loads(auth_state_file.read_text(encoding="utf-8"))
            assert saved["client_id"] == "client-paired"
            assert saved["client_secret"] == "secret-paired"

    @pytest.mark.asyncio
    async def test_creates_session_when_credentials_exist_but_session_missing(self):
        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = "client-2"
        settings.BISQ_API_CLIENT_SECRET = "secret-2"
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = ""

        api = Bisq2API(settings=settings)

        with patch.object(
            api, "_request_access", new_callable=AsyncMock
        ) as mock_access:
            mock_access.return_value = {"sessionId": "session-created"}
            mock_session = AsyncMock()
            mock_session.request = MagicMock(
                return_value=self._json_response({"messages": []})
            )
            api._session = mock_session

            await api._make_request("GET", "/api/v1/support/export")

            assert mock_access.call_count == 1
            assert mock_access.call_args.args[1] == "/api/v1/access/session"
            headers = mock_session.request.call_args.kwargs["headers"]
            assert headers["Bisq-Client-Id"] == "client-2"
            assert headers["Bisq-Session-Id"] == "session-created"

    def test_loads_auth_state_on_init_when_enabled(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"
        auth_state_file.write_text(
            json.dumps(
                {
                    "client_id": "state-client",
                    "client_secret": "state-secret",
                }
            ),
            encoding="utf-8",
        )

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = ""
        settings.BISQ_API_CLIENT_SECRET = ""
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)

        api = Bisq2API(settings=settings)

        assert api._client_id == "state-client"
        assert api._client_secret == "state-secret"
