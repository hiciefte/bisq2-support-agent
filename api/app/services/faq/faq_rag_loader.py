"""
FAQ RAG Loader for preparing FAQ data for the RAG system.

This module handles loading FAQ data from SQLite repository and preparing them
as LangChain Document objects with appropriate metadata for the RAG system.
"""

import logging
from typing import Dict, List, Optional

from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class FAQRAGLoader:
    """Loader for preparing FAQ data as RAG documents.

    This class handles:
    - Loading FAQ data from SQLite repository
    - Creating LangChain Document objects with metadata
    - Managing source weights for RAG retrieval
    - Validating FAQ entries
    """

    def __init__(self, source_weights: Optional[Dict[str, float]] = None):
        """Initialize the FAQ RAG loader.

        Args:
            source_weights: Optional dictionary of source weights for RAG retrieval.
                           Defaults to {"faq": 1.2} if not provided.
        """
        self.source_weights = source_weights or {"faq": 1.2}

    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update source weights for FAQ content.

        Args:
            new_weights: Dictionary with updated weights
        """
        if "faq" in new_weights:
            self.source_weights["faq"] = new_weights["faq"]
            logger.info(f"Updated FAQ source weight to {self.source_weights['faq']}")

    def load_faq_data(
        self, repository: FAQRepositorySQLite, only_verified: bool = True
    ) -> List[Document]:
        """Load FAQ data from SQLite repository and prepare as RAG documents.

        Args:
            repository: SQLite FAQ repository
            only_verified: If True, only load FAQs with verified=True (default: True)

        Returns:
            List of LangChain Document objects ready for RAG ingestion
        """
        logger.info(
            f"Loading FAQs from SQLite repository (only_verified={only_verified})"
        )

        documents = []
        skipped_count = 0

        try:
            # Get all FAQs from SQLite repository
            all_faqs = repository.get_all_faqs()

            for faq in all_faqs:
                # Filter by verified status if requested
                if only_verified and not faq.verified:
                    skipped_count += 1
                    logger.debug(f"Skipping unverified FAQ: {faq.question[:50]}...")
                    continue

                # Validate required fields
                if not faq.question.strip() or not faq.answer.strip():
                    logger.warning(
                        f"Skipping FAQ entry with missing question or answer: {faq.id}"
                    )
                    continue

                # Create Document with formatted content and metadata
                # Include full question/answer/id in metadata for similar FAQ search
                doc = Document(
                    page_content=f"Question: {faq.question}\nAnswer: {faq.answer}",
                    metadata={
                        "source": "sqlite://faqs.db",
                        "title": (
                            faq.question[:50] + "..."
                            if len(faq.question) > 50
                            else faq.question
                        ),
                        "type": "faq",
                        "source_weight": self.source_weights.get("faq", 1.2),
                        "category": faq.category,
                        "protocol": faq.protocol or "all",
                        "verified": faq.verified,
                        # Additional fields for similar FAQ search
                        "id": faq.id,
                        "question": faq.question,
                        "answer": faq.answer,
                    },
                )
                documents.append(doc)

        except Exception as e:
            logger.error(f"Error loading FAQ data from SQLite: {e!s}", exc_info=True)
            return []

        if only_verified:
            logger.info(
                f"Loaded {len(documents)} verified FAQ documents from SQLite "
                f"(skipped {skipped_count} unverified)"
            )
        else:
            logger.info(f"Loaded {len(documents)} FAQ documents from SQLite")

        return documents
