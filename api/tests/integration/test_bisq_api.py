"""Tests for Bisq2API send methods.

Covers:
- send_support_message() REST call and response parsing
- send_reaction() REST call and response handling
- Error handling for failed requests
- Session setup and request delegation
"""

import asyncio
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
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["support.support", "ch"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-allowed"]
    settings.BISQ2_STAFF_PROFILE_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
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
    async def test_disallowed_target_never_reaches_transport(self, mock_settings):
        """The final Bisq send boundary denies targets outside the scope."""
        mock_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["support.allowed"]
        scoped_api = Bisq2API(settings=mock_settings)
        scoped_api._make_request = AsyncMock()

        result = await scoped_api.send_support_message(
            channel_id="support.blocked",
            text="Fixture answer",
            origin_sender_profile_id="profile-allowed",
        )

        assert result == {}
        scoped_api._make_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disallowed_origin_never_reaches_transport(self, api):
        """An approved group channel cannot bypass the identity dimension."""
        api._make_request = AsyncMock()

        result = await api.send_support_message(
            channel_id="support.support",
            text="Fixture answer",
            origin_sender_profile_id="profile-blocked",
        )

        assert result == {}
        api._make_request.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("channel_id", "origin_sender_profile_id"),
        [
            (" support.support ", "profile-allowed"),
            ("support.support", " profile-allowed "),
        ],
    )
    async def test_noncanonical_scope_never_reaches_support_transport(
        self,
        api,
        channel_id,
        origin_sender_profile_id,
    ):
        api._make_request = AsyncMock()

        result = await api.send_support_message(
            channel_id=channel_id,
            text="Fixture answer",
            origin_sender_profile_id=origin_sender_profile_id,
        )

        assert result == {}
        api._make_request.assert_not_awaited()

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
            origin_sender_profile_id="profile-allowed",
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
            origin_sender_profile_id="profile-allowed",
            citation_author_user_profile_id="profile-allowed",
            citation_message_id="message-original",
        )

        call_kwargs = mock_session.request.call_args[1]
        assert call_kwargs["json"]["citation"] == "Original question"
        assert call_kwargs["json"]["citationAuthorUserProfileId"] == ("profile-allowed")
        assert call_kwargs["json"]["citationMessageId"] == "message-original"
        assert result["messageId"] == "msg-456"

    @pytest.mark.asyncio
    async def test_citation_without_exact_provenance_never_reaches_transport(self, api):
        """Text-only citation matching could attribute a reply to the wrong user."""
        api._make_request = AsyncMock()

        result = await api.send_support_message(
            channel_id="support.support",
            text="Answer text",
            citation="Repeated question text",
            origin_sender_profile_id="profile-allowed",
        )

        assert result == {}
        api._make_request.assert_not_awaited()

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
            origin_sender_profile_id="profile-allowed",
        )

        call_kwargs = mock_session.request.call_args[1]
        assert "citation" not in call_kwargs["json"]

    @pytest.mark.asyncio
    async def test_initializes_session_if_needed(self, api):
        """Session is created if not yet initialized."""
        assert api._session is None

        with patch.object(api, "_make_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"messageId": "msg-x", "timestamp": 0}
            result = await api.send_support_message(
                "ch",
                "text",
                origin_sender_profile_id="profile-allowed",
            )
            assert result["messageId"] == "msg-x"

    @pytest.mark.asyncio
    async def test_raises_on_client_error(self, api):
        """ClientError from HTTP request propagates."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("Connection refused"),
        ):
            with pytest.raises(aiohttp.ClientError):
                await api.send_support_message(
                    "ch",
                    "text",
                    origin_sender_profile_id="profile-allowed",
                )

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self, api):
        """404 response returns empty dict (endpoint not deployed yet)."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await api.send_support_message(
                "ch",
                "text",
                origin_sender_profile_id="profile-allowed",
            )
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

            result = await api.send_support_message(
                "support.support",
                "hello",
                origin_sender_profile_id="profile-allowed",
            )

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
        settings.BISQ2_ALLOWED_CHANNEL_IDS = ["support.support"]
        settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-allowed"]
        settings.BISQ2_STAFF_PROFILE_IDS = []
        settings.BISQ2_CHATOPS_ENABLED = False
        settings.BISQ2_CHATOPS_CHANNEL_IDS = []
        settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
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

        result = await api.send_support_message(
            "support.support",
            "hello",
            origin_sender_profile_id="profile-allowed",
        )

        assert result == {"messageId": "msg-fallback"}
        assert mock_session.request.call_count == 2
        urls = [call.args[1] for call in mock_session.request.call_args_list]
        assert urls == [
            "http://bisq2-api:8090/api/v1/support/channels/support.support/messages",
            "http://host.docker.internal:8090/api/v1/support/channels/support.support/messages",
        ]

    @pytest.mark.asyncio
    async def test_read_timeout_falls_back_to_host_docker_internal(self, mock_settings):
        """Retries a timed-out read against the next API candidate."""
        mock_settings.BISQ_API_URL = "http://bisq2-api:8090"
        api = Bisq2API(settings=mock_settings)

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json = AsyncMock(return_value={"messages": []})
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(
            side_effect=[asyncio.TimeoutError(), mock_response]
        )
        api._session = mock_session

        result = await api._make_request("GET", "/api/v1/support/export")

        assert result == {"messages": []}
        urls = [call.args[1] for call in mock_session.request.call_args_list]
        assert urls == [
            "http://bisq2-api:8090/api/v1/support/export",
            "http://host.docker.internal:8090/api/v1/support/export",
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "timeout_error",
        [
            pytest.param(asyncio.TimeoutError(), id="asyncio-timeout"),
            pytest.param(aiohttp.SocketTimeoutError(), id="socket-timeout"),
        ],
    )
    async def test_write_timeout_does_not_retry_uncertain_delivery(
        self, mock_settings, timeout_error
    ):
        """Does not repeat a mutation whose remote outcome is unknown."""
        mock_settings.BISQ_API_URL = "http://bisq2-api:8090"
        api = Bisq2API(settings=mock_settings)

        mock_session = AsyncMock()
        mock_session.request = MagicMock(side_effect=timeout_error)
        api._session = mock_session

        with pytest.raises(aiohttp.ClientError, match="request timed out"):
            await api.send_support_message(
                "support.support",
                "hello",
                origin_sender_profile_id="profile-allowed",
            )

        mock_session.request.assert_called_once()


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
    async def test_disallowed_reaction_scope_never_reaches_transport(self, api):
        api._make_request = AsyncMock()

        result = await api.send_reaction(
            channel_id="support.support",
            message_id="msg-blocked",
            reaction_id=0,
            origin_sender_profile_id="profile-blocked",
        )

        assert result == {}
        api._make_request.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("channel_id", "origin_sender_profile_id"),
        [
            (" support.support ", "profile-allowed"),
            ("support.support", " profile-allowed "),
        ],
    )
    async def test_noncanonical_scope_never_reaches_reaction_transport(
        self,
        api,
        channel_id,
        origin_sender_profile_id,
    ):
        api._make_request = AsyncMock()

        result = await api.send_reaction(
            channel_id=channel_id,
            message_id="msg-safe",
            reaction_id=0,
            origin_sender_profile_id=origin_sender_profile_id,
        )

        assert result == {}
        api._make_request.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "message_id",
        [
            "",
            "   ",
            ".",
            "..",
            "../private-message",
            "path/to/message",
            r"path\to\message",
            "message?query=private",
            "message#fragment",
            "a" * 257,
            None,
        ],
    )
    async def test_invalid_message_id_never_reaches_transport(self, api, message_id):
        api._make_request = AsyncMock()

        result = await api.send_reaction(
            channel_id="support.support",
            message_id=message_id,
            reaction_id=0,
            origin_sender_profile_id="profile-allowed",
        )

        assert result == {}
        api._make_request.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "reaction_id",
        [-1, 6, True, False, "0", 0.0, None],
    )
    async def test_invalid_reaction_id_never_reaches_transport(self, api, reaction_id):
        api._make_request = AsyncMock()

        result = await api.send_reaction(
            channel_id="support.support",
            message_id="msg-safe",
            reaction_id=reaction_id,
            origin_sender_profile_id="profile-allowed",
        )

        assert result == {}
        api._make_request.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("is_removed", [0, 1, "false", None])
    async def test_non_boolean_removal_flag_never_reaches_transport(
        self, api, is_removed
    ):
        api._make_request = AsyncMock()

        result = await api.send_reaction(
            channel_id="support.support",
            message_id="msg-safe",
            reaction_id=0,
            is_removed=is_removed,
            origin_sender_profile_id="profile-allowed",
        )

        assert result == {}
        api._make_request.assert_not_awaited()

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
                origin_sender_profile_id="profile-allowed",
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
                origin_sender_profile_id="profile-allowed",
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
                origin_sender_profile_id="profile-allowed",
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
                origin_sender_profile_id="profile-allowed",
            )

            call_kwargs = mock_req.call_args[1]
            assert call_kwargs["json"]["isRemoved"] is False

    @pytest.mark.asyncio
    async def test_raises_on_error(self, api):
        """Errors propagate to caller."""
        with patch.object(
            api,
            "_make_request",
            new_callable=AsyncMock,
            side_effect=aiohttp.ClientError("timeout"),
        ):
            with pytest.raises(aiohttp.ClientError):
                await api.send_reaction(
                    "ch",
                    "msg",
                    0,
                    origin_sender_profile_id="profile-allowed",
                )


