"""
LLM Provider for RAG system model initialization.

This module handles initialization of language models and embeddings:
- OpenAI embeddings model initialization
- LLM provider selection (OpenAI or xAI)
- Model configuration and fallback handling
"""

import logging
from typing import Any

from app.core.config import Settings
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


class LLMProvider:
    """Provider for LLM and embeddings initialization in RAG system.

    This class handles:
    - OpenAI embeddings initialization
    - LLM provider selection and configuration
    - Fallback logic for unavailable providers
    """

    def __init__(self, settings: Settings):
        """Initialize the LLM provider.

        Args:
            settings: Application settings with API keys and model configuration
        """
        self.settings = settings
        self.embeddings = None
        self.llm = None

        logger.info("LLM provider initialized")

    def initialize_embeddings(self) -> OpenAIEmbeddings:
        """Initialize the OpenAI embedding model.

        Returns:
            OpenAIEmbeddings instance configured with API key and model

        Raises:
            Warning if API key is not provided
        """
        logger.info("Initializing OpenAI embeddings model...")

        if not self.settings.OPENAI_API_KEY:
            logger.warning(
                "OpenAI API key not provided. Embeddings will not work properly."
            )

        self.embeddings = OpenAIEmbeddings(
            api_key=self.settings.OPENAI_API_KEY,
            model=self.settings.OPENAI_EMBEDDING_MODEL,
        )

        logger.info("OpenAI embeddings model initialized")
        return self.embeddings

    def initialize_llm(self) -> Any:
        """Initialize the language model based on configuration.

        Determines which LLM provider to use (OpenAI or xAI) based on settings
        and initializes the appropriate model with fallback handling.

        Returns:
            Initialized LLM instance (ChatOpenAI or ChatXai)
        """
        logger.info("Initializing language model...")

        # Determine which LLM provider to use based on the configuration
        llm_provider = self.settings.LLM_PROVIDER.lower()

        if llm_provider == "openai" and self.settings.OPENAI_API_KEY:
            self._initialize_openai_llm()
        elif llm_provider == "xai" and self.settings.XAI_API_KEY:
            self._initialize_xai_llm()
        else:
            logger.warning(
                f"LLM provider '{llm_provider}' not configured properly. Using OpenAI as default."
            )
            self._initialize_openai_llm()

        logger.info("LLM initialization complete")
        return self.llm

    def _initialize_openai_llm(self):
        """Initialize OpenAI model.

        Configures ChatOpenAI with API key, model name, and token limits
        from settings.
        """
        model_name = self.settings.OPENAI_MODEL
        logger.info(f"Using OpenAI model: {model_name}")

        # Import directly from langchain_openai for more control
        from langchain_openai import ChatOpenAI

        # Configure model parameters
        self.llm = ChatOpenAI(
            api_key=self.settings.OPENAI_API_KEY,
            model=model_name,
            max_tokens=self.settings.MAX_TOKENS,
            verbose=True,
        )
        logger.info(
            f"OpenAI model initialized: {model_name} with max_tokens={self.settings.MAX_TOKENS}"
        )

    def _initialize_xai_llm(self):
        """Initialize xAI (Grok) model.

        Attempts to initialize ChatXai with API key and model configuration.
        Falls back to OpenAI if langchain_xai package is not installed.
        """
        model_name = self.settings.XAI_MODEL
        logger.info(f"Using xAI model: {model_name}")

        try:
            from langchain_xai import ChatXai

            # Initialize the model
            self.llm = ChatXai(
                api_key=self.settings.XAI_API_KEY,
                model=model_name,
                temperature=0.7,
                max_tokens=self.settings.MAX_TOKENS,
                timeout=30,
            )
            logger.info(
                f"xAI model initialized: {model_name} with max_tokens={self.settings.MAX_TOKENS}"
            )
        except ImportError:
            logger.error(
                "langchain_xai package not installed. Please install it to use xAI models."
            )
            logger.info("Falling back to OpenAI model.")
            self._initialize_openai_llm()

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
