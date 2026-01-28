"""
Qdrant Hybrid Retriever with semantic + BM25 search.

This module implements hybrid search combining:
- Dense vectors (semantic similarity via OpenAI embeddings)
- Sparse vectors (BM25 keyword matching)

The combination provides better retrieval quality than semantic-only search,
especially for queries with specific technical terms or exact matches.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.services.rag.interfaces import HybridRetrieverProtocol, RetrievedDocument
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.exceptions import ResponseHandlingException

logger = logging.getLogger(__name__)


class QdrantHybridRetriever(HybridRetrieverProtocol):
    """Hybrid retriever using Qdrant for semantic + keyword search.

    This retriever combines dense vector search (OpenAI embeddings) with
    sparse vector search (BM25) for improved retrieval quality.

    Features:
    - Configurable semantic/keyword weight balance
    - Protocol-aware filtering (bisq_easy, multisig_v1, all)
    - Automatic connection management and health checks
    - LlamaIndex integration for embeddings

    Attributes:
        settings: Application settings with Qdrant configuration
        client: QdrantClient instance
        collection_name: Name of the Qdrant collection
        embeddings: Embedding model for dense vectors
    """

    def __init__(
        self,
        settings: Settings,
        client: Optional[QdrantClient] = None,
        embeddings=None,
    ):
        """Initialize the Qdrant hybrid retriever.

        Args:
            settings: Application settings with Qdrant configuration
            client: Optional pre-configured QdrantClient (for testing)
            embeddings: Optional embedding model (defaults to OpenAI)
        """
        self.settings = settings
        self.collection_name = settings.QDRANT_COLLECTION

        # Initialize client (use provided or create new)
        if client is not None:
            self._client = client
        else:
            self._client = self._create_client()

        # Initialize embeddings (use provided or create OpenAI)
        if embeddings is not None:
            self._embeddings = embeddings
        else:
            self._embeddings = self._create_embeddings()

        self._is_healthy: Optional[bool] = None

    def _create_client(self) -> QdrantClient:
        """Create a QdrantClient instance.

        Returns:
            Configured QdrantClient
        """
        logger.info(
            f"Connecting to Qdrant at {self.settings.QDRANT_HOST}:{self.settings.QDRANT_PORT}"
        )
        return QdrantClient(
            host=self.settings.QDRANT_HOST,
            port=self.settings.QDRANT_PORT,
            prefer_grpc=False,  # Use HTTP for simpler deployment
            timeout=30,
        )

    def _create_embeddings(self):
        """Create embedding model for dense vectors.

        Returns:
            OpenAI embeddings model via LlamaIndex
        """
        try:
            from llama_index.embeddings.openai import OpenAIEmbedding

            return OpenAIEmbedding(
                model=self.settings.OPENAI_EMBEDDING_MODEL,
                api_key=self.settings.OPENAI_API_KEY,
            )
        except ImportError:
            logger.warning(
                "LlamaIndex OpenAI embeddings not available, falling back to LangChain"
            )
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(
                model=self.settings.OPENAI_EMBEDDING_MODEL,
                openai_api_key=self.settings.OPENAI_API_KEY,
            )

    @property
    def client(self) -> QdrantClient:
        """Get the Qdrant client instance."""
        return self._client

    def health_check(self) -> bool:
        """Check if Qdrant is healthy and accessible.

        Returns:
            True if Qdrant is healthy, False otherwise
        """
        try:
            # Check basic connectivity
            collections = self._client.get_collections()
            logger.debug(
                f"Qdrant health check: {len(collections.collections)} collections"
            )

            # Check if our collection exists
            collection_exists = any(
                c.name == self.collection_name for c in collections.collections
            )

            if not collection_exists:
                logger.warning(
                    f"Collection '{self.collection_name}' not found in Qdrant"
                )
                # Still healthy, just no collection yet
                self._is_healthy = True
                return True

            self._is_healthy = True
            return True

        except ResponseHandlingException as e:
            logger.error(f"Qdrant health check failed: {e}")
            self._is_healthy = False
            return False
        except Exception as e:
            logger.error(f"Qdrant health check error: {e}")
            self._is_healthy = False
            return False

    def _get_query_embedding(self, query: str) -> List[float]:
        """Get embedding vector for a query.

        Args:
            query: Query text

        Returns:
            Embedding vector as list of floats
        """
        # LlamaIndex OpenAIEmbedding
        if hasattr(self._embeddings, "get_query_embedding"):
            return self._embeddings.get_query_embedding(query)
        # LangChain OpenAIEmbeddings
        elif hasattr(self._embeddings, "embed_query"):
            return self._embeddings.embed_query(query)
        else:
            raise ValueError("Embeddings model does not support query embedding")

    def _build_filter(
        self, filter_dict: Optional[Dict[str, Any]] = None
    ) -> Optional[rest.Filter]:
        """Build Qdrant filter from filter dictionary.

        Args:
            filter_dict: Dictionary of metadata filters

        Returns:
            Qdrant Filter object or None
        """
        if not filter_dict:
            return None

        conditions = []
        for key, value in filter_dict.items():
            if isinstance(value, list):
                # Handle list values with "should" (OR)
                conditions.append(
                    rest.FieldCondition(
                        key=key,
                        match=rest.MatchAny(any=value),
                    )
                )
            else:
                conditions.append(
                    rest.FieldCondition(
                        key=key,
                        match=rest.MatchValue(value=value),
                    )
                )

        return rest.Filter(must=conditions)

    def retrieve(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievedDocument]:
        """Retrieve documents using semantic search only.

        For full hybrid search, use retrieve_hybrid() instead.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            filter_dict: Optional metadata filters

        Returns:
            List of RetrievedDocument objects
        """
        return self.retrieve_hybrid(
            query=query,
            k=k,
            semantic_weight=1.0,
            keyword_weight=0.0,
            filter_dict=filter_dict,
        )

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
            List of RetrievedDocument objects with scores populated
        """
        return self.retrieve_hybrid(
            query=query,
            k=k,
            semantic_weight=self.settings.HYBRID_SEMANTIC_WEIGHT,
            keyword_weight=self.settings.HYBRID_KEYWORD_WEIGHT,
            filter_dict=filter_dict,
        )

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
        try:
            # Get query embedding for dense search
            query_vector = self._get_query_embedding(query)

            # Build filter
            qdrant_filter = self._build_filter(filter_dict)

            # Perform hybrid search using Qdrant's query API
            # For pure semantic search (keyword_weight=0), use standard search
            if keyword_weight == 0:
                results = self._client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=k,
                    query_filter=qdrant_filter,
                    with_payload=True,
                )
            else:
                # Use hybrid search with sparse vectors
                # Qdrant supports hybrid search via prefetch + fusion
                results = self._client.query_points(
                    collection_name=self.collection_name,
                    prefetch=[
                        # Dense vector search
                        rest.Prefetch(
                            query=query_vector,
                            using="dense",
                            limit=k * 2,
                            filter=qdrant_filter,
                        ),
                        # Sparse vector search (BM25)
                        rest.Prefetch(
                            query=rest.SparseVector(
                                indices=self._tokenize_query(query),
                                values=self._get_bm25_weights(query),
                            ),
                            using="sparse",
                            limit=k * 2,
                            filter=qdrant_filter,
                        ),
                    ],
                    query=rest.FusionQuery(fusion=rest.Fusion.RRF),
                    limit=k,
                    with_payload=True,
                ).points

            # Convert to RetrievedDocument objects
            documents = []
            for result in results:
                payload = result.payload or {}
                doc = RetrievedDocument(
                    content=payload.get("content", payload.get("text", "")),
                    metadata={
                        k: v for k, v in payload.items() if k not in ("content", "text")
                    },
                    score=result.score if hasattr(result, "score") else 0.0,
                    id=str(result.id) if result.id else None,
                )
                documents.append(doc)

            logger.info(
                f"Qdrant hybrid search returned {len(documents)} documents "
                f"(semantic_weight={semantic_weight}, keyword_weight={keyword_weight})"
            )
            return documents

        except Exception as e:
            logger.error(f"Qdrant hybrid search failed: {e}", exc_info=True)
            return []

    def _tokenize_query(self, query: str) -> List[int]:
        """Tokenize query for sparse vector search.

        Simple whitespace tokenization with hashing for BM25-style search.

        Args:
            query: Query text

        Returns:
            List of token indices
        """
        tokens = query.lower().split()
        # Simple hash-based indexing (production would use proper vocabulary)
        return [hash(token) % 30000 for token in tokens]

    def _get_bm25_weights(self, query: str) -> List[float]:
        """Get BM25-style weights for query tokens.

        Simple IDF-like weighting (production would use corpus statistics).

        Args:
            query: Query text

        Returns:
            List of token weights
        """
        tokens = query.lower().split()
        # Simple uniform weighting (production would use actual IDF)
        return [1.0] * len(tokens)

    def collection_exists(self) -> bool:
        """Check if the collection exists in Qdrant.

        Returns:
            True if collection exists, False otherwise
        """
        try:
            collections = self._client.get_collections()
            return any(c.name == self.collection_name for c in collections.collections)
        except Exception as e:
            logger.error(f"Error checking collection existence: {e}")
            return False

    def get_collection_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the collection.

        Returns:
            Dictionary with collection info or None if not found
        """
        try:
            info = self._client.get_collection(self.collection_name)
            return {
                "name": self.collection_name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status,
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return None
