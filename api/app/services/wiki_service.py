"""
Wiki service for loading and processing MediaWiki documents for the Bisq Support Assistant.

This service handles loading wiki documentation from MediaWiki XML dump files,
processing the documents, and preparing them for use in the RAG system.
"""

import logging
import os
from typing import Dict, List

from langchain_community.document_loaders import MWDumpLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WikiService:
    """Service for loading and processing wiki documentation from MediaWiki XML dumps."""

    def __init__(self, settings=None):
        """Initialize the WikiService.

        Args:
            settings: Application settings
        """
        self.settings = settings

        # Default source weight
        self.source_weights = {
            "wiki": 1.0  # Standard weight for wiki content
        }

        # Configure text splitter with default settings
        # (SimplifiedRAGService will still handle the actual splitting)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,
            chunk_overlap=300,
            separators=["\n\n", "\n", "==", "=", ". ", " ", ""],
        )

        logger.info("Wiki service initialized")

    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update source weights for wiki content.

        Args:
            new_weights: Dictionary with updated weights
        """
        if "wiki" in new_weights:
            self.source_weights["wiki"] = new_weights["wiki"]
            logger.info(f"Updated wiki source weight to {self.source_weights['wiki']}")

    def load_wiki_data(self, wiki_dir: str = None) -> List[Document]:
        """Load wiki documentation from MediaWiki XML dump.

        Args:
            wiki_dir: Directory containing the MediaWiki XML dump.
                      If None, uses the default path from settings.

        Returns:
            List of Document objects
        """
        if wiki_dir is None:
            wiki_dir = self.settings.WIKI_DIR_PATH

        logger.info(f"Using wiki_dir path: {wiki_dir}")

        if not os.path.exists(wiki_dir):
            logger.warning(f"Wiki directory not found: {wiki_dir}")
            return []

        # Look for the XML dump file
        xml_dump_path = os.path.join(wiki_dir, "bisq_dump.xml")
        if not os.path.exists(xml_dump_path):
            logger.warning(f"MediaWiki XML dump file not found: {xml_dump_path}")
            return []

        try:
            logger.info(f"Loading MediaWiki XML dump from: {xml_dump_path}")

            # Initialize the MWDumpLoader
            loader = MWDumpLoader(
                file_path=xml_dump_path,
                encoding="utf-8"
            )

            # Load documents
            documents = loader.load()
            logger.info(
                f"Successfully loaded {len(documents)} documents using MWDumpLoader")

            # Add metadata to documents
            for doc in documents:
                doc.metadata.update({
                    "source": xml_dump_path,
                    "title": doc.metadata.get("title", "Bisq Wiki"),
                    "type": "wiki",
                    "source_weight": self.source_weights.get("wiki", 1.0)
                })

            logger.info(f"Loaded {len(documents)} wiki documents from XML dump")
            return documents
        except Exception as e:
            logger.error(f"Error loading MediaWiki XML dump: {str(e)}", exc_info=True)
            return []


def get_wiki_service(request) -> WikiService:
    """Get the WikiService from FastAPI request state.

    Args:
        request: FastAPI request object

    Returns:
        WikiService instance
    """
    return request.app.state.wiki_service
