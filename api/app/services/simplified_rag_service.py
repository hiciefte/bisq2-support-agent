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

import json
import logging
import os
import re
import shutil
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from fastapi import Request
# Vector store and embeddings
from langchain_chroma import Chroma
from langchain_community.document_loaders import MWDumpLoader
# Core LangChain imports
from langchain_core.documents import Document
# LLM providers
from langchain_openai import OpenAIEmbeddings
# Text splitter
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add these constants near the top of the file with imports
MAX_CHAT_HISTORY_LENGTH = 10  # Configurable maximum chat history length to use
MAX_CONTEXT_LENGTH = 10000  # Maximum length of context to include in prompt
MAX_SAMPLE_LOG_LENGTH = 200  # Maximum length to log in samples


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

    def __init__(self, settings: Settings):
        """Initialize the RAG service.

        Args:
            settings: Application settings
        """
        self.settings = settings

        # Set up paths
        self.db_path = os.path.join(self.settings.DATA_DIR, "vectorstore")

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

        # Source weights for different document types
        self.source_weights = {
            "faq": 1.2,  # Prioritize FAQ content
            "wiki": 1.0,  # Standard weight for wiki content
        }

        logger.info("Simplified RAG service initialized")

    def load_wiki_data(self, wiki_dir: str = None) -> List[Document]:
        """Load wiki documentation from MediaWiki XML dump.

        Args:
            wiki_dir: Directory containing the MediaWiki XML dump

        Returns:
            List of Document objects
        """
        if wiki_dir is None:
            wiki_dir = os.path.join(self.settings.DATA_DIR, "wiki")

        logger.info(f"Using wiki_dir path: {wiki_dir}")

        if not os.path.exists(wiki_dir):
            logger.warning(f"Wiki directory not found: {wiki_dir}")
            return []

        # Look for the XML dump file
        xml_dump_path = os.path.join(wiki_dir, "bisq_dump.xml")
        if not os.path.exists(xml_dump_path):
            logger.warning(f"MediaWiki XML dump file not found: {xml_dump_path}")
            return []

        try:
            logger.info(f"Loading MediaWiki XML dump from: {xml_dump_path}")

            # Initialize the MWDumpLoader
            loader = MWDumpLoader(
                file_path=xml_dump_path,
                encoding="utf-8"
            )

            # Load documents
            documents = loader.load()
            logger.info(
                f"Successfully loaded {len(documents)} documents using MWDumpLoader")

            # Add metadata to documents
            for doc in documents:
                doc.metadata.update({
                    "source": xml_dump_path,
                    "title": doc.metadata.get("title", "Bisq Wiki"),
                    "type": "wiki",
                    "source_weight": self.source_weights.get("wiki", 1.0)
                })

            logger.info(f"Loaded {len(documents)} wiki documents from XML dump")
            return documents
        except Exception as e:
            logger.error(f"Error loading MediaWiki XML dump: {str(e)}", exc_info=True)
            return []

    def load_faq_data(self, faq_file: str = None) -> List[Document]:
        """Load FAQ data from JSONL file.

        Args:
            faq_file: Path to the FAQ JSONL file

        Returns:
            List of Document objects
        """
        if faq_file is None:
            faq_file = os.path.join(self.settings.DATA_DIR, "extracted_faq.jsonl")

        if not os.path.exists(faq_file):
            logger.warning(f"FAQ file not found: {faq_file}")
            return []

        documents = []
        try:
            with open(faq_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        question = data.get("question", "")
                        answer = data.get("answer", "")

                        # Combine question and answer
                        content = f"Question: {question}\nAnswer: {answer}"

                        # Create document
                        doc = Document(
                            page_content=content,
                            metadata={
                                "source": faq_file,
                                "title": question[:50] + "..." if len(
                                    question) > 50 else question,
                                "type": "faq",
                                "source_weight": self.source_weights.get("faq", 1.0)
                            }
                        )
                        documents.append(doc)
                    except json.JSONDecodeError:
                        logger.error(f"Error parsing JSON line in FAQ file: {line}")
        except Exception as e:
            logger.error(f"Error loading FAQ file {faq_file}: {str(e)}")

        logger.info(f"Loaded {len(documents)} FAQ entries")
        return documents

    def initialize_embeddings(self):
        """Initialize the OpenAI embedding model."""
        logger.info("Initializing OpenAI embeddings model...")

        if not self.settings.OPENAI_API_KEY:
            logger.warning(
                "OpenAI API key not provided. Embeddings will not work properly.")

        self.embeddings = OpenAIEmbeddings(
            api_key=self.settings.OPENAI_API_KEY,
            model="text-embedding-3-small"
        )

        logger.info("OpenAI embeddings model initialized")

    def initialize_llm(self):
        """Initialize the language model based on configuration."""
        logger.info("Initializing language model...")

        # Determine which LLM provider to use based on the configuration
        llm_provider = getattr(self.settings, "LLM_PROVIDER", "openai").lower()

        if llm_provider == "openai" and self.settings.OPENAI_API_KEY:
            self._initialize_openai_llm()
        elif llm_provider == "xai" and hasattr(self.settings,
                                               "XAI_API_KEY") and self.settings.XAI_API_KEY:
            self._initialize_xai_llm()
        else:
            logger.warning(
                f"LLM provider '{llm_provider}' not configured properly. Using OpenAI as default.")
            self._initialize_openai_llm()

        logger.info("LLM initialization complete")

    def _initialize_openai_llm(self):
        """Initialize OpenAI model."""
        model_name = getattr(self.settings, "OPENAI_MODEL", "o3-mini")
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
        model_name = getattr(self.settings, "XAI_MODEL", "grok-1")
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
            docs: List of Document objects

        Returns:
            Formatted string
        """
        formatted_chunks = []
        for doc in docs:
            content = doc.page_content
            source_type = doc.metadata.get("type", "unknown")
            title = doc.metadata.get("title", "Documentation")

            # Determine Bisq version based on source type, title and content
            if source_type == "faq":
                # All FAQ entries are for Bisq 2
                bisq_version = "Bisq 2"
            else:
                # For wiki entries, determine version based on content
                bisq_version = "General"
                if "Bisq 2" in title or "Bisq 2" in content:
                    bisq_version = "Bisq 2"
                elif "Bisq 1" in title or "Bisq 1" in content:
                    bisq_version = "Bisq 1"
                elif "<!-- BISQ VERSION:" in content:
                    version_match = re.search(r'<!-- BISQ VERSION: (.*?) -->', content)
                    if version_match:
                        bisq_version = version_match.group(1)
                        # Remove the metadata comment from the content
                        content = re.sub(
                            r'<!-- BISQ VERSION: .*? -->\n<!-- This page is classified as .*? content -->\n\n',
                            '', content)

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

            # Load wiki data from XML dump
            wiki_docs = self.load_wiki_data()

            faq_docs = self.load_faq_data()

            # Load any feedback-generated FAQs if available
            feedback_faq_file = os.path.join(self.settings.DATA_DIR,
                                             "feedback_generated_faq.jsonl")
            feedback_faqs = []
            if os.path.exists(feedback_faq_file):
                logger.info("Loading feedback-generated FAQs...")
                try:
                    with open(feedback_faq_file, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                data = json.loads(line.strip())
                                question = data.get("question", "")
                                answer = data.get("answer", "")

                                # Create a document with special metadata to indicate its source
                                doc = Document(
                                    page_content=f"Question: {question}\nAnswer: {answer}",
                                    metadata={
                                        "source": feedback_faq_file,
                                        "title": question[:50] + "..." if len(
                                            question) > 50 else question,
                                        "type": "faq",
                                        "source_weight": self.source_weights.get("faq",
                                                                                 1.0) * 1.2,
                                        # Prioritize feedback-based FAQs
                                        "feedback_generated": True
                                    }
                                )
                                feedback_faqs.append(doc)
                            except json.JSONDecodeError:
                                logger.error(
                                    f"Error parsing JSON line in feedback FAQ file: {line}")
                    logger.info(
                        f"Loaded {len(feedback_faqs)} feedback-generated FAQ entries")
                except Exception as e:
                    logger.error(
                        f"Error loading feedback-generated FAQ file {feedback_faq_file}: {str(e)}")

            # Combine all documents
            all_docs = wiki_docs + faq_docs + feedback_faqs
            logger.info(
                f"Loaded {len(wiki_docs)} wiki documents, {len(faq_docs)} FAQ documents, and {len(feedback_faqs)} feedback-generated FAQ documents")

            if not all_docs:
                logger.warning("No documents loaded. Check your data paths.")
                return False

            # Apply feedback-based improvements
            logger.info("Applying feedback-based improvements...")
            self._apply_feedback_weights()
            self._update_prompt_based_on_feedback()

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

            if vector_store_exists:
                # Load existing vector store
                logger.info("Loading existing vector store...")
                self.vectorstore = Chroma(
                    persist_directory=self.db_path,
                    embedding_function=self.embeddings
                )

                # Check if we need to refresh the vector store
                refresh_needed = False

                try:
                    # Get the current document count
                    collection_size = len(self.vectorstore.get()['ids'])
                    logger.info(f"Vector store contains {collection_size} documents")

                    # Check if the number of documents has changed
                    if collection_size != len(splits):
                        logger.info(
                            f"Document count mismatch: {collection_size} in store vs {len(splits)} loaded")
                        refresh_needed = True
                except Exception as e:
                    logger.warning(
                        f"Error checking vector store: {str(e)}. Will refresh.")
                    refresh_needed = True

                if refresh_needed:
                    logger.info("Refreshing vector store with latest data...")
                    # Delete the existing collection
                    self.vectorstore.delete_collection()
                    # Create a new collection
                    self.vectorstore = Chroma(
                        persist_directory=self.db_path,
                        embedding_function=self.embeddings
                    )
                    # Add the documents
                    self.vectorstore.add_documents(splits)
                    logger.info(
                        f"Added {len(splits)} documents to refreshed vector store")
                else:
                    logger.info("Vector store is up to date, no refresh needed")
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
        from langchain_core.prompts import ChatPromptTemplate

        # Define a function to retrieve documents
        def retrieve_and_format(question):
            logger.info(
                f"Retrieving documents for question: {redact_pii(question[:50])}...")
            docs = self.retriever.invoke(question)
            logger.info(f"Retrieved {len(docs)} documents")
            formatted_docs = self._format_docs(docs)
            logger.info(f"Formatted documents length: {len(formatted_docs)}")
            return formatted_docs

        # Create a custom prompt based on the hub template but with improvements
        logger.info("Creating custom prompt for RAG chain...")

        # Custom system template with proper sections for context, chat history, and question
        system_template = f"""You are an assistant for question-answering tasks about Bisq 2.

IMPORTANT: You are a Bisq 2 support assistant.
Pay special attention to content marked with [VERSION: Bisq 2] as it is specifically about Bisq 2.
If content is marked with [VERSION: Bisq 1], it refers to the older version of Bisq and may not be applicable to Bisq 2.
Content marked with [VERSION: Both] contains information relevant to both versions.
Content marked with [VERSION: General] is general information that may apply to both versions.

Always prioritize Bisq 2 specific information in your answers.
If you don't know the answer, just say that you don't know.
Use three sentences maximum and keep the answer concise.

Question: {{question}}

Chat History: {{chat_history}}

Context: {{context}}

Answer:"""

        # Create the prompt template
        custom_prompt = ChatPromptTemplate.from_template(system_template)
        logger.info(f"Custom RAG prompt created with {len(system_template)} characters")

        # Create a simple RAG chain
        def generate_response(question, chat_history=None):
            try:
                # Start timing response generation
                response_start_time = time.time()

                # Get context from retriever
                context = retrieve_and_format(question)

                # Truncate context if too long to save tokens
                if len(context) > MAX_CONTEXT_LENGTH:
                    logger.info(
                        f"Truncating context from {len(context)} to {MAX_CONTEXT_LENGTH} characters")
                    context = context[:MAX_CONTEXT_LENGTH]

                # Create safe sample for logging
                if os.environ.get('ENVIRONMENT', '').lower() != 'production':
                    context_sample = context[:MAX_SAMPLE_LOG_LENGTH] + "..." if len(
                        context) > MAX_SAMPLE_LOG_LENGTH else context
                    logger.info(f"Context sample: {redact_pii(context_sample)}")

                # Format chat history if provided - with safety limits
                chat_history_str = ""
                if chat_history and len(chat_history) > 0:
                    # Apply history length limits
                    if len(chat_history) > MAX_CHAT_HISTORY_LENGTH:
                        logger.info(
                            f"Limiting chat history from {len(chat_history)} to {MAX_CHAT_HISTORY_LENGTH} messages")
                        chat_history = chat_history[-MAX_CHAT_HISTORY_LENGTH:]

                    logger.info(f"Using chat history with {len(chat_history)} messages")
                    formatted_history = []

                    for msg in chat_history:
                        try:
                            # Handle both dictionary and Pydantic model formats
                            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                                # This is a Pydantic model
                                role = msg.role
                                content = msg.content
                            else:
                                # This is a dictionary
                                role = msg.get('role', '')
                                content = msg.get('content', '')

                            if role and content:
                                formatted_history.append(
                                    f"{role.capitalize()}: {content}")
                        except Exception as e:
                            logger.warning(f"Error formatting chat message: {str(e)}")

                    if formatted_history:
                        chat_history_str = "\n".join(formatted_history)

                        # Only log in non-production or at debug level
                        is_production = os.environ.get('ENVIRONMENT',
                                                   '').lower() == 'production'
                        if not is_production:
                            sample = chat_history_str[
                                     :MAX_SAMPLE_LOG_LENGTH] + "..." if len(
                                chat_history_str) > MAX_SAMPLE_LOG_LENGTH else chat_history_str
                            logger.info(f"Formatted chat history: {redact_pii(sample)}")

                # Format the prompt with the question, context and chat history
                messages = custom_prompt.format_messages(
                    context=context,
                    question=question,
                    chat_history=chat_history_str or "No previous conversation."
                )

                logger.info(f"Formatted {len(messages)} messages")

                # Get response from LLM
                logger.info("Sending request to LLM...")
                response = self.llm.invoke(messages)

                # Extract content from response
                content = ""
                if hasattr(response, "content"):
                    content = response.content
                else:
                    # Try to convert to string
                    content = str(response)

                # Log response information with privacy protection
                if content:
                    # Calculate response time
                    response_time = time.time() - response_start_time
                    logger.info(
                        f"Response generated in {response_time:.2f}s, length: {len(content)}")

                    # Log sample in non-production
                    is_production = os.environ.get('ENVIRONMENT',
                                               '').lower() == 'production'
                    if not is_production:
                        sample = content[:MAX_SAMPLE_LOG_LENGTH] + "..." if len(
                            content) > MAX_SAMPLE_LOG_LENGTH else content
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

    def _post_process_response(self, response: str) -> str:
        """Clean and format the model's response."""
        # Extract content between <answer> tags
        match = re.search(r'<answer>(.*?)</answer>', response, re.DOTALL)
        if match:
            answer = match.group(1).strip()
        else:
            answer = response.strip()

        # Remove any remaining XML-like tags
        answer = re.sub(r'<[^>]+>', '', answer)

        # Clean up whitespace
        answer = ' '.join(answer.split())

        return answer

    def query(self, question: str, chat_history: List = None) -> Dict[str, Any]:
        """Process a query and return a response with sources.

        Args:
            question: User's question
            chat_history: Chat history for context

        Returns:
            Dictionary with answer, sources, and response time
        """
        start_time = time.time()
        is_production = os.environ.get('ENVIRONMENT', '').lower() == 'production'
        debug_level = logging.INFO if not is_production else logging.DEBUG

        # Log question with PII protection
        if debug_level <= logging.INFO:
            logger.info(f"Processing query: {redact_pii(question[:50])}...")

        try:
            # Generate response using the simplified RAG chain with chat history
            logger.info("Generating response...")
            if chat_history:
                logger.info(f"Using chat history with {len(chat_history)} messages")
                # Log first and last messages for debugging purposes
                if len(chat_history) > 0 and debug_level <= logging.INFO:
                    # Handle both dictionary and Pydantic model formats
                    try:
                        if hasattr(chat_history[0], 'role') and hasattr(chat_history[0],
                                                                        'content'):
                            # This is a Pydantic model
                            first_role = chat_history[0].role
                            first_content = redact_pii(chat_history[0].content[:30]) if \
                            chat_history[0].content else ""
                            last_role = chat_history[-1].role
                            last_content = redact_pii(chat_history[-1].content[:30]) if \
                            chat_history[-1].content else ""
                        else:
                            # This is a dictionary
                            first_role = chat_history[0].get('role', 'unknown')
                            first_content = redact_pii(
                                chat_history[0].get('content', '')[:30])
                            last_role = chat_history[-1].get('role', 'unknown')
                            last_content = redact_pii(
                                chat_history[-1].get('content', '')[:30])

                        logger.info(
                            f"First message: role={first_role}, content={first_content}...")
                        logger.info(
                            f"Last message: role={last_role}, content={last_content}...")
                    except Exception as e:
                        logger.warning(f"Error logging chat history: {str(e)}")

                # Generate response using chat history
                response = self.rag_chain(question, chat_history)
            else:
                logger.info("No chat history provided")
                response = self.rag_chain(question)

            # Only log detailed response info at DEBUG level
            if debug_level <= logging.DEBUG:
                logger.debug(f"Raw response: {redact_pii(str(response)[:100])}...")
                logger.debug(f"Response type: {type(response)}")
                logger.debug(f"Response length: {len(str(response))}")
            else:
                logger.info(f"Generated response of length {len(str(response))}")

            if not response or (isinstance(response, str) and not response.strip()):
                logger.warning("Received empty response from LLM")
                response = "I apologize, but I couldn't generate a proper response. Please try asking your question again."

            # Post-process response
            clean_response = self._post_process_response(response)
            logger.info(f"Cleaned response: {clean_response}")

            # Get the retrieved documents for source information
            docs = self.retriever.invoke(question)

            # Prepare source information with deduplication
            source_types_seen = set()
            sources = []
            for doc in docs:
                source_type = doc.metadata.get("type", "unknown")
                # Skip if we've already seen this source type
                if source_type in source_types_seen:
                    continue
                source_types_seen.add(source_type)

                title = doc.metadata.get("title", "Documentation")
                content = doc.page_content[:200] + "..." if len(
                    doc.page_content) > 200 else doc.page_content

                sources.append({
                    "title": title,
                    "type": source_type,
                    "content": content
                })

            # Calculate response time
            response_time = time.time() - start_time

            # Log the query and response
            logger.info(f"Response generated successfully in {response_time:.2f}s")

            return {
                "answer": clean_response,
                "sources": sources,
                "response_time": response_time
            }
        except Exception as e:
            # Handle errors gracefully
            error_time = time.time() - start_time
            logger.error(f"Error processing query: {str(e)}", exc_info=True)

            return {
                "answer": f"I'm sorry, I encountered an error while processing your question. Please try again or rephrase your question.",
                "sources": [],
                "response_time": error_time,
                "error": str(e)
            }

    def load_feedback(self):
        """Load feedback data from month-based JSONL files.

        Loads feedback data from the standardized format: feedback_YYYY-MM.jsonl
        stored in the DATA_DIR/feedback directory.

        Returns:
            List of feedback entries as dictionaries
        """
        all_feedback = []

        # Load from the feedback directory (standard location)
        feedback_dir = os.path.join(self.settings.DATA_DIR, "feedback")
        if not os.path.exists(feedback_dir) or not os.path.isdir(feedback_dir):
            logger.info(f"Feedback directory not found: {feedback_dir}")
            return all_feedback

        try:
            # Process month-based files (current convention)
            month_pattern = re.compile(r"feedback_\d{4}-\d{2}\.jsonl$")
            month_files = [os.path.join(feedback_dir, f) for f in
                           os.listdir(feedback_dir)
                           if month_pattern.match(f)]

            # Sort files chronologically (newest first) to prioritize recent feedback
            month_files.sort(reverse=True)

            for file_path in month_files:
                try:
                    with open(file_path, "r") as f:
                        file_feedback = [json.loads(line) for line in f]
                        all_feedback.extend(file_feedback)
                        logger.info(
                            f"Loaded {len(file_feedback)} feedback entries from {os.path.basename(file_path)}")
                except Exception as e:
                    logger.error(f"Error loading feedback from {file_path}: {str(e)}")

            logger.info(f"Loaded a total of {len(all_feedback)} feedback entries")
        except Exception as e:
            logger.error(f"Error loading feedback data: {str(e)}")

        return all_feedback

    async def store_feedback(self, feedback_data):
        """Store user feedback in the feedback file."""
        # Create feedback directory if it doesn't exist
        feedback_dir = os.path.join(self.settings.DATA_DIR, 'feedback')
        os.makedirs(feedback_dir, exist_ok=True)

        # Use current month for filename following the established convention
        current_month = datetime.now().strftime("%Y-%m")
        feedback_file = os.path.join(feedback_dir, f"feedback_{current_month}.jsonl")

        # Add timestamp if not already present
        if 'timestamp' not in feedback_data:
            feedback_data['timestamp'] = datetime.now().isoformat()

        # Write to the feedback file
        with open(feedback_file, 'a') as f:
            f.write(json.dumps(feedback_data) + '\n')

        logger.info(f"Stored feedback in {os.path.basename(feedback_file)}")

        # Apply feedback weights to improve future responses
        await self.apply_feedback_weights_async(feedback_data)

        return True

    async def update_feedback_entry(self, message_id, updated_entry):
        """Update an existing feedback entry in a month-based feedback file.

        Args:
            message_id: The unique ID of the message to update
            updated_entry: The updated feedback entry

        Returns:
            Boolean indicating whether the update was successful
        """
        feedback_dir = os.path.join(self.settings.DATA_DIR, 'feedback')
        if not os.path.exists(feedback_dir) or not os.path.isdir(feedback_dir):
            logger.warning(f"Feedback directory not found: {feedback_dir}")
            return False

        # Get all month-based files in the feedback directory
        month_pattern = re.compile(r"feedback_\d{4}-\d{2}\.jsonl$")
        feedback_files = [os.path.join(feedback_dir, f) for f in
                          os.listdir(feedback_dir)
                          if month_pattern.match(f)]

        # Sort files chronologically (newest first) to prioritize recent files
        feedback_files.sort(reverse=True)

        # First check current month's file as it's most likely to contain recent entries
        current_month = datetime.now().strftime("%Y-%m")
        current_month_file = os.path.join(feedback_dir,
                                          f"feedback_{current_month}.jsonl")

        if os.path.exists(current_month_file):
            # Try to update in current month's file first
            temp_path = current_month_file + '.tmp'
            updated = False

            with open(current_month_file, 'r') as original, open(temp_path,
                                                                 'w') as temp:
                for line in original:
                    entry = json.loads(line.strip())
                    if entry.get('message_id') == message_id:
                        # Update the entry
                        temp.write(json.dumps(updated_entry) + '\n')
                        updated = True
                    else:
                        # Keep the original entry
                        temp.write(line)

            # Replace the original file if updated
            if updated:
                os.replace(temp_path, current_month_file)
                logger.info(
                    f"Updated feedback entry in current month's file {os.path.basename(current_month_file)}")
                return True
            else:
                os.remove(temp_path)
                # Continue checking other files

        # If not found in current month, check all other month-based files
        for file_path in [f for f in feedback_files if f != current_month_file]:
            temp_path = file_path + '.tmp'
            updated = False

            with open(file_path, 'r') as original, open(temp_path, 'w') as temp:
                for line in original:
                    entry = json.loads(line.strip())
                    if entry.get('message_id') == message_id:
                        # Update the entry
                        temp.write(json.dumps(updated_entry) + '\n')
                        updated = True
                    else:
                        # Keep the original entry
                        temp.write(line)

            # Replace the original file if updated
            if updated:
                os.replace(temp_path, file_path)
                logger.info(f"Updated feedback entry in {os.path.basename(file_path)}")
                return True
            else:
                os.remove(temp_path)

        # If we got here, the entry wasn't found
        logger.warning(f"Could not find feedback entry with message_id: {message_id}")
        return False

    async def analyze_feedback_text(self, explanation_text):
        """Analyze feedback explanation text to identify common issues.

        This uses simple keyword matching for now but could be enhanced with
        NLP or LLM-based analysis in the future.
        """
        detected_issues = []

        # Simple keyword-based issue detection
        if not explanation_text:
            return detected_issues

        explanation_lower = explanation_text.lower()

        # Dictionary of issues and their associated keywords
        issue_keywords = {
            "too_verbose": ["too long", "verbose", "wordy", "rambling", "shorter",
                            "concise"],
            "too_technical": ["technical", "complex", "complicated", "jargon",
                              "simpler", "simplify"],
            "not_specific": ["vague", "unclear", "generic", "specific", "details",
                             "elaborate", "more info"],
            "inaccurate": ["wrong", "incorrect", "false", "error", "mistake",
                           "accurate", "accuracy"],
            "outdated": ["outdated", "old", "not current", "update"],
            "not_helpful": ["useless", "unhelpful", "doesn't help", "didn't help",
                            "not useful"],
            "missing_context": ["context", "missing", "incomplete", "partial"],
            "confusing": ["confusing", "confused", "unclear", "hard to understand"]
        }

        # Check for each issue
        for issue, keywords in issue_keywords.items():
            for keyword in keywords:
                if keyword in explanation_lower:
                    detected_issues.append(issue)
                    break  # Found one match for this issue, no need to check other keywords

        return detected_issues

    def _update_prompt_based_on_feedback(self):
        """Dynamically adjust the system prompt based on feedback patterns."""
        feedback = self.load_feedback()

        if not feedback or len(feedback) < 20:  # Need sufficient data
            logger.info("Not enough feedback data to update prompt")
            return

        # Analyze common issues in negative feedback
        common_issues = self._analyze_feedback_issues(feedback)

        # Generate additional prompt guidance
        prompt_guidance = []

        if common_issues.get('too_verbose', 0) > 5:
            prompt_guidance.append("Keep answers very concise and to the point.")

        if common_issues.get('too_technical', 0) > 5:
            prompt_guidance.append("Use simple terms and avoid technical jargon.")

        if common_issues.get('not_specific', 0) > 5:
            prompt_guidance.append(
                "Be specific and provide concrete examples when possible.")

        # Update the system template with new guidance
        if prompt_guidance:
            self.prompt_guidance = prompt_guidance
            logger.info(f"Updated prompt guidance based on feedback: {prompt_guidance}")

    def _analyze_feedback_issues(self, feedback: List[Dict[str, Any]]) -> Dict[
        str, int]:
        """Analyze feedback to identify common issues."""
        issues = defaultdict(int)

        for item in feedback:
            if not item.get('helpful', True):
                # Check for specific issue fields
                for issue_key in ['too_verbose', 'too_technical', 'not_specific',
                                  'inaccurate']:
                    if item.get(issue_key):
                        issues[issue_key] += 1

                # Also check issue list if present
                for issue in item.get('issues', []):
                    issues[issue] += 1

        return dict(issues)

    def _generate_feedback_faqs(self):
        """Generate new FAQ entries from feedback data."""
        # Load priority improvements
        priority_file = os.path.join(self.settings.DATA_DIR,
                                     "priority_improvements.jsonl")
        faq_file = os.path.join(self.settings.DATA_DIR, "feedback_generated_faq.jsonl")

        if not os.path.exists(priority_file):
            logger.info("No priority improvements file found")
            return

        try:
            improvements = []
            with open(priority_file, 'r') as f:
                for line in f:
                    improvements.append(json.loads(line))

            if not improvements:
                logger.info("No priority improvements to process")
                return

            logger.info(f"Processing {len(improvements)} priority improvement items")

            # For simplicity, we'll just take the most recent entries for now
            # In a complete implementation, we would cluster similar questions
            recent_issues = improvements[-10:]

            new_faqs = []
            for issue in recent_issues:
                if 'original_query' in issue and 'original_response' in issue:
                    # In a real implementation, we would generate an improved answer
                    # Here we're just using the original question with a note
                    question = issue['original_query']
                    answer = f"This question was frequently asked and identified for improvement. " \
                             f"The original answer was: {issue['original_response']}"

                    new_faqs.append({
                        "question": question,
                        "answer": answer,
                        "generated_from_feedback": True,
                        "created_at": datetime.now().isoformat()
                    })

            # Save new FAQs
            with open(faq_file, 'a') as f:
                for faq in new_faqs:
                    f.write(json.dumps(faq) + '\n')

            logger.info(f"Generated {len(new_faqs)} new FAQ entries from feedback")

            # Backup the existing file with date
            os.rename(priority_file,
                      f"{priority_file}.{datetime.now().strftime('%Y%m%d')}")
            logger.info(f"Backed up and cleared priority improvements file")

        except Exception as e:
            logger.error(f"Error generating feedback FAQs: {str(e)}")

    def _update_system_template(self, additional_guidance: str = None):
        """Update the system template with additional guidance."""
        # This would be called when creating the RAG chain
        # The implementation depends on how the template is stored/used
        logger.info(f"Added system template guidance: {additional_guidance}")

    def _apply_feedback_weights(self, feedback_data=None):
        """Core implementation for applying feedback weight adjustments.

        This private method contains the actual implementation logic for analyzing
        feedback data and adjusting source weights accordingly.

        Args:
            feedback_data: Optional specific feedback entry to process.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        try:
            # If specific feedback item was provided, we could do targeted processing
            # For now we'll process all feedback for simplicity
            feedback = self.load_feedback()

            if not feedback:
                logger.info("No feedback available for weight adjustment")
                return True

            # Count positive/negative responses by source type
            source_scores = defaultdict(
                lambda: {'positive': 0, 'negative': 0, 'total': 0})

            for item in feedback:
                # Skip items without necessary data
                if 'sources_used' not in item or 'helpful' not in item:
                    continue

                helpful = item['helpful']

                for source in item['sources_used']:
                    source_type = source.get('type', 'unknown')

                    if helpful:
                        source_scores[source_type]['positive'] += 1
                    else:
                        source_scores[source_type]['negative'] += 1

                    source_scores[source_type]['total'] += 1

            # Calculate new weights
            for source_type, scores in source_scores.items():
                if scores['total'] > 10:  # Only adjust if we have enough data
                    # Calculate success rate: positive / total
                    success_rate = scores['positive'] / scores['total']

                    # Scale it between 0.5 and 1.5
                    new_weight = 0.5 + success_rate

                    # Update weight if this source type exists
                    if source_type in self.source_weights:
                        old_weight = self.source_weights[source_type]
                        # Apply gradual adjustment (70% old, 30% new)
                        self.source_weights[source_type] = (0.7 * old_weight) + (
                                0.3 * new_weight)
                        logger.info(
                            f"Adjusted weight for {source_type}: {old_weight:.2f} → {self.source_weights[source_type]:.2f}")

            logger.info(
                f"Updated source weights based on feedback: {self.source_weights}")
            return True

        except Exception as e:
            logger.error(f"Error applying feedback weights: {str(e)}", exc_info=True)
            return False

    def apply_feedback_weights(self, feedback_data=None):
        """
        Update source weights based on feedback data (synchronous version).

        This public method applies feedback-derived adjustments to the source weights,
        prioritizing more helpful content sources based on user feedback ratings.

        Args:
            feedback_data: Optional specific feedback entry to use for adjustment.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        return self._apply_feedback_weights(feedback_data)

    async def apply_feedback_weights_async(self, feedback_data=None):
        """
        Update source weights based on feedback data (asynchronous version).

        This is the async-compatible version of apply_feedback_weights.
        It properly handles the CPU-bound weight calculation in an async context.

        Args:
            feedback_data: Optional specific feedback entry to use for adjustment.
                          If None, all feedback will be processed.

        Returns:
            bool: True if weights were successfully updated
        """
        import asyncio

        # Use run_in_executor to move the CPU-bound task to a thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,  # Use default executor
            self._apply_feedback_weights,
            feedback_data
        )

    def migrate_legacy_feedback(self):
        """Migrate legacy feedback files to the current month-based convention.

        Note: This function has been used to migrate existing legacy feedback files,
        but is kept for historical purposes and in case additional legacy files are
        discovered in the future. Under normal operation, this should not be needed
        as all feedback now uses the standardized month-based naming convention.

        This function:
        1. Reads all feedback from legacy files (day-based and root feedback.jsonl)
        2. Sorts them by timestamp
        3. Writes them to appropriate month-based files
        4. Backs up original files
        5. Returns statistics about the migration

        Returns:
            Dict with migration statistics
        """
        migration_stats = {
            "total_entries_migrated": 0,
            "legacy_files_processed": 0,
            "entries_by_month": {},
            "backed_up_files": []
        }

        feedback_dir = os.path.join(self.settings.DATA_DIR, 'feedback')
        os.makedirs(feedback_dir, exist_ok=True)

        # Setup backup directory
        backup_dir = os.path.join(feedback_dir, 'legacy_backup')
        os.makedirs(backup_dir, exist_ok=True)

        # Collect entries from legacy files
        legacy_entries = []

        # 1. Check day-based files
        day_pattern = re.compile(r"feedback_\d{8}\.jsonl$")
        day_files = [os.path.join(feedback_dir, f) for f in os.listdir(feedback_dir)
                     if day_pattern.match(f)]

        for file_path in day_files:
            try:
                with open(file_path, 'r') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        legacy_entries.append(entry)

                # Back up the file
                backup_path = os.path.join(backup_dir, os.path.basename(file_path))
                shutil.copy2(file_path, backup_path)
                migration_stats["backed_up_files"].append(os.path.basename(file_path))
                migration_stats["legacy_files_processed"] += 1
            except Exception as e:
                logger.error(f"Error processing legacy file {file_path}: {str(e)}")

        # 2. Check root feedback.jsonl
        root_feedback = os.path.join(self.settings.DATA_DIR, 'feedback.jsonl')
        if os.path.exists(root_feedback):
            try:
                with open(root_feedback, 'r') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        legacy_entries.append(entry)

                # Back up the file
                backup_path = os.path.join(backup_dir, 'feedback.jsonl')
                shutil.copy2(root_feedback, backup_path)
                migration_stats["backed_up_files"].append('feedback.jsonl')
                migration_stats["legacy_files_processed"] += 1
            except Exception as e:
                logger.error(f"Error processing root feedback file: {str(e)}")

        # Sort entries by timestamp where available
        for entry in legacy_entries:
            if 'timestamp' not in entry:
                # Add a placeholder timestamp for entries without one
                entry['timestamp'] = '2025-01-01T00:00:00'

        legacy_entries.sort(key=lambda e: e.get('timestamp', ''))
        migration_stats["total_entries_migrated"] = len(legacy_entries)

        # Group by month and write to appropriate files
        for entry in legacy_entries:
            try:
                # Extract month from timestamp
                timestamp = entry.get('timestamp', '')
                month = timestamp[:7] if timestamp else '2025-01'  # YYYY-MM format

                # Ensure month is in proper format
                if not re.match(r'^\d{4}-\d{2}$', month):
                    month = '2025-01'  # Default if format is invalid

                # Update stats
                if month not in migration_stats["entries_by_month"]:
                    migration_stats["entries_by_month"][month] = 0
                migration_stats["entries_by_month"][month] += 1

                # Write to month-based file
                month_file = os.path.join(feedback_dir, f"feedback_{month}.jsonl")
                with open(month_file, 'a') as f:
                    f.write(json.dumps(entry) + '\n')
            except Exception as e:
                logger.error(f"Error writing entry to month file: {str(e)}")

        logger.info(
            f"Migration completed: {migration_stats['total_entries_migrated']} entries "
            f"from {migration_stats['legacy_files_processed']} files")

        return migration_stats

    def generate_feedback_faqs(self):
        """
        Generate new FAQs from collected feedback data.

        This public method provides access to the feedback FAQ generation functionality,
        creating new FAQ entries based on common user questions and feedback patterns.
        """
        return self._generate_feedback_faqs()

    def update_prompt_based_on_feedback(self):
        """
        Update system prompts based on feedback patterns.

        This public method enhances prompt guidance using patterns identified in
        user feedback, improving response quality by addressing common issues.
        """
        return self._update_prompt_based_on_feedback()

    async def generate_feedback_faqs_async(self):
        """
        Generate new FAQs from collected feedback data (asynchronous version).
        
        This is the async-compatible version of generate_feedback_faqs.
        It properly handles the potentially I/O-bound FAQ generation in an async context.
        
        Returns:
            The result of the FAQ generation process
        """
        import asyncio
        
        # Use run_in_executor to move the I/O-bound task to a thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,  # Use default executor
            self._generate_feedback_faqs
        )
        
    async def update_prompt_based_on_feedback_async(self):
        """
        Update system prompts based on feedback patterns (asynchronous version).
        
        This is the async-compatible version of update_prompt_based_on_feedback.
        It properly handles the potentially I/O-bound prompt update in an async context.
        
        Returns:
            The result of the prompt update process
        """
        import asyncio
        
        # Use run_in_executor to move the I/O-bound task to a thread pool
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,  # Use default executor
            self._update_prompt_based_on_feedback
        )


def get_rag_service(request: Request) -> SimplifiedRAGService:
    """Get the RAG service from the request state.

    This is a generic getter that provides access to the current RAG implementation.
    The function name is implementation-agnostic to facilitate switching implementations.
    """
    return request.app.state.rag_service
