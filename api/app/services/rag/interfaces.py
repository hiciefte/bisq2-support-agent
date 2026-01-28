"""
Protocol interfaces for RAG retrieval system.

This module defines abstract interfaces (Protocols) for retrieval components,
enabling pluggable backends (ChromaDB, Qdrant, etc.) with consistent APIs.

Usage:
    class MyRetriever(RetrieverProtocol):
        def retrieve(self, query: str, k: int = 10) -> List[RetrievedDocument]:
            ...

    class MyReranker(RerankerProtocol):
        def rerank(self, query: str, documents: List[RetrievedDocument], top_n: int = 5) -> List[RetrievedDocument]:
            ...
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class RetrievedDocument:
    """Standardized document representation for retrieval results.

    This dataclass provides a consistent interface across different retrieval
    backends (ChromaDB, Qdrant, etc.) with optional scoring and metadata.

    Attributes:
        content: The document text content
        metadata: Document metadata (title, source, protocol, etc.)
        score: Relevance/similarity score (0-1, higher is better)
        id: Optional unique document identifier
    """

    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    id: Optional[str] = None

    @property
    def title(self) -> str:
        """Get document title from metadata."""
        return self.metadata.get("title", "Unknown")

    @property
    def source_type(self) -> str:
        """Get document source type (wiki, faq, etc.)."""
        return self.metadata.get("type", "unknown")

    @property
    def protocol(self) -> str:
        """Get protocol (bisq_easy, multisig_v1, all)."""
        return self.metadata.get("protocol", "all")

    def to_langchain_document(self):
        """Convert to LangChain Document format for compatibility."""
        from langchain_core.documents import Document

        return Document(page_content=self.content, metadata=self.metadata)

    @classmethod
    def from_langchain_document(cls, doc, score: float = 0.0) -> "RetrievedDocument":
        """Create from LangChain Document for compatibility."""
        return cls(
            content=doc.page_content,
            metadata=dict(doc.metadata) if doc.metadata else {},
            score=score,
        )


@runtime_checkable
class RetrieverProtocol(Protocol):
    """Protocol for document retrieval backends.

    Implementations must provide methods for:
    - Basic retrieval with optional filtering
    - Retrieval with similarity scores
    - Health checking

    Examples of implementations:
    - ChromaDBRetriever (current)
    - QdrantHybridRetriever (new)
    """

    def retrieve(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve documents matching the query.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            filter_dict: Optional metadata filters (e.g., {"protocol": "bisq_easy"})

        Returns:
            List of RetrievedDocument objects, ordered by relevance
        """
        ...

    def retrieve_with_scores(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve documents with similarity scores populated.

        Same as retrieve() but ensures score field is set on each document.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects with scores
        """
        ...

    def health_check(self) -> bool:
        """Check if the retriever backend is healthy and accessible.

        Returns:
            True if backend is healthy, False otherwise
        """
        ...


@runtime_checkable
class RerankerProtocol(Protocol):
    """Protocol for document reranking models.

    Rerankers take initial retrieval results and reorder them using
    more sophisticated scoring (e.g., ColBERT, cross-encoder).

    Examples of implementations:
    - ColBERTReranker (new)
    - CrossEncoderReranker (future)
    """

    def rerank(
        self,
        query: str,
        documents: List[RetrievedDocument],
        top_n: int = 5,
    ) -> List[RetrievedDocument]:
        """Rerank documents by relevance to query.

        Args:
            query: Original search query
            documents: Documents from initial retrieval
            top_n: Number of top documents to return after reranking

        Returns:
            Reranked list of documents (top_n or fewer)
        """
        ...

    def is_loaded(self) -> bool:
        """Check if the reranking model is loaded and ready.

        Returns:
            True if model is ready for inference
        """
        ...

    def load_model(self) -> None:
        """Load the reranking model into memory.

        Should be called during application startup for eager loading,
        or will be called lazily on first rerank() call.
        """
        ...


@runtime_checkable
class HybridRetrieverProtocol(RetrieverProtocol, Protocol):
    """Extended protocol for hybrid (semantic + keyword) retrieval.

    Hybrid retrievers combine dense vector search with sparse BM25/keyword
    search for improved retrieval quality.
    """

    def retrieve_hybrid(
        self,
        query: str,
        k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve using hybrid search (semantic + keyword).

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            semantic_weight: Weight for semantic/dense vector scores (0-1)
            keyword_weight: Weight for keyword/BM25 scores (0-1)
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects with combined scores
        """
        ...


class ResilientRetrieverProtocol(RetrieverProtocol, Protocol):
    """Protocol for retriever with fallback capability.

    Wraps a primary retriever with automatic fallback to a secondary
    retriever on failure.
    """

    @property
    def primary_retriever(self) -> RetrieverProtocol:
        """Get the primary retriever."""
        ...

    @property
    def fallback_retriever(self) -> RetrieverProtocol:
        """Get the fallback retriever."""
        ...

    @property
    def using_fallback(self) -> bool:
        """Check if currently using fallback retriever."""
        ...

    def reset_to_primary(self) -> bool:
        """Attempt to reset to primary retriever.

        Returns:
            True if successfully reset to primary, False if primary unhealthy
        """
        ...
