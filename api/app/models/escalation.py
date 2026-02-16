"""Pydantic models for the escalation learning pipeline."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EscalationStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESPONDED = "responded"
    CLOSED = "closed"


class EscalationPriority(str, Enum):
    NORMAL = "normal"
    HIGH = "high"


class EscalationDeliveryStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Core data models
# ---------------------------------------------------------------------------


class EscalationCreate(BaseModel):
    """Fields required to create a new escalation."""

    message_id: str = Field(..., description="UUID from the original question")
    channel: str = Field(..., description="Source channel identifier")
    user_id: str = Field(..., max_length=128)
    username: Optional[str] = Field(None, max_length=256)
    channel_metadata: Optional[Dict[str, Any]] = None
    question: str = Field(..., min_length=1, max_length=4000)
    ai_draft_answer: str = Field(..., min_length=1, max_length=10000)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    routing_action: str = Field(..., description="e.g. needs_human")
    routing_reason: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    priority: EscalationPriority = Field(default=EscalationPriority.NORMAL)

    @field_validator("channel", mode="before")
    @classmethod
    def strip_channel(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("channel must not be empty")
        return v

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, v: str) -> str:
        return v.strip() if isinstance(v, str) else v


class Escalation(BaseModel):
    """Full escalation record (database row)."""

    id: int
    message_id: str
    channel: str
    user_id: str
    username: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None
    question: str
    ai_draft_answer: str
    confidence_score: float
    routing_action: str
    routing_reason: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    staff_answer: Optional[str] = None
    staff_id: Optional[str] = None
    edit_distance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    staff_answer_rating: Optional[int] = None
    delivery_status: EscalationDeliveryStatus = EscalationDeliveryStatus.NOT_REQUIRED
    delivery_error: Optional[str] = None
    delivery_attempts: int = 0
    last_delivery_at: Optional[datetime] = None
    generated_faq_id: Optional[str] = None
    status: EscalationStatus = EscalationStatus.PENDING
    priority: EscalationPriority = EscalationPriority.NORMAL
    created_at: datetime
    claimed_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class EscalationUpdate(BaseModel):
    """Patch fields for updating an escalation."""

    status: Optional[EscalationStatus] = None
    staff_answer: Optional[str] = Field(default=None, max_length=10000)
    staff_id: Optional[str] = None
    edit_distance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    delivery_status: Optional[EscalationDeliveryStatus] = None
    delivery_error: Optional[str] = None
    delivery_attempts: Optional[int] = None
    last_delivery_at: Optional[datetime] = None
    generated_faq_id: Optional[str] = None
    priority: Optional[EscalationPriority] = None
    claimed_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


class EscalationFilters(BaseModel):
    """Query filters for listing escalations."""

    status: Optional[EscalationStatus] = None
    channel: Optional[str] = None
    priority: Optional[EscalationPriority] = None
    staff_id: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


# ---------------------------------------------------------------------------
# API request / response models
# ---------------------------------------------------------------------------


class ClaimRequest(BaseModel):
    staff_id: str = Field(default="admin", min_length=1, max_length=128)


class RespondRequest(BaseModel):
    staff_answer: str = Field(..., min_length=1, max_length=10000)
    staff_id: str = Field(default="admin", min_length=1, max_length=128)

    @field_validator("staff_answer", mode="before")
    @classmethod
    def strip_answer(cls, v: str) -> str:
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("staff_answer must not be empty")
        return v


class RateStaffAnswerRequest(BaseModel):
    rating: int = Field(..., ge=0, le=1, description="0=unhelpful, 1=helpful")
    rate_token: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=1024,
        description="Optional signed token enabling trusted learning lane",
    )


class GenerateFAQRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    answer: str = Field(..., min_length=1, max_length=10000)
    category: str = Field(default="General")
    protocol: Optional[str] = None

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        # Keep categories flexible (frontend may offer more than the backend knows about).
        # We only enforce "non-empty after stripping" and a sane max length.
        v = v.strip() if isinstance(v, str) else v
        if not v:
            return "General"
        if len(v) > 128:
            raise ValueError("category must be 128 characters or fewer")
        return v

    @field_validator("protocol", mode="before")
    @classmethod
    def validate_protocol(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = {"multisig_v1", "bisq_easy", "musig", "all"}
            if v not in allowed:
                raise ValueError(f"protocol must be one of {allowed} or null")
        return v


class EscalationListResponse(BaseModel):
    escalations: List[Escalation]
    total: int
    limit: int
    offset: int


class EscalationCountsResponse(BaseModel):
    pending: int = 0
    in_review: int = 0
    responded: int = 0
    closed: int = 0
    total: int = 0


class UserPollResponse(BaseModel):
    status: str
    staff_answer: Optional[str] = None
    responded_at: Optional[datetime] = None
    # Backwards-compatible: polling historically only returned `status="resolved"`.
    # This field disambiguates "answered by staff" vs "closed/dismissed without reply".
    resolution: Optional[str] = None  # "responded" | "closed"
    closed_at: Optional[datetime] = None
    staff_answer_rating: Optional[int] = None
    rate_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class EscalationNotFoundError(Exception):
    pass


class EscalationAlreadyClaimedError(Exception):
    pass


class DuplicateEscalationError(Exception):
    pass


class EscalationNotRespondedError(Exception):
    pass


class EscalationDeliveryFailedError(Exception):
    pass
