"""Tests for ChannelBase ABC and ChannelProtocol.

TDD tests for the plugin interface contract.
"""

import asyncio
from typing import TYPE_CHECKING, Set
from unittest.mock import MagicMock

import pytest
from app.channels.models import ChannelCapability, HealthStatus, OutgoingMessage

if TYPE_CHECKING:
    from app.channels.base import ChannelBase


class TestChannelProtocol:
    """Verify Protocol contract enforcement."""

    @pytest.mark.unit
    def test_protocol_is_runtime_checkable(self):
        """Protocol should be runtime checkable for isinstance()."""
        from app.channels.base import ChannelProtocol

        # Protocol should have __protocol_attrs__ or be runtime_checkable
        assert hasattr(ChannelProtocol, "__protocol_attrs__") or hasattr(
            ChannelProtocol, "_is_runtime_protocol"
        )

    @pytest.mark.unit
    def test_protocol_defines_channel_id_property(self):
        """Protocol must define channel_id property."""
        from app.channels.base import ChannelProtocol

        # Check protocol defines the required attributes
        assert "channel_id" in dir(ChannelProtocol)

    @pytest.mark.unit
    def test_protocol_defines_capabilities_property(self):
        """Protocol must define capabilities property."""
        from app.channels.base import ChannelProtocol

        assert "capabilities" in dir(ChannelProtocol)


class TestChannelBaseContract:
    """Verify ABC contract enforcement."""

    @pytest.mark.unit
    def test_cannot_instantiate_abstract_class(self):
        """ChannelBase should not be directly instantiable."""
        from app.channels.base import ChannelBase

        with pytest.raises(TypeError, match="abstract"):
            ChannelBase(runtime=MagicMock())

    @pytest.mark.unit
    def test_concrete_class_must_implement_all_abstract_methods(self):
        """Incomplete implementation raises TypeError."""
        from app.channels.base import ChannelBase

        class IncompleteChannel(ChannelBase):
            @property
            def channel_id(self) -> str:
                return "incomplete"

            # Missing: start, stop, send_message, capabilities

        with pytest.raises(TypeError, match="abstract"):
            IncompleteChannel(runtime=MagicMock())

    @pytest.mark.unit
    def test_complete_implementation_instantiates(self):
        """Complete implementation should instantiate successfully."""
        from app.channels.base import ChannelBase

        class CompleteChannel(ChannelBase):
            @property
            def channel_id(self) -> str:
                return "complete"

            @property
            def capabilities(self) -> Set[ChannelCapability]:
                return {ChannelCapability.RECEIVE_MESSAGES}

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_message(self, target: str, message: OutgoingMessage) -> bool:
                return True

        runtime = MagicMock()
        channel = CompleteChannel(runtime)
        assert channel.channel_id == "complete"


class TestChannelBaseRequiredMethods:
    """Verify required method signatures."""

    @pytest.fixture
    def mock_channel(self) -> "ChannelBase":
        """Create a complete test channel implementation."""
        from app.channels.base import ChannelBase

        class CompleteTestChannel(ChannelBase):
            def __init__(self, runtime):
                super().__init__(runtime)
                self.started = False
                self.stopped = False

            @property
            def channel_id(self) -> str:
                return "test"

            @property
            def capabilities(self) -> Set[ChannelCapability]:
                return {
                    ChannelCapability.RECEIVE_MESSAGES,
                    ChannelCapability.SEND_RESPONSES,
                }

            async def start(self) -> None:
                self.started = True

            async def stop(self) -> None:
                self.stopped = True

            async def send_message(self, target: str, message: OutgoingMessage) -> bool:
                return True

        return CompleteTestChannel(MagicMock())

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_method_is_async(self, mock_channel):
        """start() must be async."""
        result = mock_channel.start()
        assert asyncio.iscoroutine(result)
        await result
        assert mock_channel.started is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_stop_method_is_async(self, mock_channel):
        """stop() must be async."""
        result = mock_channel.stop()
        assert asyncio.iscoroutine(result)
        await result
        assert mock_channel.stopped is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_message_accepts_target_and_message(
        self, mock_channel, sample_outgoing_message
    ):
        """send_message(target, message) signature correct."""
        result = await mock_channel.send_message(
            target="user123", message=sample_outgoing_message
        )
        assert isinstance(result, bool)

    @pytest.mark.unit
    def test_health_check_returns_health_status(self, mock_channel):
        """health_check() returns HealthStatus dataclass."""
        # Default implementation from base class returns healthy=is_connected
        # By default _is_connected is False
        status = mock_channel.health_check()
        assert isinstance(status, HealthStatus)
        # The channel was just created, so it's not connected yet
        assert status.healthy is False
        assert "channel_id" in status.details


