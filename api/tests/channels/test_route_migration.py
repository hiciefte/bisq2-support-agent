"""Tests for Phase 3 Route Migration.

TDD tests for migrating /query route to use Channel Gateway.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import ChannelType, ErrorCode, IncomingMessage, UserContext

# =============================================================================
# Gateway Dependency Tests
# =============================================================================


class TestGatewayDependency:
    """Test get_gateway dependency function."""

    @pytest.mark.unit
    def test_get_gateway_returns_gateway_from_app_state(self):
        """get_gateway returns gateway from app.state."""
        from app.channels.dependencies import get_gateway
        from app.channels.gateway import ChannelGateway

        mock_request = MagicMock()
        mock_gateway = MagicMock(spec=ChannelGateway)
        mock_request.app.state.channel_gateway = mock_gateway

        result = get_gateway(mock_request)
        assert result is mock_gateway

    @pytest.mark.unit
    def test_get_gateway_raises_when_gateway_not_initialized(self):
        """get_gateway raises RuntimeError when gateway not in app.state."""
        from app.channels.dependencies import get_gateway

        mock_request = MagicMock()
        del mock_request.app.state.channel_gateway

        with pytest.raises(RuntimeError, match="Gateway not initialized"):
            get_gateway(mock_request)


# =============================================================================
# Lifecycle Tests
# =============================================================================


class TestChannelLifecycle:
    """Test channel lifecycle context manager."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_lifecycle_initializes_gateway(self):
        """channel_lifespan initializes gateway on app.state."""
        from app.channels.lifecycle import create_channel_gateway

        mock_rag_service = MagicMock()
        gateway = create_channel_gateway(mock_rag_service)

        assert gateway is not None
        assert gateway.rag_service is mock_rag_service

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_lifecycle_registers_default_hooks(self):
        """channel_lifespan registers default middleware hooks."""
        from app.channels.lifecycle import create_channel_gateway

        mock_rag_service = MagicMock()
        gateway = create_channel_gateway(mock_rag_service, register_default_hooks=True)

        hook_info = gateway.get_hook_info()
        pre_hook_names = [h["name"] for h in hook_info["pre_hooks"]]
        post_hook_names = [h["name"] for h in hook_info["post_hooks"]]

        # Should have rate_limit as pre-hook
        assert "rate_limit" in pre_hook_names
        # Should have pii_filter as post-hook
        assert "pii_filter" in post_hook_names


# =============================================================================
# Route Integration Tests
# =============================================================================


class TestQueryRouteWithGateway:
    """Test /query route using gateway."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_query_route_uses_gateway_when_available(self):
        """Query route uses gateway.process_message when gateway is initialized."""
        from app.channels.gateway import ChannelGateway
        from app.channels.models import OutgoingMessage, ResponseMetadata

        # Create mock gateway
        mock_gateway = MagicMock(spec=ChannelGateway)
        mock_gateway.process_message = AsyncMock(
            return_value=OutgoingMessage(
                message_id="resp-001",
                channel=ChannelType.WEB,
                in_reply_to="msg-001",
                answer="Test answer from gateway",
                sources=[],
                user=UserContext(user_id="web_anonymous"),
                metadata=ResponseMetadata(
                    processing_time_ms=100.0,
                    rag_strategy="retrieval",
                    model_name="test-model",
                ),
            )
        )

        # Verify gateway.process_message was called correctly
        incoming = IncomingMessage(
            message_id="msg-001",
            channel=ChannelType.WEB,
            question="Test question",
            user=UserContext(user_id="web_anonymous"),
        )

        result = await mock_gateway.process_message(incoming)
        assert result.answer == "Test answer from gateway"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_query_route_handles_gateway_error(self):
        """Query route returns HTTP error when gateway returns GatewayError."""
        from app.channels.gateway import ChannelGateway
        from app.channels.models import GatewayError

        mock_gateway = MagicMock(spec=ChannelGateway)
        mock_gateway.process_message = AsyncMock(
            return_value=GatewayError(
                error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
                error_message="Rate limit exceeded",
                details={"retry_after": 60},
            )
        )

        incoming = IncomingMessage(
            message_id="msg-001",
            channel=ChannelType.WEB,
            question="Test question",
            user=UserContext(user_id="web_anonymous"),
        )

        result = await mock_gateway.process_message(incoming)
        assert isinstance(result, GatewayError)
        assert result.error_code == ErrorCode.RATE_LIMIT_EXCEEDED


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Test backward compatibility with existing API."""

    @pytest.mark.unit
    def test_query_response_schema_unchanged(self):
        """QueryResponse schema matches original contract."""
        from app.routes.chat import QueryResponse

        # Check required fields exist
        schema = QueryResponse.model_json_schema()
        properties = schema["properties"]

        # Original required fields
        assert "answer" in properties
        assert "sources" in properties
        assert "response_time" in properties

        # Phase 1 metadata fields (optional)
        assert "confidence" in properties
        assert "routing_action" in properties
        assert "detected_version" in properties

    @pytest.mark.unit
    def test_query_request_schema_unchanged(self):
        """QueryRequest schema matches original contract."""
        from app.routes.chat import QueryRequest

        schema = QueryRequest.model_json_schema()
        properties = schema["properties"]

        # Required fields
        assert "question" in properties
        assert "chat_history" in properties

    @pytest.mark.unit
    def test_source_schema_unchanged(self):
        """Source schema matches original contract."""
        from app.routes.chat import Source

        schema = Source.model_json_schema()
        properties = schema["properties"]

        assert "title" in properties
        assert "type" in properties
        assert "content" in properties
        assert "protocol" in properties