class TestBisqApiRequestPrivacy:
    """Transport failures must not expose scoped identifiers."""

    @pytest.mark.asyncio
    async def test_response_error_redacts_endpoint_identifiers(self, api, caplog):
        channel_sentinel = "channel-sentinel-private"
        message_sentinel = "message-sentinel-private"
        response = AsyncMock()
        response.status = 500
        response.headers = {"content-type": "application/json"}
        response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(
                    real_url=(
                        f"/support/{channel_sentinel}/{message_sentinel}/reactions"
                    )
                ),
                history=(),
                status=500,
                message="fixture failure",
                headers={},
            )
        )
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)
        session = AsyncMock()
        session.request = MagicMock(return_value=response)
        api._session = session
        api._auth_enabled = False

        with pytest.raises(aiohttp.ClientError) as exc_info:
            await api._make_request(
                "POST",
                f"/api/v1/support/channels/{channel_sentinel}/"
                f"{message_sentinel}/reactions",
            )

        output = caplog.text + str(exc_info.value)
        assert channel_sentinel not in output
        assert message_sentinel not in output

    @pytest.mark.asyncio
    async def test_connection_error_redacts_target_and_raw_exception(
        self, mock_settings, caplog
    ):
        username_sentinel = "userinfo-sentinel-a"
        password_sentinel = "userinfo-sentinel-b"
        host_sentinel = ".".join(("host-sentinel", "invalid"))
        ip_sentinel = ".".join(("192", "0", "2", "123"))
        raw_error_sentinel = "raw-transport-detail"
        sentinels = {
            username_sentinel,
            password_sentinel,
            host_sentinel,
            ip_sentinel,
            raw_error_sentinel,
        }
        mock_settings.BISQ_API_URL = "http://{}:{}@{}:8090".format(
            username_sentinel,
            password_sentinel,
            host_sentinel,
        )
        scoped_api = Bisq2API(settings=mock_settings)
        session = AsyncMock()
        session.request = MagicMock(
            side_effect=aiohttp.ClientConnectionError(
                f"{raw_error_sentinel} at {ip_sentinel}"
            )
        )
        scoped_api._session = session
        scoped_api._auth_enabled = False

        with pytest.raises(aiohttp.ClientConnectionError) as exc_info:
            await scoped_api._make_request("GET", "/api/v1/support/export")

        output = caplog.text + str(exc_info.value)
        assert str(exc_info.value) == "Bisq2 API connection failed"
        for sentinel in sentinels:
            assert sentinel not in output


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
        settings.ADMIN_API_KEY = "admin-secret"

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
            assert "secret-paired" not in auth_state_file.read_text(
                encoding="utf-8", errors="ignore"
            )
            reloaded = Bisq2API(settings=settings)
            assert reloaded._client_id == "client-paired"
            assert reloaded._client_secret == "secret-paired"
            assert reloaded._session_id == "session-paired"

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

    @pytest.mark.asyncio
    async def test_re_pairs_when_configured_credentials_can_no_longer_create_session(
        self, tmp_path
    ):
        auth_state_file = tmp_path / "bisq_api_auth.json"

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = "stale-client"
        settings.BISQ_API_CLIENT_SECRET = "stale-secret"
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = "pairing-code-id-1"
        settings.BISQ_API_PAIRING_CLIENT_NAME = "support-agent-test"
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)
        settings.ADMIN_API_KEY = "admin-secret"

        api = Bisq2API(settings=settings)

        with patch.object(
            api, "_request_access", new_callable=AsyncMock
        ) as mock_access:
            mock_access.side_effect = [
                aiohttp.ClientResponseError(
                    request_info=MagicMock(
                        real_url="http://localhost:8090/api/v1/access/session"
                    ),
                    history=(),
                    status=401,
                    message="Unauthorized",
                    headers={},
                ),
                {
                    "clientId": "paired-client",
                    "clientSecret": "paired-secret",
                    "sessionId": "paired-session",
                },
            ]
            mock_session = AsyncMock()
            mock_session.request = MagicMock(
                return_value=self._json_response({"messages": []})
            )
            api._session = mock_session

            await api._make_request("GET", "/api/v1/support/export")

            assert mock_access.call_count == 2
            assert mock_access.call_args_list[0].args[1] == "/api/v1/access/session"
            assert mock_access.call_args_list[1].args[1] == "/api/v1/access/pairing"
            headers = mock_session.request.call_args.kwargs["headers"]
            assert headers["Bisq-Client-Id"] == "paired-client"
            assert headers["Bisq-Session-Id"] == "paired-session"
            assert "paired-secret" not in auth_state_file.read_text(
                encoding="utf-8", errors="ignore"
            )
            reloaded = Bisq2API(settings=settings)
            assert reloaded._client_id == "stale-client"
            assert reloaded._client_secret == "stale-secret"
            reloaded._load_auth_state(override_existing=True)
            assert reloaded._client_id == "paired-client"
            assert reloaded._client_secret == "paired-secret"
            assert reloaded._session_id == "paired-session"

    @pytest.mark.asyncio
    async def test_recreates_session_after_unauthorized_request_without_reusing_stale_session(
        self, tmp_path
    ):
        auth_state_file = tmp_path / "bisq_api_auth.json"
        auth_state_file.write_text(
            json.dumps(
                {
                    "client_id": "state-client",
                    "client_secret": "state-secret",
                    "session_id": "stale-session",
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

        unauthorized = AsyncMock()
        unauthorized.status = 403
        unauthorized.headers = {"content-type": "application/json"}
        unauthorized.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(
                    real_url="http://localhost:8090/api/v1/support/export"
                ),
                history=(),
                status=403,
                message="Forbidden",
                headers={},
            )
        )
        unauthorized.__aenter__ = AsyncMock(return_value=unauthorized)
        unauthorized.__aexit__ = AsyncMock(return_value=False)

        success = self._json_response({"messages": []})

        with patch.object(
            api,
            "_request_access",
            new_callable=AsyncMock,
            return_value={"sessionId": "fresh-session"},
        ) as mock_access:
            mock_session = AsyncMock()
            mock_session.request = MagicMock(side_effect=[unauthorized, success])
            api._session = mock_session

            await api._make_request("GET", "/api/v1/support/export")

            assert mock_access.call_count == 1
            assert mock_access.call_args.args[1] == "/api/v1/access/session"
            first_headers = mock_session.request.call_args_list[0].kwargs["headers"]
            second_headers = mock_session.request.call_args_list[1].kwargs["headers"]
            assert first_headers["Bisq-Session-Id"] == "stale-session"
            assert second_headers["Bisq-Session-Id"] == "fresh-session"

    def test_loads_auth_state_on_init_when_enabled(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"
        auth_state_file.write_text(
            json.dumps(
                {
                    "client_id": "state-client",
                    "client_secret": "state-secret",
                    "session_id": "state-session",
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
        assert api._session_id == "state-session"

    def test_auth_state_does_not_override_explicit_env_credentials(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"
        auth_state_file.write_text(
            json.dumps(
                {
                    "client_id": "state-client",
                    "client_secret": "state-secret",
                    "session_id": "state-session",
                }
            ),
            encoding="utf-8",
        )

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = "env-client"
        settings.BISQ_API_CLIENT_SECRET = "env-secret"
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)
        settings.ADMIN_API_KEY = "admin-secret"

        api = Bisq2API(settings=settings)
        api._load_auth_state()

        assert api._client_id == "env-client"
        assert api._client_secret == "env-secret"
        assert api._session_id == "state-session"

    def test_ignores_partial_auth_state_without_client_secret(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"
        auth_state_file.write_text(
            json.dumps(
                {
                    "client_id": "partial-client",
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
        settings.ADMIN_API_KEY = "admin-secret"

        api = Bisq2API(settings=settings)

        assert api._client_id == ""
        assert api._client_secret == ""
        assert api._session_id == ""

    def test_does_not_persist_partial_auth_state(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = ""
        settings.BISQ_API_CLIENT_SECRET = ""
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)
        settings.ADMIN_API_KEY = "admin-secret"

        api = Bisq2API(settings=settings)
        api._client_id = "client-only"

        api._save_auth_state()

        assert auth_state_file.exists() is False

    def test_persists_auth_state_encrypted_at_rest(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = ""
        settings.BISQ_API_CLIENT_SECRET = ""
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)
        settings.ADMIN_API_KEY = "admin-secret"

        api = Bisq2API(settings=settings)
        api._client_id = "client-id"
        api._client_secret = "client-secret"
        api._session_id = "session-id"

        api._save_auth_state()

        payload = auth_state_file.read_text(encoding="utf-8", errors="ignore")
        assert "client-secret" not in payload
        assert "session-id" not in payload

        reloaded = Bisq2API(settings=settings)
        assert reloaded._client_id == "client-id"
        assert reloaded._client_secret == "client-secret"
        assert reloaded._session_id == "session-id"

    def test_loads_plaintext_auth_state_and_rewrites_encrypted_when_secret_available(
        self, tmp_path
    ):
        auth_state_file = tmp_path / "bisq_api_auth.json"
        auth_state_file.write_text(
            json.dumps(
                {
                    "client_id": "state-client",
                    "client_secret": "state-secret",
                    "session_id": "state-session",
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
        settings.ADMIN_API_KEY = "admin-secret"

        api = Bisq2API(settings=settings)

        assert api._client_id == "state-client"
        assert api._client_secret == "state-secret"
        assert api._session_id == "state-session"
        migrated_payload = auth_state_file.read_text(encoding="utf-8", errors="ignore")
        assert "state-secret" not in migrated_payload

    def test_skips_persisting_auth_state_without_encryption_secret(self, tmp_path):
        auth_state_file = tmp_path / "bisq_api_auth.json"

        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_API_AUTH_ENABLED = True
        settings.BISQ_API_CLIENT_ID = ""
        settings.BISQ_API_CLIENT_SECRET = ""
        settings.BISQ_API_SESSION_ID = ""
        settings.BISQ_API_PAIRING_CODE_ID = ""
        settings.BISQ_API_PAIRING_QR_FILE = ""
        settings.BISQ_API_AUTH_STATE_FILE = str(auth_state_file)
        settings.ADMIN_API_KEY = ""
        settings.OPENAI_API_KEY = ""

        api = Bisq2API(settings=settings)
        api._client_id = "client-id"
        api._client_secret = "client-secret"

        api._save_auth_state()

        assert auth_state_file.exists() is False
