"""
FAQ RAG Loader for preparing FAQ data for the RAG system.

This module handles loading FAQ data from JSONL files and preparing them
as LangChain Document objects with appropriate metadata for the RAG system.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class FAQRAGLoader:
    """Loader for preparing FAQ data as RAG documents.

    This class handles:
    - Loading FAQ data from JSONL files
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

    def load_faq_data(self, faq_file_path: Path) -> List[Document]:
        """Load FAQ data from JSONL file and prepare as RAG documents.

        Args:
            faq_file_path: Path to the FAQ JSONL file

        Returns:
            List of LangChain Document objects ready for RAG ingestion
        """
        logger.info(f"Using FAQ file path: {faq_file_path}")

        if not faq_file_path.exists():
            logger.warning(f"FAQ file not found: {faq_file_path}")
            return []

        documents = []
        try:
            with open(faq_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        question = data.get("question", "")
                        answer = data.get("answer", "")
                        category = data.get("category", "General")

                        # Validate required fields
                        if not question.strip() or not answer.strip():
                            logger.warning(
                                f"Skipping FAQ entry with missing question or answer: {data}"
                            )
                            continue

                        # Create Document with formatted content and metadata
                        doc = Document(
                            page_content=f"Question: {question}\nAnswer: {answer}",
                            metadata={
                                "source": str(faq_file_path),
                                "title": (
                                    question[:50] + "..."
                                    if len(question) > 50
                                    else question
                                ),
                                "type": "faq",
                                "source_weight": self.source_weights.get("faq", 1.0),
                                "category": category,
                                "bisq_version": "General",  # FAQs apply to all versions
                            },
                        )
                        documents.append(doc)
                    except json.JSONDecodeError:
                        logger.exception(f"Error parsing JSON line in FAQ file: {line}")
            logger.info(f"Loaded {len(documents)} FAQ documents")
            return documents
        except Exception as e:
            logger.error(f"Error loading FAQ data: {e!s}", exc_info=True)
            return []
