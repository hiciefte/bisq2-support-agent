"""Authentication middleware hook.

Implements channel-specific authentication requirements.
"""

import logging
from typing import Optional, Set

from app.channels.hooks import BasePreProcessingHook, HookPriority
from app.channels.models import ChannelType, GatewayError, IncomingMessage
from app.channels.security import ErrorFactory

logger = logging.getLogger(__name__)


# Channels that require authentication
AUTHENTICATED_CHANNELS = {
    ChannelType.BISQ2,
    ChannelType.MATRIX,
}


class AuthenticationHook(BasePreProcessingHook):
    """Pre-processing hook for authentication.

    Validates authentication tokens for channels that require it.

    Args:
        valid_tokens: Set of valid tokens for validation.
        skip_channels: Channels to skip authentication for.
    """

    def __init__(
        self,
        valid_tokens: Optional[Set[str]] = None,
        skip_channels: Optional[Set[ChannelType]] = None,
    ):
        """Initialize authentication hook.

        Args:
            valid_tokens: Set of valid authentication tokens.
            skip_channels: Channels to skip authentication for.
        """
        super().__init__(name="authentication", priority=HookPriority.CRITICAL)
        self._valid_tokens = valid_tokens or set()
        self._skip_channels = skip_channels or {ChannelType.WEB}

        if not self._valid_tokens:
            self._logger.warning(
                "AuthenticationHook initialized without valid_tokens. "
                "Any non-empty token will be accepted for authenticated channels "
                "not in skip_channels."
            )

    async def execute(self, message: IncomingMessage) -> Optional[GatewayError]:
        """Validate authentication for incoming message.

        Args:
            message: Incoming message to authenticate.

        Returns:
            None if authenticated, GatewayError if auth failed.
        """
        # Skip authentication for allowed channels
        if message.channel in self._skip_channels:
            self._logger.debug(f"Authentication skipped for channel {message.channel}")
            return None

        # Check if channel requires authentication
        if message.channel not in AUTHENTICATED_CHANNELS:
            return None

        # Validate token
        token = message.user.auth_token

        if not token:
            self._logger.warning(
                f"Authentication failed for {message.channel}: no token provided"
            )
            return ErrorFactory.authentication_failed(
                "No authentication token provided"
            )

        if self._valid_tokens and token not in self._valid_tokens:
            self._logger.warning(
                f"Authentication failed for {message.channel}: invalid token"
            )
            return ErrorFactory.authentication_failed("Invalid authentication token")

        self._logger.debug(f"Authentication successful for {message.channel}")
        return None
