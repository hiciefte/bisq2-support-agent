"""Shared fixtures for RAG service tests."""

from unittest.mock import MagicMock

import pytest
from app.core.config import Settings


@pytest.fixture()
def mock_ai_client():
    """Mock AISuite Client with chat.completions.create."""
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = (
        '{"rewritten_query": "test query", "was_rewritten": true, "confidence": 0.9}'
    )
    client.chat.completions.create.return_value = response
    return client


@pytest.fixture()
def rewriter_settings():
    """Settings with query rewrite enabled."""
    settings = Settings(
        DATA_DIR="/tmp/test_data",
        OPENAI_API_KEY="test-key",
        ADMIN_API_KEY="test-admin-key",
        ENABLE_QUERY_REWRITE=True,
        QUERY_REWRITE_MODEL="openai:gpt-4o-mini",
        QUERY_REWRITE_TIMEOUT_SECONDS=2.0,
        QUERY_REWRITE_MAX_HISTORY_TURNS=4,
    )
    return settings


@pytest.fixture()
def sample_chat_history_dicts():
    """Chat history in dict format (as passed by simplified_rag_service)."""
    return [
        {"role": "user", "content": "How do I create a trade offer in Bisq Easy?"},
        {
            "role": "assistant",
            "content": "To create a trade offer in Bisq Easy, go to the Trade tab...",
        },
        {"role": "user", "content": "What are the fees for that?"},
    ]
