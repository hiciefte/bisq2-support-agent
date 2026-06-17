"""OpenAI embeddings provider.

This module provides a LangChain-compatible embeddings implementation using
the already-installed ``langchain-openai`` package. LiteLLM is intentionally not
used here because secure LiteLLM releases require ``httpx>=0.28`` while the
current AISuite release still pins ``httpx<0.28``.

For multilingual support, BGE-M3 embeddings can be used instead.
"""

import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings as LangChainOpenAIEmbeddings

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)


def get_multilingual_embeddings(model_name: str = "BAAI/bge-m3") -> Embeddings:
    """Get multilingual embeddings using HuggingFace BGE-M3.

    BGE-M3 supports 100+ languages and produces high-quality
    multilingual embeddings suitable for cross-lingual retrieval.

    Args:
        model_name: HuggingFace model name (default: "BAAI/bge-m3")

    Returns:
        Embeddings instance configured for multilingual support

    Note:
        This requires langchain-huggingface and sentence-transformers packages.
        The model will be downloaded on first use (~2GB).
    """
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info(f"Multilingual embeddings initialized: {model_name}")
        return embeddings
    except ImportError as e:
        logger.error(
            f"Failed to load HuggingFace embeddings: {e}. "
            "Install with: pip install langchain-huggingface sentence-transformers"
        )
        raise
    except Exception as e:
        logger.error(f"Failed to initialize multilingual embeddings: {e}")
        raise


def _normalize_openai_embedding_model(model: str) -> str:
    """Return a LangChain/OpenAI model id from legacy provider-prefixed values."""
    if model.startswith("openai/"):
        return model.split("/", 1)[1]
    if model.startswith("openai:"):
        return model.split(":", 1)[1]
    return model


class OpenAIEmbeddingsProvider(Embeddings):
    """LangChain-compatible OpenAI embeddings provider."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float = 60.0,
    ):
        """Initialize the OpenAI embeddings provider.

        Args:
            model: OpenAI embedding model. Legacy "openai/..." and "openai:..."
                prefixes are accepted for backward compatibility.
            dimensions: Optional embedding dimensions (supported by some models)
            api_key: Optional API key (uses environment variable if not provided)
            api_base: Optional API base URL for custom endpoints
            timeout: Request timeout in seconds (default: 60.0)
        """
        self.model = _normalize_openai_embedding_model(model)
        self.dimensions = dimensions
        self.api_key = api_key
        self.api_base = api_base
        self.timeout = timeout

        self._embeddings = LangChainOpenAIEmbeddings(
            model=self.model,
            dimensions=self.dimensions,
            api_key=cast(Any, self.api_key or None),
            base_url=self.api_base or None,
            timeout=self.timeout,
        )

        logger.info(f"OpenAI embeddings initialized: {self.model}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of documents.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (each vector is a list of floats)

        Raises:
            Exception: If embedding fails
        """
        if not texts:
            return []

        try:
            result = self._embeddings.embed_documents(texts)
            logger.debug(f"Embedded {len(texts)} documents")
            return result
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text.

        Args:
            text: Text string to embed

        Returns:
            Embedding vector (list of floats)
        """
        embeddings = self.embed_documents([text])
        return embeddings[0] if embeddings else []

    @classmethod
    def from_settings(cls, settings: "Settings") -> "OpenAIEmbeddingsProvider":
        """Create embeddings provider from application settings.

        Args:
            settings: Application settings object

        Returns:
            Configured OpenAIEmbeddingsProvider instance
        """
        provider = getattr(settings, "EMBEDDING_PROVIDER", None) or "openai"
        if provider != "openai":
            raise ValueError(
                "Only OpenAI embeddings are currently supported. "
                "LiteLLM was removed from the runtime dependency set because "
                "secure LiteLLM releases conflict with AISuite's httpx pin."
            )

        model = getattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small")

        # Construct full model ID if not already prefixed
        if "/" not in model:
            model = f"openai/{model}"

        return cls(
            model=model,
            api_key=getattr(settings, "OPENAI_API_KEY", None),
            dimensions=getattr(settings, "EMBEDDING_DIMENSIONS", None),
        )


# Backward-compatible export for older imports and tests. New code should import
# OpenAIEmbeddingsProvider directly.
LiteLLMEmbeddings = OpenAIEmbeddingsProvider
