"""
Conversation Handler for detecting corrections and aggregating reply chains.

.. deprecated::
    This module is deprecated in favor of `unified_faq_extractor.py`.
    Use `UnifiedFAQExtractor` for FAQ extraction instead.

    The rule-based conversation grouping approach in this module has been
    superseded by the single-pass LLM extraction approach which achieves:
    - 98% reduction in API calls
    - 85% token reduction
    - 95% cost savings (~$0.15/100 msgs vs ~$3.10/100 msgs)

    This module is kept for backward compatibility with existing analysis
    scripts but should not be used in the main training pipeline.

Phase 8 implementation for improved FAQ quality through conversation analysis.
Handles:
- Correction detection (CRITICAL for FAQ accuracy)
- Reply chain aggregation
- Multi-turn conversation consolidation
- LLM distillation for complex threads
- Unified format conversion (Bisq 2 → Matrix-compatible)
"""

import logging
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# Correction indicators - words/phrases that signal a staff member
# is correcting their previous answer
CORRECTION_INDICATORS = [
    "wait",
    "actually",
    "correction",
    "sorry",
    "i meant",
    "hold on",
    "scratch that",
    "my mistake",
    "let me correct",
    "i was wrong",
    "that's not right",
    "ignore what i said",
    "i need to check",
]


