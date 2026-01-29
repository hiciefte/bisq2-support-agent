"""
ChromaDB Retriever Adapter for Protocol compatibility.

This module provides an adapter that wraps the existing ChromaDB/LangChain
retriever to implement the RetrieverProtocol interface.
"""

import logging
from typing import Any, Dict, List, Optional

from app.services.rag.interfaces import RetrievedDocument, RetrieverProtocol
from langchain_chroma import Chroma
from langchain_core.vectorstores import VectorStoreRetriever

logger = logging.getLogger(__name__)


class ChromaDBRetrieverAdapter(RetrieverProtocol):
    """Adapter to make ChromaDB retriever compatible with RetrieverProtocol.

    This adapter wraps the existing LangChain Chroma vectorstore and retriever
    to implement the RetrieverProtocol interface, enabling it to be used as
    a fallback in ResilientRetriever.

    Attributes:
        vectorstore: LangChain Chroma vectorstore instance
        retriever: LangChain VectorStoreRetriever instance
    """

    def __init__(
        self,
        vectorstore: Chroma,
        retriever: Optional[VectorStoreRetriever] = None,
    ):
        """Initialize the ChromaDB retriever adapter.

        Args:
            vectorstore: LangChain Chroma vectorstore instance
            retriever: Optional LangChain retriever (created from vectorstore if None)
        """
        self.vectorstore = vectorstore
        self.retriever = retriever or vectorstore.as_retriever()

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
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects
        """
        try:
            # Use similarity_search with filter if provided
            if filter_dict:
                docs = self.vectorstore.similarity_search(
                    query, k=k, filter=filter_dict
                )
            else:
                docs = self.vectorstore.similarity_search(query, k=k)

            # Convert to RetrievedDocument format
            return [
                RetrievedDocument.from_langchain_document(doc, score=0.5)
                for doc in docs
            ]

        except Exception as e:
            logger.error(f"ChromaDB retrieval failed: {e}", exc_info=True)
            return []

    def retrieve_with_scores(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve documents with similarity scores.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects with scores
        """
        try:
            # Use similarity_search_with_score
            if filter_dict:
                results = self.vectorstore.similarity_search_with_score(
                    query, k=k, filter=filter_dict
                )
            else:
                results = self.vectorstore.similarity_search_with_score(query, k=k)

            # Convert to RetrievedDocument format
            # ChromaDB returns (doc, distance) where lower distance = more similar
            documents = []
            for doc, distance in results:
                # Convert L2 distance to similarity score (0-1)
                # For normalized vectors, L2 distance ranges 0 to 2
                # similarity = 1 - (distance / 2) maps [0,2] to [1,0]
                # Clamp to [0, 1] to handle any edge cases
                similarity = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
                documents.append(
                    RetrievedDocument.from_langchain_document(doc, score=similarity)
                )

            return documents

        except Exception as e:
            logger.error(f"ChromaDB retrieval with scores failed: {e}", exc_info=True)
            return []

    def health_check(self) -> bool:
        """Check if ChromaDB is healthy and accessible.

        Returns:
            True if ChromaDB is healthy, False otherwise
        """
        try:
            # Try to get collection info
            collection = self.vectorstore._collection
            count = collection.count()
            logger.debug(f"ChromaDB health check: {count} documents")
            return True
        except Exception as e:
            logger.error(f"ChromaDB health check failed: {e}")
            return False
