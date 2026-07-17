"""Bisq2 Channel Plugin.

Wraps existing Bisq2 API integration into channel plugin architecture.
"""

import asyncio
import hashlib
import inspect
import json
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Literal, Optional, Set, cast

from app.channels.base import ChannelBase
from app.channels.escalation_localization import render_escalation_notice
from app.channels.history_builder import ConversationMessage, build_channel_chat_history
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    ChatMessage,
    IncomingMessage,
    OutgoingMessage,
    SendResult,
    UserContext,
)
from app.channels.plugins.bisq2.client.websocket import (
    is_valid_subscription_response,
)
from app.channels.plugins.bisq2.test_scope import (
    Bisq2TestScope,
    resolve_bisq2_test_scope,
)
from app.channels.plugins.support_markdown import (
    compose_support_answer_markdown,
    serialize_sources_for_tracking,
)
from app.channels.question_prefilter import QuestionPrefilter, QuestionPrefilterProtocol
from app.channels.registry import register_channel
from app.channels.staff import (
    StaffResolver,
    collect_staff_display_names,
    collect_trusted_staff_ids,
    resolve_channel_staff_resolver,
    staff_resolver_service_key,
)
from app.channels.traits import ChannelTraits


class _BisqMessagePreparationError(RuntimeError):
    """Signal a retryable failure before an inbound event is durably claimed."""


