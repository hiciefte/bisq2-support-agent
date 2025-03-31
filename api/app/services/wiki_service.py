"""
Wiki service for loading and processing MediaWiki documents for the Bisq Support Assistant.

This service handles loading wiki documentation from processed JSONL files,
processing the documents, and preparing them for use in the RAG system.
"""

import json
import logging
import os
import re
from typing import Dict, List

from langchain_core.documents import Document

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WikiService:
    """Service for loading and processing wiki documentation from processed JSONL files."""

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
        """Load wiki documentation from processed JSONL file.

        Args:
            wiki_dir: Directory containing the processed wiki JSONL file.
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

        # Look for the processed JSONL file
        jsonl_path = os.path.join(wiki_dir, "processed_wiki.jsonl")
        if not os.path.exists(jsonl_path):
            logger.warning(f"Processed wiki JSONL file not found: {jsonl_path}")
            return []

        try:
            logger.info(f"Loading processed wiki content from: {jsonl_path}")
            documents = []

            # Load and process each entry from the JSONL file
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    entry = json.loads(line)

                    # Extract section information from content
                    content = entry['content']
                    section = ""
                    if "==" in content:
                        # Get the first section header
                        section_match = re.search(r'==\s*(.*?)\s*==', content)
                        if section_match:
                            section = section_match.group(1).strip()

                    # Create a Document object with enhanced metadata
                    doc = Document(
                        page_content=content,
                        metadata={
                            "source": jsonl_path,
                            "title": entry['title'],
                            "category": entry['category'],
                            "type": "wiki",
                            "section": section,
                            "source_weight": self.source_weights.get("wiki", 1.0),
                            "bisq_version": "Bisq 2" if entry[
                                                            'category'] == "bisq2" else
                            "Bisq 1" if entry['category'] == "bisq1" else
                            "General"
                        }
                    )
                    documents.append(doc)

            logger.info(f"Loaded {len(documents)} wiki documents from JSONL file")
            return documents
        except Exception as e:
            logger.error(f"Error loading processed wiki content: {str(e)}",
                         exc_info=True)
            return []


def get_wiki_service(request) -> WikiService:
    """Get the WikiService from FastAPI request state.

    Args:
        request: FastAPI request object

    Returns:
        WikiService instance
    """
    return request.app.state.wiki_service
