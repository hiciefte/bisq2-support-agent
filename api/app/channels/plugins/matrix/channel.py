"""Matrix Channel Plugin.

Wraps existing Matrix integration into channel plugin architecture.
"""

import asyncio
from typing import Any, Set

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
            ChannelCapability.REACTIONS,
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
            self._logger.exception(f"Failed to connect to Matrix homeserver: {e}")
            self._is_connected = False

        # Wire reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("matrix_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.start_listening()
                self._logger.info("Matrix reaction handler started")
            except Exception as e:
                self._logger.warning(f"Failed to start reaction handler: {e}")

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
                self._logger.exception(f"Error disconnecting from Matrix: {e}")

        # Stop reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("matrix_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.stop_listening()
            except Exception as e:
                self._logger.warning(f"Failed to stop reaction handler: {e}")

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
            response = await asyncio.wait_for(
                client.room_send(
                    room_id=target,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": message.answer,
                    },
                ),
                timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
            )

            # Check for successful send (has event_id)
            if hasattr(response, "event_id") and response.event_id:
                self._logger.debug(
                    f"Message sent to {target}, event_id: {response.event_id}"
                )
                # Track for reaction correlation
                tracker = self.runtime.resolve_optional("sent_message_tracker")
                if tracker:
                    try:
                        tracker.track(
                            channel_id="matrix",
                            external_message_id=response.event_id,
                            internal_message_id=getattr(message, "message_id", ""),
                            question=getattr(message, "original_question", "") or "",
                            answer=message.answer,
                            user_id=getattr(
                                getattr(message, "user", None), "user_id", ""
                            ),
                            sources=[],
                        )
                    except Exception as e:
                        self._logger.warning(f"Failed to track sent message: {e}")
                return True
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to send message to {target}: {error_msg}")
                return False

        except asyncio.TimeoutError:
            self._logger.error(
                f"Timed out sending message to Matrix room {target} "
                f"after {self.MATRIX_OP_TIMEOUT_SECONDS}s"
            )
            return False
        except Exception as e:
            self._logger.exception(
                f"Error sending message to Matrix room {target}: {e}"
            )
            return False

    def get_delivery_target(self, metadata: dict[str, Any]) -> str:
        """Extract Matrix room ID from channel metadata."""
        return metadata.get("room_id", "")

    def format_escalation_message(
        self, username: str, escalation_id: int, support_handle: str
    ) -> str:
        """Format escalation message for Matrix room."""
        return (
            f"Your question has been escalated to {support_handle} for review. "
            f"A support team member will respond in this room. "
            f"(Reference: #{escalation_id})"
        )

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
            response = await asyncio.wait_for(
                client.join(room_id),
                timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
            )

            # Check for successful join (has room_id)
            if hasattr(response, "room_id") and response.room_id:
                self._logger.info(f"Successfully joined room {room_id}")
                return True
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to join room {room_id}: {error_msg}")
                return False

        except asyncio.TimeoutError:
            self._logger.error(
                f"Timed out joining Matrix room {room_id} "
                f"after {self.MATRIX_OP_TIMEOUT_SECONDS}s"
            )
            return False
        except Exception as e:
            self._logger.exception(f"Error joining Matrix room {room_id}: {e}")
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
            response = await asyncio.wait_for(
                client.room_leave(room_id),
                timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
            )

            # Check for successful leave (has room_id or no error)
            if hasattr(response, "room_id") and response.room_id:
                self._logger.info(f"Successfully left room {room_id}")
                return True
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to leave room {room_id}: {error_msg}")
                return False

        except asyncio.TimeoutError:
            self._logger.error(
                f"Timed out leaving Matrix room {room_id} "
                f"after {self.MATRIX_OP_TIMEOUT_SECONDS}s"
            )
            return False
        except Exception as e:
            self._logger.exception(f"Error leaving Matrix room {room_id}: {e}")
            return False

    MATRIX_OP_TIMEOUT_SECONDS = 30.0
