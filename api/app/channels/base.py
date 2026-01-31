"""Channel plugin base classes and protocols.

Defines the ChannelProtocol and ChannelBase ABC for channel plugins.
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, Set, runtime_checkable

from app.channels.models import ChannelCapability, HealthStatus, OutgoingMessage

if TYPE_CHECKING:
    from app.channels.runtime import ChannelRuntime


@runtime_checkable
class ChannelProtocol(Protocol):
    """Structural typing for channel plugins (duck typing friendly).

    This protocol enables isinstance() checks via @runtime_checkable
    while allowing duck typing without explicit inheritance.
    """

    @property
    def channel_id(self) -> str:
        """Unique identifier for this channel."""
        ...

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Set of capabilities this channel supports."""
        ...

    async def start(self) -> None:
        """Initialize channel resources."""
        ...

    async def stop(self) -> None:
        """Cleanup channel resources."""
        ...

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send message to target."""
        ...

    def health_check(self) -> HealthStatus:
        """Check channel health."""
        ...


class ChannelBase(ABC):
    """Base class providing common functionality for channel plugins.

    Plugins should extend this class to get shared functionality
    while implementing the abstract methods.

    Example:
        class MatrixChannel(ChannelBase):
            @property
            def channel_id(self) -> str:
                return "matrix"

            @property
            def capabilities(self) -> Set[ChannelCapability]:
                return {ChannelCapability.RECEIVE_MESSAGES, ChannelCapability.SEND_RESPONSES}

            async def start(self) -> None:
                await self._connect_to_homeserver()

            async def stop(self) -> None:
                await self._disconnect()

            async def send_message(self, target: str, message: OutgoingMessage) -> bool:
                return await self._send_to_room(target, message)
    """

    def __init__(self, runtime: "ChannelRuntime") -> None:
        """Initialize channel with runtime dependencies.

        Args:
            runtime: ChannelRuntime providing access to services and configuration.
        """
        self.runtime = runtime
        self._logger = logging.getLogger(f"channel.{self.channel_id}")
        self._is_connected = False

    @property
    @abstractmethod
    def channel_id(self) -> str:
        """Unique identifier for this channel.

        Returns:
            String identifier like "matrix", "bisq2", "web".
        """

    @property
    @abstractmethod
    def capabilities(self) -> Set[ChannelCapability]:
        """Set of capabilities this channel supports.

        Returns:
            Set of ChannelCapability enum values.
        """

    @property
    def is_connected(self) -> bool:
        """Whether channel is currently connected.

        Returns:
            True if connected, False otherwise.
        """
        return self._is_connected

    @abstractmethod
    async def start(self) -> None:
        """Initialize channel resources.

        Called during application startup. Should:
        - Establish connections
        - Initialize background tasks
        - Validate configuration

        Raises:
            ChannelStartupError: If channel fails to start.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Cleanup channel resources.

        Called during application shutdown. Should:
        - Close connections
        - Cancel background tasks
        - Flush pending data
        """

    @abstractmethod
    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send message to target.

        Args:
            target: Target identifier (user ID, room ID, etc.)
            message: OutgoingMessage to send.

        Returns:
            True if sent successfully, False otherwise.
        """

    def health_check(self) -> HealthStatus:
        """Check channel health.

        Returns:
            HealthStatus with current health information.
        """
        return HealthStatus(
            healthy=self._is_connected,
            message="Connected" if self._is_connected else "Not connected",
            details={"channel_id": self.channel_id},
        )

    async def on_startup(self) -> None:
        """Hook called before start().

        Override to perform pre-startup tasks.
        """

    async def on_shutdown(self) -> None:
        """Hook called after stop().

        Override to perform post-shutdown cleanup.
        """

    async def on_error(self, error: Exception) -> None:
        """Hook called when an error occurs.

        Args:
            error: The exception that occurred.
        """
        self._logger.error(f"Channel error: {error}", exc_info=True)