class TestChannelBaseProperties:
    """Verify required properties."""

    @pytest.fixture
    def mock_channel(self):
        """Create a test channel with specific capabilities."""
        from app.channels.base import ChannelBase

        class TestChannel(ChannelBase):
            @property
            def channel_id(self) -> str:
                return "test-channel-123"

            @property
            def capabilities(self) -> Set[ChannelCapability]:
                return {
                    ChannelCapability.RECEIVE_MESSAGES,
                    ChannelCapability.SEND_RESPONSES,
                    ChannelCapability.POLL_CONVERSATIONS,
                }

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_message(self, target: str, message: OutgoingMessage) -> bool:
                return True

        return TestChannel(MagicMock())

    @pytest.mark.unit
    def test_channel_id_is_string_property(self, mock_channel):
        """channel_id property returns string."""
        channel_id = mock_channel.channel_id
        assert isinstance(channel_id, str)
        assert channel_id == "test-channel-123"

    @pytest.mark.unit
    def test_capabilities_returns_capability_set(self, mock_channel):
        """capabilities returns set of ChannelCapability."""
        capabilities = mock_channel.capabilities
        assert isinstance(capabilities, set)
        assert all(isinstance(cap, ChannelCapability) for cap in capabilities)
        assert ChannelCapability.RECEIVE_MESSAGES in capabilities

    @pytest.mark.unit
    def test_is_connected_property_default_false(self, mock_channel):
        """is_connected should default to False."""
        assert mock_channel.is_connected is False


class TestChannelBaseLifecycleHooks:
    """Verify lifecycle hooks."""

    @pytest.fixture
    def channel_with_hooks(self):
        """Channel that tracks lifecycle hook calls."""
        from app.channels.base import ChannelBase

        class HookTrackingChannel(ChannelBase):
            def __init__(self, runtime):
                super().__init__(runtime)
                self.hook_calls = []
                self._is_connected = False

            @property
            def channel_id(self) -> str:
                return "hook-test"

            @property
            def capabilities(self) -> Set[ChannelCapability]:
                return {ChannelCapability.RECEIVE_MESSAGES}

            async def start(self) -> None:
                self.hook_calls.append("start")
                self._is_connected = True

            async def stop(self) -> None:
                self.hook_calls.append("stop")
                self._is_connected = False

            async def send_message(self, target: str, message: OutgoingMessage) -> bool:
                return True

            async def on_startup(self) -> None:
                self.hook_calls.append("on_startup")

            async def on_shutdown(self) -> None:
                self.hook_calls.append("on_shutdown")

            async def on_error(self, error: Exception) -> None:
                self.hook_calls.append(f"on_error:{type(error).__name__}")

        return HookTrackingChannel(MagicMock())

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_startup_hook_exists(self, channel_with_hooks):
        """on_startup() hook should exist."""
        assert hasattr(channel_with_hooks, "on_startup")
        await channel_with_hooks.on_startup()
        assert "on_startup" in channel_with_hooks.hook_calls

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_shutdown_hook_exists(self, channel_with_hooks):
        """on_shutdown() hook should exist."""
        assert hasattr(channel_with_hooks, "on_shutdown")
        await channel_with_hooks.on_shutdown()
        assert "on_shutdown" in channel_with_hooks.hook_calls

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_on_error_hook_called_on_exception(self, channel_with_hooks):
        """on_error() hook should be called when exceptions occur."""
        test_error = ValueError("test error")
        await channel_with_hooks.on_error(test_error)
        assert "on_error:ValueError" in channel_with_hooks.hook_calls


class TestChannelBaseLogging:
    """Test logging integration in ChannelBase."""

    @pytest.mark.unit
    def test_channel_has_logger(self):
        """Channel should have a logger instance."""
        from app.channels.base import ChannelBase

        class LoggingChannel(ChannelBase):
            @property
            def channel_id(self) -> str:
                return "logging-test"

            @property
            def capabilities(self) -> Set[ChannelCapability]:
                return {ChannelCapability.RECEIVE_MESSAGES}

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def send_message(self, target: str, message: OutgoingMessage) -> bool:
                return True

        channel = LoggingChannel(MagicMock())
        assert hasattr(channel, "_logger")
        assert channel._logger.name == "channel.logging-test"
