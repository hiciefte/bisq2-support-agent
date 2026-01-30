"""Matrix alert service for Prometheus Alertmanager notifications.

This service sends alerts from Prometheus Alertmanager to a dedicated
Matrix room. It uses the same authentication infrastructure as the
Matrix sync service but targets a separate alert room.

Architecture:
    Alertmanager -> POST /alertmanager/alerts -> MatrixAlertService -> Matrix room
"""

import logging
import re
from typing import Any, Optional

try:
    from nio import AsyncClient, RoomSendResponse

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    RoomSendResponse = None

logger = logging.getLogger(__name__)


class MatrixAlertService:
    """Service for sending alerts to a Matrix room.

    This service is specifically for Alertmanager notifications and uses
    a dedicated MATRIX_ALERT_ROOM separate from the support rooms monitored
    by MatrixSyncService.

    Attributes:
        settings: Application settings with Matrix configuration
    """

    def __init__(self, settings: Any):
        """Initialize Matrix alert service.

        Args:
            settings: Application settings with Matrix configuration
        """
        self.settings = settings
        self._client: Optional["AsyncClient"] = None
        self._connection_manager: Optional[Any] = None
        self._session_manager: Optional[Any] = None

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

        Returns:
            Authenticated AsyncClient instance

        Raises:
            ImportError: If matrix-nio is not installed
            Exception: If connection fails
        """
        if not NIO_AVAILABLE:
            raise ImportError("matrix-nio is not installed")

        if self._client is not None:
            return self._client

        # Import here to avoid circular imports
        from app.integrations.matrix.connection_manager import ConnectionManager
        from app.integrations.matrix.session_manager import SessionManager

        homeserver = self.settings.MATRIX_HOMESERVER_URL
        user_id = self.settings.MATRIX_USER
        password = getattr(self.settings, "MATRIX_PASSWORD", "")
        session_path = getattr(
            self.settings, "MATRIX_SESSION_PATH", "/data/matrix_alert_session.json"
        )

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

        except Exception as e:
            logger.exception(f"Error sending alert to Matrix: {e}")
            return False

    def _markdown_to_html(self, text: str) -> str:
        """Convert simple markdown to HTML for Matrix formatting.

        Args:
            text: Text with simple markdown (bold, newlines)

        Returns:
            HTML formatted text
        """
        # Convert **bold** to <strong>bold</strong>
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        # Convert newlines to <br>
        html = html.replace("\n", "<br>")
        return html

    async def close(self) -> None:
        """Close the Matrix client connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.warning(f"Error closing Matrix alert client: {e}")
            finally:
                self._client = None
                self._connection_manager = None
                self._session_manager = None
