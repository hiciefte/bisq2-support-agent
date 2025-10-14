"""
LLM Provider for RAG system model initialization.

This module handles initialization of language models and embeddings:
- OpenAI embeddings model initialization
- LLM client using AISuite for unified interface
- Model configuration
"""

import logging
from dataclasses import dataclass

import aisuite as ai
from app.core.config import Settings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM invocation compatible with LangChain interface."""

    content: str


class AISuiteLLMWrapper:
    """Wrapper class to make AISuite compatible with existing RAG code.

    This wrapper provides an interface similar to LangChain's LLM classes,
    allowing the RAG system to use AISuite without major refactoring.
    """

    def __init__(
        self, client: ai.Client, model: str, max_tokens: int, temperature: float
    ):
        """Initialize the AISuite LLM wrapper.

        Args:
            client: AISuite Client instance
            model: Full model identifier with provider prefix (e.g., "openai:gpt-4o-mini")
            max_tokens: Maximum tokens for completion
            temperature: Temperature for response generation (0.0-2.0)
        """
        self.client = client
        self.model_id = model  # Use directly, expect "provider:model" format
        self.max_tokens = max_tokens
        self.temperature = temperature

    def invoke(self, prompt: str) -> LLMResponse:
        """Invoke the LLM with a prompt string.

        Args:
            prompt: The prompt text

        Returns:
            LLMResponse object with 'content' attribute containing the response text

        Raises:
            RuntimeError: If LLM invocation fails
        """
        messages = [{"role": "user", "content": prompt}]

        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            return LLMResponse(content=response.choices[0].message.content)
        except Exception as e:
            error_msg = (
                f"Failed to invoke LLM (model={self.model_id}, "
                f"prompt_length={len(prompt)}): {e}"
            )
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e


class LLMProvider:
    """Provider for LLM and embeddings initialization in RAG system.

    This class handles:
    - OpenAI embeddings initialization
    - LLM client using AISuite for unified interface
    """

    def __init__(self, settings: Settings):
        """Initialize the LLM provider.

        Args:
            settings: Application settings with API keys and model configuration
        """
        self.settings = settings
        self.embeddings: OpenAIEmbeddings | None = None
        self.llm: AISuiteLLMWrapper | None = None

        try:
            self.ai_client = ai.Client()
            logger.info("LLM provider initialized with AISuite client")
        except Exception as e:
            error_msg = f"Failed to initialize AISuite client: {e}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def _validate_openai_api_key(self) -> None:
        """Validate that OpenAI API key is configured.

        Raises:
            ValueError: If OpenAI API key is not configured
        """
        if not self.settings.OPENAI_API_KEY:
            error_msg = (
                "OpenAI API key is required but not configured. "
                "Please set OPENAI_API_KEY in environment variables."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

    def initialize_embeddings(self) -> OpenAIEmbeddings:
        """Initialize the OpenAI embedding model.

        Returns:
            OpenAIEmbeddings instance configured with API key and model

        Raises:
            ValueError: If OpenAI API key is not configured
        """
        logger.info("Initializing OpenAI embeddings model...")
        self._validate_openai_api_key()

        try:
            self.embeddings = OpenAIEmbeddings(
                api_key=self.settings.OPENAI_API_KEY,
                model=self.settings.OPENAI_EMBEDDING_MODEL,
            )
            logger.info("OpenAI embeddings model initialized")
            return self.embeddings
        except Exception as e:
            error_msg = f"Failed to initialize OpenAI embeddings: {e}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def initialize_llm(self) -> AISuiteLLMWrapper:
        """Initialize the language model using AISuite.

        Returns:
            Initialized LLM wrapper with AISuite client
        """
        logger.info("Initializing language model with AISuite...")
        self._validate_openai_api_key()

        try:
            self.llm = AISuiteLLMWrapper(
                client=self.ai_client,
                model=self.settings.OPENAI_MODEL,
                max_tokens=self.settings.MAX_TOKENS,
                temperature=self.settings.LLM_TEMPERATURE,
            )
            logger.info(f"LLM initialized with model: {self.settings.OPENAI_MODEL}")
            return self.llm
        except Exception as e:
            error_msg = f"Failed to initialize LLM wrapper: {e}"
            logger.exception(error_msg)
            raise RuntimeError(error_msg) from e

    def get_embeddings(self) -> OpenAIEmbeddings | None:
        """Get the initialized embeddings model.

        Returns:
            OpenAIEmbeddings instance or None if not initialized
        """
        return self.embeddings

    def get_llm(self) -> AISuiteLLMWrapper | None:
        """Get the initialized LLM.

        Returns:
            LLM wrapper instance or None if not initialized
        """
        return self.llm
