"""LiteLLM-based embeddings provider with multi-provider support.

This module provides a LangChain-compatible embeddings implementation
using LiteLLM for vendor-portable embedding support (100+ providers).

For multilingual support, BGE-M3 embeddings can be used instead.
"""

import logging
from typing import TYPE_CHECKING, Any

import litellm
from langchain_core.embeddings import Embeddings

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


class LiteLLMEmbeddings(Embeddings):
    """LangChain-compatible embeddings using LiteLLM for provider abstraction.

    Supports 100+ embedding providers: OpenAI, Cohere, Voyage, Azure, Ollama, etc.
    """

    def __init__(
        self,
        model: str = "openai/text-embedding-3-small",
        dimensions: int | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: float = 60.0,
    ):
        """Initialize the LiteLLM embeddings provider.

        Args:
            model: Model identifier in format "provider/model" (e.g., "openai/text-embedding-3-small")
            dimensions: Optional embedding dimensions (supported by some models)
            api_key: Optional API key (uses environment variable if not provided)
            api_base: Optional API base URL for custom endpoints
            timeout: Request timeout in seconds (default: 60.0)
        """
        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key
        self.api_base = api_base
        self.timeout = timeout

        # Configure LiteLLM
        litellm.set_verbose = False

        # Set API keys based on provider
        if api_key:
            provider = model.split("/")[0] if "/" in model else "openai"
            if provider == "openai":
                litellm.api_key = api_key
            elif provider == "cohere":
                litellm.cohere_key = api_key
            elif provider == "voyage":
                litellm.voyage_key = api_key

        logger.info(f"LiteLLM embeddings initialized: {model}")

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
            kwargs: dict[str, Any] = {
                "model": self.model,
                "input": texts,
                "timeout": self.timeout,
            }
            if self.dimensions is not None:
                kwargs["dimensions"] = self.dimensions
            if self.api_base:
                kwargs["api_base"] = self.api_base

            response = litellm.embedding(**kwargs)
            # Handle both dict and object response formats from LiteLLM
            data = response["data"] if isinstance(response, dict) else response.data
            embeddings = []
            for item in data:
                if isinstance(item, dict):
                    embeddings.append(item["embedding"])
                else:
                    embeddings.append(item.embedding)
            logger.debug(f"Embedded {len(texts)} documents")
            return embeddings
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
    def from_settings(cls, settings: "Settings") -> "LiteLLMEmbeddings":
        """Create embeddings provider from application settings.

        Args:
            settings: Application settings object

        Returns:
            Configured LiteLLMEmbeddings instance
        """
        provider = getattr(settings, "EMBEDDING_PROVIDER", None) or "openai"
        model = getattr(settings, "EMBEDDING_MODEL", "text-embedding-3-small")

        # Construct full model ID if not already prefixed
        if "/" not in model:
            model = f"{provider}/{model}"

        # Get API key and base URL based on provider
        api_key = None
        api_base = None
        if provider == "openai":
            api_key = getattr(settings, "OPENAI_API_KEY", None)
        elif provider == "cohere":
            api_key = getattr(settings, "COHERE_API_KEY", None)
        elif provider == "voyage":
            api_key = getattr(settings, "VOYAGE_API_KEY", None)
        elif provider == "ollama":
            # Ollama requires api_base URL, API key is optional
            api_base = getattr(settings, "OLLAMA_API_URL", None)
            api_key = getattr(settings, "OLLAMA_API_KEY", None)

        return cls(
            model=model,
            api_key=api_key,
            api_base=api_base,
            dimensions=getattr(settings, "EMBEDDING_DIMENSIONS", None),
        )
