"""Response action model for routing decisions."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ResponseAction:
    """Routing decision for a RAG response."""

    action: str  # "auto_send", "queue_medium", "queue_low"
    send_immediately: bool
    queue_for_review: bool
    priority: str = "normal"
    flag: Optional[str] = None
