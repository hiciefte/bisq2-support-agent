"""Manage conversation state for multi-turn coherence."""

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversationState:
    """Track state across a conversation."""

    detected_version: Optional[str] = None
    version_confidence: float = 0.0
    topics_discussed: List[str] = field(default_factory=list)
    entities_mentioned: Dict[str, str] = field(default_factory=dict)
    turn_count: int = 0
    last_updated: datetime = field(default_factory=datetime.now)


class ConversationStateManager:
    """Manage conversation state for multi-turn coherence.

    Thread-safe implementation using RLock for concurrent access protection.
    """

    def __init__(self):
        self._states: Dict[str, ConversationState] = {}
        self._lock = threading.RLock()

    def get_or_create_state(self, conversation_id: str) -> ConversationState:
        """Get existing state or create new one."""
        with self._lock:
            if conversation_id not in self._states:
                self._states[conversation_id] = ConversationState()
            return self._states[conversation_id]

    def update_state(
        self,
        conversation_id: str,
        detected_version: Optional[str] = None,
        version_confidence: float = 0.0,
        topics: Optional[List[str]] = None,
        entities: Optional[Dict[str, str]] = None,
    ) -> ConversationState:
        """Update conversation state with new information."""
        with self._lock:
            state = self.get_or_create_state(conversation_id)

            # Update version if higher confidence
            if detected_version and version_confidence > state.version_confidence:
                state.detected_version = detected_version
                state.version_confidence = version_confidence
                logger.debug(
                    f"Updated version to {detected_version} "
                    f"(confidence={version_confidence:.2f})"
                )

            # Add new topics
            if topics:
                for topic in topics:
                    if topic not in state.topics_discussed:
                        state.topics_discussed.append(topic)

            # Update entities
            if entities:
                state.entities_mentioned.update(entities)

            state.turn_count += 1
            state.last_updated = datetime.now()

            return state

    def get_context_summary(self, conversation_id: str) -> str:
        """Generate context summary for LLM prompt."""
        state = self.get_or_create_state(conversation_id)

        parts = []

        if state.detected_version:
            parts.append(f"User is using {state.detected_version}")

        if state.topics_discussed:
            topics = ", ".join(state.topics_discussed[-5:])  # Last 5 topics
            parts.append(f"Topics discussed: {topics}")

        if state.entities_mentioned:
            entities = ", ".join(
                f"{k}: {v}" for k, v in list(state.entities_mentioned.items())[-3:]
            )
            parts.append(f"Entities: {entities}")

        return ". ".join(parts) if parts else ""

    def generate_conversation_id(self, chat_history: List) -> str:
        """Generate consistent ID from chat history.

        Uses multiple messages (up to 3) and SHA-256 for better collision resistance.
        For very short messages like "hi", multiple messages provide more entropy.
        """
        if not chat_history:
            # Include random component for empty history to prevent collisions
            import secrets

            seed = f"{datetime.now().isoformat()}-{secrets.token_hex(4)}"
            return hashlib.sha256(seed.encode()).hexdigest()[:16]

        # Use first 3 messages as seed for better collision resistance
        # Include role in hash for collision resistance when same content has different roles
        messages_to_hash = []
        for item in chat_history[:3]:
            if hasattr(item, "content") and hasattr(item, "role"):
                # Pydantic ChatMessage object - normalize with role
                normalized = f"{item.role}:{item.content}"
                messages_to_hash.append(normalized)
            elif isinstance(item, dict):
                # Dict format - normalize with role
                role = item.get("role", "unknown")
                content = item.get("content", "")
                messages_to_hash.append(f"{role}:{content}")
            else:
                messages_to_hash.append(str(item))

        # Join messages with separator and hash
        combined = "|||".join(messages_to_hash)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def cleanup_old_states(self, max_age_hours: int = 24):
        """Remove stale conversation states."""
        with self._lock:
            now = datetime.now()
            stale_ids = [
                cid
                for cid, state in self._states.items()
                if (now - state.last_updated).total_seconds() > max_age_hours * 3600
            ]

            for cid in stale_ids:
                del self._states[cid]

            if stale_ids:
                logger.info(f"Cleaned up {len(stale_ids)} stale conversation states")
