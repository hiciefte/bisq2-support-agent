"""Prompt Manager for LLM Question Extraction (Phase 1.4).

Formats conversations into prompts for LLM-based question extraction.
"""

from typing import Any, Dict, List, Set

from app.services.llm_extraction.models import ConversationInput

# System prompt for question extraction
EXTRACTION_SYSTEM_PROMPT = """You are an expert at analyzing support chat conversations to identify questions.

Your task is to analyze the conversation and identify all questions asked by users or staff members.

For each question, classify it as one of the following types:
- "initial_question": The first question in a conversation thread
- "follow_up": A follow-up question continuing the same topic
- "staff_question": A question asked by support staff for clarification
- "not_question": A message that looks like a question but is not (rhetorical, greeting, etc.)

Output Format:
Return a JSON array of objects, one for each question found:
[
  {
    "message_id": "$event_id",
    "question_text": "The exact question text",
    "question_type": "initial_question|follow_up|staff_question|not_question",
    "confidence": 0.95
  }
]

Guidelines:
- Extract the EXACT question text from the message
- Assign confidence scores (0.0-1.0) based on certainty
- Only identify genuine questions seeking information or help
- Include message_id (event ID) for each question
- Return empty array [] if no questions found

Be precise and conservative - only mark clear questions."""


class ExtractionPromptManager:
    """Manages prompt formatting for LLM question extraction."""

    def __init__(
        self,
        max_tokens: int = 4000,
        staff_senders: List[str] | None = None,
    ):
        """
        Initialize prompt manager.

        Args:
            max_tokens: Maximum tokens per conversation (for truncation)
            staff_senders: List of Matrix user IDs for staff members
        """
        self.max_tokens = max_tokens
        self.staff_senders: Set[str] = set(staff_senders or [])

    def format_conversation(
        self, conversation: ConversationInput
    ) -> List[Dict[str, Any]]:
        """
        Format conversation as LangChain-compatible messages for LLM.

        Args:
            conversation: Conversation input with messages

        Returns:
            List of message dicts with role and content
        """
        messages = []

        # Add system prompt
        messages.append({"role": "system", "content": EXTRACTION_SYSTEM_PROMPT})

        # Add conversation messages with metadata
        for msg in conversation.messages:
            # Determine role based on sender
            role = "assistant" if msg.sender in self.staff_senders else "user"

            # Format message with metadata
            content = f"[Event: {msg.event_id}] [{msg.sender}]: {msg.body}"

            messages.append({"role": role, "content": content})

        # Truncate if exceeds max_tokens (rough estimation: 4 chars per token)
        estimated_tokens = sum(len(m["content"]) for m in messages) // 4
        if estimated_tokens > self.max_tokens:
            messages = self._truncate_messages(messages)

        return messages

    def _truncate_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Truncate messages to fit within max_tokens.

        Keeps system message and recent messages that fit.

        Args:
            messages: Full message list

        Returns:
            Truncated message list
        """
        if not messages:
            return messages

        # Always keep system message
        system_msg = messages[0]
        conversation_msgs = messages[1:]

        # Estimate tokens and truncate from the beginning
        max_conv_tokens = self.max_tokens - (len(system_msg["content"]) // 4)
        current_tokens = 0
        truncated_conv: List[Dict[str, str]] = []

        # Take messages from the end (most recent)
        for msg in reversed(conversation_msgs):
            msg_tokens = len(msg["content"]) // 4
            if current_tokens + msg_tokens <= max_conv_tokens:
                truncated_conv.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break

        return [system_msg] + truncated_conv
