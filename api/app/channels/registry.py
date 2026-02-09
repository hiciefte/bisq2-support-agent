"""Channel plugin registry for registration and lifecycle management.

Provides explicit registration and lifecycle control for channel plugins.
"""

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Type, Union

from app.channels.base import ChannelBase, ChannelProtocol
from app.channels.models import HealthStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class ChannelRegistryError(Exception):
    """Base exception for channel registry errors."""

    pass


class ChannelAlreadyRegisteredError(ChannelRegistryError):
    """Raised when attempting to register a channel with duplicate ID."""

    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        super().__init__(f"Channel '{channel_id}' is already registered")


class ChannelNotFoundError(ChannelRegistryError):
    """Raised when attempting to access a non-existent channel."""

    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        super().__init__(f"Channel '{channel_id}' not found in registry")


class ChannelStartupError(ChannelRegistryError):
    """Raised when a channel fails to start."""

    def __init__(self, channel_id: str, cause: Optional[Exception] = None):
        self.channel_id = channel_id
        self.cause = cause
        msg = f"Channel '{channel_id}' failed to start"
        if cause:
            msg += f": {cause}"
        super().__init__(msg)


# =============================================================================
# Registry Entry
# =============================================================================


class RegistryEntry:
    """Internal registry entry for a channel plugin."""

    def __init__(
        self,
        plugin: Union[ChannelBase, ChannelProtocol],
        handle: str,
        priority: int = 100,
    ):
        self.plugin = plugin
        self.handle = handle
        self.priority = priority
        self.healthy = True
        self.started = False
        self.error: Optional[Exception] = None


# =============================================================================
# Channel Registry
# =============================================================================


