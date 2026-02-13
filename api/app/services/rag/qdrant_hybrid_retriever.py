"""
Qdrant Hybrid Retriever with semantic + BM25 search.

This module implements hybrid search combining:
- Dense vectors (semantic similarity via configurable embeddings)
- Sparse vectors (BM25 keyword matching)

The combination provides better retrieval quality than semantic-only search,
especially for queries with specific technical terms or exact matches.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
from app.services.rag.interfaces import HybridRetrieverProtocol, RetrievedDocument
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.exceptions import ResponseHandlingException

logger = logging.getLogger(__name__)


class QdrantHybridRetriever(HybridRetrieverProtocol):
    """Hybrid retriever using Qdrant for semantic + keyword search.

    This retriever combines dense vector search (multi-provider embeddings) with
    sparse vector search (BM25) for improved retrieval quality.

    Features:
    - Configurable semantic/keyword weight balance
    - Protocol-aware filtering (bisq_easy, multisig_v1, all)
    - Automatic connection management and health checks
    - Multi-provider embeddings via LiteLLM for dense vectors

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
        bm25_tokenizer: Optional[BM25SparseTokenizer] = None,
    ):
        """Initialize the Qdrant hybrid retriever.

        Args:
            settings: Application settings with Qdrant configuration
            client: Optional pre-configured QdrantClient (for testing)
            embeddings: Optional embedding model (defaults to LiteLLM multi-provider)
            bm25_tokenizer: Optional BM25 tokenizer (defaults to loading from file)
        """
        self.settings = settings
        self.collection_name = settings.QDRANT_COLLECTION

        # Initialize client (use provided or create new)
        if client is not None:
            self._client = client
        else:
            self._client = self._create_client()

        # Initialize embeddings (use provided or create via multi-provider abstraction)
        if embeddings is not None:
            self._embeddings = embeddings
        else:
            self._embeddings = self._create_embeddings()

        # Initialize BM25 tokenizer (use provided or load from file)
        if bm25_tokenizer is not None:
            self._bm25_tokenizer = bm25_tokenizer
        else:
            self._bm25_tokenizer = self._load_bm25_tokenizer()

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
        """Create embedding model for dense vectors using multi-provider abstraction.

        Returns:
            LiteLLM embeddings model with configurable provider
        """
        from app.services.rag.embeddings_provider import LiteLLMEmbeddings

        return LiteLLMEmbeddings.from_settings(self.settings)

    def _load_bm25_tokenizer(self) -> BM25SparseTokenizer:
        """Load BM25 tokenizer from vocabulary file.

        Returns:
            BM25SparseTokenizer with loaded vocabulary, or empty tokenizer if not found
        """
        tokenizer = BM25SparseTokenizer()

        # Get vocabulary file path from settings
        data_dir = Path(self.settings.DATA_DIR)
        vocab_filename = getattr(
            self.settings, "BM25_VOCABULARY_FILE", "bm25_vocabulary.json"
        )
        vocab_path = data_dir / vocab_filename

        if vocab_path.exists():
            try:
                vocab_json = vocab_path.read_text()
                tokenizer.load_vocabulary(vocab_json)
                logger.info(
                    f"Loaded BM25 vocabulary from {vocab_path} "
                    f"({tokenizer.vocabulary_size} tokens, {tokenizer._num_documents} documents)"
                )
            except Exception as e:
                logger.warning(f"Failed to load BM25 vocabulary from {vocab_path}: {e}")
        else:
            logger.info(
                f"BM25 vocabulary file not found at {vocab_path}, "
                "using empty tokenizer (query expansion mode)"
            )

        return tokenizer

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
        return self._embeddings.embed_query(query)

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

        return rest.Filter(must=conditions)  # type: ignore[arg-type]

    def _query_points(
        self,
        *,
        using: str,
        query: Any,
        limit: int,
        query_filter: Optional[rest.Filter],
        with_payload: bool = True,
    ) -> List[Any]:
        """Compatibility wrapper for Qdrant point search across qdrant-client versions.

        qdrant-client 1.16+ exposes `query_points()`; older versions exposed `search()`.
        We normalize to a list of scored points that `_results_to_documents()` can consume.
        """
        if hasattr(self._client, "query_points"):
            try:
                resp = self._client.query_points(
                    collection_name=self.collection_name,
                    query=query,
                    using=using,
                    limit=limit,
                    query_filter=query_filter,
                    with_payload=with_payload,
                )
                if isinstance(resp, list):
                    return resp

                points = getattr(resp, "points", None)
                if points is not None:
                    try:
                        points_list = list(points or [])
                    except TypeError:
                        points_list = []

                    # Real query_points responses provide a concrete list/tuple.
                    # MagicMock objects also expose `.points` but often iterate to [].
                    # In that mock-only case, fall through to search() compatibility path.
                    if points_list or isinstance(points, (list, tuple)):
                        return points_list
            except Exception:
                logger.debug(
                    "query_points() call failed for '%s'; falling back to search()",
                    using,
                    exc_info=True,
                )

        # Backward compatibility (older clients).
        return self._client.search(  # type: ignore[attr-defined]
            collection_name=self.collection_name,
            query_vector=(using, query),
            limit=limit,
            query_filter=query_filter,
            with_payload=with_payload,
        )

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

        Uses true weighted combination of dense and sparse search scores
        rather than RRF fusion, allowing precise control over the balance.

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
            # Build filter
            qdrant_filter = self._build_filter(filter_dict)

            # Pure semantic search (no BM25)
            if keyword_weight == 0:
                query_vector = self._get_query_embedding(query)
                results = self._query_points(
                    using="dense",
                    query=query_vector,
                    limit=k,
                    query_filter=qdrant_filter,
                    with_payload=True,
                )
                return self._results_to_documents(results)

            # Pure keyword/BM25 search (no semantic)
            if semantic_weight == 0:
                sparse_indices = self._tokenize_query(query)
                sparse_values = self._get_bm25_weights(query)
                results = self._query_points(
                    using="sparse",
                    query=rest.SparseVector(
                        indices=sparse_indices, values=sparse_values
                    ),
                    limit=k,
                    query_filter=qdrant_filter,
                    with_payload=True,
                )
                return self._results_to_documents(results)

            # True weighted hybrid search
            return self._weighted_hybrid_search(
                query=query,
                k=k,
                semantic_weight=semantic_weight,
                keyword_weight=keyword_weight,
                qdrant_filter=qdrant_filter,
            )

        except Exception as e:
            logger.error(f"Qdrant hybrid search failed: {e}", exc_info=True)
            return []

    def _weighted_hybrid_search(
        self,
        query: str,
        k: int,
        semantic_weight: float,
        keyword_weight: float,
        qdrant_filter: Optional[rest.Filter],
    ) -> List[RetrievedDocument]:
        """Perform true weighted hybrid search.

        Runs dense and sparse searches separately, normalizes scores,
        applies weights, and merges results by document ID.

        Args:
            query: Search query text
            k: Maximum number of documents to retrieve
            semantic_weight: Weight for semantic scores
            keyword_weight: Weight for keyword scores
            qdrant_filter: Pre-built Qdrant filter

        Returns:
            List of RetrievedDocument objects with weighted combined scores
        """
        # Fetch more candidates than needed for better coverage
        fetch_limit = k * 3

        # Get query vectors
        query_vector = self._get_query_embedding(query)
        sparse_indices = self._tokenize_query(query)
        sparse_values = self._get_bm25_weights(query)

        # Run dense search
        dense_results = self._query_points(
            using="dense",
            query=query_vector,
            limit=fetch_limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )

        # Run sparse search
        sparse_results = self._query_points(
            using="sparse",
            query=rest.SparseVector(indices=sparse_indices, values=sparse_values),
            limit=fetch_limit,
            query_filter=qdrant_filter,
            with_payload=True,
        )

        # Normalize scores to [0, 1] range using min-max normalization
        dense_scores = self._normalize_scores(
            {str(r.id): r.score for r in dense_results}
        )
        sparse_scores = self._normalize_scores(
            {str(r.id): r.score for r in sparse_results}
        )

        # Combine payloads from both result sets
        payloads: Dict[str, Dict[str, Any]] = {}
        for r in dense_results:
            payloads[str(r.id)] = r.payload or {}
        for r in sparse_results:
            if str(r.id) not in payloads:
                payloads[str(r.id)] = r.payload or {}

        # Compute weighted combined scores
        all_ids = set(dense_scores.keys()) | set(sparse_scores.keys())
        combined_scores: Dict[str, float] = {}

        for doc_id in all_ids:
            dense_score = dense_scores.get(doc_id, 0.0)
            sparse_score = sparse_scores.get(doc_id, 0.0)
            combined_scores[doc_id] = (
                semantic_weight * dense_score + keyword_weight * sparse_score
            )

        # Sort by combined score and take top k
        sorted_ids = sorted(
            combined_scores.keys(), key=lambda x: combined_scores[x], reverse=True
        )[:k]

        # Build result documents
        documents = []
        for doc_id in sorted_ids:
            payload = payloads.get(doc_id, {})
            doc = RetrievedDocument(
                content=payload.get("content", payload.get("text", "")),
                metadata={
                    key: val
                    for key, val in payload.items()
                    if key not in ("content", "text")
                },
                score=combined_scores[doc_id],
                id=doc_id,
            )
            documents.append(doc)

        logger.info(
            f"Qdrant weighted hybrid search returned {len(documents)} documents "
            f"(semantic_weight={semantic_weight}, keyword_weight={keyword_weight})"
        )
        return documents

    def _normalize_scores(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Normalize scores to [0, 1] range using min-max normalization.

        Args:
            scores: Dictionary mapping document IDs to scores

        Returns:
            Dictionary with normalized scores
        """
        if not scores:
            return {}

        values = list(scores.values())
        min_score = min(values)
        max_score = max(values)

        # Avoid division by zero when all scores are the same
        if max_score == min_score:
            return {doc_id: 1.0 for doc_id in scores}

        return {
            doc_id: (score - min_score) / (max_score - min_score)
            for doc_id, score in scores.items()
        }

    def _results_to_documents(self, results) -> List[RetrievedDocument]:
        """Convert Qdrant search results to RetrievedDocument objects.

        Args:
            results: Qdrant search results

        Returns:
            List of RetrievedDocument objects
        """
        documents = []
        for result in results:
            payload = result.payload or {}
            doc = RetrievedDocument(
                content=payload.get("content", payload.get("text", "")),
                metadata={
                    key: val
                    for key, val in payload.items()
                    if key not in ("content", "text")
                },
                score=result.score if hasattr(result, "score") else 0.0,
                id=str(result.id) if result.id else None,
            )
            documents.append(doc)
        return documents

    def _tokenize_query(self, query: str) -> List[int]:
        """Tokenize query for sparse vector search.

        Uses BM25SparseTokenizer for vocabulary-based tokenization with
        proper IDF weighting.

        Args:
            query: Query text

        Returns:
            List of token indices
        """
        indices, _ = self._bm25_tokenizer.tokenize_query(query)
        return indices

    def _get_bm25_weights(self, query: str) -> List[float]:
        """Get BM25-style weights for query tokens.

        Uses BM25SparseTokenizer for proper IDF-based weighting from
        corpus statistics.

        Args:
            query: Query text

        Returns:
            List of token weights
        """
        _, values = self._bm25_tokenizer.tokenize_query(query)
        return values

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
                "indexed_vectors_count": info.indexed_vectors_count,
                "status": info.status,
            }
        except Exception as e:
            logger.error(f"Error getting collection info: {e}")
            return None
