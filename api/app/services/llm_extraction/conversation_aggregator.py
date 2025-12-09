"""Conversation Aggregator for Full LLM Solution (Phase 1.2).

Aggregates Matrix messages into conversations based on reply chains and threads.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class Conversation:
    """Represents an aggregated conversation from Matrix messages."""

    root_message_id: str
    messages: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def participant_count(self) -> int:
        """Count unique participants in conversation."""
        senders = {msg["sender"] for msg in self.messages}
        return len(senders)

    @property
    def message_count(self) -> int:
        """Count total messages in conversation."""
        return len(self.messages)

    @property
    def start_timestamp(self) -> int:
        """Get timestamp of first message."""
        if not self.messages:
            return 0
        return min(msg["timestamp"] for msg in self.messages)

    @property
    def end_timestamp(self) -> int:
        """Get timestamp of last message."""
        if not self.messages:
            return 0
        return max(msg["timestamp"] for msg in self.messages)


class ConversationAggregator:
    """Aggregates Matrix messages into conversations based on reply/thread metadata."""

    def aggregate(self, messages: List[Dict[str, Any]]) -> List[Conversation]:
        """
        Aggregate messages into conversations.

        Args:
            messages: List of Matrix message dicts with reply_to and thread_id fields

        Returns:
            List of Conversation objects, each containing related messages
        """
        if not messages:
            return []

        # Build conversation map: root_id -> Conversation
        conversations: Dict[str, Conversation] = {}
        # Track which messages belong to which conversation root
        message_to_root: Dict[str, str] = {}

        # Sort messages chronologically
        sorted_messages = sorted(messages, key=lambda m: m["timestamp"])

        for msg in sorted_messages:
            event_id = msg["event_id"]
            reply_to = msg.get("reply_to")
            thread_id = msg.get("thread_id")

            # Determine conversation root
            if thread_id:
                # Thread-based conversation
                root_id = thread_id
            elif reply_to and reply_to in message_to_root:
                # Reply chain - follow back to root
                root_id = message_to_root[reply_to]
            elif reply_to:
                # Orphaned reply (parent not in message set)
                root_id = event_id
            else:
                # New conversation root
                root_id = event_id

            # Create conversation if doesn't exist
            if root_id not in conversations:
                conversations[root_id] = Conversation(root_message_id=root_id)

            # Add message to conversation
            conversations[root_id].messages.append(msg)
            message_to_root[event_id] = root_id

        # Return conversations sorted by start time
        result = list(conversations.values())
        result.sort(key=lambda c: c.start_timestamp)
        return result
