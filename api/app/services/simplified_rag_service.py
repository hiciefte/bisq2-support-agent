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
import re
import time
from typing import List

from fastapi import Request
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


# Remove the constants that are now in config.py
# They'll be accessed through the settings object


def redact_pii(text: str) -> str:
    """Redact potential PII from text for logging purposes.

    Redacts:
    - Email addresses
    - IP addresses
    - Numeric sequences that might be IDs
    - Long alphanumeric strings that might be keys/passwords
    - Phone numbers (various formats)
    - Partial numeric sequences that might be sensitive identifiers
    """
    if not text:
        return text

    # Redact email addresses
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[REDACTED_EMAIL]',
                  text)

    # Redact IP addresses
    text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[REDACTED_IP]', text)

    # Redact long numeric sequences (potentially IDs)
    text = re.sub(r'\b\d{8,}\b', '[REDACTED_ID]', text)

    # Redact alphanumeric strings that look like API keys (30+ chars)
    text = re.sub(r'\b[a-zA-Z0-9_\-.]{30,}\b', '[REDACTED_KEY]', text)

    # Redact phone numbers (various formats)
    text = re.sub(r'\b(\+\d{1,2}\s?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b',
                  '[REDACTED_PHONE]', text)

    # Redact potentially sensitive partial numeric sequences (e.g., SSN fragments)
    text = re.sub(r'\b\d{3}[\s.-]?\d{2}[\s.-]?\d{4}\b', '[REDACTED_ID_PATTERN]', text)

    return text


