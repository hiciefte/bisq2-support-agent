"""Tests for LiteLLM Embeddings Provider - Written FIRST (TDD Red Phase).

These tests define the expected behavior of the LiteLLM-based embeddings provider
before the implementation exists.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestLiteLLMEmbeddingsContract:
    """Test the LiteLLM embeddings contract - these tests define expected behavior."""

    @pytest.fixture
    def mock_litellm_response(self):
        """Mock LiteLLM embedding response."""
        response = MagicMock()
        response.data = [
            MagicMock(embedding=[0.1, 0.2, 0.3, 0.4, 0.5]),
            MagicMock(embedding=[0.6, 0.7, 0.8, 0.9, 1.0]),
        ]
        return response

    def test_implements_langchain_embeddings_interface(self):
        """LiteLLMEmbeddings must implement LangChain Embeddings interface."""
        from app.services.rag.embeddings_provider import LiteLLMEmbeddings
        from langchain_core.embeddings import Embeddings

        embeddings = LiteLLMEmbeddings(model="openai/text-embedding-3-small")
        assert isinstance(embeddings, Embeddings)

    def test_embed_documents_returns_list_of_vectors(self, mock_litellm_response):
        """embed_documents must return list of embedding vectors."""
        with patch("litellm.embedding", return_value=mock_litellm_response):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(model="openai/text-embedding-3-small")
            result = embeddings.embed_documents(["Hello", "World"])

            assert isinstance(result, list)
            assert len(result) == 2
            assert all(isinstance(v, list) for v in result)
            assert all(isinstance(x, float) for v in result for x in v)

    def test_embed_documents_empty_list_returns_empty(self):
        """embed_documents with empty list must return empty list."""
        from app.services.rag.embeddings_provider import LiteLLMEmbeddings

        embeddings = LiteLLMEmbeddings(model="openai/text-embedding-3-small")
        result = embeddings.embed_documents([])

        assert result == []

    def test_embed_query_returns_single_vector(self, mock_litellm_response):
        """embed_query must return single embedding vector."""
        # Adjust mock for single document
        mock_litellm_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3, 0.4, 0.5])]

        with patch("litellm.embedding", return_value=mock_litellm_response):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(model="openai/text-embedding-3-small")
            result = embeddings.embed_query("Hello")

            assert isinstance(result, list)
            assert all(isinstance(x, float) for x in result)
            assert len(result) == 5

    def test_passes_model_to_litellm(self, mock_litellm_response):
        """Must pass correct model identifier to LiteLLM."""
        with patch(
            "litellm.embedding", return_value=mock_litellm_response
        ) as mock_embed:
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(model="cohere/embed-english-v3.0")
            embeddings.embed_documents(["test"])

            mock_embed.assert_called_once()
            call_kwargs = mock_embed.call_args[1]
            assert call_kwargs["model"] == "cohere/embed-english-v3.0"

    def test_passes_dimensions_when_specified(self, mock_litellm_response):
        """Must pass dimensions parameter when specified."""
        with patch(
            "litellm.embedding", return_value=mock_litellm_response
        ) as mock_embed:
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(
                model="openai/text-embedding-3-small", dimensions=256
            )
            embeddings.embed_documents(["test"])

            call_kwargs = mock_embed.call_args[1]
            assert call_kwargs["dimensions"] == 256

    def test_does_not_pass_dimensions_when_none(self, mock_litellm_response):
        """Must not pass dimensions parameter when None."""
        with patch(
            "litellm.embedding", return_value=mock_litellm_response
        ) as mock_embed:
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(
                model="openai/text-embedding-3-small", dimensions=None
            )
            embeddings.embed_documents(["test"])

            call_kwargs = mock_embed.call_args[1]
            assert "dimensions" not in call_kwargs

    def test_passes_timeout(self, mock_litellm_response):
        """Must pass timeout parameter to LiteLLM."""
        with patch(
            "litellm.embedding", return_value=mock_litellm_response
        ) as mock_embed:
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(
                model="openai/text-embedding-3-small", timeout=30.0
            )
            embeddings.embed_documents(["test"])

            call_kwargs = mock_embed.call_args[1]
            assert call_kwargs["timeout"] == 30.0

    def test_raises_on_litellm_error(self):
        """Must raise exception when LiteLLM fails."""
        with patch("litellm.embedding", side_effect=Exception("API Error")):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(model="openai/text-embedding-3-small")

            with pytest.raises(Exception) as exc_info:
                embeddings.embed_documents(["test"])

            assert "API Error" in str(exc_info.value)

    def test_handles_dict_response_format(self):
        """Must handle LiteLLM response with dict format (not objects with .embedding)."""
        # Create mock response with dict format (as returned by some LiteLLM versions)
        mock_response = MagicMock()
        mock_response.data = [
            {"embedding": [0.1, 0.2, 0.3, 0.4, 0.5]},
            {"embedding": [0.6, 0.7, 0.8, 0.9, 1.0]},
        ]

        with patch("litellm.embedding", return_value=mock_response):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings(model="openai/text-embedding-3-small")
            result = embeddings.embed_documents(["Hello", "World"])

            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0] == [0.1, 0.2, 0.3, 0.4, 0.5]
            assert result[1] == [0.6, 0.7, 0.8, 0.9, 1.0]


class TestLiteLLMEmbeddingsFromSettings:
    """Test the from_settings factory method."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings object."""
        settings = MagicMock()
        settings.OPENAI_API_KEY = "test-openai-key"
        settings.EMBEDDING_PROVIDER = "openai"
        settings.EMBEDDING_MODEL = "text-embedding-3-small"
        settings.EMBEDDING_DIMENSIONS = None
        return settings

    def test_from_settings_creates_instance(self, mock_settings):
        """from_settings must create valid instance."""
        with patch("litellm.embedding"):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings.from_settings(mock_settings)

            assert isinstance(embeddings, LiteLLMEmbeddings)

    def test_from_settings_constructs_model_identifier(self, mock_settings):
        """from_settings must construct provider/model identifier."""
        with patch("litellm.embedding"):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings.from_settings(mock_settings)

            assert embeddings.model == "openai/text-embedding-3-small"

    def test_from_settings_cohere_provider(self, mock_settings):
        """from_settings must handle Cohere provider."""
        mock_settings.EMBEDDING_PROVIDER = "cohere"
        mock_settings.EMBEDDING_MODEL = "embed-english-v3.0"
        mock_settings.COHERE_API_KEY = "test-cohere-key"

        with patch("litellm.embedding"):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings.from_settings(mock_settings)

            assert embeddings.model == "cohere/embed-english-v3.0"

    def test_from_settings_preserves_dimensions(self, mock_settings):
        """from_settings must preserve dimensions setting."""
        mock_settings.EMBEDDING_DIMENSIONS = 512

        with patch("litellm.embedding"):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings.from_settings(mock_settings)

            assert embeddings.dimensions == 512

    def test_from_settings_defaults_to_openai(self, mock_settings):
        """from_settings must default to OpenAI when provider not specified."""
        mock_settings.EMBEDDING_PROVIDER = None

        with patch("litellm.embedding"):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings.from_settings(mock_settings)

            assert "openai/" in embeddings.model or embeddings.model.startswith(
                "text-embedding"
            )

    def test_from_settings_handles_full_model_id(self, mock_settings):
        """from_settings must handle model ID already containing provider prefix."""
        mock_settings.EMBEDDING_MODEL = "openai/text-embedding-3-large"

        with patch("litellm.embedding"):
            from app.services.rag.embeddings_provider import LiteLLMEmbeddings

            embeddings = LiteLLMEmbeddings.from_settings(mock_settings)

            # Should not double-prefix
            assert embeddings.model == "openai/text-embedding-3-large"
