"""
RAG-based Bisq 2 support assistant using DeepSeek model with vector search.
This implementation combines wiki documentation and FAQ data
for accurate and context-aware responses.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List, Dict, Any

import torch
from fastapi import Request
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_huggingface import HuggingFaceEmbeddings, HuggingFacePipeline
from langchain_text_splitters import RecursiveCharacterTextSplitter
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    pipeline
)

from app.core.config import Settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RAGService:
    """RAG-based service for the Bisq 2 support assistant."""

    def __init__(self, settings: Settings, model_name: str = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"):
        self.settings = settings
        self.model_name = model_name

        # Check for MPS (Metal) availability on Mac
        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
            logger.info("Using MPS (Metal) device for acceleration")
        else:
            self.device = torch.device("cpu")
            logger.info("MPS not available, falling back to CPU")

        # Initialize components
        self.embeddings = None
        self.vectorstore = None
        self.llm = None
        self.prompt = None

        # Set up persistent storage using settings
        self.db_path = self.settings.VECTOR_STORE_PATH
        Path(self.db_path).mkdir(parents=True, exist_ok=True)

        # Configure text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

        self.logger = logging.getLogger(__name__)
        self.feedback_cache = {}  # Cache for recent feedback
        self.source_weights = {
            'wiki': 1.0,
            'faq': 1.2  # Give slightly higher weight to FAQ entries
        }
        self.retriever_config = {
            'k': 3,
            'fetch_k': 12,  # Fetch 4x documents for MMR
            'lambda_mult': 0.7  # Balance between relevance and diversity
        }
        self.load_feedback()

    def load_wiki_data(self, wiki_dir: str = None) -> List[Document]:
        """Load and process wiki documentation."""
        # Log the current working directory and its contents
        logger.info(f"Current working directory: {os.getcwd()}")
        logger.info(f"Contents of the current directory: {os.listdir(os.getcwd())}")

        # Log the contents of the /app/api directory if it exists
        api_dir = "/app/api"
        if os.path.exists(api_dir):
            logger.info(f"Contents of {api_dir}: {os.listdir(api_dir)}")
        else:
            logger.info(f"Directory {api_dir} does not exist")

        # Log the contents of the /app/api/data directory if it exists
        data_dir = "/app/api/data"
        if os.path.exists(data_dir):
            logger.info(f"Contents of {data_dir}: {os.listdir(data_dir)}")
        else:
            logger.info(f"Directory {data_dir} does not exist")

        if wiki_dir is None:
            wiki_dir = os.path.join(self.settings.DATA_DIR, "wiki")
            logger.info(f"Using wiki_dir path: {wiki_dir}")

        documents = []

        for filename in os.listdir(wiki_dir):
            if filename.endswith(".txt"):
                with open(os.path.join(wiki_dir, filename), 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Create document with metadata
                    doc = Document(
                        page_content=content,
                        metadata={
                            "source": filename,
                            "type": "wiki",
                            "title": filename.replace(".txt", "").replace("_", " "),
                            "source_weight": self.source_weights['wiki']
                        }
                    )
                    documents.append(doc)

        logger.info(f"Loaded {len(documents)} wiki documents")
        return documents

    def load_faq_data(self, faq_file: str = None) -> List[Document]:
        """Load and process FAQ data."""
        if faq_file is None:
            faq_file = self.settings.FAQ_OUTPUT_PATH

        documents = []

        with open(faq_file, 'r', encoding='utf-8') as f:
            for line in f:
                faq = json.loads(line)
                # Create a document combining question and answer
                content = f"Q: {faq['question']}\nA: {faq['answer']}"
                doc = Document(
                    page_content=content,
                    metadata={
                        "source": "FAQ",
                        "type": "faq",
                        "category": faq.get("category", "General"),
                        "question": faq["question"],
                        "source_weight": self.source_weights['faq']
                    }
                )
                documents.append(doc)

        logger.info(f"Loaded {len(documents)} FAQ entries")
        return documents

    def initialize_embeddings(self):
        """Initialize the embedding model."""
        logger.info(f"Initializing embeddings model on {self.device}...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name=self.settings.EMBEDDING_MODEL,
            model_kwargs={'device': str(self.device)},
            encode_kwargs={'device': str(self.device), 'normalize_embeddings': True}
        )
        logger.info("Embeddings model initialized")

    def initialize_llm(self):
        """Initialize the language model and QA chain."""
        logger.info("Initializing language model and QA chain...")

        # Load tokenizer
        logger.info("Loading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True
        )
        tokenizer.pad_token = tokenizer.eos_token

        # Load model
        logger.info(f"Loading model to {self.device}...")
        model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16,
            trust_remote_code=True
        ).to(self.device)

        # Create pipeline with device specification
        logger.info("Creating pipeline...")
        pipe = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            device=self.device,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.6,
            top_p=0.95,
            repetition_penalty=1.2,
            pad_token_id=tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
            return_full_text=False
        )

        # Create LangChain wrapper
        logger.info("Wrapping pipeline for LangChain...")
        self.llm = HuggingFacePipeline(pipeline=pipe)

        # Create prompt template
        logger.info("Creating QA prompt template...")
        template = """You are a Bisq 2 support agent. Provide a direct answer using only the information from the context.

