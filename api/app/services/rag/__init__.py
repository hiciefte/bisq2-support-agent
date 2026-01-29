"""RAG service package for modular RAG system management."""

from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.confidence_scorer import ConfidenceScorer
from app.services.rag.conversation_state import (
    ConversationState,
    ConversationStateManager,
)
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.embeddings_provider import LiteLLMEmbeddings
from app.services.rag.empathy_detector import EmpathyDetector
from app.services.rag.evaluation import EvaluationResult, RAGEvaluator
from app.services.rag.interfaces import (
    HybridRetrieverProtocol,
    RerankerProtocol,
    ResilientRetrieverProtocol,
    RetrievedDocument,
    RetrieverProtocol,
)
from app.services.rag.llm_provider import LLMProvider
from app.services.rag.nli_validator import NLIValidator
from app.services.rag.prompt_manager import PromptManager
from app.services.rag.protocol_detector import ProtocolDetector
from app.services.rag.vectorstore_manager import VectorStoreManager
from app.services.rag.vectorstore_state_manager import VectorStoreStateManager

# Backwards compatibility alias
VersionDetector = ProtocolDetector

__all__ = [
    "AutoSendRouter",
    "ConfidenceScorer",
    "ConversationState",
    "ConversationStateManager",
    "DocumentProcessor",
    "DocumentRetriever",
    "EmpathyDetector",
    "HybridRetrieverProtocol",
    "LiteLLMEmbeddings",
    "EvaluationResult",
    "LLMProvider",
    "NLIValidator",
    "PromptManager",
    "ProtocolDetector",
    "RAGEvaluator",
    "RerankerProtocol",
    "ResilientRetrieverProtocol",
    "RetrievedDocument",
    "RetrieverProtocol",
    "VectorStoreManager",
    "VectorStoreStateManager",
    "VersionDetector",  # Deprecated alias
]
