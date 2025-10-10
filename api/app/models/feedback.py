from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class ConversationMessage(BaseModel):
    """Individual message in a conversation."""

    role: Literal["user", "assistant"] = Field(description="Message role")
    content: str = Field(max_length=10000, description="Message content (max 10KB)")

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        """Remove null bytes and trim surrounding whitespace."""
        v = v.replace("\x00", "")
        return v.strip()


class FeedbackRequest(BaseModel):
    """Request model for submitting feedback."""

    message_id: str = Field(
        pattern=r"^[a-f0-9-]{36}$", description="UUID of the message"
    )
    question: str = Field(max_length=5000, description="User question")
    answer: str = Field(max_length=20000, description="Assistant answer")
    rating: int = Field(ge=0, le=1, description="0 for negative, 1 for positive")
    explanation: Optional[str] = Field(
        None, max_length=5000, description="Feedback explanation"
    )
    conversation_history: Optional[List[ConversationMessage]] = Field(
        None, max_length=50, description="Conversation context (max 50 messages)"
    )

    @field_validator("conversation_history")
    @classmethod
    def validate_conversation(
        cls, v: Optional[List[ConversationMessage]]
    ) -> Optional[List[ConversationMessage]]:
        """Validate conversation history has alternating roles."""
        if v is None or len(v) == 0:
            return v

        # Enforce alternating user/assistant roles
        expected_role = "user"
        for msg in v:
            if msg.role != expected_role:
                raise ValueError(
                    f"Conversation messages must alternate between 'user' and 'assistant'. "
                    f"Expected '{expected_role}', got '{msg.role}'"
                )
            expected_role = "assistant" if expected_role == "user" else "user"

        return v


class FeedbackItem(BaseModel):
    """Individual feedback entry model."""

    model_config = ConfigDict(from_attributes=True)

    message_id: str
    question: str
    answer: str
    rating: int = Field(description="0 for negative, 1 for positive")
    timestamp: str
    sources: Optional[List[Dict[str, str]]] = None
    sources_used: Optional[List[Dict[str, str]]] = None
    metadata: Optional[Dict[str, Any]] = None
    processed: Optional[int] = Field(default=0, description="0=not processed, 1=processed into FAQ")
    processed_at: Optional[str] = Field(default=None, description="Timestamp when processed into FAQ")
    faq_id: Optional[str] = Field(default=None, description="ID of created FAQ if processed")

    @computed_field
    @property
    def is_positive(self) -> bool:
        """Check if feedback is positive."""
        return self.rating == 1

    @computed_field
    @property
    def is_negative(self) -> bool:
        """Check if feedback is negative."""
        return self.rating == 0

    @computed_field
    @property
    def explanation(self) -> Optional[str]:
        """Get explanation from metadata if available."""
        if self.metadata and "explanation" in self.metadata:
            return self.metadata["explanation"]
        return None

    @computed_field
    @property
    def issues(self) -> List[str]:
        """Get list of issues from metadata."""
        if self.metadata and "issues" in self.metadata:
            return self.metadata["issues"]
        return []

    @computed_field
    @property
    def has_no_source_response(self) -> bool:
        """Check if LLM responded that it has no source to rely on."""
        answer_lower = self.answer.lower()
        no_source_indicators = [
            "i don't have",
            "no information",
            "not found in",
            "no source",
            "cannot find",
            "don't have enough information",
            "insufficient information",
            "no specific",
            "not available in the",
        ]
        return any(indicator in answer_lower for indicator in no_source_indicators)

    @computed_field
    @property
    def is_processed(self) -> bool:
        """Check if feedback has been processed into a FAQ."""
        return self.processed == 1


class FeedbackFilterRequest(BaseModel):
    """Request model for filtering feedback."""

    rating: Optional[str] = Field(None, description="positive, negative, or all")
    date_from: Optional[str] = Field(None, description="ISO date string")
    date_to: Optional[str] = Field(None, description="ISO date string")
    issues: Optional[List[str]] = Field(
        None, description="List of issue types to filter by"
    )
    source_types: Optional[List[str]] = Field(None, description="List of source types")
    search_text: Optional[str] = Field(
        None, description="Text to search in questions/answers/explanations"
    )
    needs_faq: Optional[bool] = Field(
        None, description="Filter for feedback that needs FAQ creation"
    )
    processed: Optional[bool] = Field(
        None, description="Filter by processed status (True=processed, False=unprocessed)"
    )
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(50, ge=1, le=100, description="Number of items per page")
    sort_by: Optional[str] = Field(
        "newest", description="newest, oldest, rating_desc, rating_asc"
    )


class FeedbackListResponse(BaseModel):
    """Response model for paginated feedback list."""

    feedback_items: List[FeedbackItem]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    filters_applied: Dict[str, Any]


class FeedbackStatsResponse(BaseModel):
    """Response model for feedback statistics."""

    total_feedback: int
    positive_count: int
    negative_count: int
    helpful_rate: float
    common_issues: Dict[str, int]
    recent_negative_count: int
    needs_faq_count: int
    source_effectiveness: Dict[str, Dict[str, Any]]
    feedback_by_month: Dict[str, int]


class CreateFAQFromFeedbackRequest(BaseModel):
    """Request model for creating FAQ from feedback."""

    message_id: str
    suggested_question: Optional[str] = Field(
        None, description="Override the original question"
    )
    suggested_answer: str = Field(description="The improved answer for the FAQ")
    category: str = Field(description="Category for the new FAQ")
    additional_notes: Optional[str] = Field(
        None, description="Additional context or notes"
    )


class FeedbackForFAQItem(BaseModel):
    """Feedback item that could benefit from FAQ creation."""

    message_id: str
    question: str
    answer: str
    explanation: str
    issues: List[str]
    timestamp: str
    potential_category: str


class DashboardOverviewResponse(BaseModel):
    """Response model for dashboard overview data."""

    # Core metrics
    helpful_rate: float = Field(description="Helpful rate as percentage")
    helpful_rate_trend: float = Field(description="24h trend in helpful rate")
    average_response_time: float = Field(description="Average response time in seconds")
    response_time_trend: float = Field(
        description="Response time trend (negative = improvement)"
    )
    negative_feedback_count: int = Field(description="Recent negative feedback count")
    negative_feedback_trend: float = Field(
        description="Negative feedback trend percentage"
    )

    # Dashboard-specific data
    feedback_items_for_faq: List[FeedbackForFAQItem] = Field(
        description="Feedback items that would benefit from FAQ creation"
    )
    feedback_items_for_faq_count: int = Field(
        description="Count of feedback items for FAQ creation"
    )
    system_uptime: float = Field(description="System uptime in seconds")
    total_queries: int = Field(description="Total queries processed")
    total_faqs_created: int = Field(description="Total FAQs created from feedback")

    # Additional context
    total_feedback: int = Field(description="Total feedback entries")
    total_faqs: int = Field(description="Total FAQs in system")
    last_updated: str = Field(description="When the data was last updated")
    fallback: Optional[bool] = Field(None, description="Whether this is fallback data")


class AdminLoginRequest(BaseModel):
    """Request model for admin login."""

    api_key: str = Field(description="Admin API key for authentication")


class AdminLoginResponse(BaseModel):
    """Response model for successful admin login."""

    message: str = Field(description="Login success message")
    authenticated: bool = Field(description="Authentication status")
