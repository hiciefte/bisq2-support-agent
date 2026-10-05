"""Matrix connection lifecycle management."""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from nio import AsyncClient, SyncError, SyncResponse

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    SyncError = None
    SyncResponse = None

from app.channels.plugins.matrix.metrics import matrix_connection_status

logger = logging.getLogger(__name__)


class MatrixRoomStateError(RuntimeError):
    """Initial room-state processing needs operator reconciliation."""


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

    _MAX_INITIAL_EVENTS = 1024

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
        self._sync_running = False
        self.room_state_ready = False
        self.room_state_error: str | None = None
        self._initial_events: deque[tuple[Callable[..., Awaitable[None]], Any, Any]] = (
            deque()
        )
        self.client.add_response_callback(
            self._on_sync_response, (SyncResponse, SyncError)
        )

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
        self._sync_running = False
        if self.client:
            await self.client.close()
        self.connected = False
        matrix_connection_status.set(0)  # 0 = disconnected
        logger.info(
            f"Matrix connection closed for {self.client.user_id} "
            "(session file preserved for automatic reconnection)"
        )

    def stop_sync(self) -> None:
        """Signal sync loop shutdown."""
        self._sync_running = False

    def defer_until_room_state_ready(
        self, callback: Callable[..., Awaitable[None]], room: Any, event: Any
    ) -> bool:
        """Defer in-scope message intake while nio restores joined room state.

        The first full-state response may list a source room before the staff
        room. Nio awaits each timeline callback before processing later rooms,
        so waiting for readiness inside that callback would deadlock. Retain
        only this first response's in-scope callbacks, then release in order.
        """
        if self.room_state_error is not None:
            raise MatrixRoomStateError(self.room_state_error)
        if self.room_state_ready:
            return False
        if len(self._initial_events) >= self._MAX_INITIAL_EVENTS:
            self.room_state_error = "initial_event_buffer_limit"
            raise MatrixRoomStateError(self.room_state_error)
        self._initial_events.append((callback, room, event))
        return True

    async def _on_sync_response(self, response: Any) -> None:
        if not self._sync_running or self.room_state_ready:
            return
        if isinstance(response, SyncError):
            # Nio otherwise continues with full_state=None even after a failed
            # first sync. Restart its loop with full_state=True and the same
            # saved cursor; no message or provider operation is retried.
            raise RuntimeError("Matrix initial room-state sync failed")
        if not isinstance(response, SyncResponse):
            return
        self.room_state_ready = True
        while self._initial_events:
            if not self._sync_running:
                self.room_state_ready = False
                self.room_state_error = "initial_message_dispatch_interrupted"
                raise MatrixRoomStateError(self.room_state_error)
            callback, room, event = self._initial_events.popleft()
            try:
                await callback(room, event)
            except (Exception, asyncio.CancelledError):
                # Nio persists next_batch before invoking callbacks. Never
                # silently reconnect and replay a partially dispatched buffer.
                self.room_state_ready = False
                self.room_state_error = "initial_message_dispatch_interrupted"
                raise

    def _fail_room_state(self, reason: str) -> None:
        self.room_state_error = self.room_state_error or reason
        self.room_state_ready = False
        self.connected = False
        self._sync_running = False
        matrix_connection_status.set(0)
        logger.error(
            "Matrix room-state initialization stopped: %s; "
            "%s transient message callbacks require reconciliation",
            self.room_state_error,
            len(self._initial_events),
        )

    def _sync_cursor(self) -> Any:
        return self.client.next_batch or self.client.loaded_sync_token

    async def sync_forever(
        self,
        timeout: int = 30000,
        initial_backoff_seconds: int = 5,
        max_backoff_seconds: int = 60,
    ) -> None:
        """Run Matrix sync loop with reconnect and exponential backoff."""
        backoff = max(1, initial_backoff_seconds)
        backoff_max = max(backoff, max_backoff_seconds)
        if self.room_state_error is not None or self._initial_events:
            self._fail_room_state("initial_message_buffer_pending")
            raise MatrixRoomStateError(self.room_state_error)
        self._sync_running = True

        while self._sync_running:
            bootstrap_started = False
            bootstrap_cursor = None
            try:
                if not self.connected:
                    await self.connect()
                    backoff = max(1, initial_backoff_seconds)

                self.room_state_ready = False
                bootstrap_cursor = self._sync_cursor()
                bootstrap_started = True
                # restore_login restores crypto and the cursor, not MatrixRoom
                # objects. Nio applies full_state only to its first sync request;
                # it still limits the timeline by the unchanged saved cursor.
                await self.client.sync_forever(timeout=timeout, full_state=True)

                if not self._sync_running:
                    break

                self.connected = False
                matrix_connection_status.set(0)
                logger.warning(
                    "Matrix sync loop exited unexpectedly; reconnecting in %ss",
                    backoff,
                )

            except asyncio.CancelledError:
                incomplete_delta = (
                    bootstrap_started
                    and not self.room_state_ready
                    and self._sync_cursor() != bootstrap_cursor
                )
                self.room_state_ready = False
                self.connected = False
                self._sync_running = False
                matrix_connection_status.set(0)
                if self._initial_events or self.room_state_error or incomplete_delta:
                    self._fail_room_state("initial_sync_interrupted")
                raise
            except Exception as e:
                incomplete_delta = (
                    bootstrap_started
                    and not self.room_state_ready
                    and self._sync_cursor() != bootstrap_cursor
                )
                if self._initial_events or self.room_state_error or incomplete_delta:
                    self._fail_room_state("initial_sync_processing_failed")
                    raise MatrixRoomStateError(self.room_state_error) from e
                self.room_state_ready = False
                self.connected = False
                matrix_connection_status.set(0)
                if not self._sync_running:
                    break
                logger.warning(
                    "Matrix sync loop error; reconnecting in %ss: %s",
                    backoff,
                    e,
                )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, backoff_max)

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
            and self.room_state_error is None
            and (not self._sync_running or self.room_state_ready)
        )

        if not is_healthy:
            logger.debug(
                f"Health check failed: "
                f"connected={self.connected}, "
                f"has_token={self.client.access_token is not None}, "
                f"has_device={self.client.device_id is not None}"
            )

        return is_healthy
