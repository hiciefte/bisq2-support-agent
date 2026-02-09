"""Channel plugin message models.

Standardized models for multi-channel message handling.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ChannelType(str, Enum):
    """Supported communication channels."""

    BISQ2 = "bisq2"
    WEB = "web"
    MATRIX = "matrix"
    TELEGRAM = "telegram"  # Future
    DISCORD = "discord"  # Future


class MessagePriority(str, Enum):
    """Message priority for rate limiting."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ChannelCapability(str, Enum):
    """Capabilities that channels may support."""

    RECEIVE_MESSAGES = "receive_messages"
    SEND_RESPONSES = "send_responses"
    POLL_CONVERSATIONS = "poll_conversations"
    EXTRACT_FAQS = "extract_faqs"
    PERSISTENT_CONNECTION = "persistent"
    TEXT_MESSAGES = "text_messages"
    CHAT_HISTORY = "chat_history"


class UserContext(BaseModel):
    """User identification and context."""

    user_id: str = Field(
        ..., description="Unique user identifier", min_length=1, max_length=128
    )
    session_id: Optional[str] = Field(
        None, description="Session for conversation tracking"
    )
    channel_user_id: Optional[str] = Field(None, description="Channel-specific user ID")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    auth_token: Optional[str] = Field(
        None, description="JWT or signed token from channel"
    )
    auth_timestamp: Optional[datetime] = Field(default=None)

    @field_validator("user_id")
    @classmethod
    def validate_user_id_format(cls, v: str) -> str:
        """Enforce user_id format to prevent injection."""
        import re

        if not re.match(r"^[a-zA-Z0-9_\-@.:]{1,128}$", v):
            raise ValueError("Invalid user_id format")
        return v


class ChatMessage(BaseModel):
    """Individual message in conversation history."""

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="Message sender role"
    )
    content: str = Field(..., description="Message content", max_length=4000)
    timestamp: Optional[datetime] = Field(default=None)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate chat message content."""
        if not v or not v.strip():
            raise ValueError("Message content cannot be empty")
        if "\x00" in v:
            raise ValueError("Null bytes not allowed")
        return v.strip()


class IncomingMessage(BaseModel):
    """Standardized incoming message from any channel.

    All channel adapters transform their native format into this model.
    """

    # Identification
    message_id: str = Field(..., description="Unique message identifier")
    channel: ChannelType = Field(..., description="Source channel")

    # Content
    question: str = Field(..., min_length=1, max_length=4000)
    chat_history: Optional[List[ChatMessage]] = Field(default=None)

    # User context
    user: UserContext = Field(..., description="User identification")

    # Processing directives
    priority: MessagePriority = Field(default=MessagePriority.NORMAL)
    bypass_hooks: List[str] = Field(default_factory=list)

    # Channel-specific data
    channel_metadata: Dict[str, str] = Field(default_factory=dict)

    # Authentication
    channel_signature: Optional[str] = Field(
        None, description="HMAC-SHA256 signature for channel authentication"
    )

    # Tracking
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        """Validate and sanitize question."""
        if not v or not v.strip():
            raise ValueError("Question cannot be empty")
        if "\x00" in v:
            raise ValueError("Null bytes not allowed in question")
        return v.strip()

    def verify_channel_signature(self, channel_secret: str) -> bool:
        """Verify message authenticity using HMAC signature."""
        import hashlib
        import hmac
        import secrets

        if not self.channel_signature:
            return False

        payload = f"{self.message_id}{self.channel}{self.timestamp.isoformat()}"
        expected = hmac.new(
            channel_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return secrets.compare_digest(self.channel_signature, expected)

    def compute_signature(self, channel_secret: str) -> str:
        """Compute HMAC signature for this message."""
        import hashlib
        import hmac

        payload = f"{self.message_id}{self.channel}{self.timestamp.isoformat()}"
        return hmac.new(
            channel_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()


class ErrorCode(str, Enum):
    """Standardized error codes."""

    # Client errors
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    MESSAGE_TOO_LARGE = "MESSAGE_TOO_LARGE"

    # Server errors
    RAG_SERVICE_ERROR = "RAG_SERVICE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"

    # Business logic
    PII_DETECTED = "PII_DETECTED"
    REQUIRES_HUMAN_ESCALATION = "REQUIRES_HUMAN_ESCALATION"


class GatewayError(BaseModel):
    """Standardized error response."""

    error_code: ErrorCode
    error_message: str
    details: Optional[Dict[str, Any]] = None
    recoverable: bool = True
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DocumentReference(BaseModel):
    """Reference to a source document."""

    document_id: str
    title: str
    url: Optional[str] = None
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    category: Optional[str] = None  # bisq1/bisq2/general


class ResponseMetadata(BaseModel):
    """Metadata about response generation."""

    processing_time_ms: float
    rag_strategy: str  # retrieval/fallback/hybrid
    model_name: str
    tokens_used: Optional[int] = None
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    routing_action: Optional[str] = None
    detected_version: Optional[str] = None
    version_confidence: Optional[float] = None
    hooks_executed: List[str] = Field(default_factory=list)


class OutgoingMessage(BaseModel):
    """Standardized outgoing message to any channel.

    Channel adapters transform this into their native format.
    """

    # Identification
    message_id: str
    in_reply_to: str  # ID of incoming message
    channel: ChannelType

    # Response content
    answer: str
    sources: List[DocumentReference] = Field(default_factory=list)

    # User context (echoed from incoming)
    user: UserContext

    # Metadata
    metadata: ResponseMetadata

    # Optional features
    suggested_questions: Optional[List[str]] = None
    requires_human: bool = False

    # Tracking
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HealthStatus(BaseModel):
    """Health status for a channel."""

    healthy: bool
    message: Optional[str] = None
    last_check: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = Field(default_factory=dict)
