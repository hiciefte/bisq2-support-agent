"""
Pydantic models for Similar FAQ Candidate feature (Phase 7.1).

These models support the Similar FAQ Review Queue workflow where
auto-extracted FAQs that match existing FAQs are queued for admin review.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SimilarFaqCandidateCreate(BaseModel):
    """Input model for creating a similar FAQ candidate."""

    extracted_question: str = Field(
        ...,
        min_length=5,
        max_length=2000,
        description="The question extracted from support conversation",
    )
    extracted_answer: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The answer extracted from support conversation",
    )
    extracted_category: Optional[str] = Field(
        None,
        description="Optional category for the extracted FAQ",
    )
    matched_faq_id: int = Field(
        ...,
        description="ID of the existing FAQ that this candidate is similar to",
    )
    similarity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity score between 0.0 and 1.0",
    )


class SimilarFaqCandidate(BaseModel):
    """Response model for a similar FAQ candidate with full details."""

    id: str = Field(
        ...,
        description="Unique identifier (UUID) for the candidate",
    )
    extracted_question: str = Field(
        ...,
        description="The question extracted from support conversation",
    )
    extracted_answer: str = Field(
        ...,
        description="The answer extracted from support conversation",
    )
    extracted_category: Optional[str] = Field(
        None,
        description="Optional category for the extracted FAQ",
    )
    matched_faq_id: int = Field(
        ...,
        description="ID of the existing FAQ that this candidate is similar to",
    )
    similarity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Similarity score between 0.0 and 1.0",
    )
    status: Literal["pending", "approved", "merged", "dismissed"] = Field(
        "pending",
        description="Current status of the candidate",
    )
    extracted_at: datetime = Field(
        ...,
        description="Timestamp when the FAQ was extracted",
    )
    resolved_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the candidate was resolved (approved/merged/dismissed)",
    )
    resolved_by: Optional[str] = Field(
        None,
        description="Admin who resolved the candidate",
    )
    dismiss_reason: Optional[str] = Field(
        None,
        description="Reason for dismissal (if status is dismissed)",
    )
    matched_question: str = Field(
        ...,
        description="Question text of the matched existing FAQ",
    )
    matched_answer: str = Field(
        ...,
        description="Answer text of the matched existing FAQ",
    )
    matched_category: Optional[str] = Field(
        None,
        description="Category of the matched existing FAQ",
    )


class SimilarFaqCandidateListResponse(BaseModel):
    """Response model for listing similar FAQ candidates."""

    items: List[SimilarFaqCandidate] = Field(
        ...,
        description="List of similar FAQ candidates",
    )
    total: int = Field(
        ...,
        description="Total count of candidates matching the query",
    )


class MergeRequest(BaseModel):
    """Request model for merging a candidate into an existing FAQ."""

    mode: Literal["replace", "append"] = Field(
        ...,
        description="Merge mode: 'replace' overwrites existing, 'append' adds to existing",
    )


class DismissRequest(BaseModel):
    """Request model for dismissing a candidate."""

    reason: Optional[str] = Field(
        None,
        description="Optional reason for dismissing the candidate",
    )
