"""Matrix Shadow Mode Integration for support channel monitoring."""

import logging
from typing import Any, Dict, List, Optional, Set

try:
    from nio import AsyncClient, RoomMessagesError  # type: ignore[import-not-found]

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    RoomMessagesError = None

from app.services.shadow_mode_processor import ShadowModeProcessor

logger = logging.getLogger(__name__)


class MatrixShadowModeService:
    """Monitor Matrix support channels without sending responses."""

    def __init__(
        self,
        homeserver: str,
        user_id: str,
        access_token: str,
        room_id: str,
    ):
        """
        Initialize Matrix shadow mode service.

        Args:
            homeserver: Matrix homeserver URL
            user_id: Bot user ID
            access_token: Bot access token
            room_id: Support room to monitor
        """
        if not NIO_AVAILABLE:
            raise ImportError(
                "matrix-nio is not installed. " "Install with: pip install matrix-nio"
            )

        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.room_id = room_id

        # Initialize Matrix client
        self.client = AsyncClient(homeserver, user_id)
        self.client.access_token = access_token

        # Track processed messages
        self._processed_ids: Set[str] = set()

        # Last sync token for pagination
        self._since_token: Optional[str] = None

        logger.info(f"Matrix shadow mode initialized for room {room_id}")

    async def connect(self) -> None:
        """Connect to Matrix homeserver."""
        # Access token already set, no need to login
        logger.info(f"Connected to {self.homeserver}")

    async def disconnect(self) -> None:
        """Disconnect from Matrix homeserver."""
        await self.client.close()
        logger.info("Disconnected from Matrix")

    async def fetch_messages(
        self,
        limit: int = 100,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch messages from the support room.

        Args:
            limit: Maximum number of messages to fetch
            since: Pagination token

        Returns:
            List of message dictionaries
        """
        try:
            response = await self.client.room_messages(
                self.room_id,
                start=since or self._since_token,
                limit=limit,
            )

            if isinstance(response, RoomMessagesError):
                logger.error(f"Error fetching messages: {response.message}")
                return []

            # Update pagination token
            if hasattr(response, "end"):
                self._since_token = response.end

            # Convert to dictionaries
            messages = []
            for event in response.chunk:
                if hasattr(event, "body"):
                    messages.append(
                        {
                            "event_id": event.event_id,
                            "sender": event.sender,
                            "body": event.body,
                            "timestamp": getattr(event, "server_timestamp", 0),
                        }
                    )

            return messages

        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            return []

    def filter_support_questions(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Filter messages to find support questions.

        Args:
            messages: List of message dictionaries

        Returns:
            List of messages that appear to be support questions
        """
        questions = []
        for msg in messages:
            body = msg.get("body", "")
            if ShadowModeProcessor.is_support_question(body):
                questions.append(msg)

        return questions

    def mark_as_processed(self, event_id: str) -> None:
        """
        Mark a message as processed.

        Args:
            event_id: Matrix event ID
        """
        self._processed_ids.add(event_id)

    def is_processed(self, event_id: str) -> bool:
        """
        Check if a message has been processed.

        Args:
            event_id: Matrix event ID

        Returns:
            True if already processed
        """
        return event_id in self._processed_ids

    async def poll_for_questions(self) -> List[Dict[str, Any]]:
        """
        Poll for new support questions.

        Returns:
            List of new support questions
        """
        # Fetch recent messages
        messages = await self.fetch_messages()

        # Filter to support questions only
        questions = self.filter_support_questions(messages)

        # Filter out already processed
        new_questions = [q for q in questions if not self.is_processed(q["event_id"])]

        return new_questions

    async def process_with_shadow_mode(
        self,
        processor: "ShadowModeProcessor",
    ) -> int:
        """
        Process new questions through shadow mode.

        Args:
            processor: Shadow mode processor instance

        Returns:
            Number of questions processed
        """
        questions = await self.poll_for_questions()
        processed_count = 0

        for question in questions:
            event_id = question["event_id"]
            body = question["body"]
            sender = question["sender"]

            try:
                # Process through shadow mode
                response = await processor.process_question(
                    question=body,
                    question_id=event_id,
                    room_id=self.room_id,
                    sender=sender,
                )

                if response:
                    self.mark_as_processed(event_id)
                    processed_count += 1
                    logger.info(
                        f"Processed question {event_id}: "
                        f"confidence={response.confidence:.2f}"
                    )

            except Exception as e:
                logger.error(f"Error processing {event_id}: {e}")

        return processed_count
