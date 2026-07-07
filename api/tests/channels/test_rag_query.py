"""Tests for channel-aware RAG query compatibility helpers."""

import pytest
from app.channels.rag_query import (
    query_with_channel_context,
    stream_query_with_channel_context,
)


class LegacyQueryService:
    async def query(self, question, chat_history=None):
        return {"question": question, "chat_history": chat_history}


class LegacyStreamService:
    async def stream_query(self, question, chat_history=None):
        yield {
            "event": "final",
            "data": {"question": question, "chat_history": chat_history},
        }


@pytest.mark.asyncio
async def test_query_fallback_strips_multiple_unsupported_context_kwargs():
    result = await query_with_channel_context(
        rag_service=LegacyQueryService(),
        question="How does Bisq Easy work?",
        chat_history=[],
        detection_source="web",
        language_hint="DE",
        language_hint_confidence=0.9,
    )

    assert result == {
        "question": "How does Bisq Easy work?",
        "chat_history": [],
    }


@pytest.mark.asyncio
async def test_stream_fallback_strips_multiple_unsupported_context_kwargs():
    events = [
        event
        async for event in stream_query_with_channel_context(
            rag_service=LegacyStreamService(),
            question="How does Bisq Easy work?",
            chat_history=[],
            detection_source="web",
            language_hint="DE",
            language_hint_confidence=0.9,
        )
    ]

    assert events == [
        {
            "event": "final",
            "data": {
                "question": "How does Bisq Easy work?",
                "chat_history": [],
            },
        }
    ]
