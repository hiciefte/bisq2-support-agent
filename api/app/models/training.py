"""Shared training data models used across channels."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class QAPair:
    """A question-answer pair extracted from support channels."""

    question_event_id: str
    question_text: str
    question_sender: str
    question_timestamp: datetime

    answer_event_id: str
    answer_text: str
    answer_sender: str
    answer_timestamp: datetime

    # Metadata
    thread_depth: int = 1  # How deep in reply chain
    has_followup: bool = False
