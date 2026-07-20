"""Bisq2 reaction handler for feedback collection.

Subscribes to SUPPORT_CHAT_REACTIONS via Bisq2 WebSocket and converts
incoming events into normalized ReactionEvents for processing.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.channels.plugins.bisq2.client.websocket import (
    is_valid_subscription_response,
)
from app.channels.plugins.bisq2.test_scope import (
    Bisq2TestScope,
    mark_scope_conflict,
    payloads_have_scope_conflict,
    resolve_bisq2_test_scope,
)
from app.channels.reactions import (
    ReactionEvent,
    ReactionHandlerBase,
    ReactionProcessor,
    ReactionRating,
)

logger = logging.getLogger(__name__)

# Bisq2 reaction enum -> rating mapping
# THUMBS_UP(0), THUMBS_DOWN(1), HAPPY(2), LAUGH(3), HEART(4), PARTY(5)
BISQ2_REACTION_MAP: Dict[str, ReactionRating] = {
    "THUMBS_UP": ReactionRating.POSITIVE,
    "THUMBS_DOWN": ReactionRating.NEGATIVE,
    "HAPPY": ReactionRating.POSITIVE,
    "LAUGH": ReactionRating.POSITIVE,
    "HEART": ReactionRating.POSITIVE,
    "PARTY": ReactionRating.POSITIVE,
}

BISQ2_REACTION_ID_TO_NAME: Dict[int, str] = {
    0: "THUMBS_UP",
    1: "THUMBS_DOWN",
    2: "HAPPY",
    3: "LAUGH",
    4: "HEART",
    5: "PARTY",
}

ReactionIdentity = tuple[str, str, str, str]
ParsedReaction = tuple[str, str, str, str, str]


class Bisq2ReactionHandler(ReactionHandlerBase):
    """Push-based reaction handler using Bisq2 WebSocket subscriptions.

    Subscribes to SUPPORT_CHAT_REACTIONS topic and converts Bisq2
    reaction events into normalized ReactionEvents.
    """

    channel_id: str = "bisq2"

    def __init__(
        self,
        runtime: Any,
        processor: "ReactionProcessor",
        emoji_rating_map: Optional[Dict[str, ReactionRating]] = None,
    ):
        # Use Bisq2-specific mapping as default
        if emoji_rating_map is None:
            emoji_rating_map = dict(BISQ2_REACTION_MAP)
        super().__init__(runtime, processor, emoji_rating_map)
        self._test_scope: Bisq2TestScope = resolve_bisq2_test_scope(
            getattr(runtime, "settings", None)
        )
        self._ws_client: Any = None
        self._is_listening = False
        self._snapshot_reconciled = False
        self._active_reactions: Dict[ReactionIdentity, ParsedReaction] = {}
        self._unmapped_count: int = 0

    @property
    def is_listening(self) -> bool:
        """Return whether the scoped reaction subscription completed."""
        if (
            not self._is_listening
            or not self._snapshot_reconciled
            or self._ws_client is None
        ):
            return False
        connected = getattr(self._ws_client, "is_connected", False)
        if callable(connected) or connected is not True:
            return False
        if getattr(self._ws_client, "is_listening", False) is not True:
            return False
        has_active_subscription = getattr(
            self._ws_client, "has_active_subscription", None
        )
        if not callable(has_active_subscription):
            return False
        return has_active_subscription("SUPPORT_CHAT_REACTIONS") is True

    async def start_listening(self) -> None:
        """Connect to Bisq2 WebSocket and subscribe to reactions topic."""
        self._is_listening = False
        self._snapshot_reconciled = False
        if not self._test_scope.ready:
            raise RuntimeError("Bisq2 production-test scope is unavailable")
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client is None:
            raise RuntimeError(
                "bisq2_websocket_client must be registered before start_listening"
            )
        self._ws_client = ws_client

        is_connected = await self._resolve_is_connected(ws_client)
        if not is_connected:
            await ws_client.connect()
        on_snapshot = getattr(ws_client, "on_subscription_snapshot", None)
        if not callable(on_snapshot):
            raise RuntimeError(
                "bisq2_websocket_client must support subscription snapshots"
            )
        ws_client.on_event(self._on_websocket_event)
        on_snapshot(self._on_subscription_snapshot)
        try:
            subscription_response = await ws_client.subscribe("SUPPORT_CHAT_REACTIONS")
            if not is_valid_subscription_response(subscription_response):
                raise RuntimeError("Bisq2 reaction subscription was not acknowledged")
            if not self._snapshot_reconciled:
                raise RuntimeError("Bisq2 reaction snapshot was not reconciled")
            has_active_subscription = getattr(
                ws_client,
                "has_active_subscription",
                None,
            )
            if (
                not callable(has_active_subscription)
                or has_active_subscription("SUPPORT_CHAT_REACTIONS") is not True
            ):
                raise RuntimeError("Bisq2 reaction subscription is not current")
        except BaseException:
            off_event = getattr(ws_client, "off_event", None)
            if callable(off_event):
                off_event(self._on_websocket_event)
            off_snapshot = getattr(ws_client, "off_subscription_snapshot", None)
            if callable(off_snapshot):
                off_snapshot(self._on_subscription_snapshot)
            raise
        self._is_listening = True

        self._logger.info("Bisq2 reaction listener started")

    async def stop_listening(self) -> None:
        """Close the WebSocket connection."""
        try:
            if self._ws_client:
                try:
                    off_event = getattr(self._ws_client, "off_event", None)
                    if callable(off_event):
                        off_event(self._on_websocket_event)
                    off_snapshot = getattr(
                        self._ws_client,
                        "off_subscription_snapshot",
                        None,
                    )
                    if callable(off_snapshot):
                        off_snapshot(self._on_subscription_snapshot)
                    await self._ws_client.close()
                except Exception as exc:
                    self._logger.debug(
                        "Error closing Bisq2 WebSocket (%s)", type(exc).__name__
                    )
                self._logger.info("Bisq2 reaction listener stopped")
        finally:
            self._ws_client = None
            self._is_listening = False
            self._snapshot_reconciled = False

    async def _on_subscription_snapshot(
        self,
        topic: str,
        parameter: Optional[str],
        raw_payload: Optional[str],
    ) -> None:
        """Reconcile the authoritative active-reaction set from an ack."""
        del parameter
        if topic != "SUPPORT_CHAT_REACTIONS":
            return

        self._snapshot_reconciled = False
        if not isinstance(raw_payload, str):
            raise ValueError("Bisq2 reaction snapshot payload is missing")
        try:
            decoded = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Bisq2 reaction snapshot payload is invalid") from exc
        if not isinstance(decoded, list):
            raise ValueError("Bisq2 reaction snapshot payload must be a list")

        snapshot: Dict[ReactionIdentity, ParsedReaction] = {}
        for item in decoded:
            if not isinstance(item, dict):
                raise ValueError("Bisq2 reaction snapshot item is invalid")

            scoped_payload = self._extract_nested_payload(item)
            if not self._test_scope.allows_payload(scoped_payload):
                continue
            parsed = self._extract_reaction_fields(
                {
                    "topic": "SUPPORT_CHAT_REACTIONS",
                    "modificationType": "ADDED",
                    "payload": item,
                }
            )
            if parsed is None:
                raise ValueError("Bisq2 scoped reaction snapshot item is invalid")
            snapshot[self._reaction_identity(parsed)] = parsed

        removed = set(self._active_reactions) - set(snapshot)
        for identity in sorted(removed):
            parsed = self._active_reactions[identity]
            await self._apply_removed(parsed)
            self._active_reactions.pop(identity, None)

        added = set(snapshot) - set(self._active_reactions)
        for identity in sorted(added):
            parsed = snapshot[identity]
            await self._apply_added(parsed)
            self._active_reactions[identity] = parsed

        self._active_reactions = snapshot
        self._snapshot_reconciled = True

    async def _on_websocket_event(self, event: Dict[str, Any]) -> None:
        """Handle an incoming WebSocket event.

        Extracts reaction data from the payload and delegates to the
        processor for ADDED events, or revokes for REMOVED events.
        """
        try:
            topic = str(event.get("topic", "") or "").strip()
            modification_type = (
                str(event.get("modificationType", "") or "").strip().upper()
            )
            if topic != "SUPPORT_CHAT_REACTIONS":
                return
            if modification_type not in {"ADDED", "REMOVED"}:
                return

            parsed = self._extract_reaction_fields(event)
            if parsed is None:
                return

            identity = self._reaction_identity(parsed)
            modification_type = parsed[0]

            if modification_type == "REMOVED":
                await self._apply_removed(parsed)
                self._active_reactions.pop(identity, None)
                return

            await self._apply_added(parsed)
            self._active_reactions[identity] = parsed

        except Exception as exc:
            self._logger.warning(
                "Error processing Bisq2 reaction event (%s)", type(exc).__name__
            )

    async def _apply_added(self, parsed: ParsedReaction) -> None:
        _, reaction_name, message_id, sender_id, native_channel_id = parsed
        rating = self.map_emoji_to_rating(reaction_name)
        if rating is None:
            self._unmapped_count += 1
            self._logger.debug(
                "Unmapped Bisq2 reaction: %s (total_dropped=%d)",
                reaction_name,
                self._unmapped_count,
            )
            return

        reaction_event = ReactionEvent(
            channel_id="bisq2",
            external_message_id=message_id,
            reactor_id=sender_id,
            rating=rating,
            raw_reaction=reaction_name,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "delivery_target": native_channel_id,
                "bisq2_channel_id": native_channel_id,
            },
        )
        await self.processor.process(reaction_event)

    async def _apply_removed(self, parsed: ParsedReaction) -> None:
        _, reaction_name, message_id, sender_id, native_channel_id = parsed
        await self.processor.revoke_reaction(
            channel_id="bisq2",
            external_message_id=message_id,
            reactor_id=sender_id,
            raw_reaction=reaction_name,
            delivery_target=native_channel_id,
        )

    @staticmethod
    def _reaction_identity(parsed: ParsedReaction) -> ReactionIdentity:
        _, reaction_name, message_id, sender_id, native_channel_id = parsed
        return native_channel_id, message_id, sender_id, reaction_name

    async def _resolve_is_connected(self, ws_client: Any) -> bool:
        is_connected_attr = getattr(ws_client, "is_connected", False)
        if callable(is_connected_attr):
            result = is_connected_attr()
            if hasattr(result, "__await__"):
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

    def _extract_reaction_fields(
        self,
        event: Dict[str, Any],
    ) -> Optional[ParsedReaction]:
        """Extract normalized reaction fields from mixed Bisq2 payload shapes."""
        envelope_payload = self._parse_payload(event.get("payload"))
        if envelope_payload is None:
            return None

        # Some emitters nest the DTO under a namespaced key.
        payload = self._extract_nested_payload(envelope_payload)
        if not self._test_scope.allows_payload(payload):
            return None

        reaction_name = self._resolve_reaction_name(envelope_payload, payload)
        message_id = self._resolve_message_id(event, envelope_payload, payload)
        sender_id = self._resolve_sender_id(payload)
        native_channel_id = self._test_scope.resolve_payload_channel(payload)
        modification_type = self._resolve_modification_type(
            event, envelope_payload, payload
        )

        if (
            not modification_type
            or not reaction_name
            or not message_id
            or not sender_id
            or not native_channel_id
        ):
            self._logger.debug("Dropping incomplete Bisq2 reaction event")
            return None
        return (
            modification_type,
            reaction_name,
            message_id,
            sender_id,
            native_channel_id,
        )

    @staticmethod
    def _extract_nested_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        nested = payload.get("reaction")
        if isinstance(nested, dict):
            return Bisq2ReactionHandler._merge_nested_payload(payload, nested)
        nested = payload.get("reactionDto")
        if isinstance(nested, dict):
            return Bisq2ReactionHandler._merge_nested_payload(payload, nested)
        return payload

    @staticmethod
    def _merge_nested_payload(
        payload: Dict[str, Any], nested: Dict[str, Any]
    ) -> Dict[str, Any]:
        merged = dict(nested)
        if payloads_have_scope_conflict(payload, nested):
            mark_scope_conflict(merged)
        for key in (
            "messageId",
            "chatMessageId",
            "senderUserProfileId",
            "senderId",
            "channelId",
            "conversationId",
            "isRemoved",
        ):
            if key not in merged and key in payload:
                merged[key] = payload.get(key)
        return merged

    @staticmethod
    def _resolve_modification_type(
        event: Dict[str, Any], *payloads: Dict[str, Any]
    ) -> str:
        modification_type = str(event.get("modificationType", "") or "").strip().upper()
        if modification_type not in {"ADDED", "REMOVED"}:
            return ""

        removed_values: set[bool] = set()
        for payload in payloads:
            if "isRemoved" not in payload:
                continue
            is_removed = payload.get("isRemoved")
            if not isinstance(is_removed, bool):
                return ""
            removed_values.add(is_removed)

        if len(removed_values) > 1:
            return ""
        if removed_values and next(iter(removed_values)) != (
            modification_type == "REMOVED"
        ):
            return ""
        return modification_type

    @staticmethod
    def _resolve_message_id(*sources: Dict[str, Any]) -> str:
        values: set[str] = set()
        for source in sources:
            for key in ("messageId", "chatMessageId", "chat_message_id"):
                if key not in source:
                    continue
                raw_value = source.get(key)
                if not isinstance(raw_value, str):
                    return ""
                value = raw_value.strip()
                if not value:
                    return ""
                values.add(value)
        if len(values) != 1:
            return ""
        return next(iter(values))

    @staticmethod
    def _resolve_sender_id(payload: Dict[str, Any]) -> str:
        for key in ("senderUserProfileId", "authorId", "senderId"):
            value = str(payload.get(key, "") or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_reaction_name(*payloads: Dict[str, Any]) -> str:
        values: set[str] = set()
        for payload in payloads:
            if "reaction" in payload:
                raw_reaction = payload.get("reaction")
                if not isinstance(raw_reaction, dict):
                    if not isinstance(raw_reaction, str):
                        return ""
                    reaction_name = Bisq2ReactionHandler._normalize_reaction_name(
                        raw_reaction
                    )
                    if not reaction_name:
                        return ""
                    values.add(reaction_name)

            if "reactionId" in payload:
                raw_reaction_id = payload.get("reactionId")
                if not isinstance(raw_reaction_id, int) or isinstance(
                    raw_reaction_id, bool
                ):
                    return ""
                reaction_name = BISQ2_REACTION_ID_TO_NAME.get(raw_reaction_id, "")
                if not reaction_name:
                    return ""
                values.add(reaction_name)

        if len(values) != 1:
            return ""
        return next(iter(values))

    @staticmethod
    def _normalize_reaction_name(raw_reaction: Any) -> str:
        """Normalize textual reaction keys to stable uppercase enum-like names."""
        name = str(raw_reaction or "").strip().upper()
        if not name:
            return ""
        return name

    @staticmethod
    def _parse_payload(raw_payload: Any) -> Optional[Dict[str, Any]]:
        """Normalize WebSocket payload to dict.

        Java Bisq2 WS events send `payload` as a JSON string, while tests and
        older clients may provide it as a dict directly.
        """
        if isinstance(raw_payload, dict):
            return raw_payload
        if isinstance(raw_payload, str):
            try:
                parsed = json.loads(raw_payload)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return parsed
        return None
