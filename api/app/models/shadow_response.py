"""Shadow response model for Matrix shadow mode processing."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def _utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


@dataclass
class ShadowResponse:
    """Shadow mode response data model."""

    question_id: str
    question: str
    answer: str
    confidence: float
    sources: List[str]
    created_at: datetime = field(default_factory=_utc_now)
    room_id: Optional[str] = None
    sender: Optional[str] = None  # Anonymized sender ID
    processed: bool = False
    routing_action: Optional[str] = None  # auto_send, queue_medium, queue_low
