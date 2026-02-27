"""Shared helper for channel-aware RAG query execution."""

from __future__ import annotations

from typing import Any, Optional


async def query_with_channel_context(
    *,
    rag_service: Any,
    question: str,
    chat_history: list[dict[str, str]] | None,
    detection_source: Optional[str],
) -> dict[str, Any]:
    """Invoke rag_service.query with optional channel source context.

    Falls back to legacy signature when detection_source is unsupported.
    """
    query_kwargs = {"question": question, "chat_history": chat_history}
    source = str(detection_source or "").strip().lower()
    if source:
        query_kwargs["detection_source"] = source

    try:
        return await rag_service.query(**query_kwargs)
    except TypeError as exc:
        if "detection_source" not in query_kwargs:
            raise
        # Backward compatibility for older rag_service implementations.
        if "unexpected keyword argument 'detection_source'" not in str(exc):
            raise
        return await rag_service.query(
            question=question,
            chat_history=chat_history,
        )
