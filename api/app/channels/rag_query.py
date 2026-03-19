"""Shared helper for channel-aware RAG query execution."""

from __future__ import annotations

from typing import Any, Optional


async def query_with_channel_context(
    *,
    rag_service: Any,
    question: str,
    chat_history: list[dict[str, str]] | None,
    detection_source: Optional[str],
    language_hint: Optional[str] = None,
    language_hint_confidence: Optional[float] = None,
) -> dict[str, Any]:
    """Invoke rag_service.query with optional channel source context.

    Falls back to legacy signature when detection_source is unsupported.
    """
    query_kwargs: dict[str, Any] = {
        "question": question,
        "chat_history": chat_history,
    }
    source = str(detection_source or "").strip().lower()
    if source:
        query_kwargs["detection_source"] = source
    normalized_language_hint = str(language_hint or "").strip().lower()
    if normalized_language_hint:
        query_kwargs["language_hint"] = normalized_language_hint
        if language_hint_confidence is not None:
            query_kwargs["language_hint_confidence"] = float(language_hint_confidence)

    try:
        return await rag_service.query(**query_kwargs)
    except TypeError as exc:
        removed = False
        if "language_hint_confidence" in query_kwargs and (
            "unexpected keyword argument 'language_hint_confidence'" in str(exc)
        ):
            query_kwargs.pop("language_hint_confidence", None)
            removed = True
        if "language_hint" in query_kwargs and (
            "unexpected keyword argument 'language_hint'" in str(exc)
        ):
            query_kwargs.pop("language_hint", None)
            removed = True
        if "detection_source" in query_kwargs and (
            "unexpected keyword argument 'detection_source'" in str(exc)
        ):
            query_kwargs.pop("detection_source", None)
            removed = True
        if not removed:
            raise
        return await rag_service.query(**query_kwargs)
