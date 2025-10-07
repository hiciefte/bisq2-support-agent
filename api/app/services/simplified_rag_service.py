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
from app.utils.logging import redact_pii
from fastapi import Request
from langchain.prompts import ChatPromptTemplate

# Vector store and embeddings
from langchain_chroma import Chroma

# Core LangChain imports
from langchain_core.documents import Document

# LLM providers
from langchain_openai import OpenAIEmbeddings

# Text splitter
from langchain_text_splitters import RecursiveCharacterTextSplitter

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

        # Configure text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,
            chunk_overlap=500,  # Increased from 300 to 500 for better context preservation
            separators=["\n\n", "\n", "==", "=", "'''", "{{", "*", ". ", " ", ""],
        )

        # Configure retriever
        self.retriever_config = {
            "k": 4,  # Number of documents to retrieve
        }

        # Initialize components
        self.embeddings = None
        self.vectorstore = None
        self.retriever = None
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
        """Initialize the OpenAI embedding model."""
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

    def initialize_llm(self):
        """Initialize the language model based on configuration."""
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

    def _initialize_openai_llm(self):
        """Initialize OpenAI model."""
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
        """Initialize xAI (Grok) model."""
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

    def _format_docs(self, docs: List[Document]) -> str:
        """Format retrieved documents with version-aware processing."""
        if not docs:
            return ""

        # Sort documents by version weight and relevance
        sorted_docs = sorted(
            docs,
            key=lambda x: (
                x.metadata.get("source_weight", 1.0),
                x.metadata.get("category") == "bisq2",  # Prioritize Bisq 2 content
                x.metadata.get("category") == "bisq1",  # Then Bisq 1 content
                x.metadata.get("category") == "general",  # Then general content
            ),
            reverse=True,
        )

        formatted_docs = []
        for doc in sorted_docs:
            # Extract metadata
            title = doc.metadata.get("title", "Unknown")
            category = doc.metadata.get("category", "general")
            section = doc.metadata.get("section", "")
            source_type = doc.metadata.get("type", "wiki")
            source_weight = doc.metadata.get("source_weight", 1.0)

            # Determine version from metadata and content
            bisq_version = doc.metadata.get("bisq_version", "General")
            if bisq_version == "General":
                # Check content for version-specific information
                content = doc.page_content.lower()
                if "bisq 2" in content or "bisq2" in content:
                    bisq_version = "Bisq 2"
                elif "bisq 1" in content or "bisq1" in content:
                    bisq_version = "Bisq 1"

            # Format the entry with version context and source attribution
            entry = f"[{bisq_version}] [{source_type.upper()}] {title}"
            if section:
                entry += f" - {section}"
            entry += f"\n{doc.page_content}\n"
            formatted_docs.append(entry)

        return "\n\n".join(formatted_docs)

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
            logger.error(f"Error cleaning vector store: {str(e)}", exc_info=True)
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

            # Split documents
            logger.info("Splitting documents into chunks...")
            splits = self.text_splitter.split_documents(all_docs)
            logger.info(f"Created {len(splits)} document chunks")

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

            # Initialize language model
            logger.info("Initializing language model...")
            self.initialize_llm()

            # Create RAG chain
            logger.info("Creating RAG chain...")
            self._create_rag_chain()

            logger.info("Simplified RAG service setup complete")
            return True
        except Exception as e:
            logger.error(
                f"Error during simplified RAG service setup: {str(e)}", exc_info=True
            )
            raise

    def _create_rag_chain(self):
        """Create the RAG chain using LangChain."""
        # Get prompt guidance from the FeedbackService if available
        additional_guidance = ""
        if self.feedback_service:
            guidance = self.feedback_service.get_prompt_guidance()
            if guidance:
                additional_guidance = (
                    f"\n\nIMPORTANT GUIDANCE BASED ON USER FEEDBACK:\n{guidance}"
                )
                logger.info(f"Added prompt guidance: {guidance}")

        # Custom system template with proper sections for context, chat history, and question
        system_template = f"""You are an assistant for question-answering tasks about Bisq 2.

IMPORTANT: You are a Bisq 2 support assistant.
Pay special attention to content marked with [VERSION: Bisq 2] as it is specifically about Bisq 2.
If content is marked with [VERSION: Bisq 1], it refers to the older version of Bisq and may not be applicable to Bisq 2.
Content marked with [VERSION: Both] contains information relevant to both versions.
Content marked with [VERSION: General] is general information that may apply to both versions.

Always prioritize Bisq 2 specific information in your answers.
If you don't know the answer, just say that you don't know.
Use three sentences maximum and keep the answer concise.{additional_guidance}

Question: {{question}}

Chat History: {{chat_history}}

Context: {{context}}

Answer:"""

        # Create the prompt template
        self.prompt = ChatPromptTemplate.from_template(system_template)
        logger.info(f"Custom RAG prompt created with {len(system_template)} characters")

        # Define our chain as a simple function that handles the entire RAG process
        def generate_response(question, chat_history=None):
            # Initialize response_start_time at the beginning to avoid reference before assignment
            response_start_time = time.time()

            try:
                if not question:
                    return "I'm sorry, I didn't receive a question. How can I help you with Bisq 2?"

                # Preprocess the question
                preprocessed_question = question.strip()

                # Log the question with privacy protection
                logger.info(f"Processing question: {redact_pii(preprocessed_question)}")

                # Set default chat history
                if chat_history is None:
                    chat_history = []

                # Format chat history for the prompt
                chat_history_str = ""
                if chat_history and len(chat_history) > 0:
                    # Format each exchange in chat history
                    formatted_history = []
                    # Use only the most recent MAX_CHAT_HISTORY_LENGTH exchanges
                    recent_history = chat_history[
                        -self.settings.MAX_CHAT_HISTORY_LENGTH :
                    ]
                    for exchange in recent_history:
                        # Check if this is a ChatMessage or a dictionary
                        if hasattr(exchange, "role") and hasattr(exchange, "content"):
                            # This is a ChatMessage object
                            role = exchange.role
                            content = exchange.content
                            if role == "user":
                                formatted_history.append(f"Human: {content}")
                            elif role == "assistant":
                                formatted_history.append(f"Assistant: {content}")
                        elif isinstance(exchange, dict):
                            # This is a dictionary
                            user_msg = exchange.get("user", "")
                            ai_msg = exchange.get("assistant", "")
                            if user_msg:
                                formatted_history.append(f"Human: {user_msg}")
                            if ai_msg:
                                formatted_history.append(f"Assistant: {ai_msg}")
                        else:
                            logger.warning(
                                f"Unknown exchange type in chat history: {type(exchange)}"
                            )

                    chat_history_str = "\n".join(formatted_history)

                # Retrieve relevant documents
                docs = self.retriever.get_relevant_documents(preprocessed_question)

                logger.info(f"Retrieved {len(docs)} relevant documents")

                # Format documents for the prompt
                context = self._format_docs(docs)

                # Check context length and truncate if necessary to fit in prompt
                if len(context) > self.settings.MAX_CONTEXT_LENGTH:
                    logger.warning(
                        f"Context too long: {len(context)} chars, truncating to {self.settings.MAX_CONTEXT_LENGTH}"
                    )
                    context = context[: self.settings.MAX_CONTEXT_LENGTH]

                # Log the complete prompt and context for debugging
                logger.info("=== DEBUG: Complete Prompt and Context ===")
                logger.info(f"Question: {preprocessed_question}")
                logger.info(f"Chat History: {chat_history_str}")
                logger.info("Context:")
                logger.info(context)
                logger.info("=== End Debug Log ===")

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
                response_text = self.llm.invoke(formatted_prompt)
                response_content = (
                    response_text.content
                    if hasattr(response_text, "content")
                    else str(response_text)
                )

                # Calculate response time
                response_time = time.time() - response_start_time

                # Log response information with privacy protection
                if response_content:
                    logger.info(
                        f"Response generated in {response_time:.2f}s, length: {len(response_content)}"
                    )

                    # Log sample in non-production
                    is_production = self.settings.ENVIRONMENT.lower() == "production"
                    if not is_production:
                        sample = (
                            response_content[: self.settings.MAX_SAMPLE_LOG_LENGTH]
                            + "..."
                            if len(response_content)
                            > self.settings.MAX_SAMPLE_LOG_LENGTH
                            else response_content
                        )
                        logger.info(f"Content sample: {redact_pii(sample)}")
                else:
                    logger.warning("Empty response received from LLM")
                    return "I apologize, but I couldn't generate a proper response based on the available information."

                return response_content
            except Exception as e:
                logger.error(f"Error generating response: {str(e)}", exc_info=True)
                return "I apologize, but I'm having technical difficulties processing your request. Please try again later."

        # Store the generate_response function as our RAG chain
        self.rag_chain = generate_response
        logger.info("Custom RAG chain created successfully")

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

            # Format chat history for the prompt
            formatted_history = []
            recent_history = chat_history[-self.settings.MAX_CHAT_HISTORY_LENGTH :]

            for exchange in recent_history:
                if hasattr(exchange, "role") and hasattr(exchange, "content"):
                    role = exchange.role
                    content = exchange.content
                    if role == "user":
                        formatted_history.append(f"Human: {content}")
                    elif role == "assistant":
                        formatted_history.append(f"Assistant: {content}")

            chat_history_str = "\n".join(formatted_history)

            # Create a special prompt for context-only answers
            context_only_prompt = f"""You are a Bisq 2 support assistant. A user has asked a follow-up question, but no relevant documents were found in the knowledge base.

IMPORTANT: Only answer if the question can be answered based on the previous conversation below. If the question is about a NEW topic not covered in the conversation history, you MUST say you don't have information.

Previous Conversation:
{chat_history_str}

Current Question: {question}

Instructions:
- If the answer is clearly in the conversation above, provide it concisely
- If this is a follow-up about something mentioned in the conversation, answer based on that context
- If this is a NEW topic not in the conversation, respond: "I don't have information about that in our knowledge base"
- Keep your answer to 2-3 sentences maximum

Answer:"""

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
            logger.error(f"Error answering from context: {str(e)}", exc_info=True)
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

            # Get relevant documents
            docs = self.retriever.get_relevant_documents(preprocessed_question)
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
                            f"Error creating feedback entry: {str(e)}", exc_info=True
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

            # Format chat history
            chat_history_str = ""
            if chat_history and len(chat_history) > 0:
                # Format each exchange in chat history
                formatted_history = []
                # Use only the most recent MAX_CHAT_HISTORY_LENGTH exchanges
                recent_history = chat_history[-self.settings.MAX_CHAT_HISTORY_LENGTH :]
                for exchange in recent_history:
                    if hasattr(exchange, "role") and hasattr(exchange, "content"):
                        role = exchange.role
                        content = exchange.content
                        if role == "user":
                            formatted_history.append(f"Human: {content}")
                        elif role == "assistant":
                            formatted_history.append(f"Assistant: {content}")
                chat_history_str = "\n".join(formatted_history)

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
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "answer": "I apologize, but I encountered an error processing your query. Please try again.",
                "sources": [],
                "response_time": error_time,
                "error": str(e),
                "forwarded_to_human": False,
                "feedback_created": False,
            }

    def _deduplicate_sources(self, sources):
        """Deduplicate sources to prevent multiple identical or very similar sources.

        Args:
            sources: List of source dictionaries

        Returns:
            List of deduplicated sources
        """
        if not sources:
            return []

        # Use a set to track unique sources
        seen_sources = set()
        unique_sources = []

        for source in sources:
            # Create a key based on title and type (primary deduplication)
            source_key = f"{source['title']}:{source['type']}"

            # Only include the source if we haven't seen this key before
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                unique_sources.append(source)

        logger.info(
            f"Deduplicated sources from {len(sources)} to {len(unique_sources)}"
        )
        return unique_sources


def get_rag_service(request: Request) -> SimplifiedRAGService:
    """Get the RAG service from the request state."""
    return request.app.state.rag_service
