"""Bisq2 reaction handler for feedback collection.

Subscribes to SUPPORT_CHAT_REACTIONS via Bisq2 WebSocket and converts
incoming events into normalized ReactionEvents for processing.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
        self._ws_client: Any = None
        self._unmapped_count: int = 0

    async def start_listening(self) -> None:
        """Connect to Bisq2 WebSocket and subscribe to reactions topic."""
        ws_client = self.runtime.resolve_optional("bisq2_websocket_client")
        if ws_client is None:
            raise RuntimeError(
                "bisq2_websocket_client must be registered before start_listening"
            )
        self._ws_client = ws_client

        is_connected = await self._resolve_is_connected(ws_client)
        if not is_connected:
            await ws_client.connect()
        ws_client.on_event(self._on_websocket_event)
        await ws_client.subscribe("SUPPORT_CHAT_REACTIONS")

        self._logger.info("Bisq2 reaction listener started")

    async def stop_listening(self) -> None:
        """Close the WebSocket connection."""
        if self._ws_client:
            try:
                await self._ws_client.close()
            except Exception:
                self._logger.debug("Error closing Bisq2 WebSocket", exc_info=True)
            self._ws_client = None
            self._logger.info("Bisq2 reaction listener stopped")

    async def _on_websocket_event(self, event: Dict[str, Any]) -> None:
        """Handle an incoming WebSocket event.

        Extracts reaction data from the payload and delegates to the
        processor for ADDED events, or revokes for REMOVED events.
        """
        try:
            parsed = self._extract_reaction_fields(event)
            if parsed is None:
                return

            modification_type, reaction_name, message_id, sender_id = parsed

            if modification_type == "REMOVED":
                await self.processor.revoke_reaction(
                    channel_id="bisq2",
                    external_message_id=message_id,
                    reactor_id=sender_id,
                    raw_reaction=reaction_name,
                )
                return

            # Map reaction name to rating
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
            )

            await self.processor.process(reaction_event)

        except Exception:
            message_id = "unknown"
            parsed_payload = self._parse_payload(event.get("payload"))
            if parsed_payload is not None:
                message_id = parsed_payload.get("messageId", "unknown")
            self._logger.exception(
                "Error processing Bisq2 reaction event: %s",
                message_id,
            )

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
    ) -> Optional[tuple[str, str, str, str]]:
        """Extract normalized reaction fields from mixed Bisq2 payload shapes."""
        payload = self._parse_payload(event.get("payload"))
        if payload is None:
            return None

        # Some emitters nest the DTO under a namespaced key.
        payload = self._extract_nested_payload(payload)

        reaction_name = self._resolve_reaction_name(payload)
        message_id = self._resolve_message_id(event, payload)
        sender_id = self._resolve_sender_id(payload)
        modification_type = self._resolve_modification_type(event, payload)

        if not reaction_name or not message_id or not sender_id:
            self._logger.debug(
                "Dropping Bisq2 reaction event missing fields: modification=%s reaction=%s message_id=%s sender_id=%s payload_keys=%s",
                modification_type or "<empty>",
                reaction_name or "<empty>",
                message_id or "<empty>",
                sender_id or "<empty>",
                sorted(payload.keys()),
            )
            return None
        return modification_type, reaction_name, message_id, sender_id

    @staticmethod
    def _extract_nested_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        nested = payload.get("reaction")
        if isinstance(nested, dict):
            return nested
        nested = payload.get("reactionDto")
        if isinstance(nested, dict):
            merged = dict(nested)
            for key in ("messageId", "chatMessageId", "senderUserProfileId"):
                if key not in merged and key in payload:
                    merged[key] = payload.get(key)
            return merged
        return payload

    @staticmethod
    def _resolve_modification_type(
        event: Dict[str, Any], payload: Dict[str, Any]
    ) -> str:
        if bool(payload.get("isRemoved")):
            return "REMOVED"
        return str(event.get("modificationType", "ADDED") or "ADDED").strip().upper()

    @staticmethod
    def _resolve_message_id(event: Dict[str, Any], payload: Dict[str, Any]) -> str:
        for source in (payload, event):
            for key in ("messageId", "chatMessageId", "chat_message_id"):
                value = str(source.get(key, "") or "").strip()
                if value:
                    return value
        return ""

    @staticmethod
    def _resolve_sender_id(payload: Dict[str, Any]) -> str:
        for key in ("senderUserProfileId", "authorId", "senderId"):
            value = str(payload.get(key, "") or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _resolve_reaction_name(payload: Dict[str, Any]) -> str:
        reaction_name = Bisq2ReactionHandler._normalize_reaction_name(
            payload.get("reaction")
        )
        if reaction_name:
            return reaction_name
        raw_reaction_id = payload.get("reactionId")
        if raw_reaction_id is None:
            return ""
        try:
            return BISQ2_REACTION_ID_TO_NAME.get(int(raw_reaction_id), "")
        except (TypeError, ValueError):
            return ""

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
