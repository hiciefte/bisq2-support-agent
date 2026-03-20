"""Matrix Channel Plugin.

Wraps existing Matrix integration into channel plugin architecture.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Set

from app.channels.base import ChannelBase
from app.channels.escalation_localization import render_escalation_notice
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    OutgoingMessage,
    SendResult,
)
from app.channels.plugins.matrix.room_filter import (
    normalize_room_ids,
    resolve_allowed_reaction_rooms,
    resolve_allowed_sync_rooms,
)
from app.channels.plugins.support_markdown import (
    build_matrix_message_content,
    compose_support_answer_markdown,
    serialize_sources_for_tracking,
)
from app.channels.registry import register_channel
from app.channels.staff import (
    StaffResolver,
    collect_staff_display_names,
    collect_trusted_staff_ids,
)

logger = logging.getLogger(__name__)


@register_channel("matrix")
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

    ENABLED_FLAG = "MATRIX_SYNC_ENABLED"
    ENABLED_DEFAULT = False
    REQUIRED_PACKAGES = ("nio",)

    @classmethod
    def setup_dependencies(cls, runtime: Any, settings: Any) -> None:
        """Register Matrix channel dependencies in shared runtime."""
        try:
            from nio import (
                AsyncClient,
                AsyncClientConfig,
            )
        except ImportError:
            return
        try:
            from nio.crypto import ENCRYPTION_ENABLED
        except Exception:
            ENCRYPTION_ENABLED = False

        from app.channels.plugins.matrix.chatops_adapter import MatrixChatOpsAdapter
        from app.channels.plugins.matrix.client.connection_manager import (
            ConnectionManager,
        )
        from app.channels.plugins.matrix.client.session_manager import SessionManager
        from app.channels.plugins.matrix.message_handler import MatrixMessageHandler
        from app.channels.plugins.matrix.reaction_handler import MatrixReactionHandler
        from app.channels.plugins.matrix.trust_monitor_handler import (
            MatrixTrustMonitorHandler,
        )

        matrix_user = str(
            getattr(settings, "MATRIX_SYNC_USER_RESOLVED", "")
            or getattr(settings, "MATRIX_SYNC_USER", "")
            or ""
        ).strip()
        matrix_password = str(
            getattr(settings, "MATRIX_SYNC_PASSWORD_RESOLVED", "")
            or getattr(settings, "MATRIX_SYNC_PASSWORD", "")
            or ""
        ).strip()
        if not matrix_user:
            return
        allowed_room_ids = resolve_allowed_sync_rooms(settings)
        reaction_allowed_room_ids = resolve_allowed_reaction_rooms(settings)
        session_path = Path(str(settings.MATRIX_SYNC_SESSION_PATH)).expanduser()
        store_dir = session_path.parent / f"{session_path.stem}_store"
        encryption_enabled = bool(ENCRYPTION_ENABLED)
        client_kwargs: dict[str, Any] = {
            "config": AsyncClientConfig(
                store_sync_tokens=True,
                encryption_enabled=encryption_enabled,
            )
        }

        if encryption_enabled:
            try:
                store_dir.mkdir(parents=True, exist_ok=True)
                client_kwargs["store_path"] = str(store_dir)
            except OSError:
                logger.warning(
                    "Disabling Matrix E2EE store because store path creation failed: %s",
                    store_dir,
                    exc_info=True,
                )
                client_kwargs["config"] = AsyncClientConfig(
                    store_sync_tokens=True,
                    encryption_enabled=False,
                )

        matrix_client = AsyncClient(
            settings.MATRIX_HOMESERVER_URL,
            matrix_user,
            **client_kwargs,
        )
        matrix_session_manager = SessionManager(
            client=matrix_client,
            password=matrix_password,
            session_file=settings.MATRIX_SYNC_SESSION_PATH,
        )
        matrix_connection_manager = ConnectionManager(
            client=matrix_client,
            session_manager=matrix_session_manager,
        )
        runtime.register("matrix_client", matrix_client, allow_override=True)
        runtime.register(
            "matrix_connection_manager",
            matrix_connection_manager,
            allow_override=True,
        )

        matrix_staff_resolver = StaffResolver(
            trusted_staff_ids=collect_trusted_staff_ids(
                settings,
                channel_id="matrix",
            ),
            display_names=collect_staff_display_names(settings),
        )
        runtime.register("staff_resolver", matrix_staff_resolver, allow_override=True)

        runtime.register(
            "matrix_message_handler",
            MatrixMessageHandler(
                client=matrix_client,
                connection_manager=matrix_connection_manager,
                channel=None,
                autoresponse_policy_service=runtime.resolve_optional(
                    "channel_autoresponse_policy_service"
                ),
                allowed_room_ids=allowed_room_ids,
                staff_command_room_ids=reaction_allowed_room_ids,
                channel_id="matrix",
                trust_monitor_service=runtime.resolve_optional("trust_monitor_service"),
            ),
            allow_override=True,
        )

        chatops_rooms = normalize_room_ids(
            getattr(settings, "MATRIX_CHATOPS_ROOM_IDS", None)
        ) or normalize_room_ids(getattr(settings, "MATRIX_STAFF_ROOM", None))
        if chatops_rooms:
            runtime.register(
                "matrix_chatops_adapter",
                MatrixChatOpsAdapter(
                    runtime=runtime,
                    enabled=bool(getattr(settings, "MATRIX_CHATOPS_ENABLED", False)),
                    allowed_room_ids=set(chatops_rooms),
                ),
                allow_override=True,
            )

        trust_monitor_service = runtime.resolve_optional("trust_monitor_service")
        if trust_monitor_service is not None:
            trust_rooms = (
                getattr(settings, "TRUST_MONITOR_MATRIX_PUBLIC_ROOMS", [])
                or allowed_room_ids
            )
            runtime.register(
                "matrix_trust_monitor_handler",
                MatrixTrustMonitorHandler(
                    client=matrix_client,
                    trust_monitor_service=trust_monitor_service,
                    allowed_room_ids=trust_rooms,
                    staff_room_id=(
                        getattr(settings, "TRUST_MONITOR_MATRIX_STAFF_ROOM", "")
                        or getattr(settings, "MATRIX_STAFF_ROOM", "")
                    ),
                ),
                allow_override=True,
            )

        reaction_processor = runtime.resolve_optional("reaction_processor")
        if reaction_processor is not None:
            runtime.register(
                "matrix_reaction_handler",
                MatrixReactionHandler(
                    runtime=runtime,
                    processor=reaction_processor,
                    allowed_room_ids=reaction_allowed_room_ids,
                ),
                allow_override=True,
            )

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

    def get_staff_notification_target(
        self, metadata: dict[str, Any] | None = None
    ) -> str:
        """Resolve staff notification room target for escalation notices.

        Priority:
        1) Per-message metadata override (`staff_room_id`)
        2) Dedicated Matrix staff room (`MATRIX_STAFF_ROOM`)
        3) Matrix alert room fallback (`MATRIX_ALERT_ROOM`) for local/dev testing
        """
        payload = metadata if isinstance(metadata, dict) else {}
        metadata_target = str(payload.get("staff_room_id", "") or "").strip()
        if metadata_target:
            return metadata_target

        settings = getattr(self.runtime, "settings", None)
        staff_room = str(getattr(settings, "MATRIX_STAFF_ROOM", "") or "").strip()
        if staff_room:
            return staff_room

        return str(getattr(settings, "MATRIX_ALERT_ROOM", "") or "").strip()

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

        # Wire message handler if registered (push message flow)
        message_handler = self.runtime.resolve_optional("matrix_message_handler")
        if message_handler:
            try:
                if hasattr(message_handler, "channel"):
                    message_handler.channel = self
                await message_handler.start()
                self._logger.info("Matrix message handler started")
            except Exception as e:
                self._logger.warning(f"Failed to start message handler: {e}")

        trust_monitor_handler = self.runtime.resolve_optional(
            "matrix_trust_monitor_handler"
        )
        if trust_monitor_handler:
            try:
                await trust_monitor_handler.start()
                self._logger.info("Matrix trust monitor handler started")
            except Exception as e:
                self._logger.warning(f"Failed to start trust monitor handler: {e}")

        # Wire reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("matrix_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.start_listening()
                self._logger.info("Matrix reaction handler started")
            except Exception as e:
                self._logger.warning(f"Failed to start reaction handler: {e}")

        runtime_settings = getattr(self.runtime, "settings", None)
        allowed_rooms = set(resolve_allowed_sync_rooms(runtime_settings))
        trust_rooms = normalize_room_ids(
            getattr(runtime_settings, "TRUST_MONITOR_MATRIX_PUBLIC_ROOMS", "")
        )
        allowed_rooms.update(trust_rooms)
        chatops_rooms = normalize_room_ids(
            getattr(runtime_settings, "MATRIX_CHATOPS_ROOM_IDS", "")
        )
        allowed_rooms.update(chatops_rooms)
        trust_staff_room = str(
            getattr(runtime_settings, "TRUST_MONITOR_MATRIX_STAFF_ROOM", "") or ""
        ).strip()
        if trust_staff_room:
            allowed_rooms.add(trust_staff_room)
        for room_id in allowed_rooms:
            await self.join_room(str(room_id))

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

        trust_monitor_handler = self.runtime.resolve_optional(
            "matrix_trust_monitor_handler"
        )
        if trust_monitor_handler:
            try:
                await trust_monitor_handler.stop()
            except Exception as e:
                self._logger.warning(f"Failed to stop trust monitor handler: {e}")

        # Stop reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("matrix_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.stop_listening()
            except Exception as e:
                self._logger.warning(f"Failed to stop reaction handler: {e}")

        # Stop message handler if registered
        message_handler = self.runtime.resolve_optional("matrix_message_handler")
        if message_handler:
            try:
                await message_handler.stop()
            except Exception as e:
                self._logger.warning(f"Failed to stop message handler: {e}")

        self._is_connected = False
        self._logger.info("Matrix channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> SendResult:
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
            return SendResult(sent=False, error="matrix_client_unavailable")

        try:
            _meta = getattr(message, "metadata", None)
            rendered_answer = compose_support_answer_markdown(
                message.answer,
                sources=getattr(message, "sources", []),
                confidence_score=getattr(_meta, "confidence_score", None),
                channel_format="matrix",
            )
            msgtype = self._resolve_message_msgtype(_meta)
            content = build_matrix_message_content(rendered_answer, msgtype=msgtype)
            in_reply_to = str(getattr(message, "in_reply_to", "") or "").strip()
            if in_reply_to:
                content["m.relates_to"] = {"m.in_reply_to": {"event_id": in_reply_to}}

            # Send text message via nio client
            runtime_settings = getattr(self.runtime, "settings", None)
            ignore_unverified_devices = bool(
                getattr(
                    runtime_settings,
                    "MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES",
                    True,
                )
            )
            response = await asyncio.wait_for(
                client.room_send(
                    room_id=target,
                    message_type="m.room.message",
                    content=content,
                    ignore_unverified_devices=ignore_unverified_devices,
                ),
                timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
            )
            response, was_recovered = await self._recover_and_retry_room_send_if_needed(
                client=client,
                target=target,
                response=response,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=ignore_unverified_devices,
            )
            if was_recovered:
                self._logger.info(
                    "Recovered Matrix room state and retried message send room_id=%s",
                    target,
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
                            answer=rendered_answer,
                            user_id=getattr(
                                getattr(message, "user", None), "user_id", ""
                            ),
                            sources=serialize_sources_for_tracking(
                                getattr(message, "sources", [])
                            ),
                            confidence_score=getattr(_meta, "confidence_score", None),
                            routing_action=getattr(_meta, "routing_action", None),
                            requires_human=getattr(message, "requires_human", None),
                            in_reply_to=getattr(message, "in_reply_to", None),
                            delivery_target=target,
                            user_language=getattr(_meta, "original_language", None),
                        )
                    except Exception as e:
                        self._logger.warning(f"Failed to track sent message: {e}")
                return SendResult(
                    sent=True,
                    external_message_id=str(response.event_id),
                    editable=True,
                )
            else:
                # Error response
                error_msg = getattr(response, "message", "Unknown error")
                self._logger.error(f"Failed to send message to {target}: {error_msg}")
                return SendResult(sent=False, error=str(error_msg))

        except asyncio.TimeoutError:
            self._logger.error(
                f"Timed out sending message to Matrix room {target} "
                f"after {self.MATRIX_OP_TIMEOUT_SECONDS}s"
            )
            return SendResult(sent=False, error="matrix_send_timeout")
        except Exception as e:
            if self._is_missing_room_error(str(e)):
                recovered = await self._recover_missing_room_state(client, target)
                if recovered:
                    try:
                        runtime_settings = getattr(self.runtime, "settings", None)
                        ignore_unverified_devices = bool(
                            getattr(
                                runtime_settings,
                                "MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES",
                                True,
                            )
                        )
                        retry_response = await asyncio.wait_for(
                            client.room_send(
                                room_id=target,
                                message_type="m.room.message",
                                content=content,
                                ignore_unverified_devices=ignore_unverified_devices,
                            ),
                            timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
                        )
                        if (
                            hasattr(retry_response, "event_id")
                            and retry_response.event_id
                        ):
                            self._logger.info(
                                "Recovered Matrix room state after send exception "
                                "room_id=%s",
                                target,
                            )
                            return SendResult(
                                sent=True,
                                external_message_id=str(retry_response.event_id),
                                editable=True,
                            )
                    except Exception:
                        self._logger.debug(
                            "Matrix send retry after room recovery failed room_id=%s",
                            target,
                            exc_info=True,
                        )
            self._logger.exception(
                f"Error sending message to Matrix room {target}: {e}"
            )
            return SendResult(sent=False, error=str(e))

    @staticmethod
    def _resolve_message_msgtype(metadata: Any | None) -> str:
        routing_action = (
            str(getattr(metadata, "routing_action", "") or "").strip().lower()
        )
        if routing_action.endswith("_notice"):
            return "m.notice"
        return "m.text"

    async def send_reaction(self, room_id: str, event_id: str, key: str) -> bool:
        """Send Matrix ``m.reaction`` annotation for a room event."""
        client = self.runtime.resolve_optional("matrix_client")
        if not client:
            self._logger.warning(
                "Matrix client not registered in runtime, cannot send reaction"
            )
            return False

        normalized_room_id = str(room_id or "").strip()
        normalized_event_id = str(event_id or "").strip()
        normalized_key = str(key or "").strip()
        if not normalized_room_id or not normalized_event_id or not normalized_key:
            return False

        runtime_settings = getattr(self.runtime, "settings", None)
        ignore_unverified_devices = bool(
            getattr(runtime_settings, "MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES", True)
        )
        content = {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": normalized_event_id,
                "key": normalized_key,
            }
        }
        try:
            response = await asyncio.wait_for(
                client.room_send(
                    room_id=normalized_room_id,
                    message_type="m.reaction",
                    content=content,
                    ignore_unverified_devices=ignore_unverified_devices,
                ),
                timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self._logger.error(
                "Timed out sending Matrix reaction room_id=%s event_id=%s",
                normalized_room_id,
                normalized_event_id,
            )
            return False
        except Exception:
            self._logger.exception(
                "Failed to send Matrix reaction room_id=%s event_id=%s",
                normalized_room_id,
                normalized_event_id,
            )
            return False

        return bool(getattr(response, "event_id", None))

    @staticmethod
    def _is_missing_room_error(error_message: str) -> bool:
        normalized = str(error_message or "").strip().lower()
        return normalized.startswith("no such room with id")

    async def _recover_missing_room_state(self, client: Any, room_id: str) -> bool:
        """Try to make a room available in the nio client local room cache."""
        normalized_room_id = str(room_id or "").strip()
        if not normalized_room_id:
            return False

        room_known_before = self._client_knows_room(client, normalized_room_id)
        if room_known_before is True:
            return True

        recovered = False
        sync = getattr(client, "sync", None)
        if callable(sync):
            try:
                await asyncio.wait_for(
                    sync(timeout=0, full_state=True),
                    timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
                )
                recovered = True
            except Exception:
                self._logger.debug(
                    "Matrix full-state sync failed while recovering room_id=%s",
                    normalized_room_id,
                    exc_info=True,
                )

        room_known_after_sync = self._client_knows_room(client, normalized_room_id)
        if room_known_after_sync is True:
            return True

        join = getattr(client, "join", None)
        if callable(join):
            try:
                join_response = await asyncio.wait_for(
                    join(normalized_room_id),
                    timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
                )
                if getattr(join_response, "room_id", ""):
                    recovered = True
            except Exception:
                self._logger.debug(
                    "Matrix join failed while recovering room_id=%s",
                    normalized_room_id,
                    exc_info=True,
                )

        room_known_after_join = self._client_knows_room(client, normalized_room_id)
        if room_known_after_join is True:
            return True

        return recovered

    @staticmethod
    def _client_knows_room(client: Any, room_id: str) -> bool | None:
        """Check whether the nio client currently tracks a given room."""
        rooms = getattr(client, "rooms", None)
        if rooms is None:
            return None
        try:
            return bool(room_id in rooms)
        except Exception:
            return None

    async def _recover_and_retry_room_send_if_needed(
        self,
        client: Any,
        target: str,
        response: Any,
        message_type: str,
        content: dict[str, Any],
        ignore_unverified_devices: bool,
    ) -> tuple[Any, bool]:
        """Retry room_send once if nio says the room is missing from local cache."""
        if hasattr(response, "event_id") and getattr(response, "event_id", None):
            return response, False

        error_message = str(getattr(response, "message", "") or "").strip()
        if not self._is_missing_room_error(error_message):
            return response, False

        recovered = await self._recover_missing_room_state(client, target)
        if not recovered:
            return response, False

        retry_response = await asyncio.wait_for(
            client.room_send(
                room_id=target,
                message_type=message_type,
                content=content,
                ignore_unverified_devices=ignore_unverified_devices,
            ),
            timeout=self.MATRIX_OP_TIMEOUT_SECONDS,
        )
        return retry_response, True

    def get_delivery_target(self, metadata: dict[str, Any]) -> str:
        """Extract Matrix room ID from channel metadata."""
        return metadata.get("room_id", "")

    def format_escalation_message(
        self,
        username: str,
        escalation_id: int,
        support_handle: str,
        language_code: str | None = None,
    ) -> str:
        """Format escalation message for Matrix room."""
        _ = username
        return render_escalation_notice(
            channel_id=self.channel_id,
            escalation_id=escalation_id,
            support_handle=support_handle,
            language_code=language_code,
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
