"""
Simplified RAG-based Bisq 2 support assistant using LangChain.
This implementation combines wiki documentation from XML dump and FAQ data
for accurate and context-aware responses, with easy switching between OpenAI and xAI.

File Naming Conventions:
- Feedback files: feedback_YYYY-MM.jsonl (e.g., feedback_2025-03.jsonl)
  Stored in the DATA_DIR/feedback directory
- Legacy formats supported for reading (but not writing):
  - feedback_YYYYMMDD.jsonl (day-based naming)
  - feedback.jsonl (in root DATA_DIR)
  - negative_feedback.jsonl (special purpose file)
"""

import logging
import os
import shutil
import time
from typing import Any, Dict, List, Union

from app.core.config import get_settings
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.llm_provider import LLMProvider
from app.services.rag.prompt_manager import PromptManager
from app.utils.logging import redact_pii
from fastapi import Request

# Vector store and embeddings
from langchain_chroma import Chroma

# Core LangChain imports
from langchain_core.documents import Document

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimplifiedRAGService:
    """Simplified RAG-based support assistant for Bisq 2."""

    def __init__(
        self, settings=None, feedback_service=None, wiki_service=None, faq_service=None
    ):
        """Initialize the RAG service.

        Args:
            settings: Application settings
            feedback_service: Optional FeedbackService instance for feedback operations
            wiki_service: Optional WikiService instance for wiki operations
            faq_service: Optional FAQService instance for FAQ operations
        """
        if settings is None:
            settings = get_settings()
        self.settings = settings
        self.feedback_service = feedback_service
        self.wiki_service = wiki_service
        self.faq_service = faq_service

        # Set up paths
        self.db_path = self.settings.VECTOR_STORE_DIR_PATH

        # Initialize document processor for text splitting
        self.document_processor = DocumentProcessor(
            chunk_size=2000,  # Increased from 1500 to preserve more context per chunk
            chunk_overlap=500,  # Maintains good overlap for context preservation
        )

        # Initialize LLM provider for embeddings and model initialization
        self.llm_provider = LLMProvider(settings=self.settings)

        # Initialize prompt manager for prompt templates and chat formatting
        self.prompt_manager = PromptManager(
            settings=self.settings, feedback_service=self.feedback_service
        )

        # Configure retriever
        self.retriever_config = {
            "k": 4,  # Number of documents to retrieve
        }

        # Initialize components
        self.embeddings = None
        self.vectorstore = None
        self.retriever = None
        self.document_retriever = None  # Will be initialized after vectorstore
        self.llm = None
        self.rag_chain = None
        self.prompt = None

        # Initialize source weights
        # If feedback_service is provided, use its weights, otherwise use defaults
        if self.feedback_service:
            self.source_weights = self.feedback_service.get_source_weights()
        else:
            # Default source weights for different document types
            self.source_weights = {
                "faq": 1.2,  # Prioritize FAQ content
                "wiki": 1.1,  # Slightly increased weight for wiki content
            }

        logger.info("Simplified RAG service initialized")

    def initialize_embeddings(self):
        """Delegate to LLM provider for embeddings initialization."""
        self.embeddings = self.llm_provider.initialize_embeddings()

    def initialize_llm(self):
        """Delegate to LLM provider for model initialization."""
        self.llm = self.llm_provider.initialize_llm()

    def _retrieve_with_version_priority(self, query: str) -> List[Document]:
        """Delegate to document retriever for version-aware retrieval.

        Args:
            query: The search query

        Returns:
            List of documents prioritized by version relevance
        """
        return self.document_retriever.retrieve_with_version_priority(query)

    def _format_docs(self, docs: List[Document]) -> str:
        """Delegate to document retriever for document formatting.

        Args:
            docs: List of documents to format

        Returns:
            Formatted string with version context
        """
        return self.document_retriever.format_documents(docs)

    def _clean_vector_store(self):
        """Clean the vector store directory."""
        logger.info("Cleaning vector store directory...")
        try:
            if os.path.exists(self.db_path):
                # Remove all files and directories in the vector store
                for item in os.listdir(self.db_path):
                    item_path = os.path.join(self.db_path, item)
                    if os.path.isfile(item_path):
                        os.unlink(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                logger.info("Vector store directory cleaned successfully")
            else:
                logger.info("Vector store directory does not exist, skipping cleanup")
        except Exception as e:
            logger.error(f"Error cleaning vector store: {e!s}", exc_info=True)
            raise

    async def setup(self):
        """Set up the complete system."""
        try:
            logger.info("Starting simplified RAG service setup...")

            # Clean vector store
            self._clean_vector_store()

            # Load documents
            logger.info("Loading documents...")

            # Load wiki data from WikiService
            wiki_docs = []
            if self.wiki_service:
                wiki_docs = self.wiki_service.load_wiki_data()
            else:
                logger.warning("WikiService not provided, skipping wiki data loading")

            # Load FAQ data from FAQService
            faq_docs = []
            if self.faq_service:
                faq_docs = self.faq_service.load_faq_data()
            else:
                logger.warning("FAQService not provided, skipping FAQ data loading")

            # Combine all documents
            all_docs = wiki_docs + faq_docs
            logger.info(
                f"Loaded {len(wiki_docs)} wiki documents and {len(faq_docs)} FAQ documents"
            )

            if not all_docs:
                logger.warning("No documents loaded. Check your data paths.")
                return False

            # Apply feedback-based improvements if we have a feedback service
            if self.feedback_service:
                logger.info("Applying feedback-based improvements...")
                # Update source weights from feedback service
                self.source_weights = self.feedback_service.get_source_weights()
                logger.info(
                    f"Updated source weights from feedback service: {self.source_weights}"
                )

                # Update service weights
                if self.wiki_service:
                    self.wiki_service.update_source_weights(self.source_weights)
                if self.faq_service:
                    self.faq_service.update_source_weights(self.source_weights)

            # Split documents using document processor
            splits = self.document_processor.split_documents(all_docs)

            # Initialize embeddings
            logger.info("Initializing embedding model...")
            self.initialize_embeddings()

            # Create vector store
            logger.info("Creating vector store...")

            # Check if the vector store directory exists
            vector_store_exists = os.path.exists(self.db_path) and os.path.isdir(
                self.db_path
            )

            # Check if we have a persisted vector store by looking for the config file
            if vector_store_exists and any(
                f.endswith(".parquet") for f in os.listdir(self.db_path)
            ):
                # Load existing vector store
                logger.info("Loading existing vector store...")
                self.vectorstore = Chroma(
                    persist_directory=self.db_path,
                    embedding_function=self.embeddings,
                )
                logger.info("Vector store loaded successfully")

                # Update vector store with new documents
                if splits:
                    logger.info(
                        f"Updating vector store with {len(splits)} documents..."
                    )

                    # Use add_documents to add any new documents
                    # This avoids reprocessing already embedded documents
                    self.vectorstore.add_documents(splits)
                    logger.info("Vector store updated successfully")
            else:
                # Create new vector store
                logger.info("Creating new vector store...")
                self.vectorstore = Chroma(
                    persist_directory=self.db_path, embedding_function=self.embeddings
                )

                # Add documents to the new vector store
                logger.info("Adding documents to new vector store...")
                self.vectorstore.add_documents(splits)
                logger.info(f"Added {len(splits)} documents to new vector store")

            # Create retriever
            self.retriever = self.vectorstore.as_retriever(
                search_type="similarity_score_threshold",
                search_kwargs={
                    "k": 8,  # Increased from 5 to 8
                    "score_threshold": 0.3,  # Lowered threshold to allow more matches
                },
            )

            # Initialize document retriever for version-aware retrieval
            self.document_retriever = DocumentRetriever(
                vectorstore=self.vectorstore, retriever=self.retriever
            )
            logger.info("Document retriever initialized")

            # Initialize language model
            logger.info("Initializing language model...")
            self.initialize_llm()

            # Create RAG chain
            logger.info("Creating RAG chain...")
            # Create prompt template
            self.prompt = self.prompt_manager.create_rag_prompt()
            # Create RAG chain with dependencies
            self.rag_chain = self.prompt_manager.create_rag_chain(
                llm=self.llm,
                retrieve_func=self._retrieve_with_version_priority,
                format_docs_func=self._format_docs,
            )

            logger.info("Simplified RAG service setup complete")
            return True
        except Exception as e:
            logger.error(
                f"Error during simplified RAG service setup: {e!s}", exc_info=True
            )
            raise

    async def cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up simplified RAG service resources...")
        # Check if vectorstore has persist method before calling it
        if self.vectorstore and hasattr(self.vectorstore, "persist"):
            self.vectorstore.persist()
        logger.info("Simplified RAG service cleanup complete")

    async def _answer_from_context(
        self, question: str, chat_history: List[Union[Dict[str, str], Any]]
    ) -> dict:
        """Try to answer a question using only conversation history.

        This method is called when no relevant documents are found, but conversation
        history exists that might contain the answer.

        Args:
            question: The user's question
            chat_history: List of previous conversation exchanges

        Returns:
            dict: Response with answer, metadata, and answer source tracking
        """
        start_time = time.time()

        try:
            logger.info(
                "Attempting to answer from conversation context (no documents found)"
            )

            # Format chat history using prompt manager
            chat_history_str = self.prompt_manager.format_chat_history(chat_history)

            # Create context-only prompt using prompt manager
            context_only_prompt = self.prompt_manager.create_context_only_prompt(
                question, chat_history_str
            )

            # Get response from LLM
            response_text = self.llm.invoke(context_only_prompt)
            response_content = (
                response_text.content
                if hasattr(response_text, "content")
                else str(response_text)
            )

            logger.info(f"Generated context-based answer: {response_content[:100]}...")

            return {
                "answer": response_content,
                "sources": [],  # No document sources for context-based answers
                "response_time": time.time() - start_time,
                "answered_from": "context",  # Metadata flag
                "context_fallback": True,
            }

        except Exception as e:
            logger.error(f"Error answering from context: {e!s}", exc_info=True)
            # Fall back to "no information" response
            return {
                "answer": "I apologize, but I don't have sufficient information to answer your question. Your question has been queued for FAQ creation by our support team. In the meantime, please contact a Bisq human support agent who will be able to provide you with immediate assistance. Thank you for your patience.",
                "sources": [],
                "response_time": time.time() - start_time,
                "forwarded_to_human": True,
                "context_fallback_failed": True,
            }

    async def query(
        self, question: str, chat_history: List[Union[Dict[str, str], Any]]
    ) -> dict:
        """Process a query and return a response with metadata.

        Args:
            question: The query to process
            chat_history: List of either dictionaries containing chat messages with 'role' and 'content' keys,
                        or objects with role and content attributes

        Returns:
            Dict containing:
                - answer: The response text
                - sources: List of source documents used
                - response_time: Time taken to process the query
                - error: Error message (if any)
        """
        start_time = time.time()

        try:
            if not self.rag_chain:
                logger.error("RAG chain not initialized. Call setup() first.")
                return {
                    "answer": "I apologize, but I'm not fully initialized yet. Please try again in a moment.",
                    "sources": [],
                    "response_time": time.time() - start_time,
                    "error": "RAG chain not initialized",
                }

            # Log the question with privacy protection
            logger.info(f"Processing question: {redact_pii(question)}")

            # Preprocess the question
            preprocessed_question = question.strip()

            # Get relevant documents with version priority
            docs = self._retrieve_with_version_priority(preprocessed_question)
            logger.info(f"Retrieved {len(docs)} relevant documents")

            # If no documents were retrieved, check if we can answer from conversation context
            if not docs:
                logger.info("No relevant documents found for the query")

                # Check if we have conversation history to potentially answer from
                if chat_history and len(chat_history) > 0:
                    logger.info(
                        f"Attempting context-aware fallback with {len(chat_history)} messages in history"
                    )
                    return await self._answer_from_context(
                        preprocessed_question, chat_history
                    )

                # No conversation history either - create feedback entry and return "no info" message
                logger.info("No conversation history available for context fallback")

                # Create feedback entry for missing FAQ
                if self.feedback_service:
                    try:
                        await self.feedback_service.store_feedback(
                            {
                                "question": preprocessed_question,
                                "answer": "",
                                "feedback_type": "missing_faq",
                                "explanation": "No relevant documents found for this query. This question should be added to the FAQ database.",
                                "metadata": {
                                    "source": "rag_service",
                                    "action_required": "create_faq",
                                    "priority": "high",
                                },
                            }
                        )
                        logger.info("Created feedback entry for missing FAQ")
                    except Exception as e:
                        logger.error(
                            f"Error creating feedback entry: {e!s}", exc_info=True
                        )

                return {
                    "answer": "I apologize, but I don't have sufficient information to answer your question. Your question has been queued for FAQ creation by our support team. In the meantime, please contact a Bisq human support agent who will be able to provide you with immediate assistance. Thank you for your patience.",
                    "sources": [],
                    "response_time": time.time() - start_time,
                    "forwarded_to_human": True,
                    "feedback_created": True,
                }

            # Log document details at DEBUG level
            for i, doc in enumerate(docs):
                logger.debug(f"Document {i + 1}:")
                logger.debug(f"  Title: {doc.metadata.get('title', 'N/A')}")
                logger.debug(f"  Type: {doc.metadata.get('type', 'N/A')}")
                logger.debug(f"  Content: {doc.page_content[:200]}...")

            # Format chat history using prompt manager
            chat_history_str = self.prompt_manager.format_chat_history(chat_history)

            # Format documents for the prompt
            context = self._format_docs(docs)

            # Check context length and truncate if necessary
            if len(context) > self.settings.MAX_CONTEXT_LENGTH:
                logger.warning(
                    f"Context too long: {len(context)} chars, truncating to {self.settings.MAX_CONTEXT_LENGTH}"
                )
                context = context[: self.settings.MAX_CONTEXT_LENGTH]

            # Log complete prompt and context at DEBUG level
            logger.debug("=== DEBUG: Complete Prompt and Context ===")
            logger.debug(f"Question: {preprocessed_question}")
            logger.debug(f"Chat History: {chat_history_str}")
            logger.debug(f"Context:\n{context}")
            logger.debug("=== End Debug Log ===")

            # Format the prompt
            formatted_prompt = self.prompt.format(
                question=preprocessed_question,
                chat_history=chat_history_str,
                context=context,
            )

            # Log formatted prompt at DEBUG level
            logger.debug("=== DEBUG: Complete Formatted Prompt ===")
            logger.debug(formatted_prompt)
            logger.debug("=== End Debug Log ===")

            # Generate response
            response_text = self.rag_chain(formatted_prompt)

            # Calculate response time
            response_time = time.time() - start_time

            # Log response details at INFO level
            logger.info(
                f"Response generated in {response_time:.2f}s, length: {len(response_text)}"
            )

            # Log sample in non-production
            is_production = self.settings.ENVIRONMENT.lower() == "production"
            if not is_production:
                sample = (
                    response_text[: self.settings.MAX_SAMPLE_LOG_LENGTH] + "..."
                    if len(response_text) > self.settings.MAX_SAMPLE_LOG_LENGTH
                    else response_text
                )
                logger.info(f"Content sample: {redact_pii(sample)}")

            # Extract sources for the response
            sources = []
            for doc in docs:
                if doc.metadata.get("type") == "wiki":
                    sources.append(
                        {
                            "title": doc.metadata.get("title", "Unknown"),
                            "type": "wiki",
                            "content": (
                                doc.page_content[:200] + "..."
                                if len(doc.page_content) > 200
                                else doc.page_content
                            ),
                        }
                    )
                elif doc.metadata.get("type") == "faq":
                    sources.append(
                        {
                            "title": doc.metadata.get("title", "Unknown"),
                            "type": "faq",
                            "content": (
                                doc.page_content[:200] + "..."
                                if len(doc.page_content) > 200
                                else doc.page_content
                            ),
                        }
                    )

            # Deduplicate sources
            sources = self._deduplicate_sources(sources)

            return {
                "answer": response_text,
                "sources": sources,
                "response_time": response_time,
                "answered_from": "documents",  # Metadata flag
                "forwarded_to_human": False,
                "feedback_created": False,
            }

        except Exception as e:
            error_time = time.time() - start_time
            logger.error(f"Error processing query: {e!s}", exc_info=True)
            return {
                "answer": "I apologize, but I encountered an error processing your query. Please try again.",
                "sources": [],
                "response_time": error_time,
                "error": str(e),
                "forwarded_to_human": False,
                "feedback_created": False,
            }

    def _deduplicate_sources(self, sources):
        """Delegate to document retriever for source deduplication.

        Args:
            sources: List of source dictionaries

        Returns:
            List of deduplicated sources
        """
        return self.document_retriever.deduplicate_sources(sources)


def get_rag_service(request: Request) -> SimplifiedRAGService:
    """Get the RAG service from the request state."""
    return request.app.state.rag_service
