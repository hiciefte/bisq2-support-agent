from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class FAQItem(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "General"
    source: Optional[str] = "Manual"  # Default for manually added/edited
    verified: Optional[bool] = False  # Whether FAQ has been verified by admin
    protocol: Optional[Literal["multisig_v1", "bisq_easy", "musig", "all"]] = (
        None  # Trade protocol - None means "all protocols"
    )
    created_at: Optional[datetime] = None  # When FAQ was created
    updated_at: Optional[datetime] = None  # When FAQ was last updated
    verified_at: Optional[datetime] = (
        None  # When FAQ was verified (only set when verified=True)
    )


class FAQIdentifiedItem(FAQItem):
    id: str  # A temporary ID, like index or hash, for frontend to identify


class FAQUpdateRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    verified: Optional[bool] = None
    protocol: Optional[Literal["multisig_v1", "bisq_easy", "musig", "all"]] = None
    created_at: Optional[datetime] = None  # Normally not updated, used for migrations
    updated_at: Optional[datetime] = None  # Auto-populated on updates
    verified_at: Optional[datetime] = None  # Auto-populated when verified=True


class FAQListResponse(BaseModel):
    faqs: List[FAQIdentifiedItem]
    total_count: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=1)


class BulkFAQRequest(BaseModel):
    """Request model for bulk FAQ operations."""

    faq_ids: List[str] = Field(
        ..., min_length=1, description="List of FAQ IDs to process"
    )


class BulkFAQResponse(BaseModel):
    """Response model for bulk FAQ operations."""

    success_count: int = Field(
        ge=0, description="Number of successfully processed FAQs"
    )
    failed_count: int = Field(ge=0, description="Number of failed operations")
    failed_ids: List[str] = Field(
        default_factory=list, description="IDs of failed operations"
    )
    message: str = Field(..., description="Summary message")


# Similar FAQ check models (Phase 1: Semantic similarity checking)


class SimilarFAQRequest(BaseModel):
    """Request model for checking semantically similar FAQs."""

    question: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Question to check for similar FAQs",
    )
    threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Similarity threshold (0.0-1.0). Default 65% for UI.",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of similar FAQs to return",
    )
    exclude_id: Optional[int] = Field(
        default=None,
        description="FAQ ID to exclude from results (for edit mode)",
    )


class SimilarFAQItem(BaseModel):
    """A single similar FAQ result with similarity score."""

    id: int = Field(..., description="FAQ ID")
    question: str = Field(..., description="FAQ question text")
    answer: str = Field(..., description="FAQ answer (truncated to 200 chars)")
    similarity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity score (0.0-1.0)",
    )
    category: Optional[str] = Field(default=None, description="FAQ category")
    protocol: Optional[Literal["multisig_v1", "bisq_easy", "musig", "all"]] = Field(
        default=None, description="Trade protocol"
    )


class SimilarFAQResponse(BaseModel):
    """Response model for similar FAQ check."""

    similar_faqs: List[SimilarFAQItem] = Field(
        default_factory=list,
        description="List of similar FAQs sorted by similarity (highest first)",
    )
