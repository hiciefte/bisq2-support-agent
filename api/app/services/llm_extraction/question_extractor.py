"""Question Extractor - Main orchestration service (Phase 1.5).

Coordinates all components for LLM-based question extraction from Matrix conversations.
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.services.llm_extraction.conversation_aggregator import (
    ConversationAggregator,
)
from app.services.llm_extraction.models import (
    ConversationInput,
    ExtractedQuestion,
    ExtractionResult,
    MessageInput,
)
from app.services.llm_extraction.prompt_manager import ExtractionPromptManager

logger = logging.getLogger(__name__)


class QuestionExtractor:
    """Main orchestration service for LLM-based question extraction."""

    def __init__(
        self,
        ai_client: Any,
        settings: Settings,
        staff_senders: Optional[List[str]] = None,
    ):
        """
        Initialize question extractor.

        Args:
            ai_client: AISuite client for LLM calls
            settings: Application settings
            staff_senders: List of Matrix user IDs for staff members
        """
        self.ai_client = ai_client
        self.settings = settings
        self.staff_senders = staff_senders or []

        # Initialize components
        self.aggregator = ConversationAggregator()
        self.prompt_manager = ExtractionPromptManager(
            max_tokens=settings.LLM_EXTRACTION_MAX_TOKENS,
            staff_senders=self.staff_senders,
        )

        # Simple in-memory cache (conversation_hash -> ExtractionResult)
        self._cache: Dict[str, tuple[ExtractionResult, float]] = {}
        self._cache_ttl = settings.LLM_EXTRACTION_CACHE_TTL

    async def extract_questions(
        self,
        messages: List[Dict[str, Any]],
        room_id: str,
    ) -> ExtractionResult:
        """
        Extract questions from Matrix messages.

        Args:
            messages: List of Matrix message dicts
            room_id: Matrix room ID

        Returns:
            ExtractionResult with extracted questions
        """
        start_time = time.time()

        # Handle empty messages
        if not messages:
            return ExtractionResult(
                conversation_id=f"{room_id}_empty",
                questions=[],
                total_messages=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        # Aggregate into conversations
        conversations = self.aggregator.aggregate(messages)

        # For now, process first conversation (single conversation in most cases)
        # Future: batch processing for multiple conversations
        if not conversations:
            return ExtractionResult(
                conversation_id=f"{room_id}_no_conv",
                questions=[],
                total_messages=len(messages),
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        conversation = conversations[0]
        conversation_id = f"{room_id}_{conversation.root_message_id}"

        # Create ConversationInput from aggregated conversation
        conv_message_inputs = [
            MessageInput(
                event_id=msg["event_id"],
                sender=msg["sender"],
                body=msg["body"],
                timestamp=msg["timestamp"],
            )
            for msg in conversation.messages
        ]

        conversation_input = ConversationInput(
            conversation_id=conversation_id,
            messages=conv_message_inputs,
            room_id=room_id,
        )

        # Check cache
        cache_key = self._get_cache_key(conversation_input)
        cached_result = self._get_from_cache(cache_key)
        if cached_result:
            logger.info(f"Cache hit for conversation {conversation_id}")
            return cached_result

        # Format prompt
        prompt_messages = self.prompt_manager.format_conversation(conversation_input)

        # Call LLM
        try:
            response = await self.ai_client.chat.completions.create(
                model=self.settings.LLM_EXTRACTION_MODEL,
                messages=prompt_messages,
                temperature=self.settings.LLM_EXTRACTION_TEMPERATURE,
            )

            # Parse JSON response
            response_text = response.choices[0].message.content
            questions_data = json.loads(response_text)

            # Validate and convert to ExtractedQuestion models
            extracted_questions = [ExtractedQuestion(**q) for q in questions_data]

            # Create result
            result = ExtractionResult(
                conversation_id=conversation_id,
                questions=extracted_questions,
                total_messages=len(conversation.messages),
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

            # Cache result
            self._add_to_cache(cache_key, result)

            logger.info(
                f"Extracted {len(extracted_questions)} questions from conversation {conversation_id}"
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            raise
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            raise

    def _get_cache_key(self, conversation: ConversationInput) -> str:
        """
        Generate cache key from conversation.

        Args:
            conversation: Conversation input

        Returns:
            SHA-256 hash of conversation content
        """
        # Create deterministic string from conversation
        content = json.dumps(
            {
                "messages": [
                    {"event_id": m.event_id, "body": m.body}
                    for m in conversation.messages
                ]
            },
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[ExtractionResult]:
        """
        Get cached result if not expired.

        Args:
            cache_key: Cache key

        Returns:
            Cached result or None
        """
        if cache_key in self._cache:
            result, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return result
            else:
                # Expired, remove from cache
                del self._cache[cache_key]
        return None

    def _add_to_cache(self, cache_key: str, result: ExtractionResult) -> None:
        """
        Add result to cache.

        Args:
            cache_key: Cache key
            result: Extraction result
        """
        self._cache[cache_key] = (result, time.time())
