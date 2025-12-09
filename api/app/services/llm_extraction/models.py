"""Pydantic models for LLM question extraction (Phase 1.3).

Validated data models for input/output of question extraction pipeline.
"""

import unicodedata
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator


class MessageInput(BaseModel):
    """Individual message for LLM extraction."""

    event_id: str = Field(..., description="Matrix event ID")
    sender: str = Field(..., description="Matrix user ID")
    body: str = Field(
        ..., min_length=1, max_length=5000, description="Message content"
    )
    timestamp: int = Field(..., description="Server timestamp in milliseconds")

    @field_validator("body")
    @classmethod
    def normalize_unicode(cls, v: str) -> str:
        """Normalize Unicode to canonical form (NFKC)."""
        return unicodedata.normalize("NFKC", v)


class ConversationInput(BaseModel):
    """Conversation input for LLM extraction."""

    conversation_id: str = Field(..., description="Unique conversation identifier")
    messages: List[MessageInput] = Field(
        ..., min_length=1, max_length=100, description="Messages in conversation"
    )
    room_id: str = Field(..., description="Matrix room ID")


class ExtractedQuestion(BaseModel):
    """Single extracted question from LLM analysis."""

    message_id: str = Field(..., description="Event ID of message containing question")
    question_text: str = Field(..., description="Extracted question text")
    question_type: Literal[
        "initial_question", "follow_up", "staff_question", "not_question"
    ] = Field(..., description="Type of question detected")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )


class ExtractionResult(BaseModel):
    """Result of LLM question extraction for a conversation."""

    conversation_id: str = Field(..., description="Conversation identifier")
    questions: List[ExtractedQuestion] = Field(
        default_factory=list, description="Extracted questions"
    )
    total_messages: int = Field(..., description="Total messages processed")
    processing_time_ms: int = Field(
        ..., gt=0, description="Processing time in milliseconds"
    )
