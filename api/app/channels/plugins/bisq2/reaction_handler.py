"""Bisq2 reaction handler for feedback collection.

Subscribes to SUPPORT_CHAT_REACTIONS via Bisq2 WebSocket and converts
incoming events into normalized ReactionEvents for processing.
"""

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
    "HEART": ReactionRating.POSITIVE,
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
        ws_client = self.runtime.resolve("bisq2_websocket_client")
        self._ws_client = ws_client

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
            payload = event.get("payload")
            if not payload:
                return

            modification_type = event.get("modificationType", "ADDED")
            reaction_name = payload.get("reaction")
            message_id = payload.get("messageId")
            sender_id = payload.get("senderUserProfileId")

            if not reaction_name or not message_id or not sender_id:
                return

            if modification_type == "REMOVED":
                await self.processor.revoke_reaction(
                    channel_id="bisq2",
                    external_message_id=message_id,
                    reactor_id=sender_id,
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
            self._logger.exception(
                "Error processing Bisq2 reaction event: %s",
                event.get("payload", {}).get("messageId", "unknown"),
            )
