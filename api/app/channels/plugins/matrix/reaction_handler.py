"""Matrix reaction handler for feedback collection.

Listens for m.reaction events via nio callbacks and converts them
into normalized ReactionEvents for processing.
"""

import logging
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.channels.plugins.matrix.room_filter import normalize_room_ids
from app.channels.reactions import (
    ReactionEvent,
    ReactionHandlerBase,
    ReactionProcessor,
    ReactionRating,
)

NioReactionEventType: Any = object
NioRedactionEventType: Any = object

try:
    from nio import ReactionEvent as _NioReactionEvent
    from nio import RedactionEvent as _NioRedactionEvent
except ImportError:  # pragma: no cover - exercised in environments without nio
    pass
else:
    NioReactionEventType = _NioReactionEvent
    NioRedactionEventType = _NioRedactionEvent

# Backward-compatible exported symbols used by tests and callers.
NioReactionEvent = NioReactionEventType
NioRedactionEvent = NioRedactionEventType


logger = logging.getLogger(__name__)


class MatrixReactionHandler(ReactionHandlerBase):
    """Push-based reaction handler using nio event callbacks.

    Registers a callback on the Matrix nio AsyncClient for m.reaction
    events and converts them into ReactionEvents for the processor.
    Also tracks reaction event_ids for redaction/removal handling.
    """

    channel_id: str = "matrix"
    _MAX_TRACKED_REACTIONS: int = 10_000

    def __init__(
        self,
        runtime: Any,
        processor: "ReactionProcessor",
        allowed_room_ids: Any | None = None,
        emoji_rating_map: Optional[Dict[str, ReactionRating]] = None,
    ):
        super().__init__(runtime, processor, emoji_rating_map)
        self.allowed_room_ids = normalize_room_ids(allowed_room_ids)
        self._callback_registered = False
        # Track reaction_event_id -> target message_event_id for redaction (bounded)
        self._reaction_to_message: OrderedDict[str, str] = OrderedDict()
        # Track reaction_event_id -> sender for redaction (bounded)
        self._reaction_to_sender: OrderedDict[str, str] = OrderedDict()
        # Track reaction_event_id -> reaction key for redaction (bounded)
        self._reaction_to_key: OrderedDict[str, str] = OrderedDict()

    async def start_listening(self) -> None:
        """Register nio callbacks for m.reaction and m.room.redaction events."""
        client = self.runtime.resolve("matrix_client")
        client.add_event_callback(self._on_reaction_event, NioReactionEvent)
        client.add_event_callback(self._on_redaction_event, NioRedactionEvent)
        self._callback_registered = True
        self._logger.info("Matrix reaction listener started")

    async def stop_listening(self) -> None:
        """Remove nio callbacks."""
        client = self.runtime.resolve_optional("matrix_client")
        if (
            client
            and self._callback_registered
            and hasattr(client, "remove_event_callback")
        ):
            client.remove_event_callback(self._on_reaction_event)
            client.remove_event_callback(self._on_redaction_event)
            self._callback_registered = False
            self._reaction_to_message.clear()
            self._reaction_to_sender.clear()
            self._reaction_to_key.clear()
            self._logger.info("Matrix reaction listener stopped")

    async def _on_reaction_event(self, room: Any, event: Any) -> None:
        """Handle an incoming m.reaction event.

        Extracts m.relates_to.event_id and key, maps the emoji to a
        rating, and delegates to the processor.
        """
        try:
            room_id = str(getattr(room, "room_id", "") or "").strip()
            if not room_id or room_id not in self.allowed_room_ids:
                return

            source = getattr(event, "source", {})
            content = source.get("content", {})
            relates_to = content.get("m.relates_to")

            if not relates_to:
                return

            target_event_id = relates_to.get("event_id")
            key = relates_to.get("key")

            if not target_event_id or not key:
                return

            rating = self.map_emoji_to_rating(key)
            if rating is None:
                self._logger.debug(
                    "Unmapped Matrix reaction emoji: %s from %s",
                    key,
                    getattr(event, "sender", "unknown"),
                )
                return

            # Track for redaction handling (bounded to prevent memory leak)
            reaction_event_id = getattr(event, "event_id", None)
            sender = getattr(event, "sender", "unknown")
            if reaction_event_id:
                self._reaction_to_message[reaction_event_id] = target_event_id
                self._reaction_to_sender[reaction_event_id] = sender
                self._reaction_to_key[reaction_event_id] = str(key)
                # Evict oldest entries if over limit
                while len(self._reaction_to_message) > self._MAX_TRACKED_REACTIONS:
                    self._reaction_to_message.popitem(last=False)
                    self._reaction_to_sender.popitem(last=False)
                    self._reaction_to_key.popitem(last=False)

            ts = getattr(event, "server_timestamp", None)
            if ts:
                timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            reaction_event = ReactionEvent(
                channel_id="matrix",
                external_message_id=target_event_id,
                reactor_id=sender,
                rating=rating,
                raw_reaction=key,
                timestamp=timestamp,
            )

            await self.processor.process(reaction_event)

        except Exception:
            self._logger.exception(
                "Error processing Matrix reaction event: %s",
                getattr(event, "event_id", "unknown"),
            )

    async def _on_redaction_event(self, room: Any, event: Any) -> None:
        """Handle a redaction event (reaction removal).

        Looks up the redacted event_id in our tracking map and calls
        processor.revoke_reaction() if it was a tracked reaction.
        """
        redacts = getattr(event, "redacts", None)
        if not redacts:
            return
        room_id = str(getattr(room, "room_id", "") or "").strip()
        if not room_id or room_id not in self.allowed_room_ids:
            return

        target_msg_id = self._reaction_to_message.get(redacts)
        reactor_id = self._reaction_to_sender.get(redacts)
        reaction_key = self._reaction_to_key.get(redacts)

        if not target_msg_id or not reactor_id:
            return

        try:
            await self.processor.revoke_reaction(
                channel_id="matrix",
                external_message_id=target_msg_id,
                reactor_id=reactor_id,
                raw_reaction=reaction_key,
            )
            # Clean up tracking maps
            self._reaction_to_message.pop(redacts, None)
            self._reaction_to_sender.pop(redacts, None)
            self._reaction_to_key.pop(redacts, None)
        except Exception:
            self._logger.exception("Error revoking Matrix reaction: %s", redacts)