class SimplifiedRAGService:
    """Simplified RAG-based support assistant for Bisq 2."""

    def __init__(self, settings=None, feedback_service=None, wiki_service=None,
                 faq_service=None):
        """Initialize the RAG service.

        Args:
            settings: Application settings
            feedback_service: Optional FeedbackService instance for feedback operations
            wiki_service: Optional WikiService instance for wiki operations
            faq_service: Optional FAQService instance for FAQ operations
        """
        self.settings = settings
        self.feedback_service = feedback_service
        self.wiki_service = wiki_service
        self.faq_service = faq_service

        # Set up paths
        self.db_path = self.settings.VECTOR_STORE_DIR_PATH

        # Configure text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,
            chunk_overlap=300,
            separators=["\n\n", "\n", "==", "=", ". ", " ", ""],
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

        # Initialize source weights
        # If feedback_service is provided, use its weights, otherwise use defaults
        if self.feedback_service:
            self.source_weights = self.feedback_service.get_source_weights()
        else:
            # Default source weights for different document types
            self.source_weights = {
                "faq": 1.2,  # Prioritize FAQ content
                "wiki": 1.0,  # Standard weight for wiki content
            }

        logger.info("Simplified RAG service initialized")

    def initialize_embeddings(self):
        """Initialize the OpenAI embedding model."""
        logger.info("Initializing OpenAI embeddings model...")

        if not self.settings.OPENAI_API_KEY:
            logger.warning(
                "OpenAI API key not provided. Embeddings will not work properly.")

        self.embeddings = OpenAIEmbeddings(
            api_key=self.settings.OPENAI_API_KEY,
            model=self.settings.OPENAI_EMBEDDING_MODEL
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
                f"LLM provider '{llm_provider}' not configured properly. Using OpenAI as default.")
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
            f"OpenAI model initialized: {model_name} with max_tokens={self.settings.MAX_TOKENS}")

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
                f"xAI model initialized: {model_name} with max_tokens={self.settings.MAX_TOKENS}")
        except ImportError:
            logger.error(
                "langchain_xai package not installed. Please install it to use xAI models.")
            logger.info("Falling back to OpenAI model.")
            self._initialize_openai_llm()

    def _format_docs(self, docs: List[Document]) -> str:
        """Format documents into a single string with source attribution.

        Args:
            docs: List of retrieved documents

        Returns:
            Formatted string with source attribution
        """
        formatted_chunks = []

        for doc in docs:
            content = doc.page_content
            title = doc.metadata.get("title", "")
            source_type = doc.metadata.get("type", "unknown")

            # Set proper Bisq version based on metadata or content analysis
            bisq_version = doc.metadata.get("bisq_version", "")

            # If no explicit version is set in metadata, try to determine from content
            if not bisq_version:
                # For wiki entries, determine version based on content
                if "bisq2" in content.lower() or "bisq 2" in content.lower():
                    if "bisq1" in content.lower() or "bisq 1" in content.lower():
                        bisq_version = "Both"  # Content mentions both versions
                    else:
                        bisq_version = "Bisq 2"  # Content is Bisq 2 specific
                elif "bisq1" in content.lower() or "bisq 1" in content.lower():
                    bisq_version = "Bisq 1"  # Content is Bisq 1 specific
                else:
                    bisq_version = "General"  # Cannot determine version

            # Format the chunk with clear version labeling
            if source_type == "faq":
                formatted_chunks.append(
                    f"[SOURCE: FAQ] [VERSION: {bisq_version}]\n{content}")
            elif source_type == "wiki":
                section = doc.metadata.get("section", "")

                # Include section information
                prefix = f"[SOURCE: Wiki - {title}"
                if section:
                    prefix += f" - {section}"
                prefix += f"] [VERSION: {bisq_version}]"

                formatted_chunks.append(f"{prefix}\n{content}")

        return "\n\n" + "\n\n".join(formatted_chunks)

    async def setup(self):
        """Set up the complete system."""
        try:
            logger.info("Starting simplified RAG service setup...")

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
                f"Loaded {len(wiki_docs)} wiki documents and {len(faq_docs)} FAQ documents")

            if not all_docs:
                logger.warning("No documents loaded. Check your data paths.")
                return False

            # Apply feedback-based improvements if we have a feedback service
            if self.feedback_service:
                logger.info("Applying feedback-based improvements...")
                # Update source weights from feedback service
                self.source_weights = self.feedback_service.get_source_weights()
                logger.info(
                    f"Updated source weights from feedback service: {self.source_weights}")

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
                self.db_path)

            # Check if we have a persisted vector store by looking for the config file
            if vector_store_exists and any(
                f.endswith('.parquet') for f in os.listdir(self.db_path)):
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
                        f"Updating vector store with {len(splits)} documents...")

                    # Use add_documents to add any new documents
                    # This avoids reprocessing already embedded documents
                    self.vectorstore.add_documents(splits)
                    logger.info("Vector store updated successfully")
            else:
                # Create new vector store
                logger.info("Creating new vector store...")
                self.vectorstore = Chroma(
                    persist_directory=self.db_path,
                    embedding_function=self.embeddings
                )

                # Add documents to the new vector store
                logger.info("Adding documents to new vector store...")
                self.vectorstore.add_documents(splits)
                logger.info(f"Added {len(splits)} documents to new vector store")

            # Create retriever
            self.retriever = self.vectorstore.as_retriever(
                search_type="similarity",
                search_kwargs={"k": self.retriever_config["k"]}
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
            logger.error(f"Error during simplified RAG service setup: {str(e)}",
                         exc_info=True)
            raise

    def _create_rag_chain(self):
        """Create the RAG chain using LangChain."""
        from langchain.prompts import ChatPromptTemplate

        # Get prompt guidance from the FeedbackService if available
        additional_guidance = ""
        if self.feedback_service:
            guidance = self.feedback_service.get_prompt_guidance()
            if guidance:
                additional_guidance = f"\n\nIMPORTANT GUIDANCE BASED ON USER FEEDBACK:\n{guidance}"
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
        custom_prompt = ChatPromptTemplate.from_template(system_template)
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
                                     -self.settings.MAX_CHAT_HISTORY_LENGTH:]
                    for exchange in recent_history:
                        # Check if this is a ChatMessage or a dictionary
                        if hasattr(exchange, 'role') and hasattr(exchange, 'content'):
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
                                f"Unknown exchange type in chat history: {type(exchange)}")

                    chat_history_str = "\n".join(formatted_history)

                # Retrieve relevant documents
                docs = self.retriever.get_relevant_documents(preprocessed_question)

                logger.info(f"Retrieved {len(docs)} relevant documents")

                # Format documents for the prompt
                context = self._format_docs(docs)

                # Check context length and truncate if necessary to fit in prompt
                if len(context) > self.settings.MAX_CONTEXT_LENGTH:
                    logger.warning(
                        f"Context too long: {len(context)} chars, truncating to {self.settings.MAX_CONTEXT_LENGTH}")
                    context = context[:self.settings.MAX_CONTEXT_LENGTH]

                # Invoke the LLM with the custom prompt
                response = self.llm.invoke(
                    custom_prompt.format(
                        question=preprocessed_question,
                        chat_history=chat_history_str,
                        context=context
                    )
                )

                # Extract the content from the response
                content = response.content if hasattr(response, "content") else str(
                    response)

                # Log response information with privacy protection
                if content:
                    # Calculate response time
                    response_time = time.time() - response_start_time
                    logger.info(
                        f"Response generated in {response_time:.2f}s, length: {len(content)}")

                    # Log sample in non-production
                    is_production = self.settings.ENVIRONMENT.lower() == 'production'
                    if not is_production:
                        sample = content[
                                 :self.settings.MAX_SAMPLE_LOG_LENGTH] + "..." if len(
                            content) > self.settings.MAX_SAMPLE_LOG_LENGTH else content
                        logger.info(f"Content sample: {redact_pii(sample)}")
                else:
                    logger.warning("Empty response received from LLM")
                    return "I apologize, but I couldn't generate a proper response based on the available information."

                return content
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
        if self.vectorstore and hasattr(self.vectorstore, 'persist'):
            self.vectorstore.persist()
        logger.info("Simplified RAG service cleanup complete")

    async def query(self, question, chat_history=None):
        """Process a query and return the response with sources.

        Args:
            question: The query to process
            chat_history: Optional chat history for context

        Returns:
            Dict with response and metadata
        """
        # Initialize start_time at the beginning to avoid reference before assignment
        start_time = time.time()

        try:
            if not self.rag_chain:
                logger.error("RAG chain not initialized. Call setup() first.")
                return {
                    "answer": "I apologize, but I'm not fully initialized yet. Please try again in a moment.",
                    "sources": [],
                    "error": "RAG chain not initialized"
                }

            try:
                # Get response from RAG chain
                content = self.rag_chain(question, chat_history)
            except AttributeError as ae:
                # Handle specific attribute errors that might occur when processing chat_history
                logger.error(f"Attribute error in rag_chain: {str(ae)}", exc_info=True)

                # Check if it's specifically related to ChatMessage objects
                if "ChatMessage" in str(ae) and "get" in str(ae):
                    # Try to adapt chat_history by converting it to a more compatible format
                    try:
                        adapted_chat_history = []
                        for message in chat_history:
                            # Convert to a simple dict format with direct access
                            if hasattr(message, 'role') and hasattr(message, 'content'):
                                adapted_chat_history.append({
                                    "role": message.role,
                                    "content": message.content
                                })
                        # Retry with the adapted chat history
                        content = self.rag_chain(question, adapted_chat_history)
                    except Exception as conversion_error:
                        logger.error(
                            f"Error converting chat history: {str(conversion_error)}",
                            exc_info=True)
                        content = "I'm sorry, I encountered an error processing your conversation history. Please try again with a simpler question."
                else:
                    content = "I'm sorry, I encountered an unexpected error. Please try again or rephrase your question."
            except Exception as e:
                # Handle any other exceptions in the rag_chain
                logger.error(f"Error in rag_chain: {str(e)}", exc_info=True)
                content = "I'm sorry, I encountered an unexpected error. Please try again or rephrase your question."

            # Extract sources and search results for later analysis
            sources_used = None
            if self.retriever:
                # Get the relevant documents without affecting the response
                docs = self.retriever.get_relevant_documents(question)
                sources_used = [
                    {
                        "title": doc.metadata.get("title", "Unknown"),
                        "type": doc.metadata.get("type", "unknown"),
                        "content": doc.page_content[:200] + "..." if len(
                            doc.page_content) > 200 else doc.page_content
                    }
                    for doc in docs
                ]

                # Deduplicate sources to prevent multiple identical sources
                sources_used = self._deduplicate_sources(sources_used)

            # Calculate response time
            response_time = time.time() - start_time

            # Log completion of query
            logger.info(f"Query processed successfully in {response_time:.2f}s")

            return {
                "answer": content,
                "sources": sources_used or [],
                "response_time": response_time
            }
        except Exception as e:
            # start_time is now always defined, so we can calculate error_time directly
            error_time = time.time() - start_time
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "answer": f"I'm sorry, I encountered an error while processing your question. Please try again or rephrase your question.",
                "sources": [],
                "response_time": error_time,
                "error": str(e)
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
            f"Deduplicated sources from {len(sources)} to {len(unique_sources)}")
        return unique_sources


def get_rag_service(request: Request) -> SimplifiedRAGService:
    """Get the RAG service from the request state."""
    return request.app.state.rag_service
