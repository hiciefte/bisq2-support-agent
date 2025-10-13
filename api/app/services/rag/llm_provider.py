"""
LLM Provider for RAG system model initialization.

This module handles initialization of language models and embeddings:
- OpenAI embeddings model initialization
- LLM client using AISuite for unified interface
- Model configuration
"""

import logging
from typing import Any

import aisuite as ai
from app.core.config import Settings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


class AISuiteLLMWrapper:
    """Wrapper class to make AISuite compatible with existing RAG code.

    This wrapper provides an interface similar to LangChain's LLM classes,
    allowing the RAG system to use AISuite without major refactoring.
    """

    def __init__(self, client: ai.Client, model: str, max_tokens: int):
        """Initialize the AISuite LLM wrapper.

        Args:
            client: AISuite Client instance
            model: Model name (e.g., "gpt-4o", "gpt-3.5-turbo")
            max_tokens: Maximum tokens for completion
        """
        self.client = client
        self.model_id = f"openai:{model}"
        self.max_tokens = max_tokens

    def invoke(self, prompt: str) -> Any:
        """Invoke the LLM with a prompt string.

        Args:
            prompt: The prompt text

        Returns:
            Response object with 'content' attribute containing the response text
        """
        messages = [{"role": "user", "content": prompt}]

        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            temperature=0.7,
            max_tokens=self.max_tokens,
        )

        # Create a simple response object with content attribute
        # to match LangChain's interface
        class Response:
            def __init__(self, content: str):
                self.content = content

        return Response(content=response.choices[0].message.content)


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
        self.ai_client = ai.Client()

        logger.info("LLM provider initialized with AISuite client")

    def initialize_embeddings(self) -> OpenAIEmbeddings:
        """Initialize the OpenAI embedding model.

        Returns:
            OpenAIEmbeddings instance configured with API key and model

        Raises:
            ValueError: If OpenAI API key is not configured
        """
        logger.info("Initializing OpenAI embeddings model...")

        if not self.settings.OPENAI_API_KEY:
            error_msg = (
                "OpenAI API key is required but not configured. "
                "Please set OPENAI_API_KEY in environment variables."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        self.embeddings = OpenAIEmbeddings(
            api_key=self.settings.OPENAI_API_KEY,
            model=self.settings.OPENAI_EMBEDDING_MODEL,
        )

        logger.info("OpenAI embeddings model initialized")
        return self.embeddings

    def initialize_llm(self) -> Any:
        """Initialize the language model using AISuite.

        Returns:
            Initialized LLM wrapper with AISuite client
        """
        logger.info("Initializing language model with AISuite...")

        if not self.settings.OPENAI_API_KEY:
            error_msg = (
                "OpenAI API key is required but not configured. "
                "Please set OPENAI_API_KEY in environment variables."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Create LLM wrapper that works with AISuite
        self.llm = AISuiteLLMWrapper(
            client=self.ai_client,
            model=self.settings.OPENAI_MODEL,
            max_tokens=self.settings.MAX_TOKENS,
        )

        logger.info(f"LLM initialized with model: openai:{self.settings.OPENAI_MODEL}")
        return self.llm

    def get_embeddings(self) -> OpenAIEmbeddings:
        """Get the initialized embeddings model.

        Returns:
            OpenAIEmbeddings instance or None if not initialized
        """
        return self.embeddings

    def get_llm(self) -> Any:
        """Get the initialized LLM.

        Returns:
            LLM instance or None if not initialized
        """
        return self.llm
