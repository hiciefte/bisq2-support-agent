"""Response action model for routing decisions."""

from dataclasses import dataclass
from typing import Literal, Optional

# Type aliases for valid action and priority values
ActionType = Literal["auto_send", "queue_medium", "needs_human"]
PriorityType = Literal["low", "normal", "high", "urgent"]


@dataclass
class ResponseAction:
    """Routing decision for a RAG response."""

    action: ActionType
    send_immediately: bool
    queue_for_review: bool
    priority: PriorityType = "normal"
    flag: Optional[str] = None
