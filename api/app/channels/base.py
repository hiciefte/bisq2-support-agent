"""Channel plugin base classes and protocols.

Defines the ChannelProtocol and ChannelBase ABC for channel plugins.
"""

import importlib.util
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, Set, runtime_checkable

from app.channels.models import (
    ChannelCapability,
    ChannelType,
    DocumentReference,
    HealthStatus,
    IncomingMessage,
    OutgoingMessage,
    ResponseMetadata,
)
from app.channels.response_builder import build_metadata, build_sources

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

    Class Attributes:
        REQUIRED_PACKAGES: Tuple of pip package names required by this channel.
            Used by check_dependencies() to verify availability.

    Example:
        @register_channel("matrix")
        class MatrixChannel(ChannelBase):
            REQUIRED_PACKAGES = ("nio",)

            @classmethod
            def setup_dependencies(cls, runtime, settings):
                from nio import AsyncClient
                client = AsyncClient(settings.MATRIX_URL, settings.MATRIX_USER)
                runtime.register("matrix_client", client)

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

    # Immutable tuple of required pip packages for this channel
    REQUIRED_PACKAGES: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def check_dependencies(cls) -> tuple[bool, list[str]]:
        """Check if required packages are available.

        Uses importlib.util.find_spec() to check package availability
        without actually importing the package.

        Returns:
            Tuple of (all_available, missing_packages).
            all_available is True if all packages are installed.
            missing_packages is a list of package names that are not installed.

        Example:
            >>> ok, missing = MatrixChannel.check_dependencies()
            >>> if not ok:
            ...     print(f"Missing packages: {missing}")
        """
        missing = []
        for package in cls.REQUIRED_PACKAGES:
            if importlib.util.find_spec(package) is None:
                missing.append(package)
        return len(missing) == 0, missing

    @classmethod
    def setup_dependencies(cls, runtime: "ChannelRuntime", settings: Any) -> None:
        """Register channel-specific dependencies in runtime.

        Override in subclasses that need external services registered
        before channel instantiation. Called by ChannelBootstrapper.

        Args:
            runtime: ChannelRuntime to register services in.
            settings: Application settings object.

        Example:
            @classmethod
            def setup_dependencies(cls, runtime, settings):
                from slack_sdk import WebClient
                client = WebClient(token=settings.SLACK_TOKEN)
                runtime.register("slack_client", client)
        """
        # Default implementation does nothing - for simple channels like Web
        pass

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
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Channel type for outgoing messages.

        Returns:
            ChannelType enum value for this channel.
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

    @abstractmethod
    def get_delivery_target(self, metadata: dict[str, Any]) -> str:
        """Extract delivery target from channel metadata.

        Args:
            metadata: Deserialized channel_metadata dict from escalation.

        Returns:
            Target identifier for outbound delivery (empty string if N/A).
        """

    @abstractmethod
    def format_escalation_message(
        self, username: str, escalation_id: int, support_handle: str
    ) -> str:
        """Format channel-specific escalation message shown to user.

        Args:
            username: User's display name or channel_user_id.
            escalation_id: Database ID of the created escalation.
            support_handle: Channel-appropriate support contact.

        Returns:
            Human-readable escalation message string.
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

    async def handle_incoming(self, message: IncomingMessage) -> OutgoingMessage:
        """Handle incoming message from channel.

        Template method that processes incoming messages through the RAG service
        and builds standardized responses. Subclasses can override helper methods
        to customize behavior without duplicating the entire flow.

        Args:
            message: Incoming message from the channel.

        Returns:
            OutgoingMessage with RAG response.
        """
        import time
        import uuid

        start_time = time.time()

        if self.runtime.rag_service is None:
            raise RuntimeError("RAG service not configured in channel runtime")

        try:
            # Build chat history for RAG service
            chat_history = self._format_chat_history(message)

            # Query RAG service
            rag_response = await self.runtime.rag_service.query(
                question=message.question,
                chat_history=chat_history,
            )

            # Build response components
            sources = self._build_sources(rag_response)
            processing_time = (time.time() - start_time) * 1000
            metadata = self._build_metadata(rag_response, processing_time)

            return OutgoingMessage(
                message_id=str(uuid.uuid4()),
                in_reply_to=message.message_id,
                channel=self.channel_type,
                answer=rag_response.get("answer", ""),
                sources=sources,
                user=message.user,
                metadata=metadata,
                original_question=message.question,
                suggested_questions=rag_response.get("suggested_questions"),
                requires_human=rag_response.get("requires_human", False),
            )
        except Exception:
            self._logger.exception(
                "Error handling incoming message for channel '%s'", self.channel_id
            )
            processing_time = (time.time() - start_time) * 1000
            return OutgoingMessage(
                message_id=str(uuid.uuid4()),
                in_reply_to=message.message_id,
                channel=self.channel_type,
                answer="I encountered an internal error while processing your request.",
                sources=[],
                user=message.user,
                metadata=ResponseMetadata(
                    processing_time_ms=processing_time,
                    rag_strategy="error",
                    model_name="unavailable",
                    tokens_used=None,
                    confidence_score=None,
                    routing_action=None,
                    detected_version=None,
                    version_confidence=None,
                    hooks_executed=[],
                ),
                suggested_questions=None,
                requires_human=True,
            )

    def _format_chat_history(self, message: IncomingMessage) -> list | None:
        """Format chat history for RAG service.

        Override in subclasses to customize chat history formatting.

        Args:
            message: Incoming message containing chat history.

        Returns:
            Formatted chat history or None if no history.
        """
        if not message.chat_history:
            return None
        return [
            {"role": msg.role, "content": msg.content} for msg in message.chat_history
        ]

    def _build_sources(self, rag_response: dict) -> list[DocumentReference]:
        """Build DocumentReference list from RAG response.

        Override in subclasses to customize source building.

        Args:
            rag_response: Response dictionary from RAG service.

        Returns:
            List of DocumentReference objects.
        """
        return build_sources(rag_response)

    def _build_metadata(
        self, rag_response: dict, processing_time_ms: float
    ) -> ResponseMetadata:
        """Build ResponseMetadata from RAG response.

        Override in subclasses to customize metadata building.

        Args:
            rag_response: Response dictionary from RAG service.
            processing_time_ms: Processing time in milliseconds.

        Returns:
            ResponseMetadata object.
        """
        return build_metadata(
            rag_response=rag_response,
            processing_time_ms=processing_time_ms,
            hooks_executed=[],
        )
