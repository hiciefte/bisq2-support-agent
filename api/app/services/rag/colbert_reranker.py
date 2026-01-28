"""
ColBERT Reranker for improved document ranking.

This module implements late-interaction reranking using ColBERT,
which provides more accurate relevance scoring than initial retrieval.

ColBERT uses token-level similarity matching for fine-grained relevance
assessment, particularly effective for:
- Technical documentation with specific terminology
- Multi-faceted queries
- Nuanced semantic matching
"""

import logging
import threading
from typing import List, Optional

from app.core.config import Settings
from app.services.rag.interfaces import RerankerProtocol, RetrievedDocument

logger = logging.getLogger(__name__)


class ColBERTReranker(RerankerProtocol):
    """ColBERT-based reranker for improved document ranking.

    Uses RAGatouille's ColBERT implementation for late-interaction reranking.
    The model is loaded lazily on first use and cached for subsequent calls.

    Features:
    - Lazy model loading to reduce startup time
    - Thread-safe model initialization
    - Configurable top_n output
    - Graceful fallback if model loading fails

    Attributes:
        settings: Application settings with ColBERT configuration
        model_name: HuggingFace model identifier
        top_n: Default number of documents to return after reranking
    """

    def __init__(
        self,
        settings: Settings,
        model_name: Optional[str] = None,
        top_n: Optional[int] = None,
    ):
        """Initialize the ColBERT reranker.

        Args:
            settings: Application settings with ColBERT configuration
            model_name: Optional model name override (defaults to settings)
            top_n: Optional top_n override (defaults to settings)
        """
        self.settings = settings
        self.model_name = model_name or settings.COLBERT_MODEL
        self.top_n = top_n or settings.COLBERT_TOP_N

        self._model = None
        self._model_lock = threading.Lock()
        self._load_attempted = False
        self._load_error: Optional[Exception] = None

    def is_loaded(self) -> bool:
        """Check if the ColBERT model is loaded and ready.

        Returns:
            True if model is loaded and ready for inference
        """
        return self._model is not None

    def load_model(self) -> None:
        """Load the ColBERT model into memory.

        Thread-safe model loading with error handling.
        Can be called explicitly during startup for eager loading,
        or will be called lazily on first rerank() call.

        Raises:
            RuntimeError: If model loading fails
        """
        with self._model_lock:
            if self._model is not None:
                return  # Already loaded

            if self._load_attempted and self._load_error:
                raise RuntimeError(
                    f"ColBERT model loading previously failed: {self._load_error}"
                )

            self._load_attempted = True

            try:
                logger.info(f"Loading ColBERT model: {self.model_name}")

                from ragatouille import (  # type: ignore[import-not-found]
                    RAGPretrainedModel,
                )

                self._model = RAGPretrainedModel.from_pretrained(self.model_name)
                logger.info(f"ColBERT model loaded successfully: {self.model_name}")

            except ImportError as e:
                self._load_error = e
                logger.error(
                    "RAGatouille not installed. Install with: pip install ragatouille"
                )
                raise RuntimeError(f"ColBERT dependencies not available: {e}") from e

            except Exception as e:
                self._load_error = e
                logger.error(f"Failed to load ColBERT model: {e}", exc_info=True)
                raise RuntimeError(f"ColBERT model loading failed: {e}") from e

    def _ensure_model_loaded(self) -> bool:
        """Ensure model is loaded, loading lazily if needed.

        Returns:
            True if model is available, False otherwise
        """
        if self._model is not None:
            return True

        try:
            self.load_model()
            return True
        except Exception as e:
            logger.warning(f"ColBERT model not available: {e}")
            return False

    def rerank(
        self,
        query: str,
        documents: List[RetrievedDocument],
        top_n: Optional[int] = None,
    ) -> List[RetrievedDocument]:
        """Rerank documents by relevance to query using ColBERT.

        Args:
            query: Original search query
            documents: Documents from initial retrieval
            top_n: Number of top documents to return (defaults to self.top_n)

        Returns:
            Reranked list of documents (top_n or fewer)
        """
        if not documents:
            return []

        effective_top_n = top_n or self.top_n

        # If reranking is disabled, just return top_n documents
        if not self.settings.ENABLE_COLBERT_RERANK:
            logger.debug("ColBERT reranking disabled, returning original order")
            return documents[:effective_top_n]

        # Ensure model is loaded
        if not self._ensure_model_loaded():
            logger.warning(
                "ColBERT model not available, returning documents without reranking"
            )
            return documents[:effective_top_n]

        try:
            # Extract document texts for reranking
            doc_texts = [doc.content for doc in documents]

            # Rerank using ColBERT
            logger.debug(
                f"Reranking {len(documents)} documents with ColBERT (top_n={effective_top_n})"
            )

            # mypy doesn't know _ensure_model_loaded guarantees self._model is not None
            reranked_results = self._model.rerank(  # type: ignore[attr-defined]
                query=query,
                documents=doc_texts,
                k=effective_top_n,
            )

            # Map reranked results back to RetrievedDocument objects
            reranked_docs = []
            for result in reranked_results:
                # RAGatouille returns dict with 'content' and 'score'
                if isinstance(result, dict):
                    content = result.get("content", "")
                    score = result.get("score", 0.0)
                else:
                    # Handle tuple format (content, score)
                    content, score = result if len(result) == 2 else (result[0], 0.0)

                # Find matching original document
                matching_doc = None
                for doc in documents:
                    if doc.content == content:
                        matching_doc = doc
                        break

                if matching_doc:
                    # Create new doc with updated score
                    reranked_docs.append(
                        RetrievedDocument(
                            content=matching_doc.content,
                            metadata=matching_doc.metadata,
                            score=float(score),
                            id=matching_doc.id,
                        )
                    )
                else:
                    # Document not found in original list (shouldn't happen)
                    logger.warning("Reranked document not found in original list")
                    reranked_docs.append(
                        RetrievedDocument(
                            content=content,
                            metadata={},
                            score=float(score),
                        )
                    )

            logger.info(
                f"ColBERT reranking complete: {len(documents)} -> {len(reranked_docs)} documents"
            )
            return reranked_docs

        except Exception as e:
            logger.error(f"ColBERT reranking failed: {e}", exc_info=True)
            # Fallback: return original documents without reranking
            return documents[:effective_top_n]

    def rerank_with_threshold(
        self,
        query: str,
        documents: List[RetrievedDocument],
        top_n: Optional[int] = None,
        score_threshold: float = 0.0,
    ) -> List[RetrievedDocument]:
        """Rerank documents and filter by score threshold.

        Args:
            query: Original search query
            documents: Documents from initial retrieval
            top_n: Number of top documents to return
            score_threshold: Minimum score to include document

        Returns:
            Reranked and filtered list of documents
        """
        reranked = self.rerank(query, documents, top_n)

        if score_threshold > 0:
            filtered = [doc for doc in reranked if doc.score >= score_threshold]
            logger.debug(
                f"Score threshold filter: {len(reranked)} -> {len(filtered)} documents "
                f"(threshold={score_threshold})"
            )
            return filtered

        return reranked

    def get_model_info(self) -> dict:
        """Get information about the loaded model.

        Returns:
            Dictionary with model information
        """
        return {
            "model_name": self.model_name,
            "is_loaded": self.is_loaded(),
            "enabled": self.settings.ENABLE_COLBERT_RERANK,
            "top_n": self.top_n,
            "load_error": str(self._load_error) if self._load_error else None,
        }
