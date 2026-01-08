"""Shadow response V2 model with two-phase workflow support."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ShadowStatus(str, Enum):
    """Status values for shadow mode workflow."""

    PENDING_VERSION_REVIEW = "pending_version_review"
    PENDING_RESPONSE_REVIEW = "pending_response_review"
    RAG_FAILED = "rag_failed"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    SKIPPED = "skipped"


def _utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


@dataclass
class ShadowResponse:
    """Shadow mode response V2 with two-phase workflow support."""

    # Required fields
    id: str
    channel_id: str
    user_id: str
    messages: List[Dict[str, Any]]  # [{content, timestamp, sender_type, message_id}]

    # Synthesized question for RAG
    synthesized_question: Optional[str] = None

    # Version detection
    detected_version: Optional[str] = None  # bisq1, bisq2, unknown
    version_confidence: float = 0.0
    detection_signals: Dict[str, float] = field(default_factory=dict)

    # Admin confirmation
    confirmed_version: Optional[str] = None
    version_change_reason: Optional[str] = None

    # Unknown version enhancement fields
    training_protocol: Optional[str] = None  # "multisig_v1" | "bisq_easy" | None
    requires_clarification: bool = False  # Pattern learning flag
    clarifying_question: Optional[str] = None  # Custom or auto-generated question
    source: str = "shadow_mode"  # "shadow_mode" | "rag_bot_clarification"
    clarification_answer: Optional[str] = None  # User's answer when asked

    # Pre-processing (computed during version review)
    preprocessed: Optional[Dict[str, Any]] = None  # embedding, entities, question_type

    # Response generation
    generated_response: Optional[str] = None
    sources: List[Dict[str, Any]] = field(default_factory=list)
    edited_response: Optional[str] = None

    # Confidence scoring and routing
    confidence: Optional[float] = None  # Overall confidence score 0-1
    routing_action: Optional[str] = None  # auto_send, queue_medium, needs_human

    # Status tracking
    status: ShadowStatus = ShadowStatus.PENDING_VERSION_REVIEW
    rag_error: Optional[str] = None
    retry_count: int = 0
    skip_reason: Optional[str] = None  # For ML training on question detection

    # Question classification metadata (Phase 1-3)
    classification_result: Optional[Dict[str, Any]] = None  # Full classifier output
    speaker_role: Optional[str] = None  # staff, user, unknown
    message_intent: Optional[str] = (
        None  # support_question, warning, acknowledgment, etc.
    )
    is_follow_up: Optional[bool] = None  # Conversation context analysis
    filter_reason: Optional[str] = (
        None  # Why message was filtered (if is_question=False)
    )

    # Timestamps
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    version_confirmed_at: Optional[datetime] = None
    response_generated_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "messages": self.messages,
            "synthesized_question": self.synthesized_question,
            "detected_version": self.detected_version,
            "version_confidence": self.version_confidence,
            "detection_signals": self.detection_signals,
            "confirmed_version": self.confirmed_version,
            "version_change_reason": self.version_change_reason,
            "training_protocol": self.training_protocol,
            "requires_clarification": self.requires_clarification,
            "clarifying_question": self.clarifying_question,
            "source": self.source,
            "clarification_answer": self.clarification_answer,
            "preprocessed": self.preprocessed,
            "generated_response": self.generated_response,
            "sources": self.sources,
            "edited_response": self.edited_response,
            "confidence": self.confidence,
            "routing_action": self.routing_action,
            "status": (
                self.status.value
                if isinstance(self.status, ShadowStatus)
                else self.status
            ),
            "rag_error": self.rag_error,
            "retry_count": self.retry_count,
            "skip_reason": self.skip_reason,
            "classification_result": self.classification_result,
            "speaker_role": self.speaker_role,
            "message_intent": self.message_intent,
            "is_follow_up": self.is_follow_up,
            "filter_reason": self.filter_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "version_confirmed_at": (
                self.version_confirmed_at.isoformat()
                if self.version_confirmed_at
                else None
            ),
            "response_generated_at": (
                self.response_generated_at.isoformat()
                if self.response_generated_at
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShadowResponse":
        """Create instance from dictionary."""
        # Parse status
        status_value = data.get("status", "pending_version_review")
        if isinstance(status_value, str):
            status = ShadowStatus(status_value)
        else:
            status = status_value

        # Parse timestamps
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = _utc_now()

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = _utc_now()

        version_confirmed_at = data.get("version_confirmed_at")
        if isinstance(version_confirmed_at, str):
            version_confirmed_at = datetime.fromisoformat(version_confirmed_at)

        response_generated_at = data.get("response_generated_at")
        if isinstance(response_generated_at, str):
            response_generated_at = datetime.fromisoformat(response_generated_at)

        return cls(
            id=data["id"],
            channel_id=data["channel_id"],
            user_id=data["user_id"],
            messages=data.get("messages", []),
            synthesized_question=data.get("synthesized_question"),
            detected_version=data.get("detected_version"),
            version_confidence=data.get("version_confidence", 0.0),
            detection_signals=data.get("detection_signals", {}),
            confirmed_version=data.get("confirmed_version"),
            version_change_reason=data.get("version_change_reason"),
            training_protocol=data.get("training_protocol"),
            requires_clarification=data.get("requires_clarification", False),
            clarifying_question=data.get("clarifying_question"),
            source=data.get("source", "shadow_mode"),
            clarification_answer=data.get("clarification_answer"),
            preprocessed=data.get("preprocessed"),
            generated_response=data.get("generated_response"),
            sources=data.get("sources", []),
            edited_response=data.get("edited_response"),
            confidence=data.get("confidence"),
            routing_action=data.get("routing_action"),
            status=status,
            rag_error=data.get("rag_error"),
            retry_count=data.get("retry_count", 0),
            skip_reason=data.get("skip_reason"),
            classification_result=data.get("classification_result"),
            speaker_role=data.get("speaker_role"),
            message_intent=data.get("message_intent"),
            is_follow_up=data.get("is_follow_up"),
            filter_reason=data.get("filter_reason"),
            created_at=created_at,
            updated_at=updated_at,
            version_confirmed_at=version_confirmed_at,
            response_generated_at=response_generated_at,
        )
