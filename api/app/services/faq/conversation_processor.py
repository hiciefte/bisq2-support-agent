"""
Conversation Processor for organizing chat messages into meaningful conversation threads.

This module handles loading messages from CSV files and organizing them into
conversation threads based on message references and timestamps.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)


class ConversationProcessor:
    """Processor for organizing chat messages into conversation threads.

    This class provides functionality to:
    - Load messages from CSV files
    - Build conversation threads following message references
    - Validate conversation completeness and meaningfulness
    - Group messages into structured conversations
    """

    def __init__(self):
        """Initialize the conversation processor."""
        self.messages: Dict[str, Dict] = {}
        self.references: Dict[str, str] = {}
        self.conversations: List[Dict] = []

    def load_messages(self, csv_path: Path) -> None:
        """Load messages from CSV and organize them.

        Args:
            csv_path: Path to the CSV file containing messages

        Raises:
            FileNotFoundError: If the CSV file doesn't exist
            ValueError: If the CSV file is malformed
        """
        if not csv_path.exists():
            logger.warning(f"No input file found at {csv_path}")
            return

        logger.info(f"Loading messages from CSV: {csv_path}")

        try:
            # Read the CSV file
            df = pd.read_csv(csv_path)
            logger.debug(f"CSV columns: {list(df.columns)}")
            total_lines = len(df)
            logger.info(f"Processing {total_lines} lines from input file")

            # Reset message collections
            self.messages = {}
            self.references = {}

            for _, row_data in df.iterrows():
                try:
                    msg_id = row_data["Message ID"]

                    # Skip empty or invalid messages
                    if pd.isna(row_data["Message"]) or not row_data["Message"].strip():
                        continue

                    # Parse timestamp
                    timestamp = None
                    if pd.notna(row_data["Date"]):
                        try:
                            timestamp = pd.to_datetime(row_data["Date"])
                        except Exception as exc:
                            logger.warning(
                                f"Timestamp parse error for msg {msg_id}: {exc}"
                            )

                    # Create message object
                    msg = {
                        "msg_id": msg_id,
                        "text": row_data["Message"].strip(),
                        "author": (
                            row_data["Author"]
                            if pd.notna(row_data["Author"])
                            else "unknown"
                        ),
                        "channel": row_data["Channel"],
                        "is_support": row_data["Channel"].lower() == "support",
                        "timestamp": timestamp,
                        "referenced_msg_id": (
                            row_data["Referenced Message ID"]
                            if pd.notna(row_data["Referenced Message ID"])
                            else None
                        ),
                    }
                    self.messages[msg_id] = msg

                    # Store reference if it exists
                    if msg["referenced_msg_id"]:
                        self.references[msg_id] = msg["referenced_msg_id"]
                        if msg["referenced_msg_id"] not in self.messages and pd.notna(
                            row_data["Referenced Message Text"]
                        ):
                            ref_timestamp = None
                            ref_rows = df[df["Message ID"] == msg["referenced_msg_id"]]
                            if not ref_rows.empty and pd.notna(
                                ref_rows.iloc[0]["Date"]
                            ):
                                try:
                                    ref_timestamp = pd.to_datetime(
                                        ref_rows.iloc[0]["Date"]
                                    )
                                except Exception as exc:
                                    logger.warning(
                                        f"Ref timestamp parse error for msg {msg_id}: {exc}"
                                    )
                            if ref_timestamp is None and timestamp is not None:
                                ref_timestamp = timestamp - pd.Timedelta(seconds=1)
                            ref_msg = {
                                "msg_id": msg["referenced_msg_id"],
                                "text": row_data["Referenced Message Text"].strip(),
                                "author": (
                                    row_data["Referenced Message Author"]
                                    if pd.notna(row_data["Referenced Message Author"])
                                    else "unknown"
                                ),
                                "channel": "user",
                                "is_support": False,
                                "timestamp": ref_timestamp,
                                "referenced_msg_id": None,
                            }
                            self.messages[msg["referenced_msg_id"]] = ref_msg
                except Exception as e:
                    logger.error(f"Error processing row: {e}")
                    continue

            logger.info(
                f"Loaded {len(self.messages)} messages with {len(self.references)} references"
            )
        except Exception as e:
            logger.error(f"Error loading CSV file: {e}")
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

        thread = []
        seen_messages: Set[str] = set()
        to_process = {start_msg_id}
        depth = 0

        while to_process and depth < max_depth:
            current_id = to_process.pop()

            if current_id in seen_messages or current_id not in self.messages:
                continue

            seen_messages.add(current_id)
            msg = self.messages[current_id].copy()
            msg["original_index"] = len(thread)

            # Add message to thread
            thread.append(msg)

            # Follow reference backward
            if msg["referenced_msg_id"]:
                to_process.add(msg["referenced_msg_id"])

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
            to_process.update(forward_refs)

            depth += 1

        # Sort thread by timestamp, using the original position as tie-breaker
        thread.sort(
            key=lambda x: (
                x["timestamp"] if x["timestamp"] is not None else pd.Timestamp.min,
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