When asked about who you are, emphasize your quirky digital personality as Bisq's AI assistant with humor and flair.

OUTPUT FORMAT:
<answer>
[Your direct answer here, using only facts from the context. 2-3 short sentences maximum.]
</answer>

RULES:
- Stay within the <answer> tags
- Use ONLY information from the context
- NO thinking out loud
- NO explanations of your process
- NO meta-commentary
- NO markdown
- NO prefixes or qualifiers
- NO summarizing statements

Context:
{context}

Question: {question}

<answer>"""

        self.prompt = PromptTemplate(
            template=template,
            input_variables=["context", "question"]
        )

        logger.info("LLM initialization complete")

    def _format_docs(self, docs):
        """Format documents into a single string with source attribution."""
        formatted_chunks = []
        for doc in docs:
            content = doc.page_content
            source_type = doc.metadata.get("type", "unknown")
            if source_type == "faq":
                formatted_chunks.append(f"FAQ: {content}")
            elif source_type == "wiki":
                title = doc.metadata.get("title", "Documentation")
                formatted_chunks.append(f"{title}: {content}")
        return "\n\n".join(formatted_chunks)

    async def setup(self):
        """Set up the complete system."""
        logger.info("Loading documents...")
        wiki_docs = self.load_wiki_data()
        faq_docs = self.load_faq_data()
        all_docs = wiki_docs + faq_docs

        logger.info("Splitting documents into chunks...")
        splits = self.text_splitter.split_documents(all_docs)

        logger.info("Initializing embedding model...")
        self.initialize_embeddings()

        logger.info("Creating vector store...")
        self.vectorstore = Chroma(
            persist_directory=self.db_path,
            embedding_function=self.embeddings
        )

        # Only add documents if the collection is empty
        if len(self.vectorstore.get()['ids']) == 0:
            logger.info("Adding documents to vector store...")
            self.vectorstore.add_documents(splits)
        else:
            logger.info("Vector store already populated")

        logger.info("Initializing language model...")
        self.initialize_llm()

        logger.info("Setup complete")

    async def cleanup(self):
        """Clean up resources."""
        if self.vectorstore:
            self.vectorstore.persist()
        logger.info("Cleanup complete")

    def _apply_source_weights(self, docs: List[Document]) -> List[Document]:
        """Apply source-specific weights to document scores."""
        for doc in docs:
            doc.metadata['score'] = doc.metadata.get('score', 0) * doc.metadata.get('source_weight', 1.0)
        return docs

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
        """Process a query and return a response with sources."""
        start_time = time.time()

        # Retrieve relevant documents
        docs = self.vectorstore.similarity_search_with_score(
            question,
            k=self.retriever_config['k']
        )

        # Apply source weights
        weighted_docs = self._apply_source_weights([doc for doc, _ in docs])

        # Format context
        context = self._format_docs(weighted_docs)

        # Generate response
        chain = (
                {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
                | self.prompt
                | self.llm
                | StrOutputParser()
        )

        response = chain.invoke({"context": context, "question": question})

        # Post-process response
        clean_response = self._post_process_response(response)

        # Prepare source information with deduplication
        source_types_seen = set()
        sources = []
        for doc in weighted_docs:
            source_type = doc.metadata.get("type", "unknown")
            # Skip if we've already seen this source type
            if source_type in source_types_seen:
                continue

            source_types_seen.add(source_type)
            source_info = {
                "type": source_type,
                "title": doc.metadata.get("title", "Unknown"),
                "content": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            }
            if source_type == "faq":
                source_info["question"] = doc.metadata.get("question")
            sources.append(source_info)

        # Calculate response time
        response_time = time.time() - start_time

        return {
            "answer": clean_response,
            "sources": sources,
            "response_time": response_time
        }

    def _clean_response(self, response: str) -> str:
        """Clean the response text."""
        # Remove any XML-like tags
        response = re.sub(r'<[^>]+>', '', response)

        # Remove multiple newlines
        response = re.sub(r'\n\s*\n', '\n', response)

        # Remove leading/trailing whitespace
        response = response.strip()

        return response

    def load_feedback(self):
        """Load feedback data for response improvement."""
        feedback_file = os.path.join(self.settings.DATA_DIR, "feedback.jsonl")
        if os.path.exists(feedback_file):
            try:
                with open(feedback_file, 'r') as f:
                    for line in f:
                        feedback = json.loads(line)
                        self.feedback_cache[feedback['query']] = feedback
                logger.info(f"Loaded {len(self.feedback_cache)} feedback entries")
            except Exception as e:
                logger.error(f"Error loading feedback: {str(e)}")


def get_rag_service(request: Request) -> RAGService:
    """Return the RAG service instance stored in the application state."""
    return request.app.state.rag_service
