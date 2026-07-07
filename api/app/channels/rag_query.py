"""Shared helper for channel-aware RAG query execution."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

_OPTIONAL_CONTEXT_KWARGS = (
    "language_hint_confidence",
    "language_hint",
    "detection_source",
)


def _build_query_kwargs(
    question: str,
    chat_history: list[dict[str, str]] | None,
    detection_source: Optional[str],
    language_hint: Optional[str],
    language_hint_confidence: Optional[float],
) -> dict[str, Any]:
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
    return query_kwargs


async def _call_query_with_supported_kwargs(
    query_func: Any,
    query_kwargs: dict[str, Any],
) -> dict[str, Any]:
    supported_kwargs = dict(query_kwargs)
    while True:
        try:
            return await query_func(**supported_kwargs)
        except TypeError as exc:
            if not _remove_unsupported_context_kwargs(supported_kwargs, exc):
                raise


def _remove_unsupported_context_kwargs(
    query_kwargs: dict[str, Any],
    exc: TypeError,
) -> bool:
    message = str(exc)
    removed = False
    for key in _OPTIONAL_CONTEXT_KWARGS:
        if key in query_kwargs and f"unexpected keyword argument '{key}'" in message:
            query_kwargs.pop(key, None)
            removed = True
    return removed


async def _stream_query_with_supported_kwargs(
    stream_query: Any,
    query_kwargs: dict[str, Any],
) -> AsyncIterator[dict[str, Any]]:
    supported_kwargs = dict(query_kwargs)
    while True:
        emitted = False
        try:
            async for event in stream_query(**supported_kwargs):
                emitted = True
                yield event
            return
        except TypeError as exc:
            if emitted or not _remove_unsupported_context_kwargs(supported_kwargs, exc):
                raise


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
    query_kwargs = _build_query_kwargs(
        question,
        chat_history,
        detection_source,
        language_hint,
        language_hint_confidence,
    )
    return await _call_query_with_supported_kwargs(rag_service.query, query_kwargs)


async def stream_query_with_channel_context(
    *,
    rag_service: Any,
    question: str,
    chat_history: list[dict[str, str]] | None,
    detection_source: Optional[str],
    language_hint: Optional[str] = None,
    language_hint_confidence: Optional[float] = None,
) -> AsyncIterator[dict[str, Any]]:
    """Invoke rag_service.stream_query when available, else yield buffered final."""
    query_kwargs = _build_query_kwargs(
        question,
        chat_history,
        detection_source,
        language_hint,
        language_hint_confidence,
    )
    stream_query = getattr(rag_service, "stream_query", None)
    if not callable(stream_query):
        result = await _call_query_with_supported_kwargs(
            rag_service.query,
            query_kwargs,
        )
        yield {"event": "final", "data": result}
        return

    async for event in _stream_query_with_supported_kwargs(stream_query, query_kwargs):
        yield event
