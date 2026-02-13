"""Matrix connection lifecycle management."""

import logging

try:
    from nio import AsyncClient

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None

from app.channels.plugins.matrix.metrics import matrix_connection_status

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages Matrix connection lifecycle and health checks.

    Provides:
    - Graceful connection establishment with error handling
    - Connection health monitoring
    - Clean shutdown handling
    - Container restart resilience

    Attributes:
        client: Matrix AsyncClient instance
        session_manager: SessionManager for authentication
        connected: Connection status flag
    """

    def __init__(self, client: "AsyncClient", session_manager):
        """Initialize connection manager.

        Args:
            client: Matrix AsyncClient instance
            session_manager: SessionManager for authentication
        """
        if not NIO_AVAILABLE:
            raise ImportError(
                "matrix-nio is not installed. Install with: pip install matrix-nio"
            )

        self.client = client
        self.session_manager = session_manager
        self.connected = False

    async def connect(self) -> None:
        """Establish Matrix connection with authentication.

        Performs login via SessionManager and marks connection as established.
        Container restart triggers automatic session restoration if session
        file exists.

        Raises:
            Exception: If authentication fails
        """
        try:
            await self.session_manager.login()
            self.connected = True
            matrix_connection_status.set(1)  # 1 = connected
            logger.info(
                f"Matrix connection established to {self.client.homeserver} "
                f"for {self.client.user_id}"
            )
        except Exception as e:
            logger.error(f"Matrix connection failed to {self.client.homeserver}: {e}")
            self.connected = False
            matrix_connection_status.set(0)  # 0 = disconnected
            raise

    async def disconnect(self) -> None:
        """Clean shutdown of Matrix connection.

        Closes Matrix client connection gracefully. Does NOT delete
        session file - allows automatic reconnection on next startup.
        """
        if self.client:
            await self.client.close()
        self.connected = False
        matrix_connection_status.set(0)  # 0 = disconnected
        logger.info(
            f"Matrix connection closed for {self.client.user_id} "
            "(session file preserved for automatic reconnection)"
        )

    def health_check(self) -> bool:
        """Check if connection is healthy.

        Validates:
        - Connection flag is True
        - Access token is set (authenticated)
        - Device ID is set (session established)

        Returns:
            True if connection is healthy, False otherwise
        """
        is_healthy = (
            self.connected
            and self.client.access_token is not None
            and self.client.device_id is not None
        )

        if not is_healthy:
            logger.debug(
                f"Health check failed: "
                f"connected={self.connected}, "
                f"has_token={self.client.access_token is not None}, "
                f"has_device={self.client.device_id is not None}"
            )

        return is_healthy
