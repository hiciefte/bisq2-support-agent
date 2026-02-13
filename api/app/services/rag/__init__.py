"""RAG service package for modular RAG system management.

This module exposes public RAG symbols via lazy imports to avoid
import-time side effects from heavyweight ML dependencies.
"""

from importlib import import_module
from typing import Any

_EXPORT_MAP = {
    "AutoSendRouter": ("app.services.rag.auto_send_router", "AutoSendRouter"),
    "ConfidenceScorer": ("app.services.rag.confidence_scorer", "ConfidenceScorer"),
    "ConversationState": ("app.services.rag.conversation_state", "ConversationState"),
    "ConversationStateManager": (
        "app.services.rag.conversation_state",
        "ConversationStateManager",
    ),
    "DocumentProcessor": ("app.services.rag.document_processor", "DocumentProcessor"),
    "DocumentRetriever": ("app.services.rag.document_retriever", "DocumentRetriever"),
    "EvaluationResult": ("app.services.rag.evaluation", "EvaluationResult"),
    "HybridRetrieverProtocol": (
        "app.services.rag.interfaces",
        "HybridRetrieverProtocol",
    ),
    "LiteLLMEmbeddings": (
        "app.services.rag.embeddings_provider",
        "LiteLLMEmbeddings",
    ),
    "LLMProvider": ("app.services.rag.llm_provider", "LLMProvider"),
    "NLIValidator": ("app.services.rag.nli_validator", "NLIValidator"),
    "PromptManager": ("app.services.rag.prompt_manager", "PromptManager"),
    "ProtocolDetector": ("app.services.rag.protocol_detector", "ProtocolDetector"),
    "RAGEvaluator": ("app.services.rag.evaluation", "RAGEvaluator"),
    "RerankerProtocol": ("app.services.rag.interfaces", "RerankerProtocol"),
    "ResilientRetrieverProtocol": (
        "app.services.rag.interfaces",
        "ResilientRetrieverProtocol",
    ),
    "RetrievedDocument": ("app.services.rag.interfaces", "RetrievedDocument"),
    "RetrieverProtocol": ("app.services.rag.interfaces", "RetrieverProtocol"),
}

__all__ = [*_EXPORT_MAP.keys(), "VersionDetector"]


def __getattr__(name: str) -> Any:
    """Load exported symbols lazily at first access."""
    if name == "VersionDetector":
        value = __getattr__("ProtocolDetector")
        globals()["VersionDetector"] = value
        return value

    target = _EXPORT_MAP.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = target
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
