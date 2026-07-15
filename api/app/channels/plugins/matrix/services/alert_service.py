"""Matrix alert service for Prometheus Alertmanager notifications.

This service sends alerts from Prometheus Alertmanager to a dedicated
Matrix room. It uses the same authentication infrastructure as the
Matrix sync service but targets a separate alert room.

Architecture:
    Alertmanager -> POST /alertmanager/alerts -> MatrixAlertService -> Matrix room
"""

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from app.channels.plugins.support_markdown import build_matrix_message_content
from app.metrics.privacy_metrics import record_privacy_retention_run

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
ALERT_RELAY_RETENTION_STORE = "matrix_alert_relay_session"


@runtime_checkable
class MatrixAlertSettings(Protocol):
    """Protocol defining required settings for Matrix alerting.

    This Protocol enables static type checking while allowing any
    settings object that has the required attributes (structural subtyping).

    Attributes:
        MATRIX_HOMESERVER_URL: Matrix homeserver URL (e.g., https://matrix.org)
        MATRIX_ALERT_USER: Matrix alert bot user ID (e.g., @alerts-bot:matrix.org)
        MATRIX_ALERT_ROOM: Room ID for alert notifications
    """

    MATRIX_HOMESERVER_URL: str
    MATRIX_ALERT_USER: str
    MATRIX_ALERT_PASSWORD: str
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
        self._lifecycle_lock = asyncio.Lock()

    def _get_session_path(self) -> str:
        """Get the session file path for alert service.

        Priority:
        1. MATRIX_ALERT_SESSION_FILE_PATH (optional resolved path)
        2. MATRIX_ALERT_SESSION_FILE (optional explicit file)
        3. Derived from MATRIX_SYNC_SESSION_FILE directory using
           "matrix_alert_session.json" as the filename
        4. Default fallback path

        Returns:
            Path to the alert session file
        """
        # 1. Preferred resolved alert session path
        explicit_path = getattr(self.settings, "MATRIX_ALERT_SESSION_FILE_PATH", None)
        if isinstance(explicit_path, str) and explicit_path.strip():
            return explicit_path

        explicit_file = getattr(self.settings, "MATRIX_ALERT_SESSION_FILE", None)
        if isinstance(explicit_file, str) and explicit_file.strip():
            return explicit_file

        # 2. Derive from Matrix sync session file directory
        session_file = getattr(self.settings, "MATRIX_SYNC_SESSION_FILE", None)
        if isinstance(session_file, str) and session_file.strip():
            directory = os.path.dirname(session_file)
            if directory:
                return os.path.join(directory, "matrix_alert_session.json")

        # 3. Default fallback
        return DEFAULT_ALERT_SESSION_PATH

    def _get_alert_user(self) -> str:
        resolved = getattr(self.settings, "MATRIX_ALERT_USER_RESOLVED", None)
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
        value = getattr(self.settings, "MATRIX_ALERT_USER", None)
        return value.strip() if isinstance(value, str) else ""

    def _get_alert_password(self) -> str:
        resolved = getattr(self.settings, "MATRIX_ALERT_PASSWORD_RESOLVED", None)
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
        value = getattr(self.settings, "MATRIX_ALERT_PASSWORD", None)
        return value.strip() if isinstance(value, str) else ""

    def is_configured(self) -> bool:
        """Check if Matrix alerting is configured.

        Returns:
            True if the complete password-authenticated alert lane is configured
        """
        homeserver_value = getattr(self.settings, "MATRIX_HOMESERVER_URL", "")
        alert_room_value = getattr(self.settings, "MATRIX_ALERT_ROOM", "")
        homeserver = (
            homeserver_value.strip() if isinstance(homeserver_value, str) else ""
        )
        alert_room = (
            alert_room_value.strip() if isinstance(alert_room_value, str) else ""
        )
        return bool(
            homeserver
            and alert_room
            and self._get_alert_user()
            and self._get_alert_password()
            and NIO_AVAILABLE
        )

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
            user_id = self._get_alert_user()
            password = self._get_alert_password()
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
            async with self._lifecycle_lock:
                client = await self._get_client()

                # Send the message
                response = await client.room_send(
                    room_id=alert_room,
                    message_type="m.room.message",
                    content=build_matrix_message_content(message),
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

    async def close(self, *, strict: bool = False) -> None:
        """Close the alert client without racing sends or rotation."""
        async with self._lifecycle_lock:
            await self._close_unlocked(strict=strict)

    async def _close_unlocked(self, *, strict: bool = False) -> None:
        """Close the Matrix client connection.

        Uses ConnectionManager.disconnect() to properly update metrics
        and connection state flags.
        """
        try:
            if self._connection_manager is not None:
                await self._connection_manager.disconnect()
            elif self._client is not None:
                await self._client.close()
        except Exception as error:
            logger.warning("Error closing Matrix alert client")
            if strict:
                raise RuntimeError(
                    "Matrix alert client did not close cleanly"
                ) from error
        else:
            self._client = None
            self._connection_manager = None
            self._session_manager = None

    async def rotate_expired_session(self, *, dry_run: bool = False) -> int:
        """Rotate the relay session generation after the privacy window."""
        from app.services.privacy_retention_service import (
            prune_matrix_session_artifacts,
        )

        retention_days = int(getattr(self.settings, "DATA_RETENTION_DAYS", 30))
        session_file = Path(self._get_session_path())
        run_at = datetime.now(UTC)
        preview = prune_matrix_session_artifacts(
            session_file=session_file,
            retention_days=retention_days,
            now=run_at,
            dry_run=True,
        )
        if dry_run:
            return preview.deleted_rows
        if not preview.deleted_rows:
            record_privacy_retention_run(
                stores={ALERT_RELAY_RETENTION_STORE: preview},
                successful_store_groups=(ALERT_RELAY_RETENTION_STORE,),
                run_at=run_at.timestamp(),
            )
            return 0

        async with self._lifecycle_lock:
            await self._close_unlocked(strict=True)
            result = prune_matrix_session_artifacts(
                session_file=session_file,
                retention_days=retention_days,
                now=datetime.now(UTC),
            )
        record_privacy_retention_run(
            stores={ALERT_RELAY_RETENTION_STORE: result},
            successful_store_groups=(ALERT_RELAY_RETENTION_STORE,),
            run_at=datetime.now(UTC).timestamp(),
        )
        return result.deleted_rows