@register_channel("bisq2")
class Bisq2Channel(ChannelBase):
    """Bisq2 native support chat channel.

    This plugin wraps the existing bisq_api.py functionality to integrate
    with the channel plugin architecture. The Bisq2 channel:
    - Polls Bisq2 API for new support conversations
    - Sends responses via REST API
    - Receives reactions via WebSocket subscription
    - Processes incoming questions through the RAG service

    Example:
        runtime = ChannelRuntime(settings=settings, rag_service=rag)
        channel = Bisq2Channel(runtime)
        await channel.start()

        # Poll for new messages
        messages = await channel.poll_conversations()
        for message in messages:
            response = await channel.handle_incoming(message)
    """

    _last_poll_since: Optional[datetime]
    _seen_message_ids: set[str]
    _seen_message_order: Deque[str]
    _max_seen_message_ids: int
    _message_cache_by_id: Dict[str, Dict[str, Any]]
    _ws_message_buffer: Deque[Dict[str, Any]]
    _ws_listener_task: Optional[asyncio.Task[None]]
    _ws_callback_registered: bool
    _ws_callback_client: Any
    _support_snapshot_reconciled: bool
    _support_subscription_established: bool
    _last_rest_fallback_poll_at: float
    _ws_rest_fallback_interval_seconds: float
    _ws_startup_timeout_seconds: float
    _question_prefilter: QuestionPrefilterProtocol
    _seen_message_lock: threading.RLock
    _mutation_lock: asyncio.Lock
    _sync_state_persistence_required: bool
    _sync_state_capable: bool
    _VALID_USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-@.:]{1,128}$")
    _MAX_WS_MESSAGE_BUFFER = 5000
    ENABLED_FLAG = "BISQ2_CHANNEL_ENABLED"
    ENABLED_DEFAULT = False
    CHANNEL_TRAITS = ChannelTraits(
        group_room=True,
        supports_staff_grounding=True,
        supports_chatops=True,
        max_answer_length=500,
    )

    @classmethod
    def setup_dependencies(cls, runtime: Any, settings: Any) -> None:
        """Register Bisq2 channel dependencies in shared runtime."""
        from app.channels.plugins.bisq2.chatops_adapter import Bisq2ChatOpsAdapter
        from app.channels.plugins.bisq2.client.api import Bisq2API
        from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
        from app.channels.plugins.bisq2.client.websocket import Bisq2WebSocketClient
        from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler
        from app.channels.plugins.bisq2.utils import build_bisq_websocket_url

        bisq_api = Bisq2API(settings=settings)
        ws_client = Bisq2WebSocketClient(
            url=build_bisq_websocket_url(getattr(settings, "BISQ_API_URL", "")),
        )
        staff_resolver = StaffResolver(
            trusted_staff_ids=collect_trusted_staff_ids(
                settings,
                channel_id="bisq2",
            ),
            display_names=collect_staff_display_names(settings),
            case_sensitive=True,
        )
        runtime.register("bisq2_api", bisq_api, allow_override=True)
        runtime.register("bisq2_websocket_client", ws_client, allow_override=True)
        runtime.register(
            "bisq2_sync_state_manager",
            BisqSyncStateManager(
                str(
                    Path(str(getattr(settings, "DATA_DIR", "/data") or "/data"))
                    / "bisq_live_channel_sync_state.json"
                ),
                retention_days=int(getattr(settings, "DATA_RETENTION_DAYS", 30) or 30),
            ),
            allow_override=True,
        )
        runtime.register(
            staff_resolver_service_key("bisq2"),
            staff_resolver,
            allow_override=True,
        )

        chatops_channel_ids = {
            str(channel_id or "").strip()
            for channel_id in getattr(settings, "BISQ2_CHATOPS_CHANNEL_IDS", []) or []
            if str(channel_id or "").strip()
        }
        if chatops_channel_ids:
            runtime.register(
                "bisq2_chatops_adapter",
                Bisq2ChatOpsAdapter(
                    runtime=runtime,
                    enabled=bool(getattr(settings, "BISQ2_CHATOPS_ENABLED", False)),
                    allowed_channel_ids=chatops_channel_ids,
                ),
                allow_override=True,
            )

        reaction_processor = runtime.resolve_optional("reaction_processor")
        if reaction_processor is not None:
            runtime.register(
                "bisq2_reaction_handler",
                Bisq2ReactionHandler(runtime=runtime, processor=reaction_processor),
                allow_override=True,
            )

    @property
    def channel_id(self) -> str:
        """Return channel identifier."""
        return "bisq2"

    @property
    def capabilities(self) -> Set[ChannelCapability]:
        """Return supported capabilities."""
        return {
            ChannelCapability.RECEIVE_MESSAGES,
            ChannelCapability.POLL_CONVERSATIONS,
            ChannelCapability.SEND_RESPONSES,
            ChannelCapability.REACTIONS,
            ChannelCapability.GROUP_ROOM,
            ChannelCapability.STAFF_GROUNDING,
            ChannelCapability.CHATOPS,
        }

    @property
    def channel_type(self) -> ChannelType:
        """Return channel type for outgoing messages."""
        return ChannelType.BISQ2

    def get_staff_notification_target(
        self, metadata: dict[str, Any] | None = None
    ) -> str:
        """Resolve Bisq2 staff-notification target for escalation notices.

        Priority:
        1) Per-message metadata override (`staff_room_id`)
        2) Static fallback (`BISQ2_STAFF_NOTIFICATION_TARGET`)
        """
        payload = metadata if isinstance(metadata, dict) else {}
        if "staff_room_id" in payload:
            metadata_target = payload.get("staff_room_id")
            return (
                metadata_target
                if self._test_scope.allows_channel(metadata_target)
                else ""
            )

        settings = getattr(self.runtime, "settings", None)
        configured_target = getattr(settings, "BISQ2_STAFF_NOTIFICATION_TARGET", "")
        return (
            configured_target
            if self._test_scope.allows_channel(configured_target)
            else ""
        )

    async def start(self) -> None:
        """Start the Bisq2 channel.

        Verifies connectivity to Bisq2 API. If Bisq2API is not registered
        in the runtime, the channel will start in degraded mode (polling
        will return empty results).
        """
        self._logger.info("Starting Bisq2 channel")
        if not self._test_scope.ready:
            self._logger.error(
                "Bisq2 channel scope is unavailable; live channel remains stopped "
                "(reason=%s channel_count=%s sender_profile_count=%s)",
                self._test_scope.reason,
                self._test_scope.channel_count,
                self._test_scope.sender_profile_count,
            )
            self._is_connected = False
            return

        # Verify Bisq2API is available in runtime
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning(
                "Bisq2API not registered in runtime. "
                "Channel will start but polling will be unavailable."
            )
            self._is_connected = False
            return

        # Verify API connectivity by attempting to setup the session
        try:
            await bisq_api.setup()
            self._is_connected = True
            self._logger.info("Bisq2 channel started - API connection verified")
        except Exception:
            self._logger.error("Failed to connect to Bisq2 API")
            self._is_connected = False

        # Open the live stream before capturing the REST boundary. Events that
        # arrive while the fresh snapshot is built remain provably live work.
        await self._maintain_websocket_lifecycle()

        # Suppress one fresh, complete snapshot before making the new scope
        # ready. The cursor remains at the pre-request boundary so REST can
        # recover a live event omitted while the export was being built.
        await self._prime_rest_fallback_cursor(bisq_api)
        if (
            not self._scope_rebaseline_pending
            and not self._sync_state_persistence_healthy
        ):
            await self._persist_sync_state()

    async def stop(self) -> None:
        """Stop the Bisq2 channel."""
        self._logger.info("Stopping Bisq2 channel")

        # Stop reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.stop_listening()
                self._logger.info("Bisq2 reaction handler stopped")
            except Exception as exc:
                self._logger.debug(
                    "Error stopping Bisq2 reaction handler (%s)",
                    type(exc).__name__,
                )

        if self._ws_listener_task is not None:
            self._ws_listener_task.cancel()
            try:
                await self._ws_listener_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self._logger.debug(
                    "Error stopping Bisq2 websocket loop (%s)",
                    type(exc).__name__,
                )
            finally:
                self._ws_listener_task = None

        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        close_fn = getattr(ws_client, "close", None) if ws_client else None
        if callable(close_fn):
            try:
                await close_fn()
            except Exception as exc:
                self._logger.debug(
                    "Error closing Bisq2 websocket client (%s)",
                    type(exc).__name__,
                )

        self._ws_message_buffer.clear()
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client is not None:
            self._detach_websocket_callback(ws_client)
        self._ws_callback_registered = False
        self._ws_callback_client = None
        self._support_snapshot_reconciled = False
        self._support_subscription_established = False
        self._is_connected = False
        self._logger.info("Bisq2 channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> SendResult:
        """Send a response to an approved Bisq group channel and test identity.

        Args:
            target: Group-channel ID in the Bisq2 system.
            message: Response message to send.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        sender_profile_id = self._resolve_outbound_sender_profile_id(message)
        if not self._test_scope.allows_outbound(target, sender_profile_id):
            self._logger.warning("Blocked Bisq2 send outside production-test scope")
            return SendResult(
                sent=False,
                error="bisq2_test_scope_not_allowed",
            )

        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning(
                "Bisq2API not registered in runtime, cannot send message"
            )
            return SendResult(sent=False, error="bisq2_api_unavailable")

        try:
            _meta = getattr(message, "metadata", None)
            rendered_answer = compose_support_answer_markdown(
                message.answer,
                sources=getattr(message, "sources", []),
                confidence_score=getattr(_meta, "confidence_score", None),
                channel_format="bisq2",
            )
            citation = self._resolve_visible_citation(
                getattr(message, "original_question", None)
            )
            raw_reply_to = getattr(message, "in_reply_to", None)
            citation_message_id = (
                raw_reply_to if isinstance(raw_reply_to, str) and raw_reply_to else None
            )
            response = await bisq_api.send_support_message(
                channel_id=target,
                text=rendered_answer,
                citation=citation,
                origin_sender_profile_id=sender_profile_id,
                citation_author_user_profile_id=(
                    sender_profile_id if citation is not None else None
                ),
                citation_message_id=(
                    citation_message_id if citation is not None else None
                ),
            )

            raw_external_message_id = (
                response.get("messageId") if isinstance(response, dict) else None
            )
            if (
                not isinstance(raw_external_message_id, str)
                or not raw_external_message_id.strip()
            ):
                self._logger.warning(
                    "Bisq2 API send_support_message returned an invalid messageId"
                )
                return SendResult(sent=False, error="missing_external_message_id")
            external_message_id = raw_external_message_id.strip()

            # Mark self-sent messages as seen immediately so polling does not
            # feed them back as new incoming user questions.
            self._mark_seen(external_message_id)
            await self._persist_sync_state()

            # Track sent message for reaction correlation
            tracker = self.runtime.resolve_optional("sent_message_tracker")
            if tracker:
                try:
                    tracker.track(
                        channel_id="bisq2",
                        external_message_id=external_message_id,
                        internal_message_id=getattr(message, "message_id", ""),
                        question=getattr(message, "original_question", "") or "",
                        answer=rendered_answer,
                        user_id=getattr(getattr(message, "user", None), "user_id", ""),
                        sources=serialize_sources_for_tracking(
                            getattr(message, "sources", [])
                        ),
                        confidence_score=getattr(_meta, "confidence_score", None),
                        routing_action=getattr(_meta, "routing_action", None),
                        requires_human=getattr(message, "requires_human", None),
                        in_reply_to=getattr(message, "in_reply_to", None),
                        delivery_target=target,
                        origin_sender_profile_id=sender_profile_id,
                        user_language=getattr(_meta, "original_language", None),
                    )
                except Exception as exc:
                    self._logger.warning(
                        "Failed to track sent message for reactions (%s)",
                        type(exc).__name__,
                    )

            self._logger.info("Sent message within Bisq2 production-test scope")
            return SendResult(
                sent=True,
                external_message_id=str(external_message_id),
                editable=False,
            )

        except Exception as exc:
            self._logger.warning(
                "Failed to send message within Bisq2 test scope (%s)",
                type(exc).__name__,
            )
            return SendResult(sent=False, error="bisq2_send_failed")

    @staticmethod
    def _resolve_outbound_sender_profile_id(message: OutgoingMessage) -> str:
        """Resolve the originating test identity carried through the pipeline."""
        user = getattr(message, "user", None)
        metadata = getattr(user, "metadata", None)
        return Bisq2Channel._resolve_sender_metadata_aliases(metadata)

    @staticmethod
    def _resolve_sender_metadata_aliases(metadata: Any) -> str:
        if not isinstance(metadata, dict):
            return ""
        values: set[str] = set()
        for key in ("bisq2_sender_profile_id", "sender_profile_id"):
            if key not in metadata or metadata.get(key) is None:
                continue
            value = metadata.get(key)
            if not isinstance(value, str):
                return ""
            if value:
                values.add(value)
        if len(values) != 1:
            return ""
        return next(iter(values))

    def resolve_delivery_sender_profile(self, metadata: dict[str, Any]) -> str:
        """Resolve one unambiguous sender from persisted delivery metadata."""
        return self._resolve_sender_metadata_aliases(metadata)

    def allows_test_delivery(self, target: str, sender_profile_id: str) -> bool:
        """Validate a reviewed delivery without causing external side effects."""
        return self._test_scope.allows_outbound(target, sender_profile_id)

    def get_delivery_target(self, metadata: dict[str, Any]) -> str:
        """Extract an unambiguous, approved Bisq group-channel target."""
        target = self._test_scope.resolve_payload_channel(metadata)
        return target if self._test_scope.allows_channel(target) else ""

    def format_escalation_message(
        self,
        username: str,
        escalation_id: int,
        support_handle: str,
        language_code: str | None = None,
    ) -> str:
        """Format escalation message for Bisq2 chat."""
        _ = username
        return render_escalation_notice(
            channel_id=self.channel_id,
            escalation_id=escalation_id,
            support_handle=support_handle,
            language_code=language_code,
        )

    # handle_incoming() inherited from ChannelBase

    async def poll_conversations(self) -> List[IncomingMessage]:
        """Serialize cursor, dedup, and WebSocket-buffer mutations per channel."""
        async with self._mutation_lock:
            return await self._poll_conversations_locked()

    async def _poll_conversations_locked(self) -> List[IncomingMessage]:
        """Poll Bisq2 API for new support conversations.

        Delegates to Bisq2API.export_chat_messages() to fetch new conversations,
        then transforms them into IncomingMessage format.

        Returns:
            List of new incoming messages from Bisq2.
        """
        if not self._test_scope.ready:
            return []

        self._logger.debug("Polling Bisq2 API for new conversations")

        # A new or changed allowlist must first suppress one complete snapshot.
        # Until that succeeds, do not drain live buffers or enter orchestration.
        if self._scope_rebaseline_pending:
            await self._maintain_readiness_unlocked()
            if self._scope_rebaseline_pending:
                return []
        if (
            not self._sync_state_persistence_healthy
            and not await self._persist_sync_state()
        ):
            return []

        incoming_messages: List[IncomingMessage] = []
        ws_messages = self._drain_ws_messages()
        if ws_messages:
            try:
                ws_incoming = await self._process_raw_messages(
                    ws_messages, source_name="Bisq2 WebSocket"
                )
            except _BisqMessagePreparationError:
                return incoming_messages
            if not self._sync_state_persistence_healthy:
                return incoming_messages
            incoming_messages.extend(ws_incoming)
            await self._persist_sync_state()
            if ws_incoming:
                self._logger.info(
                    "Consumed %s messages from Bisq2 WebSocket",
                    len(ws_incoming),
                )

        # When websocket is configured, REST export acts as low-frequency backfill.
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client and not self._should_run_rest_fallback_poll():
            return incoming_messages

        # Get Bisq2API from runtime services
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning("Bisq2API not registered in runtime, cannot poll")
            return incoming_messages

        try:
            # Export messages from Bisq2 API
            poll_since = self._last_poll_since
            request_boundary = self._rest_boundary_now()
            result = await bisq_api.export_chat_messages(since=poll_since)
            if "messages" not in result:
                self._logger.warning(
                    "Bisq2 API export response missing 'messages'; skipping poll cycle"
                )
                return incoming_messages
            messages = result.get("messages", [])
            if not isinstance(messages, list):
                self._logger.warning(
                    "Bisq2 API export response contains invalid 'messages'; "
                    "skipping poll cycle"
                )
                return incoming_messages
            messages = self._filter_rest_messages_at_or_after_cursor(
                messages,
                poll_since,
            )

            export_timestamp = self._extract_export_timestamp(result)
            snapshot_is_fresh = bool(
                export_timestamp is not None and export_timestamp >= request_boundary
            )

            if not messages:
                if snapshot_is_fresh:
                    self._update_rest_cursor(request_boundary)
                await self._persist_sync_state()
                return incoming_messages

            rest_incoming = await self._process_raw_messages(
                messages, source_name="Bisq2 API"
            )
            if not self._sync_state_persistence_healthy:
                # Keep the REST high-water mark unchanged so the same export can
                # be retried after durable state recovers.
                return incoming_messages
            incoming_messages.extend(rest_incoming)

            self._logger.info(
                f"Polled {len(incoming_messages)} messages from Bisq2 API"
            )
            if snapshot_is_fresh:
                self._update_rest_cursor(request_boundary)
            await self._persist_sync_state()
            return incoming_messages

        except Exception as exc:
            self._logger.warning(
                "Error polling Bisq2 API (%s)",
                type(exc).__name__,
            )
            return incoming_messages

    def _transform_bisq_message(
        self,
        msg: Dict[str, Any],
        chat_history: Optional[List[ChatMessage]] = None,
    ) -> Optional[IncomingMessage]:
        """Transform a Bisq2 API message to IncomingMessage format.

        Args:
            msg: Raw message from Bisq2 API.

        Returns:
            IncomingMessage or None if transformation fails.
        """
        try:
            if not self._test_scope.allows_payload(msg):
                return None
            message_id = str(msg.get("messageId", "")).strip()
            if not message_id:
                message_id = self._derive_message_id(msg)
            author = str(msg.get("author", "unknown") or "unknown")
            author_id = self._resolve_sender_profile_id(msg)
            user_id = self._derive_user_id(author_id=author_id, author=author)
            text = msg.get("message", "")

            if not text:
                return None

            native_channel_id = self._test_scope.resolve_payload_channel(msg)
            channel_metadata = {
                "conversation_id": native_channel_id,
                "channel_id": native_channel_id,
                "delivery_target": native_channel_id,
                "date": msg.get("date", ""),
                "sender_profile_id": author_id,
                "origin_sender_profile_id": author_id,
            }
            for source_key, target_key in (
                ("channelId", "channel_id"),
                ("conversationId", "conversation_id"),
                ("citationMessageId", "citation_message_id"),
                ("citation_message_id", "citation_message_id"),
            ):
                value = msg.get(source_key)
                if isinstance(value, str) and value.strip():
                    channel_metadata[target_key] = value.strip()

            return IncomingMessage(
                message_id=message_id,
                channel=ChannelType.BISQ2,
                question=text,
                user=UserContext(
                    user_id=user_id,
                    session_id=None,
                    channel_user_id=author,
                    metadata={"bisq2_sender_profile_id": author_id},
                    auth_token=None,
                ),
                chat_history=chat_history,
                channel_metadata=channel_metadata,
                channel_signature=None,
            )
        except Exception as exc:
            self._logger.warning(
                "Failed to transform Bisq2 message (%s)",
                type(exc).__name__,
            )
            return None

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._test_scope: Bisq2TestScope = resolve_bisq2_test_scope(
            getattr(self.runtime, "settings", None)
        )
        if not self._test_scope.ready:
            self._logger.warning(
                "Bisq2 production-test scope is deny-all "
                "(reason=%s channel_count=%s sender_profile_count=%s)",
                self._test_scope.reason,
                self._test_scope.channel_count,
                self._test_scope.sender_profile_count,
            )
        self._seen_message_lock = threading.RLock()
        self._mutation_lock = asyncio.Lock()
        self._sync_state_manager = self.runtime.resolve_optional(
            "bisq2_sync_state_manager"
        )
        settings = getattr(self.runtime, "settings", None)
        self._sync_state_persistence_required = (
            getattr(settings, "BISQ2_CHANNEL_ENABLED", False) is True
        )
        required_sync_methods = (
            "begin_scope_rebaseline",
            "claim_processed_and_save",
            "get_processed_ids_in_order",
            "mark_scope_rebaseline_complete",
            "register_prune_listener",
            "reset_scope_rebaseline_cursor",
            "save_state",
            "update_last_sync",
        )
        self._sync_state_capable = bool(
            self._sync_state_manager is not None
            and all(
                inspect.getattr_static(
                    self._sync_state_manager,
                    method_name,
                    None,
                )
                is not None
                and callable(getattr(self._sync_state_manager, method_name, None))
                for method_name in required_sync_methods
            )
        )
        self._sync_state_persistence_healthy = not self._sync_state_persistence_required
        scope_fingerprint = self._test_scope.fingerprint
        persisted_scope_fingerprint = getattr(
            self._sync_state_manager,
            "scope_fingerprint",
            None,
        )
        persisted_since = getattr(
            self._sync_state_manager,
            "last_sync_timestamp",
            None,
        )
        scope_fingerprint_matches = persisted_scope_fingerprint == scope_fingerprint
        scope_state_matches = bool(
            scope_fingerprint_matches
            and isinstance(persisted_since, datetime)
            and getattr(
                self._sync_state_manager,
                "scope_rebaseline_complete",
                False,
            )
            is True
        )
        self._scope_rebaseline_pending = not scope_state_matches
        if not scope_state_matches:
            begin_rebaseline = getattr(
                self._sync_state_manager,
                "begin_scope_rebaseline",
                None,
            )
            if callable(begin_rebaseline):
                begin_rebaseline(scope_fingerprint)
            elif not scope_fingerprint_matches:
                bind_scope = getattr(self._sync_state_manager, "bind_scope", None)
                if callable(bind_scope):
                    bind_scope(scope_fingerprint)

        self._last_poll_since = (
            (persisted_since if isinstance(persisted_since, datetime) else None)
            if scope_state_matches
            else None
        )
        get_ordered_ids = getattr(
            self._sync_state_manager, "get_processed_ids_in_order", None
        )
        if scope_fingerprint_matches and callable(get_ordered_ids):
            persisted_ids: Any = get_ordered_ids()
        elif scope_fingerprint_matches:
            persisted_ids = getattr(
                self._sync_state_manager, "processed_message_ids", set()
            )
        else:
            persisted_ids = []
        if not isinstance(persisted_ids, (list, set, tuple)):
            persisted_ids = []
        persisted_order = list(
            dict.fromkeys(
                str(message_id)
                for message_id in persisted_ids
                if str(message_id).strip()
            )
        )
        self._seen_message_ids = set(persisted_order)
        self._seen_message_order = deque(persisted_order)
        self._max_seen_message_ids = 10000
        self._message_cache_by_id = {}
        register_prune_listener = getattr(
            self._sync_state_manager, "register_prune_listener", None
        )
        if callable(register_prune_listener):
            register_prune_listener(self._prune_seen_message_ids)
        self._ws_message_buffer = deque(maxlen=self._MAX_WS_MESSAGE_BUFFER)
        self._ws_listener_task = None
        self._ws_callback_registered = False
        self._ws_callback_client = None
        self._support_snapshot_reconciled = False
        self._support_subscription_established = False
        self._last_rest_fallback_poll_at = 0.0
        self._ws_rest_fallback_interval_seconds = self._resolve_ws_fallback_interval()
        self._ws_startup_timeout_seconds = self._resolve_ws_startup_timeout()
        self._question_prefilter = (
            self.runtime.resolve_optional("question_prefilter") or QuestionPrefilter()
        )

    @property
    def test_scope_rebaseline_complete(self) -> bool:
        """Return whether a changed scope has a durable fresh REST boundary."""
        return not self._scope_rebaseline_pending

    @property
    def test_scope_persistence_healthy(self) -> bool:
        """Return whether the latest Bisq cursor/dedup state write succeeded."""
        return self._sync_state_persistence_healthy

    @property
    def test_scope_persistence_capable(self) -> bool:
        """Return whether the full production sync-state interface is present."""
        return self._sync_state_capable

    @property
    def test_scope_websocket_ready(self) -> bool:
        """Return whether both scoped subscriptions are current and receiving."""
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        return self._websocket_subscriptions_ready(ws_client, reaction_handler)

    async def maintain_readiness(self) -> bool:
        """Serialize recovery with polling mutations."""
        async with self._mutation_lock:
            return await self._maintain_readiness_unlocked()

    async def _maintain_readiness_unlocked(self) -> bool:
        """Retry a fail-closed scope rebaseline without entering generation."""
        if not self._test_scope.ready:
            return False
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            return False
        if not self._is_connected:
            try:
                await bisq_api.setup()
                self._is_connected = True
                self._logger.info("Bisq2 API connection recovered")
            except Exception:
                self._logger.warning("Bisq2 API connection recovery failed")
                return False
        websocket_ready = await self._maintain_websocket_lifecycle()
        if self._scope_rebaseline_pending:
            await self._prime_rest_fallback_cursor(bisq_api)
        if (
            not self._scope_rebaseline_pending
            and not self._sync_state_persistence_healthy
        ):
            await self._persist_sync_state()
        return bool(
            self._is_connected
            and not self._scope_rebaseline_pending
            and self._sync_state_persistence_healthy
            and websocket_ready
        )

    async def _maintain_websocket_lifecycle(self) -> bool:
        """Start all subscriptions before the shared receive loop.

        A public ``subscribe()`` call reads the next frame directly, so retrying a
        subscription while ``listen_forever()`` is active would create two readers
        on one socket. An active listener owns reconnect and re-subscription. A
        stopped listener is reset and rebuilt in the required order: reactions,
        support messages, then the single receive loop.
        """
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client is None:
            return False

        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        if reaction_handler is None:
            return False
        listener_task = self._ws_listener_task
        if listener_task is not None and not listener_task.done():
            return self._websocket_subscriptions_ready(ws_client, reaction_handler)

        if listener_task is not None:
            try:
                listener_task.result()
            except (asyncio.CancelledError, Exception) as exc:
                self._logger.warning(
                    "Bisq2 websocket listener stopped (%s)",
                    type(exc).__name__,
                )
            self._ws_listener_task = None

        await self._close_stopped_websocket(ws_client)
        try:
            await self._await_with_startup_timeout(reaction_handler.start_listening())
            support_started = await self._start_support_message_websocket(ws_client)
            if not support_started:
                await self._close_stopped_websocket(ws_client)
                return False

            # Give the task one turn to enter listen_forever() so readiness cannot
            # latch green for a receive loop that failed immediately.
            await asyncio.sleep(0)
            listener_task = self._ws_listener_task
            if listener_task is None or listener_task.done():
                await self._close_stopped_websocket(ws_client)
                return False
            return self._websocket_subscriptions_ready(ws_client, reaction_handler)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.warning(
                "Bisq2 websocket lifecycle recovery failed (%s)",
                type(exc).__name__,
            )
            await self._close_stopped_websocket(ws_client)
            return False

    def _websocket_subscriptions_ready(
        self,
        ws_client: Any,
        reaction_handler: Any,
    ) -> bool:
        """Validate subscriptions on the socket owned by the live receive task."""
        listener_task = self._ws_listener_task
        if (
            ws_client is None
            or reaction_handler is None
            or listener_task is None
            or listener_task.done()
        ):
            return False
        if getattr(ws_client, "is_connected", False) is not True:
            return False
        if getattr(ws_client, "is_listening", False) is not True:
            return False
        has_active_subscription = getattr(ws_client, "has_active_subscription", None)
        if not callable(has_active_subscription):
            return False
        return bool(
            getattr(reaction_handler, "is_listening", False) is True
            and self._support_snapshot_reconciled
            and has_active_subscription("SUPPORT_CHAT_REACTIONS") is True
            and has_active_subscription("SUPPORT_CHAT_MESSAGES") is True
        )

    async def _close_stopped_websocket(self, ws_client: Any) -> None:
        """Reset a socket only when no live receive task owns it."""
        listener_task = self._ws_listener_task
        if listener_task is not None and not listener_task.done():
            return
        close_fn = getattr(ws_client, "close", None)
        if not callable(close_fn):
            return
        try:
            result = close_fn()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self._logger.debug(
                "Failed to reset stopped Bisq2 websocket (%s)",
                type(exc).__name__,
            )

    async def _start_support_message_websocket(self, ws_client: Any) -> bool:
        """Start SUPPORT_CHAT_MESSAGES websocket stream when available."""
        try:
            if (
                self._ws_callback_client is not ws_client
                and self._ws_callback_registered
            ):
                self._detach_websocket_callback(self._ws_callback_client)
            if not self._ws_callback_registered:
                on_snapshot = getattr(ws_client, "on_subscription_snapshot", None)
                if not callable(on_snapshot):
                    raise RuntimeError(
                        "Bisq2 websocket client does not support snapshots"
                    )
                ws_client.on_event(self._on_websocket_event)
                on_snapshot(self._on_support_subscription_snapshot)
                self._ws_callback_registered = True
                self._ws_callback_client = ws_client

            is_connected = await self._resolve_ws_connected(ws_client)
            connect_fn = getattr(ws_client, "connect", None)
            if not is_connected and callable(connect_fn):
                await self._await_with_startup_timeout(connect_fn())

            subscribe_fn = getattr(ws_client, "subscribe", None)
            if callable(subscribe_fn):
                self._support_snapshot_reconciled = False
                subscription_response = await self._await_with_startup_timeout(
                    subscribe_fn("SUPPORT_CHAT_MESSAGES")
                )
                if not is_valid_subscription_response(subscription_response):
                    raise RuntimeError(
                        "Bisq2 support subscription was not acknowledged"
                    )
                # Simple test/alternate clients may return the acknowledgement
                # without dispatching its snapshot callback. Reconcile it here;
                # the production client has already done so before returning.
                if not self._support_snapshot_reconciled:
                    await self._on_support_subscription_snapshot(
                        "SUPPORT_CHAT_MESSAGES",
                        None,
                        subscription_response.get("payload"),
                    )
                if not self._support_snapshot_reconciled:
                    raise RuntimeError("Bisq2 support snapshot was not reconciled")
                self._support_subscription_established = True

            listen_forever_fn = getattr(ws_client, "listen_forever", None)
            if callable(listen_forever_fn) and (
                self._ws_listener_task is None or self._ws_listener_task.done()
            ):
                self._ws_listener_task = asyncio.create_task(listen_forever_fn())

            self._logger.info("Bisq2 support message websocket stream started")
            return True
        except asyncio.TimeoutError:
            self._support_snapshot_reconciled = False
            self._logger.warning(
                "Bisq2 support websocket startup timed out after %.2fs; "
                "continuing with REST polling fallback",
                self._ws_startup_timeout_seconds,
            )
            close_fn = getattr(ws_client, "close", None)
            if callable(close_fn):
                try:
                    await close_fn()
                except Exception as exc:
                    self._logger.debug(
                        "Error closing timed-out Bisq2 websocket client (%s)",
                        type(exc).__name__,
                    )
            return False
        except Exception as exc:
            self._support_snapshot_reconciled = False
            self._logger.warning(
                "Failed to start Bisq2 support websocket stream (%s)",
                type(exc).__name__,
            )
            return False

    async def _resolve_ws_connected(self, ws_client: Any) -> bool:
        is_connected_attr = getattr(ws_client, "is_connected", False)
        if callable(is_connected_attr):
            result = is_connected_attr()
            if inspect.isawaitable(result):
                result = await result
            candidate = result
        else:
            candidate = is_connected_attr

        if isinstance(candidate, bool):
            return candidate
        if isinstance(candidate, (int, float)):
            return bool(candidate)
        if isinstance(candidate, str):
            lowered = candidate.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return False

    def _detach_websocket_callback(self, ws_client: Any) -> None:
        if ws_client is None:
            return
        remove_fn = getattr(ws_client, "off_event", None)
        remove_snapshot_fn = getattr(ws_client, "off_subscription_snapshot", None)
        if callable(remove_fn):
            try:
                remove_fn(self._on_websocket_event)
            except Exception as exc:
                self._logger.debug(
                    "Failed to remove Bisq2 websocket callback (%s)",
                    type(exc).__name__,
                )
        if callable(remove_snapshot_fn):
            try:
                remove_snapshot_fn(self._on_support_subscription_snapshot)
            except Exception as exc:
                self._logger.debug(
                    "Failed to remove Bisq2 websocket snapshot callback (%s)",
                    type(exc).__name__,
                )
        self._ws_callback_registered = False
        self._ws_callback_client = None
        self._support_snapshot_reconciled = False
        self._support_subscription_established = False

    async def _prime_rest_fallback_cursor(self, bisq_api: Any) -> None:
        """Initialize REST fallback cursor to avoid replaying full export history."""
        if self._last_poll_since is not None and not self._scope_rebaseline_pending:
            return

        # Capture the live boundary before fallible I/O. The first regular REST
        # poll resumes from this exact point even if the startup snapshot takes a
        # long time or reports a later export timestamp.
        if self._last_poll_since is None:
            prime_boundary = self._rest_boundary_now()
            self._update_rest_cursor(prime_boundary)
        else:
            prime_boundary = self._last_poll_since

        export_chat_messages = getattr(bisq_api, "export_chat_messages", None)
        if not callable(export_chat_messages):
            return

        try:
            result_or_awaitable = export_chat_messages(since=None)
            if not inspect.isawaitable(result_or_awaitable):
                return
            result = await result_or_awaitable
        except Exception as exc:
            self._logger.debug(
                "Failed to prime Bisq2 REST fallback cursor (%s)",
                type(exc).__name__,
            )
            return

        if not isinstance(result, dict):
            return

        export_timestamp = self._extract_export_timestamp(result)
        if export_timestamp is None or export_timestamp < prime_boundary:
            self._logger.info(
                "Waiting for a fresh Bisq2 export snapshot before scope activation"
            )
            return

        # Prevalidate the full approved snapshot before mutating dedup state. A
        # row at/after the local boundary is ambiguous unless the websocket saw
        # that exact event after its subscription completed. Ambiguous future or
        # same-boundary history keeps the scope unavailable instead of relying on
        # a bounded seen-ID cache for safety.
        prime_messages = result.get("messages")
        if isinstance(prime_messages, list):
            live_message_ids = {
                self._derive_message_id(message)
                for message in self._ws_message_buffer
                if isinstance(message, dict)
            }
            approved_snapshot: list[tuple[str, Dict[str, Any]]] = []
            for raw_message in prime_messages:
                if not isinstance(raw_message, dict):
                    continue
                message_id = self._derive_message_id(raw_message)
                if not self._test_scope.allows_payload(raw_message):
                    continue
                raw_with_id = dict(raw_message)
                raw_with_id["messageId"] = message_id
                timestamp_ms = self._resolve_timestamp_ms(raw_with_id)
                if timestamp_ms > 0:
                    message_time = datetime.fromtimestamp(
                        timestamp_ms / 1000.0, tz=timezone.utc
                    )
                else:
                    message_time = None
                if (
                    message_time is not None
                    and message_time >= prime_boundary
                    and message_id not in live_message_ids
                ):
                    self._logger.warning(
                        "Bisq2 scope rebaseline found ambiguous boundary history"
                    )
                    self._last_poll_since = None
                    reset_cursor = getattr(
                        self._sync_state_manager,
                        "reset_scope_rebaseline_cursor",
                        None,
                    )
                    if callable(reset_cursor):
                        reset_cursor()
                    return
                approved_snapshot.append((message_id, raw_with_id))
        else:
            return

        for message_id, _raw_with_id in approved_snapshot:
            if message_id not in live_message_ids:
                self._mark_seen(message_id)

        mark_complete = getattr(
            self._sync_state_manager,
            "mark_scope_rebaseline_complete",
            None,
        )
        if callable(mark_complete):
            mark_complete()
        if await self._persist_sync_state():
            self._scope_rebaseline_pending = False

    def _filter_rest_messages_at_or_after_cursor(
        self,
        messages: List[Any],
        cursor: Optional[datetime],
    ) -> List[Dict[str, Any]]:
        """Reject REST history older than the requested high-water mark.

        The local check remains necessary if an upstream implementation ignores
        its ``since`` parameter. Once a cursor exists, missing timestamps fail
        closed so an older out-of-scope event cannot become eligible after a
        later allowlist expansion.
        """
        if cursor is None:
            return [message for message in messages if isinstance(message, dict)]

        normalized_cursor = cursor
        if normalized_cursor.tzinfo is None:
            normalized_cursor = normalized_cursor.replace(tzinfo=timezone.utc)
        else:
            normalized_cursor = normalized_cursor.astimezone(timezone.utc)

        filtered: List[Dict[str, Any]] = []
        dropped_count = 0
        for message in messages:
            if not isinstance(message, dict):
                dropped_count += 1
                continue
            timestamp_ms = self._resolve_timestamp_ms(message)
            if timestamp_ms <= 0:
                dropped_count += 1
                continue
            message_time = datetime.fromtimestamp(
                timestamp_ms / 1000.0,
                tz=timezone.utc,
            )
            if message_time < normalized_cursor:
                dropped_count += 1
                continue
            filtered.append(message)

        if dropped_count:
            self._logger.info(
                "Suppressed %s stale or timestamp-less Bisq2 REST message(s)",
                dropped_count,
            )
        return filtered

    def _update_rest_cursor(self, timestamp: datetime) -> None:
        """Update the in-memory and durable REST high-water marks together."""
        if self._last_poll_since is not None and timestamp < self._last_poll_since:
            timestamp = self._last_poll_since
        self._last_poll_since = timestamp
        update_last_sync = getattr(self._sync_state_manager, "update_last_sync", None)
        if callable(update_last_sync):
            update_last_sync(timestamp)

    async def _persist_sync_state(self) -> bool:
        """Persist cursor/dedup state without blocking the channel event loop."""
        if self._sync_state_persistence_required and not self._sync_state_capable:
            self._sync_state_persistence_healthy = False
            self._logger.warning(
                "Bisq2 sync-state manager is incomplete while the channel is enabled"
            )
            return False
        save_state = getattr(self._sync_state_manager, "save_state", None)
        if not callable(save_state):
            self._sync_state_persistence_healthy = (
                not self._sync_state_persistence_required
            )
            if self._sync_state_persistence_required:
                self._logger.warning(
                    "Bisq2 sync-state persistence is unavailable while the channel is enabled"
                )
            return self._sync_state_persistence_healthy
        try:
            await asyncio.to_thread(save_state)
            self._sync_state_persistence_healthy = True
            return True
        except Exception:
            self._sync_state_persistence_healthy = False
            self._logger.warning("Failed to persist Bisq2 sync state")
            return False

    async def _claim_messages_durably(
        self,
        messages: List[Dict[str, Any]],
    ) -> Optional[set[str]]:
        """Persist message claims before any downstream or external side effect."""
        message_ids = {self._derive_message_id(message) for message in messages}
        if not message_ids:
            return set()

        manager = self._sync_state_manager
        if self._sync_state_persistence_required and not self._sync_state_capable:
            self._sync_state_persistence_healthy = False
            self._logger.warning(
                "Blocked Bisq2 message processing without durable sync state"
            )
            return None
        static_claim = (
            inspect.getattr_static(manager, "claim_processed_and_save", None)
            if manager is not None
            else None
        )
        claim_and_save = (
            getattr(manager, "claim_processed_and_save", None)
            if static_claim is not None
            else None
        )
        if callable(claim_and_save):
            try:
                claimed_result = await asyncio.to_thread(claim_and_save, message_ids)
            except Exception:
                self._sync_state_persistence_healthy = False
                self._logger.warning(
                    "Blocked Bisq2 message processing because sync state is not durable"
                )
                return None
            if not isinstance(claimed_result, set) or not claimed_result.issubset(
                message_ids
            ):
                self._sync_state_persistence_healthy = False
                self._logger.warning(
                    "Blocked Bisq2 message processing after an invalid durable claim"
                )
                return None
            for message_id in message_ids:
                self._mark_seen(message_id, record_in_sync_state=False)
            self._sync_state_persistence_healthy = True
            return claimed_result

        prior_order = list(self._seen_message_order)
        for message_id in message_ids:
            self._mark_seen(message_id)
        if await self._persist_sync_state():
            return message_ids

        unmark_processed = getattr(manager, "unmark_processed", None)
        if callable(unmark_processed):
            unmark_processed(message_ids)
        with self._seen_message_lock:
            self._seen_message_order = deque(prior_order)
            self._seen_message_ids = set(prior_order)
            for message_id in message_ids:
                self._message_cache_by_id.pop(message_id, None)
        return None

    async def _on_websocket_event(self, event: Dict[str, Any]) -> None:
        """Buffer support websocket events for processing in poll cycle."""
        try:
            topic = str(event.get("topic", "") or "")
            modification_type = str(event.get("modificationType", "ADDED") or "ADDED")
            payload = self._parse_websocket_payload(event.get("payload"))
            if payload is None:
                return

            if topic == "SUPPORT_CHAT_MESSAGES":
                if modification_type != "ADDED":
                    return
                if not self._test_scope.allows_payload(payload):
                    return
                normalized = self._normalize_websocket_support_message(payload)
                if normalized is None:
                    return
                if not self._test_scope.allows_payload(normalized):
                    return
                self._cache_message(normalized)
                if (
                    self._ws_message_buffer.maxlen is not None
                    and len(self._ws_message_buffer) == self._ws_message_buffer.maxlen
                ):
                    self._logger.warning(
                        "Bisq2 websocket buffer full (%s); dropping oldest message",
                        self._ws_message_buffer.maxlen,
                    )
                self._ws_message_buffer.append(normalized)
                return

            if topic == "SUPPORT_CHAT_REACTIONS":
                # Reactions are handled by dedicated feedback processors.
                return
        except Exception as exc:
            self._logger.debug(
                "Failed processing Bisq2 websocket event (%s)",
                type(exc).__name__,
            )

    async def _on_support_subscription_snapshot(
        self,
        topic: str,
        parameter: Optional[str],
        raw_payload: Optional[str],
    ) -> None:
        """Buffer the authoritative scoped support snapshot before readiness."""
        del parameter
        if topic != "SUPPORT_CHAT_MESSAGES":
            return

        self._support_snapshot_reconciled = False
        if not isinstance(raw_payload, str):
            raise ValueError("Bisq2 support snapshot payload is missing")
        try:
            decoded = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Bisq2 support snapshot payload is invalid") from exc
        if not isinstance(decoded, list):
            raise ValueError("Bisq2 support snapshot payload must be a list")

        snapshot_messages: List[Dict[str, Any]] = []
        snapshot_ids: set[str] = set()
        for item in decoded:
            if not isinstance(item, dict):
                raise ValueError("Bisq2 support snapshot item is invalid")
            candidate = item
            if "payload" in item:
                nested = self._parse_websocket_payload(item.get("payload"))
                if nested is None:
                    raise ValueError("Bisq2 support snapshot item is invalid")
                candidate = nested
            if not self._test_scope.allows_payload(candidate):
                continue
            normalized = self._normalize_websocket_support_message(candidate)
            if normalized is None or not self._test_scope.allows_payload(normalized):
                raise ValueError("Bisq2 scoped support snapshot item is invalid")
            message_id = self._derive_message_id(normalized)
            if message_id in snapshot_ids:
                continue
            snapshot_ids.add(message_id)
            snapshot_messages.append(normalized)

        # The first acknowledgement is a history baseline, not live work. It
        # is deliberately suppressed and reconciled against the fresh REST
        # baseline before scope readiness. Later acknowledgements are reconnect
        # snapshots and may contain events missed while the socket was down.
        if not self._support_subscription_established:
            self._support_snapshot_reconciled = True
            return

        # No test event is valid before the fresh scope baseline. A reconnect
        # during startup therefore remains history and cannot enter generation.
        if self._scope_rebaseline_pending or self._last_poll_since is None:
            self._support_snapshot_reconciled = True
            return

        buffered_ids = {
            self._derive_message_id(message) for message in self._ws_message_buffer
        }
        pending: List[Dict[str, Any]] = []
        cursor = self._last_poll_since
        if cursor.tzinfo is None:
            cursor = cursor.replace(tzinfo=timezone.utc)
        else:
            cursor = cursor.astimezone(timezone.utc)
        for message in snapshot_messages:
            message_id = self._derive_message_id(message)
            if message_id in self._seen_message_ids or message_id in buffered_ids:
                continue
            timestamp_ms = self._resolve_timestamp_ms(message)
            if timestamp_ms <= 0:
                raise ValueError(
                    "Bisq2 reconnect snapshot item has no usable timestamp"
                )
            message_time = datetime.fromtimestamp(
                timestamp_ms / 1000.0,
                tz=timezone.utc,
            )
            if message_time < cursor:
                continue
            pending.append(message)
        maxlen = self._ws_message_buffer.maxlen
        if maxlen is not None and len(self._ws_message_buffer) + len(pending) > maxlen:
            raise ValueError("Bisq2 scoped support snapshot exceeds buffer capacity")

        for message in pending:
            self._cache_message(message)
            self._ws_message_buffer.append(message)
        self._support_snapshot_reconciled = True

    def _normalize_websocket_support_message(
        self, payload: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Normalize websocket support payload to REST-export message shape."""
        text = payload.get("text", payload.get("message"))
        if not isinstance(text, str) or not text.strip():
            return None

        conversation_id = str(
            payload.get("conversationId", payload.get("channelId", "")) or ""
        ).strip()
        channel_id = str(payload.get("channelId", conversation_id) or "").strip()
        author_id = str(
            payload.get("senderUserProfileId", payload.get("authorId", "")) or ""
        ).strip()
        author = str(payload.get("author", author_id or "unknown") or "unknown")
        message_id = str(payload.get("messageId", "") or "").strip()

        date = ""
        timestamp = payload.get("timestamp")
        if isinstance(timestamp, (int, float)):
            date = (
                datetime.fromtimestamp(float(timestamp) / 1000.0, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        elif isinstance(payload.get("date"), str):
            date = payload.get("date", "")

        normalized: Dict[str, Any] = {
            "messageId": message_id,
            "author": author,
            "authorId": author_id,
            "message": text.strip(),
            "conversationId": conversation_id,
            "channelId": channel_id,
            "date": date,
        }
        if isinstance(timestamp, (int, float)):
            normalized["timestamp"] = int(timestamp)
        for source_key, target_key in (("citationMessageId", "citationMessageId"),):
            value = payload.get(source_key)
            if isinstance(value, str) and value.strip():
                normalized[target_key] = value.strip()
        return normalized

    def _drain_ws_messages(self) -> List[Dict[str, Any]]:
        """Drain buffered websocket messages atomically."""
        if not self._ws_message_buffer:
            return []
        messages = list(self._ws_message_buffer)
        self._ws_message_buffer.clear()
        return messages

    def _requeue_ws_messages(self, messages: List[Dict[str, Any]]) -> None:
        """Restore unclaimed events ahead of frames received during persistence I/O."""
        if not messages:
            return
        combined = [*messages, *self._ws_message_buffer]
        maxlen = self._ws_message_buffer.maxlen
        if maxlen is not None and len(combined) > maxlen:
            self._logger.warning(
                "Bisq2 websocket retry buffer full (%s); REST backfill is required",
                maxlen,
            )
            combined = combined[-maxlen:]
        self._ws_message_buffer.clear()
        self._ws_message_buffer.extend(combined)

    def _parse_websocket_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        """Parse websocket payloads that can arrive as dict or JSON string."""
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return parsed
        return None

    async def _process_raw_messages(
        self, messages: List[Dict[str, Any]], source_name: str
    ) -> List[IncomingMessage]:
        """Run dedupe + transform pipeline for raw messages."""
        eligible_messages = []
        seen_in_batch: set[str] = set()
        blocked_count = 0
        for msg in messages:
            message_id = self._derive_message_id(msg)
            if message_id in seen_in_batch or not self._should_process_message(
                message_id
            ):
                continue
            seen_in_batch.add(message_id)
            if not self._test_scope.allows_payload(msg):
                blocked_count += 1
                continue
            msg_with_id = dict(msg)
            msg_with_id["messageId"] = message_id
            eligible_messages.append(msg_with_id)

        with self._seen_message_lock:
            reference_by_id = dict(self._message_cache_by_id)
        reference_by_id.update(
            {self._derive_message_id(message): message for message in eligible_messages}
        )
        new_messages = [
            self._sanitize_message_citation(message, reference_by_id)
            for message in eligible_messages
        ]
        for message in new_messages:
            self._cache_message(message)

        if blocked_count:
            self._logger.info(
                "Suppressed %s %s message(s) outside Bisq2 production-test scope",
                blocked_count,
                source_name,
            )

        staff_message_ids: set[str] = set()
        prepared_incoming: dict[str, IncomingMessage] = {}
        try:
            for msg in new_messages:
                message_id = self._derive_message_id(msg)
                if self._is_staff_message(msg):
                    staff_message_ids.add(message_id)
                    continue

                decision = self._question_prefilter.evaluate_text(msg.get("message"))
                if not decision.should_process:
                    self._logger.debug(
                        "Skipped %s message after question prefilter (reason=%s)",
                        source_name,
                        decision.reason,
                    )
                    continue

                chat_history = self._build_chat_history_for_message(msg)
                incoming = self._transform_bisq_message(msg, chat_history=chat_history)
                if incoming:
                    prepared_incoming[message_id] = incoming
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for msg in new_messages:
                self._message_cache_by_id.pop(self._derive_message_id(msg), None)
            if source_name == "Bisq2 WebSocket":
                self._requeue_ws_messages(new_messages)
            self._logger.warning(
                "Bisq2 message preparation failed before durable claim (%s)",
                type(exc).__name__,
            )
            raise _BisqMessagePreparationError from None

        claimed_ids = (
            await self._claim_messages_durably(new_messages) if new_messages else set()
        )
        if claimed_ids is None:
            for msg in new_messages:
                self._message_cache_by_id.pop(self._derive_message_id(msg), None)
            if source_name == "Bisq2 WebSocket":
                self._requeue_ws_messages(new_messages)
            return []
        if len(claimed_ids) != len(new_messages):
            for msg in new_messages:
                message_id = self._derive_message_id(msg)
                if message_id not in claimed_ids:
                    self._message_cache_by_id.pop(message_id, None)
            new_messages = [
                msg
                for msg in new_messages
                if self._derive_message_id(msg) in claimed_ids
            ]

        incoming_messages = []
        for msg in new_messages:
            message_id = self._derive_message_id(msg)
            if message_id in staff_message_ids:
                await self._maybe_handle_staff_chatops_message(msg)
                await self._record_staff_activity_from_message(msg)
                continue
            incoming = prepared_incoming.get(message_id)
            if incoming:
                incoming_messages.append(incoming)

        if new_messages and not incoming_messages:
            self._logger.debug(
                "Dropped %s %s message(s) after staff/question filtering",
                len(new_messages),
                source_name,
            )
        return incoming_messages

    async def _maybe_handle_staff_chatops_message(self, msg: Dict[str, Any]) -> bool:
        """Handle trusted-staff `!case` commands before normal suppression."""
        adapter = self.runtime.resolve_optional("bisq2_chatops_adapter")
        handle_message = getattr(adapter, "handle_message", None) if adapter else None
        if not callable(handle_message):
            return False
        try:
            return bool(await handle_message(msg))
        except Exception as exc:
            self._logger.debug(
                "Failed processing Bisq2 ChatOps command (%s)",
                type(exc).__name__,
            )
            return False

    async def _record_staff_activity_from_message(self, msg: Dict[str, Any]) -> None:
        """Forward trusted Bisq2 staff activity to arbitration service."""
        arbitration = self.runtime.resolve_optional("arbitration_service")
        if arbitration is None:
            return
        record_staff_activity = getattr(arbitration, "record_staff_activity", None)
        if not callable(record_staff_activity):
            return
        room_or_conversation_id = str(
            msg.get("conversationId", msg.get("channelId", "")) or ""
        ).strip()
        staff_id = self._resolve_sender_profile_id(msg).strip()
        if not room_or_conversation_id or not staff_id:
            return
        try:
            result = record_staff_activity(
                room_or_conversation_id=room_or_conversation_id,
                staff_id=staff_id,
            )
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            self._logger.debug(
                "Failed recording Bisq2 staff activity (%s)",
                type(exc).__name__,
            )

    def _resolve_ws_fallback_interval(self) -> float:
        """Read REST fallback interval used when websocket client is configured."""
        default_seconds = 30.0
        settings = getattr(self.runtime, "settings", None)
        raw_value = None
        if settings is not None and hasattr(
            settings, "BISQ_WS_REST_FALLBACK_INTERVAL_SECONDS"
        ):
            raw_value = getattr(settings, "BISQ_WS_REST_FALLBACK_INTERVAL_SECONDS")
        if isinstance(raw_value, (int, float)):
            return max(0.0, float(raw_value))
        if isinstance(raw_value, str):
            try:
                return max(0.0, float(raw_value))
            except ValueError:
                return default_seconds
        return default_seconds

    def _resolve_ws_startup_timeout(self) -> float:
        """Read startup timeout for websocket connect/subscribe handshake."""
        default_seconds = 5.0
        settings = getattr(self.runtime, "settings", None)
        raw_value = None
        if settings is not None and hasattr(
            settings, "BISQ_WS_STARTUP_TIMEOUT_SECONDS"
        ):
            raw_value = getattr(settings, "BISQ_WS_STARTUP_TIMEOUT_SECONDS")

        if isinstance(raw_value, (int, float)):
            return max(0.1, float(raw_value))
        if isinstance(raw_value, str):
            try:
                return max(0.1, float(raw_value))
            except ValueError:
                return default_seconds
        return default_seconds

    async def _await_with_startup_timeout(self, awaitable: Any) -> Any:
        """Await helper with bounded timeout to avoid startup deadlocks."""
        return await asyncio.wait_for(
            awaitable, timeout=self._ws_startup_timeout_seconds
        )

    def _should_run_rest_fallback_poll(self) -> bool:
        """Throttle REST fallback polling while websocket stream is active."""
        interval = self._ws_rest_fallback_interval_seconds
        if interval <= 0:
            return True
        now = time.monotonic()
        if now - self._last_rest_fallback_poll_at < interval:
            return False
        self._last_rest_fallback_poll_at = now
        return True

    def _derive_message_id(self, msg: Dict[str, Any]) -> str:
        """Derive a stable message ID when API messageId is missing."""
        message_id = str(msg.get("messageId", "")).strip()
        if message_id:
            return message_id

        stable_payload = {
            "conversationId": msg.get("conversationId", ""),
            "channelId": msg.get("channelId", ""),
            "author": msg.get("author", ""),
            "message": msg.get("message", ""),
            "date": msg.get("date", ""),
        }
        payload = json.dumps(stable_payload, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"derived-{digest}"

    def _derive_user_id(self, author_id: str, author: str) -> str:
        """Derive a UserContext-compliant user_id from Bisq payload fields."""
        if author_id:
            if self._VALID_USER_ID_PATTERN.match(author_id):
                return author_id
            digest = hashlib.sha256(author_id.encode("utf-8")).hexdigest()[:24]
            return f"bisq2-user-{digest}"

        normalized_alias = author.strip()
        if normalized_alias and self._VALID_USER_ID_PATTERN.match(normalized_alias):
            return normalized_alias

        fallback_source = normalized_alias or "unknown"
        digest = hashlib.sha256(fallback_source.encode("utf-8")).hexdigest()[:24]
        return f"bisq2-user-{digest}"

    def _should_process_message(self, message_id: str) -> bool:
        with self._seen_message_lock:
            return message_id not in self._seen_message_ids

    def _build_chat_history_for_message(
        self, msg: Dict[str, Any]
    ) -> Optional[List[ChatMessage]]:
        """Build compact chat history for a user question."""
        conversation_id = str(
            msg.get("conversationId", msg.get("channelId", "")) or ""
        ).strip()
        requester_id = self._derive_user_id(
            author_id=self._resolve_sender_profile_id(msg),
            author=self._resolve_sender_alias(msg),
        )
        current_message_id = self._derive_message_id(msg)
        if not conversation_id or not requester_id or not current_message_id:
            return None

        conversation_messages = self._collect_conversation_messages(conversation_id)
        history_payload = build_channel_chat_history(
            conversation_messages,
            current_message_id=current_message_id,
            requester_id=requester_id,
            is_staff_message=self._is_staff_conversation_message,
        )
        if not history_payload:
            return None

        history: List[ChatMessage] = []
        for entry in history_payload:
            role = str(entry.get("role", "")).strip().lower()
            content = str(entry.get("content", "")).strip()
            if role not in {"user", "assistant", "system"} or not content:
                continue
            try:
                history.append(
                    ChatMessage(
                        role=cast(Literal["user", "assistant", "system"], role),
                        content=content,
                    )
                )
            except Exception:
                continue
        return history or None

    def _collect_conversation_messages(
        self, conversation_id: str
    ) -> List[ConversationMessage]:
        """Collect normalized messages for one conversation from local cache."""
        by_id: Dict[str, ConversationMessage] = {}
        with self._seen_message_lock:
            cached_messages = list(self._message_cache_by_id.values())
        for raw in cached_messages:
            if not isinstance(raw, dict):
                continue
            raw_conversation_id = str(
                raw.get("conversationId", raw.get("channelId", "")) or ""
            ).strip()
            if raw_conversation_id != conversation_id:
                continue
            normalized = self._to_conversation_message(raw, raw_conversation_id)
            if normalized is None:
                continue
            by_id[normalized.message_id] = normalized
        return list(by_id.values())

    def _to_conversation_message(
        self, msg: Dict[str, Any], conversation_id: str
    ) -> Optional[ConversationMessage]:
        message_id = self._derive_message_id(msg)
        text = str(msg.get("message", "") or "").strip()
        sender_alias = self._resolve_sender_alias(msg)
        sender_id = self._derive_user_id(
            author_id=self._resolve_sender_profile_id(msg),
            author=sender_alias,
        )
        if not message_id or not text:
            return None

        return ConversationMessage(
            message_id=message_id,
            conversation_id=conversation_id,
            sender_id=sender_id,
            immutable_sender_id=self._resolve_sender_profile_id(msg),
            sender_alias=sender_alias,
            text=text,
            timestamp_ms=self._resolve_timestamp_ms(msg),
            citation_message_id=self._extract_citation_message_id(msg) or None,
        )

    def _resolve_sender_profile_id(self, msg: Dict[str, Any]) -> str:
        """Resolve stable sender profile ID from message payload."""
        return self._test_scope.resolve_payload_sender_profile(msg)

    def _resolve_sender_alias(self, msg: Dict[str, Any]) -> str:
        """Resolve display alias for sender when available."""
        return str(msg.get("author", "") or "").strip()

    def _extract_citation_message_id(self, msg: Dict[str, Any]) -> str:
        """Resolve citation message ID from flat or nested payload fields."""
        values: set[str] = set()
        for key in ("citationMessageId", "citation_message_id"):
            if key not in msg or msg.get(key) is None:
                continue
            value = msg.get(key)
            if not isinstance(value, str) or not value:
                return ""
            values.add(value)

        citation = msg.get("citation")
        if isinstance(citation, dict):
            for key in ("messageId", "chatMessageId"):
                if key not in citation or citation.get(key) is None:
                    continue
                value = citation.get(key)
                if not isinstance(value, str) or not value:
                    return ""
                values.add(value)
        return next(iter(values)) if len(values) == 1 else ""

    def _sanitize_message_citation(
        self,
        msg: Dict[str, Any],
        reference_by_id: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Keep only a same-channel citation to an exact in-scope message."""
        sanitized = dict(msg)
        citation = sanitized.pop("citation", None)
        sanitized.pop("citationMessageId", None)
        sanitized.pop("citation_message_id", None)
        if not isinstance(citation, dict):
            return sanitized

        citation_message_id = self._extract_citation_message_id(msg)
        citation_sender = self._test_scope.resolve_payload_sender_profile(citation)
        if not citation_message_id or not self._test_scope.allows_sender_profile(
            citation_sender
        ):
            return sanitized

        referenced = reference_by_id.get(citation_message_id)
        if not isinstance(referenced, dict) or not self._test_scope.allows_payload(
            referenced
        ):
            return sanitized
        outer_channel = self._test_scope.resolve_payload_channel(msg)
        referenced_channel = self._test_scope.resolve_payload_channel(referenced)
        referenced_sender = self._test_scope.resolve_payload_sender_profile(referenced)
        if (
            not outer_channel
            or referenced_channel != outer_channel
            or referenced_sender != citation_sender
            or self._message_order_key(referenced) >= self._message_order_key(sanitized)
        ):
            return sanitized

        sanitized["citationMessageId"] = citation_message_id
        return sanitized

    def _message_order_key(self, msg: Dict[str, Any]) -> tuple[int, str]:
        """Return the deterministic order used for citation validation."""
        return (self._resolve_timestamp_ms(msg), self._derive_message_id(msg))

    def _resolve_timestamp_ms(self, msg: Dict[str, Any]) -> int:
        """Resolve event timestamp in epoch milliseconds for deterministic ordering."""
        timestamp = msg.get("timestamp")
        if isinstance(timestamp, (int, float)):
            return int(timestamp)

        date_str = str(msg.get("date", "") or "").strip()
        if date_str:
            try:
                return int(
                    datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
                    * 1000
                )
            except ValueError:
                return 0
        return 0

    def _is_staff_conversation_message(self, message: ConversationMessage) -> bool:
        """Check whether a normalized conversation message was sent by staff."""
        staff_resolver = resolve_channel_staff_resolver(self.runtime, self.channel_id)
        if staff_resolver is None:
            return False

        sender_id = message.immutable_sender_id
        return bool(sender_id and staff_resolver.is_staff(sender_id))

    def _is_staff_message(self, msg: Dict[str, Any]) -> bool:
        """Return True when message author is trusted staff or support agent identity."""
        sender_id = self._resolve_sender_profile_id(msg)
        sender_alias = self._resolve_sender_alias(msg)
        conversation_message = ConversationMessage(
            message_id=self._derive_message_id(msg),
            conversation_id=str(
                msg.get("conversationId", msg.get("channelId", "")) or ""
            ).strip(),
            sender_id=sender_id,
            immutable_sender_id=sender_id,
            sender_alias=sender_alias,
            text=str(msg.get("message", "") or "").strip(),
            timestamp_ms=self._resolve_timestamp_ms(msg),
            citation_message_id=self._extract_citation_message_id(msg) or None,
        )
        return self._is_staff_conversation_message(conversation_message)

    def _cache_message(self, msg: Dict[str, Any]) -> None:
        """Cache normalized support message by ID for reaction resolution."""
        if not self._test_scope.allows_payload(msg):
            return
        message_id = self._derive_message_id(msg)
        msg_with_id = dict(msg)
        msg_with_id.pop("citation", None)
        msg_with_id["messageId"] = message_id
        with self._seen_message_lock:
            self._message_cache_by_id[message_id] = msg_with_id

    def _mark_seen(
        self,
        message_id: str,
        *,
        record_in_sync_state: bool = True,
    ) -> None:
        """Track seen message IDs with bounded memory usage."""
        with self._seen_message_lock:
            if message_id in self._seen_message_ids:
                return

            self._seen_message_ids.add(message_id)
            self._seen_message_order.append(message_id)
            mark_processed = getattr(self._sync_state_manager, "mark_processed", None)
            if record_in_sync_state and callable(mark_processed):
                mark_processed(message_id)

            while len(self._seen_message_order) > self._max_seen_message_ids:
                oldest = self._seen_message_order.popleft()
                self._seen_message_ids.discard(oldest)
                self._message_cache_by_id.pop(oldest, None)

    def _prune_seen_message_ids(self, expired_ids: set[str]) -> None:
        """Evict privacy-expired IDs from all live Bisq channel caches."""
        if not expired_ids:
            return
        with self._seen_message_lock:
            self._seen_message_ids.difference_update(expired_ids)
            self._seen_message_order = deque(
                message_id
                for message_id in self._seen_message_order
                if message_id not in expired_ids
            )
            for message_id in expired_ids:
                self._message_cache_by_id.pop(message_id, None)

    def _resolve_visible_citation(self, original_question: Any) -> Optional[str]:
        """Return user-facing citation text without internal history scaffolding."""
        if original_question is None:
            return None

        citation = str(original_question).strip()
        if not citation:
            return None

        lines = [line.strip() for line in citation.splitlines() if line.strip()]
        if not lines:
            return None

        first_line = lines[0]
        if not first_line.lower().startswith("current question:"):
            return citation

        visible_lines = [first_line]
        quoted_context = next(
            (line for line in lines[1:] if line.lower().startswith("quoted context:")),
            None,
        )
        if quoted_context:
            visible_lines.append(quoted_context)
        return "\n".join(visible_lines)

    def _extract_export_timestamp(self, result: Dict[str, Any]) -> Optional[datetime]:
        """Extract export timestamp from Bisq API payload."""
        export_date = result.get("exportDate")
        if not isinstance(export_date, str) or not export_date.strip():
            return None

        try:
            parsed = datetime.fromisoformat(export_date.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _rest_boundary_now() -> datetime:
        """Capture a UTC cursor at the Bisq message timestamp's millisecond precision."""
        now = datetime.now(timezone.utc)
        return now.replace(microsecond=(now.microsecond // 1000) * 1000)
