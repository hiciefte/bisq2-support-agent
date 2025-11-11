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

import asyncio
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional, Union

import chromadb
from app.core.config import get_settings
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.llm_provider import LLMProvider
from app.services.rag.prompt_manager import PromptManager
from app.services.rag.vectorstore_manager import VectorStoreManager
from app.services.rag.vectorstore_state_manager import VectorStoreStateManager
from app.utils.instrumentation import (
    RAG_REQUEST_RATE,
    instrument_stage,
    track_tokens_and_cost,
    update_error_rate,
)
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

        # Initialize vector store manager for change detection and rebuilds
        self.vectorstore_manager = VectorStoreManager(
            vectorstore_path=self.db_path, data_dir=self.settings.DATA_DIR
        )

        # Initialize state manager for manual rebuild coordination
        self.state_manager = VectorStoreStateManager()

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
        self.chroma_client = None  # Store client reference for proper cleanup
        self.vectorstore = None
        self.retriever = None
        self.document_retriever = None  # Will be initialized after vectorstore
        self.llm = None
        self.rag_chain = None
        self.prompt = None

        # Initialize lock for rebuild serialization to prevent concurrent rebuilds
        self._setup_lock = asyncio.Lock()

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

        # Register callback for runtime vector store updates
        # Wrap async callback in create_task to avoid un-awaited coroutine
        self.vectorstore_manager.register_update_callback(
            lambda src: asyncio.create_task(self._handle_source_update(src))
        )

        # Register with FAQ service for FAQ updates (manual rebuild mode)
        if self.faq_service:
            self.faq_service.register_update_callback(self._handle_faq_update)
            logger.info("Registered FAQ service update callback (manual rebuild mode)")

        logger.info("Simplified RAG service initialized")

    def _handle_faq_update(
        self,
        rebuild: bool,
        operation: str,
        faq_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Handle FAQ updates with optional manual rebuild.

        Args:
            rebuild: If True, rebuild immediately (legacy behavior)
                    If False, mark for manual rebuild (new behavior)
            operation: Type of change (add, update, delete, bulk_delete)
            faq_id: ID of changed FAQ
            metadata: Additional context about the change
        """
        if rebuild:
            # Legacy behavior - trigger immediate automatic rebuild
            logger.info("Legacy automatic rebuild requested")
            self.vectorstore_manager.trigger_update("faq")
        else:
            # New behavior - mark for manual rebuild
            logger.debug(f"Marking FAQ change for rebuild: {operation} on {faq_id}")
            self.state_manager.mark_change(
                operation=operation or "unknown",
                faq_id=faq_id or "unknown",
                metadata=metadata,
            )

    async def _handle_source_update(self, source_name: str) -> None:
        """Handle runtime updates to source files (FAQ or wiki).

        This callback is triggered when source files are updated at runtime
        (e.g., new FAQs extracted, wiki updated). It rebuilds the vector store
        to ensure new content is searchable.

        Args:
            source_name: Name of the source that was updated ("faq" or "wiki")
        """
        logger.info(
            f"Source '{source_name}' updated at runtime, triggering vector store rebuild..."
        )
        try:
            # Trigger a rebuild by calling setup again
            # This will detect changes and rebuild the vector store
            await self.setup()
            logger.info(f"Vector store successfully rebuilt after {source_name} update")
        except Exception as e:
            logger.error(
                f"Failed to rebuild vector store after {source_name} update: {e}",
                exc_info=True,
            )

    def initialize_embeddings(self) -> None:
        """Delegate to LLM provider for embeddings initialization."""
        self.embeddings = self.llm_provider.initialize_embeddings()

    def initialize_llm(self) -> None:
        """Delegate to LLM provider for model initialization."""
        self.llm = self.llm_provider.initialize_llm()

    @instrument_stage("retrieval")
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

    def _clean_vector_store(self) -> None:
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

    async def setup(self, force_rebuild: bool = False):
        """Set up the complete system.

        Args:
            force_rebuild: If True, force rebuilding the vector store from scratch.
                          Otherwise, reuse existing vector store if available.
        """
        # Acquire lock to prevent concurrent rebuilds
        async with self._setup_lock:
            try:
                logger.info("Starting simplified RAG service setup...")

                # Only clean vector store if force rebuild is requested
                if force_rebuild:
                    logger.info("Force rebuild requested - cleaning vector store")
                    self._clean_vector_store()
                else:
                    logger.info(
                        "Reusing existing vector store if available (use force_rebuild=True to rebuild)"
                    )

                # Load documents
                logger.info("Loading documents...")

                # Load wiki data from WikiService
                wiki_docs = []
                if self.wiki_service:
                    wiki_docs = self.wiki_service.load_wiki_data()
                else:
                    logger.warning(
                        "WikiService not provided, skipping wiki data loading"
                    )

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

                # Create vector store with change detection
                logger.info("Checking if vector store rebuild is needed...")

                # Check if we need to rebuild based on source file changes
                if self.vectorstore_manager.should_rebuild():
                    rebuild_reason = self.vectorstore_manager.get_rebuild_reason()
                    logger.info(f"Rebuilding vector store: {rebuild_reason}")

                    # Properly close ChromaDB client to release database locks
                    if self.chroma_client:
                        try:
                            logger.info(
                                "Closing ChromaDB client to release database locks..."
                            )
                            # Clear heartbeat to allow clean shutdown
                            self.chroma_client.clear_system_cache()
                            self.chroma_client = None
                            logger.info("ChromaDB client closed successfully")
                        except Exception as e:
                            logger.warning(f"Error closing ChromaDB client: {e!s}")
                            self.chroma_client = None

                    # Clear vectorstore reference
                    self.vectorstore = None

                    # Clean existing vector store before rebuilding
                    self._clean_vector_store()

                    # Create new vector store with PersistentClient for disk persistence
                    logger.info("Creating new vector store with persistent storage...")
                    self.chroma_client = chromadb.PersistentClient(path=self.db_path)
                    self.vectorstore = Chroma(
                        client=self.chroma_client,
                        embedding_function=self.embeddings,
                    )

                    # Add documents to the new vector store
                    logger.info(
                        f"Adding {len(splits)} documents to new vector store..."
                    )
                    self.vectorstore.add_documents(splits)
                    logger.info(
                        f"Added {len(splits)} documents to new vector store at {self.db_path}"
                    )

                    # Save metadata after successful build
                    metadata = self.vectorstore_manager.collect_source_metadata()
                    self.vectorstore_manager.save_metadata(metadata)
                    logger.info("Saved vector store metadata for change detection")
                else:
                    # Load existing vector store from cache
                    logger.info("Loading existing vector store from cache...")
                    self.chroma_client = chromadb.PersistentClient(path=self.db_path)
                    self.vectorstore = Chroma(
                        client=self.chroma_client,
                        embedding_function=self.embeddings,
                    )
                    logger.info(
                        f"Vector store loaded successfully from {self.db_path} (skipping re-embedding of {len(splits)} documents)"
                    )

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

        # Properly close ChromaDB client to release database locks
        if self.chroma_client:
            try:
                logger.info("Closing ChromaDB client during cleanup...")
                self.chroma_client.clear_system_cache()
                self.chroma_client = None
                logger.info("ChromaDB client closed successfully")
            except Exception as e:
                logger.warning(f"Error closing ChromaDB client during cleanup: {e!s}")
                self.chroma_client = None

        self.vectorstore = None
        logger.info("Simplified RAG service cleanup complete")

    async def manual_rebuild(self) -> Dict[str, Any]:
        """
        Manually triggered vector store rebuild.

        Returns:
            Dictionary with rebuild results (success, duration, changes applied)
        """
        logger.info("Manual rebuild requested")

        # Use state manager to coordinate rebuild
        return await self.state_manager.execute_rebuild(
            rebuild_callback=self._perform_rebuild
        )

    async def _perform_rebuild(self) -> None:
        """
        Internal method to perform actual vector store rebuild.

        Called by state_manager.execute_rebuild() with proper state tracking.
        """
        await self.setup(force_rebuild=True)

    def get_rebuild_status(self) -> Dict[str, Any]:
        """Get current rebuild status for API consumption."""
        return self.state_manager.get_status()

    def get_rebuild_summary(self) -> Dict[str, Any]:
        """Get lightweight rebuild status for polling."""
        return self.state_manager.get_summary_status()

    @instrument_stage("generation")
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

            # Track token usage and cost
            if hasattr(response_text, "usage") and response_text.usage:
                track_tokens_and_cost(
                    input_tokens=response_text.usage.get("prompt_tokens", 0),
                    output_tokens=response_text.usage.get("completion_tokens", 0),
                    input_cost_per_token=self.settings.OPENAI_INPUT_COST_PER_TOKEN,
                    output_cost_per_token=self.settings.OPENAI_OUTPUT_COST_PER_TOKEN,
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

        # Track request rate
        RAG_REQUEST_RATE.inc()

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

            # Generate response using the RAG chain
            # The chain handles retrieval, formatting, and LLM invocation internally
            # Note: We already retrieved docs above for logging/source tracking,
            # but the chain will do its own retrieval which is fine
            response_text = self.rag_chain(preprocessed_question, chat_history)

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

            # Update error rate (success)
            update_error_rate(is_error=False)

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

            # Update error rate (failure)
            update_error_rate(is_error=True)

            return {
                "answer": "I apologize, but I encountered an error processing your query. Please try again.",
                "sources": [],
                "response_time": error_time,
                "error": str(e),
                "forwarded_to_human": False,
                "feedback_created": False,
            }

    def _deduplicate_sources(
        self, sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
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