class ConversationHandler:
    """Handler for conversation analysis and correction detection.

    .. deprecated::
        Use `UnifiedFAQExtractor` instead for FAQ extraction.

    This class provides functionality to:
    - Detect correction patterns in staff messages
    - Get the final authoritative answer from a thread
    - Extract correction metadata for routing decisions
    - Build and aggregate reply chains
    """

    def __init__(
        self,
        distillation_threshold: int = 4,
        temporal_proximity_threshold_ms: int = 300000,
    ):
        """Initialize the conversation handler.

        Args:
            distillation_threshold: Number of messages above which
                LLM distillation is recommended (default: 4)
            temporal_proximity_threshold_ms: Maximum time gap in milliseconds
                for temporal proximity grouping of orphan staff messages.
                Default: 300000 (5 minutes). Based on analysis of Bisq 2 and
                Matrix support message timing patterns.
        """
        warnings.warn(
            "ConversationHandler is deprecated. Use UnifiedFAQExtractor instead "
            "for FAQ extraction with 95% cost savings.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.correction_indicators = CORRECTION_INDICATORS
        self.distillation_threshold = distillation_threshold
        self.temporal_proximity_threshold_ms = temporal_proximity_threshold_ms

    def is_correction(self, message: str) -> Tuple[bool, Optional[str]]:
        """Detect if a message contains a correction indicator.

        Uses position-based detection for "actually" to reduce false positives.
        "Actually" mid-sentence (e.g., "The feature actually works differently")
        is typically emphasis, not a correction indicator.

        Args:
            message: The message text to analyze

        Returns:
            Tuple of (is_correction, correction_type) where type is:
            - "explicit": Direct correction words ("actually", "correction", "sorry")
            - None: Not a correction
        """
        if not message:
            return False, None

        message_lower = message.lower()

        # Patterns that need position-based checking (only valid at sentence start/after punctuation)
        position_sensitive_patterns = {"actually"}

        for pattern in self.correction_indicators:
            if pattern not in message_lower:
                continue

            # For position-sensitive patterns, check if at sentence start or after punctuation
            if pattern in position_sensitive_patterns:
                if self._is_pattern_at_sentence_position(message_lower, pattern):
                    logger.debug(
                        f"Detected correction pattern '{pattern}' at sentence position"
                    )
                    return True, "explicit"
            else:
                # Other patterns like "sorry", "wait", "my mistake" are always corrections
                logger.debug(f"Detected correction pattern '{pattern}' in message")
                return True, "explicit"

        return False, None

    def _is_pattern_at_sentence_position(self, message: str, pattern: str) -> bool:
        """Check if pattern appears at sentence-start position.

        A pattern is at sentence position if it:
        - Starts the message
        - Appears after a period, exclamation, question mark, or comma followed by space

        Args:
            message: Lowercase message text
            pattern: Lowercase pattern to check

        Returns:
            True if pattern is at a sentence-start position
        """
        import re

        # Check if pattern starts the message
        if message.startswith(pattern):
            return True

        # Check if pattern appears after sentence-ending punctuation or comma
        # Patterns like ". actually", "! actually", "? actually", ", actually"
        sentence_start_regex = rf"[.!?,]\s+{re.escape(pattern)}"
        if re.search(sentence_start_regex, message):
            return True

        return False

    def get_final_answer(
        self,
        messages: List[Dict],
        staff_senders: Set[str],
    ) -> Dict:
        """Get the final authoritative answer from a thread.

        If corrections are detected, returns the last corrected version.
        This ensures FAQs contain accurate, corrected information rather
        than potentially wrong initial answers.

        Args:
            messages: List of message dicts with 'sender' and 'content' keys
            staff_senders: Set of sender IDs that are staff members

        Returns:
            Dict with:
            - content: The final answer text
            - original_was_corrected: True if a correction was detected
            - correction_type: Type of correction (or None)
            - corrected_message_index: Index of the correction message (or None)
        """
        # Filter to staff messages only
        staff_messages = [m for m in messages if m.get("sender") in staff_senders]

        if not staff_messages:
            return {
                "content": None,
                "original_was_corrected": False,
                "correction_type": None,
                "corrected_message_index": None,
            }

        # Check for corrections from last to first (most recent correction wins)
        for i, msg in enumerate(reversed(staff_messages)):
            content = msg.get("content", "")
            is_corr, corr_type = self.is_correction(content)
            if is_corr:
                actual_index = len(staff_messages) - 1 - i
                logger.info(
                    f"Found correction at index {actual_index}: {content[:50]}..."
                )
                return {
                    "content": content,
                    "original_was_corrected": True,
                    "correction_type": corr_type,
                    "corrected_message_index": actual_index,
                }

        # No correction detected - return last staff message
        return {
            "content": staff_messages[-1].get("content"),
            "original_was_corrected": False,
            "correction_type": None,
            "corrected_message_index": None,
        }

    def get_correction_metadata(
        self,
        messages: List[Dict],
        staff_senders: Set[str],
    ) -> Dict:
        """Extract correction metadata for candidate creation.

        This metadata is used to:
        - Flag candidates with corrections for FULL_REVIEW
        - Provide context about what was corrected
        - Help admins understand the correction during review

        Args:
            messages: List of message dicts
            staff_senders: Set of staff sender IDs

        Returns:
            Dict with:
            - has_correction: True if correction detected
            - correction_type: Type of correction
            - correction_context: String describing the correction (for admin review)
        """
        final_answer = self.get_final_answer(messages, staff_senders)

        if not final_answer["original_was_corrected"]:
            return {
                "has_correction": False,
                "correction_type": None,
                "correction_context": None,
            }

        # Build correction context for admin review
        correction_content = final_answer["content"] or ""
        context = f"Correction detected. Final answer: {correction_content[:200]}"
        if len(correction_content) > 200:
            context += "..."

        return {
            "has_correction": True,
            "correction_type": final_answer["correction_type"],
            "correction_context": context,
        }

    # ========== Reply Chain Aggregation (TASK 8.2) ==========

    def build_reply_chain(
        self,
        message: Dict,
        all_messages: Dict[str, Dict],
    ) -> List[Dict]:
        """Build complete reply chain ending at the given message.

        Traces the m.in_reply_to links backward to build the full
        conversation thread in chronological order.

        Includes cycle detection to prevent infinite loops from circular
        references (e.g., A replies to B, B replies to A).

        Args:
            message: Target message to trace back from
            all_messages: Dict mapping event_id -> message

        Returns:
            List of messages in chronological order forming the chain
        """
        chain: List[Dict[str, Any]] = []
        current = message
        visited: Set[str] = set()  # Track visited event IDs to detect cycles

        while current:
            event_id = current.get("event_id", "")

            # Cycle detection: if we've seen this message, break
            if event_id in visited:
                logger.warning(f"Cycle detected in reply chain at event_id: {event_id}")
                break

            visited.add(event_id)
            chain.insert(0, current)  # Prepend to maintain chronological order

            # Get the reply-to event ID from Matrix message format
            content = current.get("content", {})
            relates_to = content.get("m.relates_to", {})
            reply_to = relates_to.get("m.in_reply_to", {})
            reply_to_id = reply_to.get("event_id")

            if reply_to_id and reply_to_id in all_messages:
                # Self-reference check (message replies to itself)
                if reply_to_id == event_id:
                    logger.warning(f"Self-referencing message detected: {event_id}")
                    break
                current = all_messages[reply_to_id]
            else:
                break

        return chain

    def _get_reply_to_id(self, message: Dict) -> Optional[str]:
        """Extract the reply-to event ID from a message."""
        content = message.get("content", {})
        relates_to = content.get("m.relates_to", {})
        reply_to = relates_to.get("m.in_reply_to", {})
        return reply_to.get("event_id")

    def _get_replies_to(
        self,
        event_id: str,
        all_messages: List[Dict],
    ) -> List[Dict]:
        """Find all messages that reply to the given event_id."""
        replies = []
        for msg in all_messages:
            if self._get_reply_to_id(msg) == event_id:
                replies.append(msg)
        return replies

    def group_conversations(
        self,
        messages: List[Dict],
    ) -> List[List[Dict]]:
        """Group messages into independent conversation threads.

        Uses reply chain analysis to cluster related messages together.
        Messages that don't reply to anything form their own groups.

        Args:
            messages: List of message dicts with event_id and content

        Returns:
            List of message groups, each group is a conversation thread
        """
        # Build lookup by event_id
        messages_by_id = {m["event_id"]: m for m in messages}
        processed = set()
        groups = []

        # Process messages in order
        for msg in messages:
            event_id = msg["event_id"]
            if event_id in processed:
                continue

            # Build chain going backward from this message
            chain = self.build_reply_chain(msg, messages_by_id)

            # Also find any replies TO this chain (extend forward)
            chain = self._extend_chain_forward(chain, messages)

            # Mark all messages in chain as processed
            for m in chain:
                processed.add(m["event_id"])

            groups.append(chain)

        return groups

    def _extend_chain_forward(
        self,
        chain: List[Dict],
        all_messages: List[Dict],
    ) -> List[Dict]:
        """Extend a chain by finding messages that reply to it.

        This finds messages that reply to any message in the chain,
        building out the full conversation tree. Results are sorted
        by timestamp to ensure chronological order.
        """
        chain_ids = {m["event_id"] for m in chain}
        extended = list(chain)

        # Keep extending until no new messages found
        changed = True
        while changed:
            changed = False
            for msg in all_messages:
                event_id = msg["event_id"]
                if event_id in chain_ids:
                    continue

                reply_to = self._get_reply_to_id(msg)
                if reply_to and reply_to in chain_ids:
                    extended.append(msg)
                    chain_ids.add(event_id)
                    changed = True

        # Sort by timestamp to ensure chronological order
        extended.sort(key=lambda m: m.get("origin_server_ts", 0))
        return extended

    def extract_qa_from_chain(
        self,
        chain: List[Dict],
        staff_senders: Set[str],
    ) -> Dict:
        """Extract question and answer from a reply chain.

        Combines user messages into the question, and gets the final
        authoritative staff answer (with correction handling).

        Args:
            chain: List of message dicts in chronological order
            staff_senders: Set of sender IDs that are staff members

        Returns:
            Dict with:
            - question: Combined user messages
            - answer: Final authoritative staff answer
            - message_count: Total messages in chain
            - has_correction: True if correction detected
            - correction_type: Type of correction (or None)
            - is_valid_qa_pattern: True if conversation starts with user question
        """
        if not chain:
            return {
                "question": "",
                "answer": None,
                "message_count": 0,
                "has_correction": False,
                "correction_type": None,
                "is_valid_qa_pattern": False,
            }

        user_parts = []
        staff_messages = []

        # Track first message sender for Q&A pattern validation
        first_sender = chain[0].get("sender", "") if chain else ""
        first_is_user = first_sender not in staff_senders

        for msg in chain:
            sender = msg.get("sender", "")
            # Handle both nested content (Matrix format) and flat content
            content = msg.get("content", {})
            if isinstance(content, dict):
                text = content.get("body", "")
            else:
                text = str(content)

            if sender in staff_senders:
                staff_messages.append({"sender": sender, "content": text})
            else:
                if text:
                    user_parts.append(text)

        # Get final answer with correction handling
        final_answer = self.get_final_answer(staff_messages, staff_senders)

        # Q&A pattern validation:
        # Valid pattern: User asks question first, then staff answers
        # Invalid pattern: Staff-only conversation or staff speaks first without question
        has_user_question = len(user_parts) > 0
        is_valid_qa_pattern = first_is_user and has_user_question

        return {
            "question": "\n".join(user_parts),
            "answer": final_answer["content"],
            "message_count": len(chain),
            "has_correction": final_answer["original_was_corrected"],
            "correction_type": final_answer.get("correction_type"),
            "is_valid_qa_pattern": is_valid_qa_pattern,
        }

    # ========== Multi-Turn FAQ Consolidation (TASK 8.3) ==========

    def prepare_conversation_for_candidate(
        self,
        messages: List[Dict],
        staff_senders: Set[str],
        last_event_id: str,
    ) -> Dict:
        """Prepare conversation data for unified FAQ candidate creation.

        Consolidates multi-turn conversations into a single FAQ candidate
        with proper question/answer extraction, correction detection,
        and routing suggestions.

        Args:
            messages: List of message dicts in chronological order
            staff_senders: Set of sender IDs that are staff members
            last_event_id: Event ID to use as the source_event_id

        Returns:
            Dict with:
            - source_event_id: The last event ID for deduplication
            - question_text: Combined user questions
            - staff_answer: Final authoritative staff answer
            - message_count: Total messages in conversation
            - is_multi_turn: True if more than 2 messages
            - has_correction: True if correction detected
            - conversation_context: JSON string of full conversation
            - suggested_routing: "FULL_REVIEW" if correction, else None
            - routing_reason: Reason for routing override, or None
        """
        import json

        # Extract Q&A using existing method
        qa_result = self.extract_qa_from_chain(messages, staff_senders)

        # Build conversation context for admin review
        conversation_context = []
        for msg in messages:
            sender = msg.get("sender", "")
            content = msg.get("content", {})
            if isinstance(content, dict):
                text = content.get("body", "")
            else:
                text = str(content)

            context_entry = {
                "sender": sender,
                "content": text,
            }
            # Include timestamp if available
            if "timestamp" in msg:
                context_entry["timestamp"] = msg["timestamp"]

            conversation_context.append(context_entry)

        # Determine routing based on correction detection
        suggested_routing = None
        routing_reason = None
        if qa_result["has_correction"]:
            suggested_routing = "FULL_REVIEW"
            routing_reason = "contains_correction"

        # Determine if LLM distillation is needed for complex conversations
        needs_distillation = qa_result["message_count"] > self.distillation_threshold

        return {
            "source_event_id": last_event_id,
            "question_text": qa_result["question"],
            "staff_answer": qa_result["answer"],
            "message_count": qa_result["message_count"],
            "is_multi_turn": qa_result["message_count"] > 2,
            "has_correction": qa_result["has_correction"],
            "conversation_context": json.dumps(conversation_context),
            "suggested_routing": suggested_routing,
            "routing_reason": routing_reason,
            "needs_distillation": needs_distillation,
        }

    # ========== LLM Distillation (TASK 8.4) ==========

    def create_distillation_prompt(self, messages: List[Dict]) -> str:
        """Create a prompt for LLM to distill a conversation into a clean FAQ.

        This prompt instructs the LLM to:
        - Extract the core question being asked
        - Identify the final authoritative answer (using corrections only)
        - Output a clean question/answer pair

        Args:
            messages: List of message dicts with 'sender' and 'content' keys

        Returns:
            Prompt string ready to send to the LLM
        """
        # Format conversation for the prompt
        formatted_messages = []
        for msg in messages:
            sender = msg.get("sender", "unknown")
            content = msg.get("content", "")
            if isinstance(content, dict):
                content = content.get("body", "")
            formatted_messages.append(f"[{sender}]: {content}")

        conversation_text = "\n".join(formatted_messages)

        prompt = f"""You are an FAQ distillation expert for Bisq support. Given a support conversation, extract a clean FAQ entry.

CRITICAL RULES:
1. If the staff member corrected themselves (words like "actually", "sorry", "wait", "my mistake"), use ONLY the corrected information in the answer.
2. Combine all related user questions into one comprehensive question.
3. Preserve technical accuracy - do not add information not present in the conversation.
4. The answer should be the final, authoritative response.

CONVERSATION:
{conversation_text}

OUTPUT FORMAT:
Provide a clean FAQ with:
- question: The core question the user was asking (may combine multiple related questions)
- answer: The final authoritative answer (use corrected information only)

Remember: If corrections were made, ignore the original wrong answers and use only the corrected version."""

        return prompt

    # ========== Unified Format Conversion (Multi-Source Support) ==========

    def bisq2_to_unified(self, msg: Dict) -> Dict:
        """Convert a Bisq 2 message to unified Matrix-compatible format.

        This enables using the same conversation grouping pipeline for both
        Matrix and Bisq 2 message sources.

        Args:
            msg: Bisq 2 message dict with keys:
                - date: ISO 8601 timestamp
                - author: Username
                - authorId: Unique author identifier
                - message: Message text content
                - messageId: Unique message identifier
                - citation: Optional reply reference

        Returns:
            Dict with Matrix-compatible structure:
                - event_id: Unique message ID (from messageId)
                - sender: Username (from author)
                - content: {body: message text, m.relates_to: optional reply ref}
                - origin_server_ts: Unix timestamp in milliseconds
                - source: "bisq2" (for later filtering)
                - author_id: Original authorId (for staff detection)
        """
        # Parse ISO timestamp to Unix milliseconds
        date_str = msg.get("date", "")
        try:
            # Handle ISO 8601 format: "2026-01-11T17:07:45.673Z"
            if date_str.endswith("Z"):
                date_str = date_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(date_str)
            timestamp_ms = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            timestamp_ms = 0

        # Build content dict
        content: Dict[str, Any] = {"body": msg.get("message", "")}

        # Convert citation to Matrix reply format
        citation = msg.get("citation")
        if citation and "messageId" in citation:
            content["m.relates_to"] = {
                "m.in_reply_to": {"event_id": citation["messageId"]}
            }

        return {
            "event_id": msg.get("messageId", ""),
            "sender": msg.get("author", ""),
            "content": content,
            "origin_server_ts": timestamp_ms,
            "source": "bisq2",
            "author_id": msg.get("authorId", ""),
        }

    def normalize_messages(
        self,
        messages: List[Dict],
        source: str,
    ) -> List[Dict]:
        """Normalize messages from any source to unified format.

        Args:
            messages: List of messages in source-specific format
            source: Source type ("bisq2" or "matrix")

        Returns:
            List of messages in unified Matrix-compatible format
        """
        if source == "bisq2":
            return [self.bisq2_to_unified(msg) for msg in messages]
        elif source == "matrix":
            # Matrix messages already in correct format, just add source tag
            return [
                {**msg, "source": "matrix"} if "source" not in msg else msg
                for msg in messages
            ]
        else:
            logger.warning(f"Unknown source type: {source}, returning as-is")
            return messages

    # ========== Matrix Edit Detection (Fix 4) ==========

    def is_matrix_edit(self, msg: Dict) -> bool:
        """Check if a message is a Matrix edit (starts with '* ').

        Matrix clients indicate message edits by prefixing the edited
        content with '* ' (asterisk followed by space).

        Args:
            msg: Message dict with 'content' containing 'body'

        Returns:
            True if the message body starts with '* '
        """
        content = msg.get("content", {})
        if isinstance(content, dict):
            body = content.get("body", "")
        else:
            body = str(content)
        return body.startswith("* ")

    def consolidate_matrix_edits(self, messages: List[Dict]) -> List[Dict]:
        """Consolidate Matrix edit messages by replacing originals with edits.

        When a user edits a message in Matrix, the edit appears as a new
        message starting with '* '. This method identifies consecutive edits
        from the same sender and keeps only the final version.

        Args:
            messages: List of messages sorted by timestamp

        Returns:
            List of messages with edits consolidated
        """
        if not messages:
            return messages

        # Sort by timestamp first
        sorted_msgs = sorted(messages, key=lambda m: m.get("origin_server_ts", 0))

        result = []
        i = 0

        while i < len(sorted_msgs):
            current = sorted_msgs[i]

            # Look ahead for edit messages from the same sender
            if not self.is_matrix_edit(current):
                # Check if next message(s) are edits from same sender
                final_msg = current
                j = i + 1

                while j < len(sorted_msgs):
                    next_msg = sorted_msgs[j]

                    # Must be from same sender and be an edit
                    if next_msg.get("sender") == current.get(
                        "sender"
                    ) and self.is_matrix_edit(next_msg):
                        # This is an edit - use it as the final version
                        # Strip the '* ' prefix from the edit
                        edit_content = next_msg.get("content", {})
                        if isinstance(edit_content, dict):
                            edit_body = edit_content.get("body", "")
                            if edit_body.startswith("* "):
                                # Create new message with stripped content
                                final_msg = {
                                    **next_msg,
                                    "content": {
                                        **edit_content,
                                        "body": edit_body[2:],  # Remove '* ' prefix
                                    },
                                }
                        j += 1
                    else:
                        break

                result.append(final_msg)
                i = j  # Skip past all the edits we processed
            else:
                # This is an orphan edit (no original found) - keep as-is
                result.append(current)
                i += 1

        return result

    # ========== Temporal Proximity Grouping (Phase 6) ==========

    def is_orphan_message(self, msg: Dict) -> bool:
        """Check if a message is an orphan (no explicit reply link).

        Args:
            msg: Message dict with 'content' potentially containing reply ref

        Returns:
            True if the message has no explicit reply/citation link
        """
        content = msg.get("content", {})
        if isinstance(content, dict):
            relates_to = content.get("m.relates_to", {})
            in_reply_to = relates_to.get("m.in_reply_to", {})
            return not in_reply_to.get("event_id")
        return True

    def apply_temporal_proximity(
        self,
        groups: List[List[Dict]],
        staff_senders: Set[str],
    ) -> List[List[Dict]]:
        """Merge orphan staff messages with preceding user questions using temporal proximity.

        This method addresses the case where staff members respond to user questions
        without using explicit reply/citation links. If an orphan staff message
        appears within the temporal threshold of a preceding user message, they
        are merged into a single conversation group.

        Based on analysis of Bisq 2 and Matrix support messages:
        - Default threshold: 5 minutes (300 seconds)
        - Captures ~40% of quick staff responses
        - Conservative to minimize false positive groupings

        Args:
            groups: List of conversation groups from group_conversations()
            staff_senders: Set of staff sender identifiers

        Returns:
            List of conversation groups with temporal proximity merging applied
        """
        if not groups:
            return groups

        # Sort groups by timestamp of first message
        def get_first_timestamp(group: List[Dict]) -> int:
            if not group:
                return 0
            return group[0].get("origin_server_ts", 0)

        sorted_groups = sorted(groups, key=get_first_timestamp)

        merged = []
        i = 0

        while i < len(sorted_groups):
            current_group = list(sorted_groups[i])  # Make a copy to allow extension

            # Keep merging orphan staff messages as long as they're within threshold
            while i + 1 < len(sorted_groups):
                next_group = sorted_groups[i + 1]

                # Conditions for merging:
                # 1. Next group is a single message
                # 2. That message is from staff
                # 3. That message is an orphan (no reply link)
                # 4. Current group has at least one non-staff message (original user question)
                # 5. Time gap is within threshold
                if not (
                    len(next_group) == 1
                    and next_group[0].get("sender") in staff_senders
                    and self.is_orphan_message(next_group[0])
                ):
                    break  # Next group doesn't qualify for merge

                # Check if current group has any non-staff messages
                has_user_message = any(
                    msg.get("sender") not in staff_senders for msg in current_group
                )

                if not has_user_message:
                    break  # No user message to anchor to

                # Calculate time gap from last message in current group
                current_last_ts = max(
                    msg.get("origin_server_ts", 0) for msg in current_group
                )
                next_ts = next_group[0].get("origin_server_ts", 0)
                time_gap = next_ts - current_last_ts

                if not (0 <= time_gap <= self.temporal_proximity_threshold_ms):
                    break  # Time gap too large

                # Merge: add the orphan staff message to current group
                logger.debug(
                    f"Temporal proximity merge: gap={time_gap}ms, "
                    f"threshold={self.temporal_proximity_threshold_ms}ms"
                )
                current_group.extend(next_group)
                i += 1  # Advance past the merged group

            # Add the (possibly extended) current group
            merged.append(current_group)
            i += 1

        return merged

    def extract_conversations_unified(
        self,
        messages: List[Dict],
        source: str,
        staff_ids: Set[str],
        apply_temporal_proximity: bool = False,
    ) -> List[Dict]:
        """Extract conversations from messages using unified pipeline.

        This is the main entry point for multi-source conversation extraction.
        It normalizes messages, groups them into conversations, and extracts
        Q&A pairs with correction detection.

        Args:
            messages: List of messages in source-specific format
            source: Source type ("bisq2" or "matrix")
            staff_ids: Set of staff identifiers (usernames for bisq2, sender IDs for matrix)

        Returns:
            List of extracted conversation dicts with:
                - source: Message source type
                - conversation_id: Root event ID
                - messages: List of normalized messages
                - question_text: Combined user questions
                - staff_answer: Final authoritative answer
                - message_count: Total messages in conversation
                - is_multi_turn: True if > 2 messages
                - has_correction: True if correction detected
        """
        # Step 1: Normalize to unified format
        normalized = self.normalize_messages(messages, source)

        # Step 2: Group into conversations using existing method
        groups = self.group_conversations(normalized)

        # Step 2.5: Apply temporal proximity grouping if enabled
        if apply_temporal_proximity:
            groups = self.apply_temporal_proximity(groups, staff_ids)

        # Step 3: Extract Q&A from each conversation
        results = []
        for group in groups:
            if not group:
                continue

            # Get the root event ID (first message in chain)
            conversation_id = group[0].get("event_id", "")

            # Extract Q&A with correction handling
            qa_result = self.extract_qa_from_chain(group, staff_ids)

            # Skip if no staff answer
            if not qa_result.get("answer"):
                continue

            # Fix 2: Skip if question_text is empty (orphan staff messages)
            question_text = qa_result.get("question", "").strip()
            if not question_text:
                logger.debug(
                    f"Skipping conversation {conversation_id}: empty question_text"
                )
                continue

            results.append(
                {
                    "source": source,
                    "conversation_id": conversation_id,
                    "messages": group,
                    "question_text": question_text,
                    "staff_answer": qa_result.get("answer"),
                    "message_count": qa_result.get("message_count", 0),
                    "is_multi_turn": qa_result.get("message_count", 0) > 2,
                    "has_correction": qa_result.get("has_correction", False),
                }
            )

        return results
