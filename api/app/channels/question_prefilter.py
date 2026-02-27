"""Shared channel-level prefilter for likely user questions.

Reuses the existing extraction/training pre-filter heuristics so channel adapters
(Bisq2, Matrix, etc.) can gate obvious non-question chatter before RAG calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.llm_extraction.pre_filters import MessagePreFilter


@dataclass(frozen=True)
class QuestionPrefilterDecision:
    """Decision returned by question prefilter evaluation."""

    should_process: bool
    reason: str = ""


class QuestionPrefilterProtocol(Protocol):
    """Protocol for channel question prefilters."""

    def evaluate_text(self, text: str | None) -> QuestionPrefilterDecision:
        """Return prefilter decision for a user message body."""


class QuestionPrefilter:
    """Conservative prefilter for channel incoming messages.

    It intentionally allows `too_short` messages to avoid dropping follow-up
    prompts like "USD" that rely on prior chat history context.
    """

    def __init__(
        self,
        message_pre_filter: MessagePreFilter | None = None,
        *,
        allow_too_short_messages: bool = True,
    ) -> None:
        self._message_pre_filter = message_pre_filter or MessagePreFilter()
        self._allow_too_short_messages = allow_too_short_messages

    def evaluate_text(self, text: str | None) -> QuestionPrefilterDecision:
        """Evaluate whether text should continue through RAG processing."""
        normalized = str(text or "").strip()
        if not normalized:
            return QuestionPrefilterDecision(
                should_process=False, reason="empty_message"
            )

        should_filter, reason = self._message_pre_filter.should_filter(
            {"body": normalized}
        )
        if not should_filter:
            return QuestionPrefilterDecision(should_process=True)

        if reason == "too_short" and self._allow_too_short_messages:
            return QuestionPrefilterDecision(should_process=True)

        return QuestionPrefilterDecision(should_process=False, reason=reason)
