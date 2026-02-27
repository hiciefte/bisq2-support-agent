"""Bisq2 Channel Plugin.

Wraps existing Bisq2 API integration into channel plugin architecture.
"""

import asyncio
import hashlib
import inspect
import json
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Set

from app.channels.base import ChannelBase
from app.channels.history_builder import (
    ConversationMessage,
    build_channel_chat_history,
)
from app.channels.models import (
    ChannelCapability,
    ChannelType,
    ChatMessage,
    IncomingMessage,
    OutgoingMessage,
    UserContext,
)
from app.channels.plugins.support_markdown import (
    compose_support_answer_markdown,
    serialize_sources_for_tracking,
)
from app.channels.question_prefilter import (
    QuestionPrefilter,
    QuestionPrefilterProtocol,
)
from app.channels.registry import register_channel
from app.channels.staff import StaffResolver, collect_trusted_staff_ids


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
    _last_rest_fallback_poll_at: float
    _ws_rest_fallback_interval_seconds: float
    _ws_startup_timeout_seconds: float
    _question_prefilter: QuestionPrefilterProtocol
    _VALID_USER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-@.:]{1,128}$")
    ENABLED_FLAG = "BISQ2_CHANNEL_ENABLED"
    ENABLED_DEFAULT = False

    @classmethod
    def setup_dependencies(cls, runtime: Any, settings: Any) -> None:
        """Register Bisq2 channel dependencies in shared runtime."""
        from app.channels.plugins.bisq2.client.api import Bisq2API
        from app.channels.plugins.bisq2.client.websocket import Bisq2WebSocketClient
        from app.channels.plugins.bisq2.reaction_handler import Bisq2ReactionHandler
        from app.channels.plugins.bisq2.utils import build_bisq_websocket_url

        bisq_api = Bisq2API(settings=settings)
        ws_client = Bisq2WebSocketClient(
            url=build_bisq_websocket_url(getattr(settings, "BISQ_API_URL", "")),
        )
        staff_resolver = StaffResolver(
            trusted_staff_ids=collect_trusted_staff_ids(settings),
        )
        runtime.register("bisq2_api", bisq_api, allow_override=True)
        runtime.register("bisq2_websocket_client", ws_client, allow_override=True)
        runtime.register("staff_resolver", staff_resolver, allow_override=True)

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
        }

    @property
    def channel_type(self) -> ChannelType:
        """Return channel type for outgoing messages."""
        return ChannelType.BISQ2

    async def start(self) -> None:
        """Start the Bisq2 channel.

        Verifies connectivity to Bisq2 API. If Bisq2API is not registered
        in the runtime, the channel will start in degraded mode (polling
        will return empty results).
        """
        self._logger.info("Starting Bisq2 channel")

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
        except Exception as e:
            self._logger.exception(f"Failed to connect to Bisq2 API: {e}")
            self._is_connected = False

        # Wire reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.start_listening()
                self._logger.info("Bisq2 reaction handler started")
            except Exception:
                self._logger.exception("Failed to start Bisq2 reaction handler")

        # Wire support message websocket stream if registered
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client:
            ws_started = await self._start_support_message_websocket(ws_client)
            if ws_started:
                await self._prime_rest_fallback_cursor(bisq_api)

    async def stop(self) -> None:
        """Stop the Bisq2 channel."""
        self._logger.info("Stopping Bisq2 channel")

        # Stop reaction handler if registered
        reaction_handler = self.runtime.resolve_optional("bisq2_reaction_handler")
        if reaction_handler:
            try:
                await reaction_handler.stop_listening()
                self._logger.info("Bisq2 reaction handler stopped")
            except Exception:
                self._logger.debug(
                    "Error stopping Bisq2 reaction handler", exc_info=True
                )

        if self._ws_listener_task is not None:
            self._ws_listener_task.cancel()
            try:
                await self._ws_listener_task
            except asyncio.CancelledError:
                pass
            except Exception:
                self._logger.debug("Error stopping Bisq2 websocket loop", exc_info=True)
            finally:
                self._ws_listener_task = None

        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        close_fn = getattr(ws_client, "close", None) if ws_client else None
        if callable(close_fn):
            try:
                await close_fn()
            except Exception:
                self._logger.debug(
                    "Error closing Bisq2 websocket client", exc_info=True
                )

        self._ws_message_buffer.clear()
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client is not None:
            self._detach_websocket_callback(ws_client)
        self._ws_callback_registered = False
        self._ws_callback_client = None
        self._is_connected = False
        self._logger.info("Bisq2 channel stopped")

    async def send_message(self, target: str, message: OutgoingMessage) -> bool:
        """Send response back to Bisq2 conversation via REST API.

        Args:
            target: Conversation ID in Bisq2 system.
            message: Response message to send.

        Returns:
            True if message was sent successfully, False otherwise.
        """
        bisq_api = self.runtime.resolve_optional("bisq2_api")
        if not bisq_api:
            self._logger.warning(
                "Bisq2API not registered in runtime, cannot send message"
            )
            return False

        try:
            _meta = getattr(message, "metadata", None)
            rendered_answer = compose_support_answer_markdown(
                message.answer,
                sources=getattr(message, "sources", []),
                confidence_score=getattr(_meta, "confidence_score", None),
            )
            citation = self._resolve_visible_citation(
                getattr(message, "original_question", None)
            )
            response = await bisq_api.send_support_message(
                channel_id=target,
                text=rendered_answer,
                citation=citation,
            )

            external_message_id = response.get("messageId")
            if not external_message_id:
                self._logger.warning(
                    "Bisq2 API send_support_message returned no messageId"
                )
                return False

            # Mark self-sent messages as seen immediately so polling does not
            # feed them back as new incoming user questions.
            self._mark_seen(external_message_id)

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
                    )
                except Exception:
                    self._logger.warning(
                        "Failed to track sent message for reactions", exc_info=True
                    )

            self._logger.info(
                "Sent message to Bisq2 conversation %s (messageId=%s)",
                target,
                external_message_id,
            )
            return True

        except Exception:
            self._logger.exception(
                "Failed to send message to Bisq2 conversation %s", target
            )
            return False

    def get_delivery_target(self, metadata: dict[str, Any]) -> str:
        """Extract Bisq2 delivery target from metadata.

        Prefer conversation_id, but fall back to channel_id for older rows
        created before conversation metadata normalization.
        """
        conversation_id = str(metadata.get("conversation_id", "") or "").strip()
        if conversation_id:
            return conversation_id
        return str(metadata.get("channel_id", "") or "").strip()

    def format_escalation_message(
        self, username: str, escalation_id: int, support_handle: str
    ) -> str:
        """Format escalation message for Bisq2 chat."""
        return (
            f"Your question has been escalated to {support_handle} for review. "
            f"A support team member will respond in this conversation. "
            f"(Reference: #{escalation_id})"
        )

    # handle_incoming() inherited from ChannelBase

    async def poll_conversations(self) -> List[IncomingMessage]:
        """Poll Bisq2 API for new support conversations.

        Delegates to Bisq2API.export_chat_messages() to fetch new conversations,
        then transforms them into IncomingMessage format.

        Returns:
            List of new incoming messages from Bisq2.
        """
        self._logger.debug("Polling Bisq2 API for new conversations")

        incoming_messages: List[IncomingMessage] = []
        ws_messages = self._drain_ws_messages()
        if ws_messages:
            ws_incoming = await self._process_raw_messages(
                ws_messages, source_name="Bisq2 WebSocket"
            )
            incoming_messages.extend(ws_incoming)
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
            result = await bisq_api.export_chat_messages(since=self._last_poll_since)
            if "messages" not in result:
                self._logger.warning(
                    "Bisq2 API export response missing 'messages'; skipping poll cycle"
                )
                return incoming_messages
            messages = result.get("messages", [])

            export_timestamp = self._extract_export_timestamp(result)
            if export_timestamp is None:
                export_timestamp = datetime.now(timezone.utc)

            if not messages:
                self._last_poll_since = export_timestamp
                return incoming_messages

            rest_incoming = await self._process_raw_messages(
                messages, source_name="Bisq2 API"
            )
            incoming_messages.extend(rest_incoming)

            self._logger.info(
                f"Polled {len(incoming_messages)} messages from Bisq2 API"
            )
            self._last_poll_since = export_timestamp
            return incoming_messages

        except Exception:
            self._logger.exception("Error polling Bisq2 API")
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
            message_id = str(msg.get("messageId", "")).strip()
            if not message_id:
                message_id = self._derive_message_id(msg)
            author = str(msg.get("author", "unknown") or "unknown")
            author_id = self._resolve_sender_profile_id(msg)
            user_id = self._derive_user_id(author_id=author_id, author=author)
            text = msg.get("message", "")

            if not text:
                return None

            channel_metadata = {
                "conversation_id": msg.get("conversationId", ""),
                "date": msg.get("date", ""),
                "citation": str(msg.get("citation")) if msg.get("citation") else "",
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
                    auth_token=None,
                ),
                chat_history=chat_history,
                channel_metadata=channel_metadata,
                channel_signature=None,
            )
        except Exception as e:
            self._logger.warning(f"Failed to transform Bisq2 message: {e}")
            return None

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._last_poll_since = None
        self._seen_message_ids = set()
        self._seen_message_order = deque()
        self._max_seen_message_ids = 10000
        self._message_cache_by_id = {}
        self._ws_message_buffer = deque()
        self._ws_listener_task = None
        self._ws_callback_registered = False
        self._ws_callback_client = None
        self._last_rest_fallback_poll_at = 0.0
        self._ws_rest_fallback_interval_seconds = self._resolve_ws_fallback_interval()
        self._ws_startup_timeout_seconds = self._resolve_ws_startup_timeout()
        self._question_prefilter = (
            self.runtime.resolve_optional("question_prefilter") or QuestionPrefilter()
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
                ws_client.on_event(self._on_websocket_event)
                self._ws_callback_registered = True
                self._ws_callback_client = ws_client

            is_connected = await self._resolve_ws_connected(ws_client)
            connect_fn = getattr(ws_client, "connect", None)
            if not is_connected and callable(connect_fn):
                await self._await_with_startup_timeout(connect_fn())

            subscribe_fn = getattr(ws_client, "subscribe", None)
            if callable(subscribe_fn):
                await self._await_with_startup_timeout(
                    subscribe_fn("SUPPORT_CHAT_MESSAGES")
                )

            listen_forever_fn = getattr(ws_client, "listen_forever", None)
            if callable(listen_forever_fn) and (
                self._ws_listener_task is None or self._ws_listener_task.done()
            ):
                self._ws_listener_task = asyncio.create_task(listen_forever_fn())

            self._logger.info("Bisq2 support message websocket stream started")
            return True
        except asyncio.TimeoutError:
            self._logger.warning(
                "Bisq2 support websocket startup timed out after %.2fs; "
                "continuing with REST polling fallback",
                self._ws_startup_timeout_seconds,
            )
            close_fn = getattr(ws_client, "close", None)
            if callable(close_fn):
                try:
                    await close_fn()
                except Exception:
                    self._logger.debug(
                        "Error closing timed-out Bisq2 websocket client", exc_info=True
                    )
            return False
        except Exception:
            self._logger.exception("Failed to start Bisq2 support websocket stream")
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
        if callable(remove_fn):
            try:
                remove_fn(self._on_websocket_event)
                self._ws_callback_registered = False
                self._ws_callback_client = None
            except Exception:
                self._logger.debug(
                    "Failed to remove Bisq2 websocket callback",
                    exc_info=True,
                )

    async def _prime_rest_fallback_cursor(self, bisq_api: Any) -> None:
        """Initialize REST fallback cursor to avoid replaying full export history."""
        if self._last_poll_since is not None:
            return

        export_chat_messages = getattr(bisq_api, "export_chat_messages", None)
        if not callable(export_chat_messages):
            return

        try:
            result_or_awaitable = export_chat_messages(since=None)
            if not inspect.isawaitable(result_or_awaitable):
                return
            result = await result_or_awaitable
        except Exception:
            self._logger.debug(
                "Failed to prime Bisq2 REST fallback cursor", exc_info=True
            )
            return

        if not isinstance(result, dict):
            return

        # Seed dedupe state from startup snapshot to avoid replay if backend
        # ignores `since` filtering on subsequent fallback polls.
        prime_messages = result.get("messages")
        if isinstance(prime_messages, list):
            for raw_message in prime_messages:
                if not isinstance(raw_message, dict):
                    continue
                message_id = self._derive_message_id(raw_message)
                raw_with_id = dict(raw_message)
                raw_with_id["messageId"] = message_id
                self._cache_message(raw_with_id)
                self._mark_seen(message_id)

        export_timestamp = self._extract_export_timestamp(result)
        if export_timestamp is None:
            export_timestamp = datetime.now(timezone.utc)
        self._last_poll_since = export_timestamp

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
                normalized = self._normalize_websocket_support_message(payload)
                if normalized is None:
                    return
                self._cache_message(normalized)
                self._ws_message_buffer.append(normalized)
                return

            if topic == "SUPPORT_CHAT_REACTIONS":
                # Reactions are handled by dedicated feedback processors.
                return
        except Exception:
            self._logger.debug("Failed processing Bisq2 websocket event", exc_info=True)

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
        new_messages = []
        for msg in messages:
            message_id = self._derive_message_id(msg)
            if not self._should_process_message(message_id):
                continue
            msg_with_id = dict(msg)
            msg_with_id["messageId"] = message_id
            new_messages.append(msg_with_id)
            self._cache_message(msg_with_id)

        incoming_messages = []
        for msg in new_messages:
            message_id = self._derive_message_id(msg)
            if self._is_staff_message(msg):
                self._mark_seen(message_id)
                continue

            decision = self._question_prefilter.evaluate_text(msg.get("message"))
            if not decision.should_process:
                self._logger.debug(
                    "Skipped %s messageId=%s after question prefilter (reason=%s)",
                    source_name,
                    message_id,
                    decision.reason,
                )
                self._mark_seen(message_id)
                continue

            chat_history = self._build_chat_history_for_message(msg)
            incoming = self._transform_bisq_message(msg, chat_history=chat_history)
            if incoming:
                incoming_messages.append(incoming)
            self._mark_seen(message_id)

        if new_messages and not incoming_messages:
            self._logger.debug(
                "Dropped %s %s message(s) after staff/question filtering",
                len(new_messages),
                source_name,
            )
        return incoming_messages

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
            "author": msg.get("author", ""),
            "message": msg.get("message", ""),
            "date": msg.get("date", ""),
        }
        payload = json.dumps(stable_payload, sort_keys=True, ensure_ascii=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"derived-{digest}"

    def _derive_user_id(self, author_id: str, author: str) -> str:
        """Derive a UserContext-compliant user_id from Bisq payload fields."""
        for candidate in (author_id.strip(), author.strip()):
            if candidate and self._VALID_USER_ID_PATTERN.match(candidate):
                return candidate

        fallback_source = author_id.strip() or author.strip() or "unknown"
        digest = hashlib.sha256(fallback_source.encode("utf-8")).hexdigest()[:24]
        return f"bisq2-user-{digest}"

    def _should_process_message(self, message_id: str) -> bool:
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
                history.append(ChatMessage(role=role, content=content))
            except Exception:
                continue
        return history or None

    def _collect_conversation_messages(
        self, conversation_id: str
    ) -> List[ConversationMessage]:
        """Collect normalized messages for one conversation from local cache."""
        by_id: Dict[str, ConversationMessage] = {}
        for raw in self._message_cache_by_id.values():
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
            sender_alias=sender_alias,
            text=text,
            timestamp_ms=self._resolve_timestamp_ms(msg),
            citation_message_id=self._extract_citation_message_id(msg) or None,
        )

    def _resolve_sender_profile_id(self, msg: Dict[str, Any]) -> str:
        """Resolve stable sender profile ID from message payload."""
        for key in ("senderUserProfileId", "authorId"):
            value = str(msg.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _resolve_sender_alias(self, msg: Dict[str, Any]) -> str:
        """Resolve display alias for sender when available."""
        return str(msg.get("author", "") or "").strip()

    def _extract_citation_message_id(self, msg: Dict[str, Any]) -> str:
        """Resolve citation message ID from flat or nested payload fields."""
        for key in ("citationMessageId", "citation_message_id"):
            value = str(msg.get(key, "") or "").strip()
            if value:
                return value

        citation = msg.get("citation")
        if isinstance(citation, dict):
            for key in ("messageId", "chatMessageId"):
                value = str(citation.get(key, "") or "").strip()
                if value:
                    return value
        return ""

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
        staff_resolver = self.runtime.resolve_optional("staff_resolver")
        if staff_resolver is None:
            return False

        sender_id = message.sender_id.strip()
        sender_alias = message.sender_alias.strip()
        return bool(
            (sender_id and staff_resolver.is_staff(sender_id))
            or (sender_alias and staff_resolver.is_staff(sender_alias))
        )

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
            sender_alias=sender_alias,
            text=str(msg.get("message", "") or "").strip(),
            timestamp_ms=self._resolve_timestamp_ms(msg),
            citation_message_id=self._extract_citation_message_id(msg) or None,
        )
        return self._is_staff_conversation_message(conversation_message)

    def _cache_message(self, msg: Dict[str, Any]) -> None:
        """Cache normalized support message by ID for reaction resolution."""
        message_id = self._derive_message_id(msg)
        msg_with_id = dict(msg)
        msg_with_id["messageId"] = message_id
        self._message_cache_by_id[message_id] = msg_with_id

    def _mark_seen(self, message_id: str) -> None:
        """Track seen message IDs with bounded memory usage."""
        if message_id in self._seen_message_ids:
            return

        self._seen_message_ids.add(message_id)
        self._seen_message_order.append(message_id)

        while len(self._seen_message_order) > self._max_seen_message_ids:
            oldest = self._seen_message_order.popleft()
            self._seen_message_ids.discard(oldest)
            self._message_cache_by_id.pop(oldest, None)

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
