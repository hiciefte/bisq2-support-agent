"""Channel gateway hooks for pre/post processing.

Provides extensible hook system for cross-cutting concerns.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Protocol

from app.channels.models import GatewayError, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)


# =============================================================================
# Hook Priority
# =============================================================================


class HookPriority:
    """Hook execution priority (lower = earlier)."""

    CRITICAL = 0  # Security, authentication
    HIGH = 100  # Rate limiting, validation
    NORMAL = 200  # Business logic
    LOW = 300  # Logging, metrics


# =============================================================================
# Hook Protocols
# =============================================================================


class PreProcessingHook(Protocol):
    """Protocol for pre-processing hooks.

    Pre-hooks run BEFORE RAG service and can:
    - Modify the incoming message
    - Block processing by returning GatewayError
    - Add context to channel_metadata
    """

    name: str
    priority: int

    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        """Execute pre-processing logic.

        Args:
            message: Incoming message to process.

        Returns:
            None to continue processing, GatewayError to abort.
        """
        ...

    def should_skip(self, message: IncomingMessage) -> bool:
        """Check if hook should be skipped for this message."""
        ...


class PostProcessingHook(Protocol):
    """Protocol for post-processing hooks.

    Post-hooks run AFTER RAG service and can:
    - Modify the outgoing message
    - Add metadata
    - Block response by returning GatewayError
    """

    name: str
    priority: int

    async def execute(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage
    ) -> Optional[GatewayError]:
        """Execute post-processing logic.

        Args:
            incoming: Original incoming message.
            outgoing: Response message to potentially modify.

        Returns:
            None to send response, GatewayError to block.
        """
        ...

    def should_skip(self, incoming: IncomingMessage) -> bool:
        """Check if hook should be skipped for this message."""
        ...


# =============================================================================
# Base Hook Classes
# =============================================================================


class BasePreProcessingHook(ABC):
    """Base class for pre-processing hooks.

    Provides common functionality and enforces implementation.

    Example:
        class RateLimitHook(BasePreProcessingHook):
            def __init__(self, limiter):
                super().__init__(name="rate_limit", priority=HookPriority.HIGH)
                self.limiter = limiter

            async def execute(self, message):
                if not self.limiter.allow(message.user.user_id):
                    return ErrorFactory.rate_limit_exceeded(...)
                return None
    """

    def __init__(self, name: str, priority: int = HookPriority.NORMAL):
        """Initialize hook.

        Args:
            name: Hook name for identification and bypass matching.
            priority: Execution priority (lower = earlier).
        """
        self.name = name
        self.priority = priority
        self._logger = logging.getLogger(f"hook.{name}")

    @abstractmethod
    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        """Execute pre-processing logic.

        Args:
            message: Incoming message to process.

        Returns:
            None to continue processing, GatewayError to abort.
        """
        pass

    def should_skip(self, message: IncomingMessage) -> bool:
        """Check if hook should be skipped.

        Args:
            message: Message to check.

        Returns:
            True if hook should be skipped.
        """
        return self.name in message.bypass_hooks


class BasePostProcessingHook(ABC):
    """Base class for post-processing hooks.

    Provides common functionality and enforces implementation.

    Example:
        class PIIFilterHook(BasePostProcessingHook):
            def __init__(self, detector):
                super().__init__(name="pii_filter", priority=HookPriority.HIGH)
                self.detector = detector

            async def execute(self, incoming, outgoing):
                outgoing.answer = self.detector.redact(outgoing.answer)
                return None
    """

    def __init__(self, name: str, priority: int = HookPriority.NORMAL):
        """Initialize hook.

        Args:
            name: Hook name for identification and bypass matching.
            priority: Execution priority (lower = earlier).
        """
        self.name = name
        self.priority = priority
        self._logger = logging.getLogger(f"hook.{name}")

    @abstractmethod
    async def execute(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage
    ) -> Optional[GatewayError]:
        """Execute post-processing logic.

        Args:
            incoming: Original incoming message.
            outgoing: Response message to potentially modify.

        Returns:
            None to send response, GatewayError to block.
        """
        pass

    def should_skip(self, incoming: IncomingMessage) -> bool:
        """Check if hook should be skipped.

        Args:
            incoming: Message to check.

        Returns:
            True if hook should be skipped.
        """
        return self.name in incoming.bypass_hooks
