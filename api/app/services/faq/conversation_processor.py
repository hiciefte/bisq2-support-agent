"""
Conversation Processor for organizing chat messages into meaningful conversation threads.

This module handles loading messages from JSON export and organizing them into
conversation threads based on message references and timestamps.
"""

import json
import logging
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Set

logger = logging.getLogger(__name__)


class ConversationProcessor:
    """Processor for organizing chat messages into conversation threads.

    This class provides functionality to:
    - Load messages from CSV files
    - Build conversation threads following message references
    - Validate conversation completeness and meaningfulness
    - Group messages into structured conversations
    """

    def __init__(self, support_agent_nicknames: List[str] | None = None):
        """Initialize the conversation processor.

        Args:
            support_agent_nicknames: List of nicknames that identify support agents.
                If None or empty, no messages will be marked as support messages.
        """
        self.messages: Dict[str, Dict] = {}
        self.references: Dict[str, str] = {}
        self.conversations: List[Dict] = []
        self.support_agent_nicknames = set(support_agent_nicknames or [])

    def _is_support_message(self, author: str) -> bool:
        """Determine if a message is from a support agent.

        Args:
            author: The author's nickname

        Returns:
            True if the message is from a support agent, False otherwise
        """
        # Check if author is a known support agent
        # If no support agent nicknames configured, no messages are marked as support
        return author in self.support_agent_nicknames

    def load_messages_from_json(self, json_data: Dict) -> None:
        """Load messages from JSON export data (from API or dict).

        Args:
            json_data: JSON dict matching bisq2 API export format

        Raises:
            ValueError: If the JSON data is malformed or cannot be parsed
        """
        logger.info("Loading messages from JSON data")

        try:
            # Reset message collections to prevent stale data
            self.messages = {}
            self.references = {}
            self.conversations = []

            messages_list = json_data.get("messages", [])
            logger.info(f"Processing {len(messages_list)} messages from JSON")

            for msg_data in messages_list:
                try:
                    msg_id = msg_data["messageId"]

                    # Skip empty or invalid messages
                    if not msg_data.get("message", "").strip():
                        logger.warning(f"Skipping empty message: {msg_id}")
                        continue

                    # Parse ISO 8601 timestamp
                    timestamp = None
                    if msg_data.get("date"):
                        try:
                            # Parse ISO 8601 format with timezone
                            timestamp = datetime.fromisoformat(
                                msg_data["date"].replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError) as exc:
                            logger.warning(
                                f"Timestamp parse error for msg {msg_id}: {exc}"
                            )

                    # Check if message has citation (is a reply/support message)
                    citation = msg_data.get("citation")
                    referenced_msg_id = citation.get("messageId") if citation else None

                    # Determine if this is a support message
                    author = msg_data.get("author", "unknown")
                    is_support = self._is_support_message(author)

                    # Create message object
                    msg = {
                        "msg_id": msg_id,
                        "text": msg_data["message"].strip(),
                        "author": author,
                        "channel": msg_data.get("channel", "unknown").lower(),
                        "is_support": is_support,
                        "timestamp": timestamp,
                        "referenced_msg_id": referenced_msg_id,
                    }
                    self.messages[msg_id] = msg

                    # Store reference if it exists
                    if referenced_msg_id:
                        self.references[msg_id] = referenced_msg_id

                        # Create referenced message if it doesn't exist yet
                        if referenced_msg_id not in self.messages and citation:
                            ref_timestamp = timestamp
                            if ref_timestamp:
                                # Referenced message is earlier
                                ref_timestamp = timestamp - timedelta(seconds=1)

                            ref_msg = {
                                "msg_id": referenced_msg_id,
                                "text": citation.get("text", ""),
                                "author": citation.get("author", "unknown"),
                                "channel": "user",
                                "is_support": False,
                                "timestamp": ref_timestamp,
                                "referenced_msg_id": None,
                            }
                            self.messages[referenced_msg_id] = ref_msg

                except (KeyError, ValueError, TypeError) as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    continue

            logger.info(
                f"Loaded {len(self.messages)} messages with {len(self.references)} references"
            )

        except Exception as e:
            logger.error(f"Unexpected error loading JSON data: {e}", exc_info=True)
            raise ValueError(f"Failed to parse JSON data: {e}") from e

    def load_messages_from_file(self, json_path: Path) -> None:
        """Load messages from JSON file.

        Args:
            json_path: Path to the JSON file containing messages

        Raises:
            ValueError: If the JSON file is malformed or cannot be parsed
        """
        if not json_path.exists():
            logger.warning(f"No input file found at {json_path}")
            return

        logger.info(f"Loading messages from JSON file: {json_path}")

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            self.load_messages_from_json(json_data)

        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing error: {e}", exc_info=True)
            raise ValueError(f"Failed to parse JSON file: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error loading JSON file: {e}", exc_info=True)
            raise

    def build_conversation_thread(
        self, start_msg_id: str, max_depth: int = 10
    ) -> List[Dict]:
        """Build a conversation thread starting from a message, following references both ways.

        Args:
            start_msg_id: ID of the message to start building the thread from
            max_depth: Maximum depth to traverse (prevents infinite loops)

        Returns:
            List of messages forming the conversation thread, sorted by timestamp
        """
        if not self.messages:
            return []

        thread: List[Dict] = []
        seen_messages: Set[str] = set()
        to_process = deque(
            [start_msg_id]
        )  # Use deque for deterministic FIFO processing
        depth = 0

        while to_process and depth < max_depth:
            current_id = to_process.popleft()  # FIFO ensures consistent ordering

            if current_id in seen_messages or current_id not in self.messages:
                continue

            seen_messages.add(current_id)
            msg = self.messages[current_id].copy()
            msg["original_index"] = len(thread)

            # Add message to thread
            thread.append(msg)

            # Follow reference backward
            if msg["referenced_msg_id"]:
                to_process.append(msg["referenced_msg_id"])

            # Follow references forward more conservatively
            forward_refs = [
                mid
                for mid, ref in self.references.items()
                if ref == current_id and
                # Only include forward references within 30 minutes
                self.messages[mid]["timestamp"]
                and self.messages[current_id]["timestamp"]
                and (
                    self.messages[mid]["timestamp"]
                    - self.messages[current_id]["timestamp"]
                )
                <= timedelta(minutes=30)
            ]
            to_process.extend(forward_refs)

            depth += 1

        # Sort thread by timestamp, using the original position as tie-breaker
        thread.sort(
            key=lambda x: (
                x["timestamp"] if x["timestamp"] is not None else datetime.min,
                x["original_index"],
            )
        )

        # Remove the temporary original_index field
        for msg in thread:
            msg.pop("original_index", None)

        return thread

    def is_valid_conversation(self, thread: List[Dict]) -> bool:
        """Validate if a conversation thread is complete and meaningful.

        Args:
            thread: List of messages forming a conversation thread

        Returns:
            True if the conversation is valid, False otherwise
        """
        if len(thread) < 2:
            return False

        # Check if there's at least one user message and one support message
        has_user = any(not msg["is_support"] for msg in thread)
        has_support = any(msg["is_support"] for msg in thread)

        if not (has_user and has_support):
            return False

        # Check if messages are too far apart in time
        timestamps = [
            msg["timestamp"] for msg in thread if msg["timestamp"] is not None
        ]
        if timestamps:
            time_span = max(timestamps) - min(timestamps)
            if time_span > timedelta(hours=24):  # Max time span of 24 hours
                return False

        # Check if all messages are properly connected through references
        for i in range(1, len(thread)):
            current_msg = thread[i]
            previous_msg = thread[i - 1]

            # Check if messages are connected through references
            if (
                current_msg["referenced_msg_id"] != previous_msg["msg_id"]
                and previous_msg["referenced_msg_id"] != current_msg["msg_id"]
                and not (
                    current_msg["timestamp"]
                    and previous_msg["timestamp"]
                    and (current_msg["timestamp"] - previous_msg["timestamp"])
                    <= timedelta(minutes=30)
                )
            ):
                return False

        return True

    def group_conversations(self) -> List[Dict]:
        """Group messages into conversations.

        Returns:
            List of conversation dictionaries, each with an ID and list of messages
        """
        if not self.messages:
            return []

        logger.info("Grouping messages into conversations...")

        # Start with support messages that have references
        support_messages = [
            msg_id
            for msg_id, msg in self.messages.items()
            if msg["is_support"] and msg["referenced_msg_id"]
        ]
        logger.info(f"Found {len(support_messages)} support messages with references")

        # Process each support message
        conversations = []
        processed_msg_ids: Set[str] = set()

        for msg_id in support_messages:
            if msg_id in processed_msg_ids:
                continue

            # Build conversation thread
            thread = self.build_conversation_thread(msg_id)

            # Mark all messages in thread as processed
            processed_msg_ids.update(msg["msg_id"] for msg in thread)

            # Validate and format conversation
            if self.is_valid_conversation(thread):
                conversation = {
                    "id": thread[0]["msg_id"],  # Use first message ID
                    "messages": thread,
                }
                conversations.append(conversation)

        logger.info(f"Generated {len(conversations)} conversations")
        self.conversations = conversations
        return conversations

    def get_messages(self) -> Dict[str, Dict]:
        """Get the loaded messages dictionary.

        Returns:
            Dictionary mapping message IDs to message objects
        """
        return self.messages

    def get_references(self) -> Dict[str, str]:
        """Get the message references dictionary.

        Returns:
            Dictionary mapping message IDs to their referenced message IDs
        """
        return self.references

    def get_conversations(self) -> List[Dict]:
        """Get the grouped conversations.

        Returns:
            List of conversation dictionaries
        """
        return self.conversations