class ChannelRegistry:
    """Registry for channel plugin management.

    Provides:
    - Plugin registration and unregistration
    - Lifecycle management (start/stop)
    - Health monitoring
    - Priority-based ordering

    Example:
        registry = ChannelRegistry()

        # Register plugins
        registry.register(web_channel)
        registry.register(matrix_channel, priority=2)
        registry.register(bisq2_channel, priority=1)

        # Start all channels
        await registry.start_all()

        # Access channels
        channel = registry.get("matrix")

        # Shutdown
        await registry.stop_all()
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._entries: Dict[str, RegistryEntry] = {}
        self._handles: Dict[str, str] = {}  # handle -> channel_id
        self._started_order: List[str] = []  # Track start order for reverse shutdown

    def register(
        self,
        plugin: Union[ChannelBase, ChannelProtocol],
        priority: int = 100,
    ) -> str:
        """Register a channel plugin.

        Args:
            plugin: Channel plugin implementing ChannelProtocol.
            priority: Start priority (lower = earlier). Default 100.

        Returns:
            Handle string for unregistration.

        Raises:
            ChannelAlreadyRegisteredError: If channel_id is already registered.
        """
        channel_id = plugin.channel_id

        if channel_id in self._entries:
            raise ChannelAlreadyRegisteredError(channel_id)

        handle = str(uuid.uuid4())
        entry = RegistryEntry(plugin=plugin, handle=handle, priority=priority)

        self._entries[channel_id] = entry
        self._handles[handle] = channel_id

        logger.info(f"Registered channel '{channel_id}' with priority {priority}")
        return handle

    def unregister(
        self,
        handle: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> None:
        """Unregister a channel plugin.

        Args:
            handle: Registration handle returned by register().
            channel_id: Channel ID to unregister.

        Raises:
            ChannelNotFoundError: If channel not found.
            ValueError: If neither handle nor channel_id provided.
        """
        if handle and handle in self._handles:
            channel_id = self._handles[handle]
        elif not channel_id:
            raise ValueError("Must provide either handle or channel_id")

        if channel_id not in self._entries:
            raise ChannelNotFoundError(channel_id)

        entry = self._entries[channel_id]
        del self._entries[channel_id]
        if entry.handle in self._handles:
            del self._handles[entry.handle]

        if channel_id in self._started_order:
            self._started_order.remove(channel_id)

        logger.info(f"Unregistered channel '{channel_id}'")

    def get(self, channel_id: str) -> Optional[Union[ChannelBase, ChannelProtocol]]:
        """Get a channel plugin by ID.

        Args:
            channel_id: Channel identifier.

        Returns:
            Channel plugin or None if not found.
        """
        entry = self._entries.get(channel_id)
        return entry.plugin if entry else None

    def get_all(self) -> List[Union[ChannelBase, ChannelProtocol]]:
        """Get all registered channel plugins.

        Returns:
            List of all channel plugins.
        """
        return [entry.plugin for entry in self._entries.values()]

    def list_channel_ids(self) -> List[str]:
        """List all registered channel IDs.

        Returns:
            List of channel ID strings.
        """
        return list(self._entries.keys())

    def get_status(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific channel.

        Args:
            channel_id: Channel identifier.

        Returns:
            Status dictionary or None if not found.
        """
        entry = self._entries.get(channel_id)
        if not entry:
            return None

        return {
            "channel_id": channel_id,
            "is_connected": (
                entry.plugin.is_connected
                if hasattr(entry.plugin, "is_connected")
                else False
            ),
            "healthy": entry.healthy,
            "started": entry.started,
            "priority": entry.priority,
            "error": str(entry.error) if entry.error else None,
        }

    async def start_all(
        self,
        timeout: float = 30.0,
        continue_on_error: bool = False,
    ) -> List[Exception]:
        """Start all registered channels in priority order.

        Args:
            timeout: Timeout in seconds for each channel start.
            continue_on_error: If True, continue starting other channels on failure.

        Returns:
            List of errors that occurred (empty if all succeeded).

        Raises:
            ChannelStartupError: If a channel fails to start and continue_on_error is False.
        """
        errors: List[Exception] = []

        # Sort by priority (lower = earlier)
        sorted_entries = sorted(self._entries.items(), key=lambda x: x[1].priority)

        for channel_id, entry in sorted_entries:
            try:
                # Call on_startup hook if available
                if hasattr(entry.plugin, "on_startup"):
                    await entry.plugin.on_startup()

                # Start with timeout
                await asyncio.wait_for(entry.plugin.start(), timeout=timeout)

                entry.started = True
                entry.healthy = True
                self._started_order.append(channel_id)
                logger.info(f"Started channel '{channel_id}'")

            except asyncio.TimeoutError as e:
                entry.healthy = False
                entry.error = e
                error = ChannelStartupError(channel_id, e)
                errors.append(error)
                logger.exception(
                    f"Channel '{channel_id}' start timed out after {timeout}s"
                )

                if not continue_on_error:
                    raise error from e

            except Exception as e:
                entry.healthy = False
                entry.error = e
                error = ChannelStartupError(channel_id, e)
                errors.append(error)
                logger.exception(f"Channel '{channel_id}' failed to start")

                if not continue_on_error:
                    raise error from e

        return errors

    async def stop_all(self, timeout: float = 30.0) -> List[Exception]:
        """Stop all channels in reverse start order.

        Args:
            timeout: Timeout in seconds for each channel stop.

        Returns:
            List of errors that occurred during shutdown.
        """
        errors: List[Exception] = []

        # Stop in reverse order
        for channel_id in reversed(self._started_order.copy()):
            entry = self._entries.get(channel_id)
            if not entry:
                continue

            try:
                await asyncio.wait_for(entry.plugin.stop(), timeout=timeout)
                entry.started = False

                # Call on_shutdown hook if available
                if hasattr(entry.plugin, "on_shutdown"):
                    await entry.plugin.on_shutdown()

                logger.info(f"Stopped channel '{channel_id}'")

            except Exception as e:
                entry.error = e
                errors.append(e)
                logger.error(f"Channel '{channel_id}' stop error: {e}")

        self._started_order.clear()
        return errors

    async def restart(self, channel_id: str, timeout: float = 30.0) -> None:
        """Restart a specific channel.

        Args:
            channel_id: Channel identifier.
            timeout: Timeout for start/stop operations.

        Raises:
            ChannelNotFoundError: If channel not found.
        """
        entry = self._entries.get(channel_id)
        if not entry:
            raise ChannelNotFoundError(channel_id)

        # Stop if running
        if entry.started:
            await asyncio.wait_for(entry.plugin.stop(), timeout=timeout)
            if hasattr(entry.plugin, "on_shutdown"):
                await entry.plugin.on_shutdown()
            entry.started = False
            if channel_id in self._started_order:
                self._started_order.remove(channel_id)

        # Start
        if hasattr(entry.plugin, "on_startup"):
            await entry.plugin.on_startup()
        await asyncio.wait_for(entry.plugin.start(), timeout=timeout)
        entry.started = True
        entry.healthy = True
        self._started_order.append(channel_id)

        logger.info(f"Restarted channel '{channel_id}'")

    def health_check(self, channel_id: str) -> HealthStatus:
        """Run health check on a specific channel.

        Args:
            channel_id: Channel identifier.

        Returns:
            HealthStatus from the channel.

        Raises:
            ChannelNotFoundError: If channel not found.
        """
        entry = self._entries.get(channel_id)
        if not entry:
            raise ChannelNotFoundError(channel_id)

        return entry.plugin.health_check()

    def health_check_all(self) -> Dict[str, HealthStatus]:
        """Run health checks on all channels.

        Returns:
            Dictionary mapping channel_id to HealthStatus.
        """
        results = {}
        for channel_id, entry in self._entries.items():
            results[channel_id] = entry.plugin.health_check()
        return results


# =============================================================================
# Decorator for Channel Registration
# =============================================================================

# Module-level registry for decorator-based registration
_CHANNEL_TYPES: Dict[str, Type[ChannelBase]] = {}


def register_channel(
    channel_type: str,
) -> Callable[[Type[ChannelBase]], Type[ChannelBase]]:
    """Decorator for registering channel classes.

    Example:
        @register_channel("matrix")
        class MatrixChannel(ChannelBase):
            ...

    Args:
        channel_type: Channel type identifier.

    Returns:
        Decorator function.
    """

    def decorator(cls: Type[ChannelBase]) -> Type[ChannelBase]:
        _CHANNEL_TYPES[channel_type] = cls
        return cls

    return decorator


def get_registered_channel_types() -> Dict[str, Type[ChannelBase]]:
    """Get all registered channel type classes.

    Returns:
        Dictionary mapping channel type to class.
    """
    return _CHANNEL_TYPES.copy()
