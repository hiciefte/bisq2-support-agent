"""Tests for the OpenAI embeddings provider."""

from unittest.mock import MagicMock, patch

import pytest


class TestOpenAIEmbeddingsProviderContract:
    """Test the OpenAI embeddings wrapper contract."""

    @pytest.fixture
    def mock_embeddings_client(self):
        """Mock LangChain OpenAI embeddings client."""
        client = MagicMock()
        client.embed_documents.return_value = [
            [0.1, 0.2, 0.3, 0.4, 0.5],
            [0.6, 0.7, 0.8, 0.9, 1.0],
        ]
        return client

    def test_implements_langchain_embeddings_interface(self, mock_embeddings_client):
        """OpenAIEmbeddingsProvider must implement LangChain Embeddings."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider
            from langchain_core.embeddings import Embeddings

            embeddings = OpenAIEmbeddingsProvider(model="openai/text-embedding-3-small")

            assert isinstance(embeddings, Embeddings)

    def test_embed_documents_returns_list_of_vectors(self, mock_embeddings_client):
        """embed_documents must return list of embedding vectors."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider(model="openai/text-embedding-3-small")
            result = embeddings.embed_documents(["Hello", "World"])

            assert isinstance(result, list)
            assert len(result) == 2
            assert all(isinstance(v, list) for v in result)
            assert all(isinstance(x, float) for v in result for x in v)
            mock_embeddings_client.embed_documents.assert_called_once_with(
                ["Hello", "World"]
            )

    def test_embed_documents_empty_list_returns_empty(self, mock_embeddings_client):
        """embed_documents with empty list must return empty list."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider(model="openai/text-embedding-3-small")
            result = embeddings.embed_documents([])

            assert result == []
            mock_embeddings_client.embed_documents.assert_not_called()

    def test_embed_query_returns_single_vector(self, mock_embeddings_client):
        """embed_query must return single embedding vector."""
        mock_embeddings_client.embed_documents.return_value = [
            [0.1, 0.2, 0.3, 0.4, 0.5]
        ]

        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider(model="openai/text-embedding-3-small")
            result = embeddings.embed_query("Hello")

            assert isinstance(result, list)
            assert all(isinstance(x, float) for x in result)
            assert len(result) == 5
            mock_embeddings_client.embed_documents.assert_called_once_with(["Hello"])

    def test_normalizes_legacy_slash_model_prefix(self, mock_embeddings_client):
        """Legacy openai/model identifiers must be accepted."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider(
                model="openai/text-embedding-3-small",
                api_key="test-key",
            )

            assert embeddings.model == "text-embedding-3-small"
            call_kwargs = mock_constructor.call_args[1]
            assert call_kwargs["model"] == "text-embedding-3-small"
            assert call_kwargs["api_key"] == "test-key"

    def test_normalizes_legacy_colon_model_prefix(self, mock_embeddings_client):
        """Legacy openai:model identifiers must be accepted."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            OpenAIEmbeddingsProvider(model="openai:text-embedding-3-large")

            call_kwargs = mock_constructor.call_args[1]
            assert call_kwargs["model"] == "text-embedding-3-large"

    def test_passes_dimensions_when_specified(self, mock_embeddings_client):
        """Must pass dimensions parameter when specified."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            OpenAIEmbeddingsProvider(
                model="openai/text-embedding-3-small", dimensions=256
            )

            call_kwargs = mock_constructor.call_args[1]
            assert call_kwargs["dimensions"] == 256

    def test_passes_none_dimensions_when_unspecified(self, mock_embeddings_client):
        """Must preserve the LangChain default dimensions value when unspecified."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            OpenAIEmbeddingsProvider(
                model="openai/text-embedding-3-small", dimensions=None
            )

            call_kwargs = mock_constructor.call_args[1]
            assert call_kwargs["dimensions"] is None

    def test_passes_timeout(self, mock_embeddings_client):
        """Must pass timeout parameter to the underlying embedding client."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            OpenAIEmbeddingsProvider(
                model="openai/text-embedding-3-small", timeout=30.0
            )

            call_kwargs = mock_constructor.call_args[1]
            assert call_kwargs["timeout"] == 30.0

    def test_passes_api_base_as_base_url(self, mock_embeddings_client):
        """Must pass custom OpenAI-compatible base URLs."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            OpenAIEmbeddingsProvider(
                model="openai/text-embedding-3-small",
                api_base="https://example.test/v1",
            )

            call_kwargs = mock_constructor.call_args[1]
            assert call_kwargs["base_url"] == "https://example.test/v1"

    def test_raises_on_embedding_client_error(self, mock_embeddings_client):
        """Must raise exception when the underlying embedding client fails."""
        mock_embeddings_client.embed_documents.side_effect = Exception("API Error")

        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=mock_embeddings_client,
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider(model="openai/text-embedding-3-small")

            with pytest.raises(Exception) as exc_info:
                embeddings.embed_documents(["test"])

            assert "API Error" in str(exc_info.value)

    def test_legacy_litellm_export_points_to_openai_provider(self):
        """Old imports must keep working during the dependency transition."""
        from app.services.rag.embeddings_provider import (
            LiteLLMEmbeddings,
            OpenAIEmbeddingsProvider,
        )

        assert LiteLLMEmbeddings is OpenAIEmbeddingsProvider


class TestOpenAIEmbeddingsFromSettings:
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
        """from_settings must create a valid instance."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=MagicMock(),
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider.from_settings(mock_settings)

            assert isinstance(embeddings, OpenAIEmbeddingsProvider)

    def test_from_settings_constructs_openai_model_identifier(self, mock_settings):
        """from_settings must normalize provider/model identifiers."""
        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=MagicMock(),
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider.from_settings(mock_settings)

            assert embeddings.model == "text-embedding-3-small"

    def test_from_settings_rejects_non_openai_provider(self, mock_settings):
        """Non-OpenAI providers are intentionally disabled after removing LiteLLM."""
        mock_settings.EMBEDDING_PROVIDER = "cohere"
        mock_settings.EMBEDDING_MODEL = "embed-english-v3.0"

        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=MagicMock(),
        ) as mock_constructor:
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            with pytest.raises(ValueError, match="Only OpenAI embeddings"):
                OpenAIEmbeddingsProvider.from_settings(mock_settings)

            mock_constructor.assert_not_called()

    def test_from_settings_preserves_dimensions(self, mock_settings):
        """from_settings must preserve dimensions setting."""
        mock_settings.EMBEDDING_DIMENSIONS = 512

        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=MagicMock(),
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider.from_settings(mock_settings)

            assert embeddings.dimensions == 512

    def test_from_settings_defaults_to_openai(self, mock_settings):
        """from_settings must default to OpenAI when provider is not specified."""
        mock_settings.EMBEDDING_PROVIDER = None

        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=MagicMock(),
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider.from_settings(mock_settings)

            assert embeddings.model == "text-embedding-3-small"

    def test_from_settings_handles_full_model_id(self, mock_settings):
        """from_settings must handle model IDs already containing an OpenAI prefix."""
        mock_settings.EMBEDDING_MODEL = "openai/text-embedding-3-large"

        with patch(
            "app.services.rag.embeddings_provider.LangChainOpenAIEmbeddings",
            return_value=MagicMock(),
        ):
            from app.services.rag.embeddings_provider import OpenAIEmbeddingsProvider

            embeddings = OpenAIEmbeddingsProvider.from_settings(mock_settings)

            assert embeddings.model == "text-embedding-3-large"
