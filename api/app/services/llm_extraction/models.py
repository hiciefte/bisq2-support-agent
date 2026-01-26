"""Pydantic models for LLM question extraction.

Validated data models for LLM extraction output.
"""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class ExtractedQuestion(BaseModel):
    """Single extracted question from LLM analysis."""

    message_id: str = Field(..., description="Event ID of message containing question")
    question_text: str = Field(..., description="Extracted question text")
    question_type: Literal[
        "initial_question",
        "follow_up",
        "acknowledgment",
        "staff_question",
        "not_question",
    ] = Field(..., description="Type of question detected")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)"
    )
    sender: str = Field(
        default="", description="Real Matrix user ID (restored from anonymization)"
    )


class ExtractionResult(BaseModel):
    """Result of LLM question extraction for a conversation."""

    conversation_id: str = Field(..., description="Conversation identifier")
    questions: List[ExtractedQuestion] = Field(
        default_factory=list, description="Extracted questions"
    )
    conversations: List[Dict[str, Any]] = Field(
        default_factory=list, description="LLM-generated conversation groupings"
    )
    total_messages: int = Field(..., description="Total messages processed")
    processing_time_ms: int = Field(
        ..., ge=0, description="Processing time in milliseconds"
    )
