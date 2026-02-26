"""Shared semantic duplicate detection helpers for FAQ creation flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import PIPELINE_DUPLICATE_FAQ_THRESHOLD

DEFAULT_DUPLICATE_LIMIT = 3
ANSWER_PREVIEW_CHARS = 200


@dataclass
class DuplicateFAQError(Exception):
    """Raised when semantic-duplicate FAQs are detected."""

    message: str
    similar_faqs: list[dict[str, Any]]

    def __post_init__(self) -> None:
        super().__init__(self.message)


async def find_similar_faqs(
    rag_service: Any | None,
    *,
    question: str,
    threshold: float = PIPELINE_DUPLICATE_FAQ_THRESHOLD,
    limit: int = DEFAULT_DUPLICATE_LIMIT,
    exclude_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return semantic matches from RAG similarity search."""
    if rag_service is None:
        return []
    return await rag_service.search_faq_similarity(
        question=question,
        threshold=threshold,
        limit=limit,
        exclude_id=exclude_id,
    )


def build_duplicate_faq_detail(
    *,
    message: str,
    similar_faqs: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build consistent 409 payload for duplicate FAQ conflicts."""
    detail: dict[str, Any] = {
        "error": "duplicate_faq",
        "message": message,
        "similar_faqs": [
            {
                "id": faq["id"],
                "question": faq["question"],
                "answer": _truncate_answer(str(faq.get("answer", ""))),
                "similarity": faq["similarity"],
                "category": faq.get("category"),
                "protocol": faq.get("protocol"),
            }
            for faq in similar_faqs
        ],
    }
    if context:
        detail.update(context)
    return detail


def _truncate_answer(answer: str) -> str:
    if len(answer) <= ANSWER_PREVIEW_CHARS:
        return answer
    return answer[:ANSWER_PREVIEW_CHARS] + "..."
