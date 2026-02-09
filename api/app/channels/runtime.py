"""Channel runtime for dependency injection.

Provides services and configuration to channel plugins.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Exceptions
# =============================================================================


class ServiceNotFoundError(Exception):
    """Raised when a service is not found in the runtime."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        super().__init__(f"Service '{service_name}' not found in runtime")


class ServiceAlreadyRegisteredError(Exception):
    """Raised when attempting to register a duplicate service."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        super().__init__(f"Service '{service_name}' is already registered")


# =============================================================================
# Service Registration Entry
# =============================================================================


class ServiceEntry:
    """Internal entry for a registered service."""

    def __init__(
        self,
        instance: Optional[Any] = None,
        factory: Optional[Callable[[], Any]] = None,
        singleton: bool = True,
    ):
        self.instance = instance
        self.factory = factory
        self.singleton = singleton
        self._cached_instance: Optional[Any] = None

    def resolve(self) -> Any:
        """Resolve the service instance."""
        if self.instance is not None:
            return self.instance

        if self.factory:
            if self.singleton:
                if self._cached_instance is None:
                    self._cached_instance = self.factory()
                return self._cached_instance
            else:
                return self.factory()

        raise ValueError("ServiceEntry has neither instance nor factory")


# =============================================================================
# Default Channel Config
# =============================================================================


class DefaultChannelConfig:
    """Default configuration for unconfigured channels."""

    enabled: bool = False
    rate_limit_per_minute: int = 60
    max_message_bytes: int = 4096


# =============================================================================
# Channel Runtime
# =============================================================================


@dataclass
class ChannelRuntime:
    """Runtime dependency container for channel plugins.

    Provides:
    - Core services (RAG, feedback, metrics)
    - Configuration access
    - Logging utilities
    - Custom service registration

    Example:
        runtime = ChannelRuntime(
            settings=settings,
            rag_service=rag_service,
        )

        # Access services in plugins
        channel = MyChannel(runtime)
        channel.runtime.rag_service.query(...)
    """

    # Core services
    settings: Any
    rag_service: Optional[Any] = None
    feedback_service: Optional[Any] = None
    metrics: Optional[Any] = None

    # Internal state
    _services: Dict[str, ServiceEntry] = field(default_factory=dict)
    _is_started: bool = field(default=False)

    @property
    def is_started(self) -> bool:
        """Whether runtime has been started."""
        return self._is_started

    async def start(self) -> None:
        """Start the runtime."""
        self._is_started = True
        logger.info("Channel runtime started")

    async def stop(self) -> None:
        """Stop the runtime."""
        self._is_started = False
        for entry in self._services.values():
            entry._cached_instance = None
        logger.info("Channel runtime stopped")

    # =========================================================================
    # Service Registration
    # =========================================================================

    def register(
        self,
        name: str,
        instance: Any,
        allow_override: bool = False,
    ) -> None:
        """Register a service instance.

        Args:
            name: Service name for resolution.
            instance: Service instance.
            allow_override: If True, allow overwriting existing registration.

        Raises:
            ServiceAlreadyRegisteredError: If name already registered and not allowing override.
        """
        if name in self._services and not allow_override:
            raise ServiceAlreadyRegisteredError(name)

        self._services[name] = ServiceEntry(instance=instance)
        logger.debug(f"Registered service '{name}'")

    def register_factory(
        self,
        name: str,
        factory: Callable[[], T],
        singleton: bool = True,
        allow_override: bool = False,
    ) -> None:
        """Register a service factory.

        Args:
            name: Service name for resolution.
            factory: Factory function that creates the service.
            singleton: If True (default), cache the instance.
            allow_override: If True, allow overwriting existing registration.

        Raises:
            ServiceAlreadyRegisteredError: If name already registered and not allowing override.
        """
        if name in self._services and not allow_override:
            raise ServiceAlreadyRegisteredError(name)

        self._services[name] = ServiceEntry(factory=factory, singleton=singleton)
        logger.debug(f"Registered service factory '{name}' (singleton={singleton})")

    def resolve(self, name: str) -> Any:
        """Resolve a registered service.

        Args:
            name: Service name.

        Returns:
            Service instance.

        Raises:
            ServiceNotFoundError: If service not registered.
        """
        if name not in self._services:
            raise ServiceNotFoundError(name)

        return self._services[name].resolve()

    def resolve_optional(self, name: str) -> Optional[Any]:
        """Resolve a service, returning None if not found.

        Args:
            name: Service name.

        Returns:
            Service instance or None.
        """
        if name not in self._services:
            return None

        return self._services[name].resolve()

    # =========================================================================
    # Logging
    # =========================================================================

    def get_logger(self, channel_id: str) -> logging.Logger:
        """Get a logger for a specific channel.

        Args:
            channel_id: Channel identifier.

        Returns:
            Logger instance with channel-specific name.
        """
        return logging.getLogger(f"channel.{channel_id}")

    # =========================================================================
    # Configuration
    # =========================================================================

    def get_channel_config(self, channel_id: str) -> Any:
        """Get channel-specific configuration.

        Args:
            channel_id: Channel identifier.

        Returns:
            Channel configuration object.
        """
        if hasattr(self.settings, "channels"):
            config = getattr(self.settings.channels, channel_id, None)
            if config is not None:
                return config

        return DefaultChannelConfig()

    def get_enabled_channels(self) -> List[str]:
        """Get list of enabled channel identifiers.

        Returns:
            List of channel IDs that are enabled.
        """
        enabled = []
        if hasattr(self.settings, "channels"):
            channels = self.settings.channels
            for channel_name in ["web", "matrix", "bisq2"]:
                config = getattr(channels, channel_name, None)
                if config and getattr(config, "enabled", False):
                    enabled.append(channel_name)
        return enabled


# =============================================================================
# Protocol for RAG Service (Dependency Inversion)
# =============================================================================


class RAGServiceProtocol(Protocol):
    """Protocol for RAG service interface.

    Channel plugins should depend on this protocol, not the concrete implementation.
    """

    async def query(
        self,
        question: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Query the RAG service.

        Args:
            question: User question.
            chat_history: Optional conversation history.

        Returns:
            Response dictionary with answer and metadata.
        """
        ...


class FeedbackServiceProtocol(Protocol):
    """Protocol for feedback service interface."""

    async def record_feedback(
        self,
        message_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> None:
        """Record user feedback."""
        ...


class MetricsProtocol(Protocol):
    """Protocol for metrics collection."""

    def record_message(self, channel: str, success: bool, latency_ms: float) -> None:
        """Record message processing metrics."""
        ...
