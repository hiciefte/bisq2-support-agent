"""
Simplified RAG-based Bisq 2 support assistant using LangChain.
This implementation combines wiki documentation from XML dump and FAQ data
for accurate and context-aware responses, with easy switching between OpenAI and xAI.
"""

import json
import logging
import os
import re
import time
from typing import List, Dict, Any

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
            logger.info(f"Successfully loaded {len(documents)} documents using MWDumpLoader")

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
                                "title": question[:50] + "..." if len(question) > 50 else question,
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
            logger.warning("OpenAI API key not provided. Embeddings will not work properly.")

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
        elif llm_provider == "xai" and hasattr(self.settings, "XAI_API_KEY") and self.settings.XAI_API_KEY:
            self._initialize_xai_llm()
        else:
            logger.warning(f"LLM provider '{llm_provider}' not configured properly. Using OpenAI as default.")
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
        logger.info(f"OpenAI model initialized: {model_name} with max_tokens={self.settings.MAX_TOKENS}")

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
            logger.info(f"xAI model initialized: {model_name} with max_tokens={self.settings.MAX_TOKENS}")
        except ImportError:
            logger.error("langchain_xai package not installed. Please install it to use xAI models.")
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
                formatted_chunks.append(f"[SOURCE: FAQ] [VERSION: {bisq_version}]\n{content}")
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
            all_docs = wiki_docs + faq_docs
            logger.info(f"Loaded {len(wiki_docs)} wiki documents and {len(faq_docs)} FAQ documents")

            if not all_docs:
                logger.warning("No documents loaded. Check your data paths.")
                return False

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
            vector_store_exists = os.path.exists(self.db_path) and os.path.isdir(self.db_path)

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
                        logger.info(f"Document count mismatch: {collection_size} in store vs {len(splits)} loaded")
                        refresh_needed = True
                except Exception as e:
                    logger.warning(f"Error checking vector store: {str(e)}. Will refresh.")
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
                    logger.info(f"Added {len(splits)} documents to refreshed vector store")
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
            logger.error(f"Error during simplified RAG service setup: {str(e)}", exc_info=True)
            raise

    def _create_rag_chain(self):
        """Create the RAG chain using LangChain."""
        from langchain_core.prompts import ChatPromptTemplate

        # Define a function to retrieve documents
        def retrieve_and_format(question):
            logger.info(f"Retrieving documents for question: {question}")
            docs = self.retriever.invoke(question)
            logger.info(f"Retrieved {len(docs)} documents")
            formatted_docs = self._format_docs(docs)
            logger.info(f"Formatted documents length: {len(formatted_docs)}")
            return formatted_docs

        # Create a custom prompt based on the hub template but with improvements
        logger.info("Creating custom prompt for RAG chain...")
        
        # Custom system template with proper sections for context, chat history, and question
        system_template = """You are an assistant for question-answering tasks about Bisq 2.

IMPORTANT: You are a Bisq 2 support assistant.
Pay special attention to content marked with [VERSION: Bisq 2] as it is specifically about Bisq 2.
If content is marked with [VERSION: Bisq 1], it refers to the older version of Bisq and may not be applicable to Bisq 2.
Content marked with [VERSION: Both] contains information relevant to both versions.
Content marked with [VERSION: General] is general information that may apply to both versions.

Always prioritize Bisq 2 specific information in your answers.
If you don't know the answer, just say that you don't know.
Use three sentences maximum and keep the answer concise.

Question: {question}

Chat History: {chat_history}

Context: {context}

Answer:"""

        # Create the prompt template
        custom_prompt = ChatPromptTemplate.from_template(system_template)
        logger.info("Custom RAG prompt created successfully")

        # Create a simple RAG chain
        def generate_response(question, chat_history=None):
            try:
                # Get context from retriever
                context = retrieve_and_format(question)

                # Log a sample of the context to verify it's being retrieved properly
                context_sample = context[:500] + "..." if len(context) > 500 else context
                logger.info(f"Context sample: {context_sample}")
                
                # Format chat history if provided
                chat_history_str = ""
                if chat_history and len(chat_history) > 0:
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
                                formatted_history.append(f"{role.capitalize()}: {content}")
                        except Exception as e:
                            logger.warning(f"Error formatting chat message: {str(e)}")
                    
                    if formatted_history:
                        chat_history_str = "\n".join(formatted_history)
                        logger.info(f"Formatted chat history: {chat_history_str[:200]}...")

                # Format the prompt with the question, context and chat history
                messages = custom_prompt.format_messages(
                    context=context,
                    question=question,
                    chat_history=chat_history_str or "No previous conversation."
                )

                logger.info(f"Formatted {len(messages)} messages")
                logger.info(f"Prompt content sample: {str(messages[0].content)[:200]}...")

                # Get response from LLM
                logger.info("Sending request to LLM...")
                response = self.llm.invoke(messages)

                # Log response details
                logger.info(f"Response type: {type(response)}")

                # Extract content from response
                if hasattr(response, "content"):
                    content = response.content
                    logger.info(f"Content found (first 100 chars): {content[:100] if content else 'EMPTY CONTENT'}...")
                    logger.info(f"Total content length: {len(content) if content else 0}")
                    if not content or not content.strip():
                        logger.warning("Empty content received from LLM")
                        return "I apologize, but I couldn't generate a proper response based on the available information."
                    return content
                else:
                    # Try to convert to string
                    str_response = str(response)
                    logger.info(
                        f"No content attribute, using str(): {str_response[:100] if str_response else 'EMPTY STRING'}...")
                    if not str_response or not str_response.strip():
                        logger.warning("Empty string response received from LLM")
                        return "I apologize, but I couldn't generate a proper response based on the available information."
                    return str_response
            except Exception as e:
                logger.error(f"Error invoking LLM: {str(e)}", exc_info=True)
                return f"Error generating response: {str(e)}"

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
        logger.info(f"Processing query: {question}")

        try:
            # Generate response using the simplified RAG chain with chat history
            logger.info("Generating response...")
            if chat_history:
                logger.info(f"Using chat history with {len(chat_history)} messages")
                # Log first and last messages for debugging purposes
                if len(chat_history) > 0:
                    # Handle both dictionary and Pydantic model formats
                    try:
                        if hasattr(chat_history[0], 'role') and hasattr(chat_history[0], 'content'):
                            # This is a Pydantic model
                            first_role = chat_history[0].role
                            first_content = chat_history[0].content[:30] if chat_history[0].content else ""
                            last_role = chat_history[-1].role
                            last_content = chat_history[-1].content[:30] if chat_history[-1].content else ""
                        else:
                            # This is a dictionary
                            first_role = chat_history[0].get('role', 'unknown')
                            first_content = chat_history[0].get('content', '')[:30]
                            last_role = chat_history[-1].get('role', 'unknown')
                            last_content = chat_history[-1].get('content', '')[:30]
                        
                        logger.info(f"First message: role={first_role}, content={first_content}...")
                        logger.info(f"Last message: role={last_role}, content={last_content}...")
                    except Exception as e:
                        logger.warning(f"Error logging chat history: {str(e)}")
                
                    response = self.rag_chain(question, chat_history)
            else:
                logger.info("No chat history provided")
                response = self.rag_chain(question)
                
            logger.info(f"Raw response: {response}")

            # Add more detailed logging for debugging
            logger.info(f"Response type: {type(response)}")
            logger.info(f"Response length: {len(str(response))}")
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
                content = doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content

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
        """Load feedback data for response improvement."""
        feedback_file = os.path.join(self.settings.DATA_DIR, "feedback.jsonl")
        if os.path.exists(feedback_file):
            try:
                with open(feedback_file, 'r') as f:
                    return [json.loads(line) for line in f]
            except Exception as e:
                logger.error(f"Error loading feedback data: {str(e)}")
        return []


def get_rag_service(request: Request) -> SimplifiedRAGService:
    """Get the RAG service from the request state.
    
    This is a generic getter that provides access to the current RAG implementation.
    The function name is implementation-agnostic to facilitate switching implementations.
    """
    return request.app.state.rag_service
