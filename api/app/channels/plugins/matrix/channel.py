"""Matrix Channel Plugin.

Wraps existing Matrix integration into channel plugin architecture.
"""

from typing import Set

from app.channels.base import ChannelBase
from app.channels.models import ChannelCapability, ChannelType, OutgoingMessage


class MatrixChannel(ChannelBase):
    """Matrix protocol channel for federated chat.

    This plugin wraps the existing Matrix integration to work with
    the channel plugin architecture. The Matrix channel:
    - Maintains persistent connection to Matrix homeserver via ConnectionManager
    - Receives messages from configured rooms
    - Sends responses back to Matrix rooms via nio AsyncClient

    The channel uses ChannelRuntime to resolve dependencies:
    - "matrix_connection_manager": ConnectionManager for connection lifecycle
    - "matrix_client": nio AsyncClient for room operations

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        runtime.register("matrix_connection_manager", connection_manager)
        runtime.register("matrix_client", async_client)

        channel = MatrixChannel(runtime)
        await channel.start()

        # Channel will receive messages via callbacks
        # handle_incoming is called when new messages arrive
    """

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "matrix"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities."""
        return {
            ChannelCapability.TEXT_MESSAGES,
            ChannelCapability.CHAT_HISTORY,
            ChannelCapability.PERSISTENT_CONNECTION,
            ChannelCapability.RECEIVE_MESSAGES,
            ChannelCapability.SEND_RESPONSES,
        }

    @property
    def channel_type(self) -> ChannelType:
        """Return channel type for outgoing messages."""
        return ChannelType.MATRIX

    async def start(self) -> None:
        """Start the Matrix channel.

        Connects to Matrix homeserver via ConnectionManager. If ConnectionManager
        is not registered in the runtime, the channel will start in degraded mode
        (not connected).
        """
        self._logger.info("Starting Matrix channel")

        # Get ConnectionManager from runtime
        conn_manager = self.runtime.resolve_optional("matrix_connection_manager")
        if not conn_manager:
            self._logger.warning(
                "Matrix ConnectionManager not registered in runtime. "
                "Channel will start but connection will be unavailable."
            )
            self._is_connected = False
            return

        # Connect via ConnectionManager
        try:
            await conn_manager.connect()
            self._is_connected = True
            self._logger.info("Matrix channel started - connection established")
        except Exception as e:
            self._logger.error(f"Failed to connect to Matrix homeserver: {e}")
            self._is_connected = False

    async def stop(self) -> None:
        """Stop the Matrix channel.

        Disconnects from homeserver gracefully via ConnectionManager.
        """
        self._logger.info("Stopping Matrix channel")

        # Get ConnectionManager from runtime
        conn_manager = self.runtime.resolve_optional("matrix_connection_manager")
        if conn_manager:
            try:
                await conn_manager.disconnect()
            except Exception as e:
                self._logger.error(f"Error disconnecting from Matrix: {e}")

        self._is_connected = False
        self._logger.info("Matrix channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send response to Matrix room.

        Uses Matrix nio AsyncClient to send text message to room.

        Args:
            target: Room ID (e.g., !roomid:matrix.org).
            message: Response message to send.

        Returns:
            True on success, False on failure.
        """
        self._logger.debug(f"Sending message to Matrix room {target}")

        # Get Matrix client from runtime
        client = self.runtime.resolve_optional("matrix_client")
        if not client:
            self._logger.warning(
                "Matrix client not registered in runtime, cannot send message"
            )
            return False

        try:
            # Send text message via nio client
            response = await client.room_send(
                room_id=target,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": message.answer,
                },
            )

            # Check for successful send (has event_id)
            if hasattr(response, "event_id") and response.event_id:
                self._logger.debug(
                    f"Message sent to {target}, event_id: {response.event_id}"
                )
                return True
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to send message to {target}: {error_msg}")
                return False

        except Exception as e:
            self._logger.error(f"Error sending message to Matrix room {target}: {e}")
            return False

    # handle_incoming() inherited from ChannelBase

    async def join_room(self, room_id: str) -> bool:
        """Join a Matrix room.

        Uses Matrix nio AsyncClient to join the specified room.

        Args:
            room_id: Matrix room ID to join.

        Returns:
            True on success, False on failure.
        """
        self._logger.info(f"Joining Matrix room {room_id}")

        # Get Matrix client from runtime
        client = self.runtime.resolve_optional("matrix_client")
        if not client:
            self._logger.warning(
                "Matrix client not registered in runtime, cannot join room"
            )
            return False

        try:
            response = await client.join(room_id)

            # Check for successful join (has room_id)
            if hasattr(response, "room_id") and response.room_id:
                self._logger.info(f"Successfully joined room {room_id}")
                return True
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to join room {room_id}: {error_msg}")
                return False

        except Exception as e:
            self._logger.error(f"Error joining Matrix room {room_id}: {e}")
            return False

    async def leave_room(self, room_id: str) -> bool:
        """Leave a Matrix room.

        Uses Matrix nio AsyncClient to leave the specified room.

        Args:
            room_id: Matrix room ID to leave.

        Returns:
            True on success, False on failure.
        """
        self._logger.info(f"Leaving Matrix room {room_id}")

        # Get Matrix client from runtime
        client = self.runtime.resolve_optional("matrix_client")
        if not client:
            self._logger.warning(
                "Matrix client not registered in runtime, cannot leave room"
            )
            return False

        try:
            response = await client.room_leave(room_id)

            # Check for successful leave (has room_id or no error)
            if hasattr(response, "room_id") and response.room_id:
                self._logger.info(f"Successfully left room {room_id}")
                return True
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to leave room {room_id}: {error_msg}")
                return False

        except Exception as e:
            self._logger.error(f"Error leaving Matrix room {room_id}: {e}")
            return False
