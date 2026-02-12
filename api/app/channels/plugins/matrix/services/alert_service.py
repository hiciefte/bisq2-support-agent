"""Matrix alert service for Prometheus Alertmanager notifications.

This service sends alerts from Prometheus Alertmanager to a dedicated
Matrix room. It uses the same authentication infrastructure as the
Matrix sync service but targets a separate alert room.

Architecture:
    Alertmanager -> POST /alertmanager/alerts -> MatrixAlertService -> Matrix room
"""

import asyncio
import html
import logging
import os
import re
from typing import Any, Optional, Protocol, runtime_checkable

try:
    from nio import AsyncClient, RoomSendResponse

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    RoomSendResponse = None

logger = logging.getLogger(__name__)

# Default session path for Docker environments
DEFAULT_ALERT_SESSION_PATH = "/data/matrix_alert_session.json"


@runtime_checkable
class MatrixAlertSettings(Protocol):
    """Protocol defining required settings for Matrix alerting.

    This Protocol enables static type checking while allowing any
    settings object that has the required attributes (structural subtyping).

    Attributes:
        MATRIX_HOMESERVER_URL: Matrix homeserver URL (e.g., https://matrix.org)
        MATRIX_USER: Matrix bot user ID (e.g., @bot:matrix.org)
        MATRIX_ALERT_ROOM: Room ID for alert notifications
    """

    MATRIX_HOMESERVER_URL: str
    MATRIX_USER: str
    MATRIX_ALERT_ROOM: str


class MatrixAlertService:
    """Service for sending alerts to a Matrix room.

    This service is specifically for Alertmanager notifications and uses
    a dedicated MATRIX_ALERT_ROOM separate from the support rooms monitored
    by MatrixSyncService.

    Attributes:
        settings: Application settings with Matrix configuration
    """

    def __init__(self, settings: MatrixAlertSettings):
        """Initialize Matrix alert service.

        Args:
            settings: Application settings satisfying MatrixAlertSettings Protocol
        """
        self.settings = settings
        self._client: Optional["AsyncClient"] = None
        self._connection_manager: Optional[Any] = None
        self._session_manager: Optional[Any] = None
        self._init_lock = asyncio.Lock()

    def _get_session_path(self) -> str:
        """Get the session file path for alert service.

        Priority:
        1. Explicit MATRIX_ALERT_SESSION_PATH if set
        2. Derived from MATRIX_SESSION_FILE directory (same dir, different filename)
        3. Default fallback path

        Returns:
            Path to the alert session file
        """
        # 1. Check for explicit alert session path
        explicit_path = getattr(self.settings, "MATRIX_ALERT_SESSION_PATH", None)
        if explicit_path:
            return explicit_path

        # 2. Derive from MATRIX_SESSION_FILE directory
        session_file = getattr(self.settings, "MATRIX_SESSION_FILE", None)
        if session_file:
            directory = os.path.dirname(session_file)
            if directory:
                return os.path.join(directory, "matrix_alert_session.json")

        # 3. Default fallback
        return DEFAULT_ALERT_SESSION_PATH

    def is_configured(self) -> bool:
        """Check if Matrix alerting is configured.

        Returns:
            True if homeserver and alert room are configured
        """
        homeserver = getattr(self.settings, "MATRIX_HOMESERVER_URL", "") or ""
        alert_room = getattr(self.settings, "MATRIX_ALERT_ROOM", "") or ""
        return bool(homeserver.strip()) and bool(alert_room.strip())

    async def _get_client(self) -> "AsyncClient":
        """Get or create authenticated Matrix client.

        Thread-safe initialization using asyncio.Lock to prevent
        concurrent connection attempts. Failed connections clean up
        partial state to allow retry.

        Returns:
            Authenticated AsyncClient instance

        Raises:
            ImportError: If matrix-nio is not installed
            Exception: If connection fails
        """
        if not NIO_AVAILABLE:
            raise ImportError("matrix-nio is not installed")

        # Fast path: already initialized
        if self._client is not None:
            return self._client

        # Serialize initialization to prevent concurrent connection attempts
        async with self._init_lock:
            # Double-check after acquiring lock (another task may have initialized)
            if self._client is not None:
                return self._client

            # Import here to avoid circular imports
            from app.channels.plugins.matrix.client.connection_manager import (
                ConnectionManager,
            )
            from app.channels.plugins.matrix.client.session_manager import (
                SessionManager,
            )

            homeserver = self.settings.MATRIX_HOMESERVER_URL
            user_id = self.settings.MATRIX_USER
            password = getattr(self.settings, "MATRIX_PASSWORD", "")
            session_path = self._get_session_path()

            try:
                # Create client
                self._client = AsyncClient(homeserver, user_id)

                # Create session manager for password-based auth
                self._session_manager = SessionManager(
                    client=self._client,
                    password=password,
                    session_file=session_path,
                )

                # Create connection manager
                self._connection_manager = ConnectionManager(
                    client=self._client,
                    session_manager=self._session_manager,
                )

                # Connect (handles login and session persistence)
                await self._connection_manager.connect()

                return self._client

            except Exception:
                # Clean up partial state on failure to allow retry
                self._client = None
                self._connection_manager = None
                self._session_manager = None
                raise

    async def send_alert_message(self, message: str) -> bool:
        """Send an alert message to the Matrix alert room.

        Args:
            message: The formatted alert message to send

        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.debug("Matrix alerting not configured, skipping alert")
            return False

        if not NIO_AVAILABLE:
            logger.warning("matrix-nio not installed, cannot send alert")
            return False

        alert_room = self.settings.MATRIX_ALERT_ROOM

        try:
            client = await self._get_client()

            # Send the message
            response = await client.room_send(
                room_id=alert_room,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": message,
                    "format": "org.matrix.custom.html",
                    "formatted_body": self._markdown_to_html(message),
                },
            )

            if isinstance(response, RoomSendResponse):
                logger.info(f"Alert sent to Matrix room {alert_room}")
                return True
            else:
                logger.error(f"Failed to send alert to Matrix: {response}")
                return False

        except Exception:
            logger.exception("Error sending alert to Matrix")
            return False

    def _markdown_to_html(self, text: str) -> str:
        """Convert simple markdown to HTML for Matrix formatting.

        Args:
            text: Text with simple markdown (bold, newlines)

        Returns:
            HTML formatted text with special characters escaped
        """
        # First escape HTML special characters to prevent XSS
        escaped = html.escape(text)
        # Convert **bold** to <strong>bold</strong>
        result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        # Convert newlines to <br>
        result = result.replace("\n", "<br>")
        return result

    async def close(self) -> None:
        """Close the Matrix client connection.

        Uses ConnectionManager.disconnect() to properly update metrics
        and connection state flags.
        """
        try:
            if self._connection_manager is not None:
                await self._connection_manager.disconnect()
            elif self._client is not None:
                await self._client.close()
        except Exception:
            logger.warning("Error closing Matrix alert client")
        finally:
            self._client = None
            self._connection_manager = None
            self._session_manager = None
