"""
Document Processor for RAG system text splitting and chunking.

This module handles document preparation for the RAG system including:
- Text splitting with MediaWiki-aware separators
- Chunk size and overlap management
- Document splitting orchestration
"""

import logging
import os
from typing import Any, List

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

DEFAULT_SEPARATORS = [
    "\n## ",  # Markdown level 2 headers
    "\n# ",  # Markdown level 1 headers
    "\n\n",  # Paragraph breaks
    "==",  # MediaWiki section markers
    "=",  # MediaWiki single markers
    "'''",  # MediaWiki bold text
    "{{",  # MediaWiki templates
    "*",  # List markers
    "\n",  # Line breaks
    ". ",  # Sentence endings
    " ",  # Word breaks
    "",  # Character splits (last resort)
]


class _SimpleCharacterTextSplitter:
    """Minimal splitter fallback that avoids heavyweight dependencies."""

    def __init__(
        self, chunk_size: int, chunk_overlap: int, separators: List[str]
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._separators = separators

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        step = max(1, self.chunk_size - self.chunk_overlap)

        for document in documents:
            text = document.page_content or ""
            if len(text) <= self.chunk_size:
                chunks.append(document)
                continue

            for start in range(0, len(text), step):
                chunk_text = text[start : start + self.chunk_size]
                if not chunk_text:
                    continue
                chunks.append(
                    Document(page_content=chunk_text, metadata=dict(document.metadata))
                )

        return chunks


class DocumentProcessor:
    """Processor for splitting documents into chunks for RAG system.

    This class handles:
    - Configuration of text splitter with MediaWiki-specific separators
    - Document splitting with configurable chunk size and overlap
    - Preservation of document context through intelligent splitting
    """

    def __init__(
        self,
        chunk_size: int = 2000,
        chunk_overlap: int = 500,
    ):
        """Initialize the document processor.

        Args:
            chunk_size: Size of each text chunk (default: 2000)
            chunk_overlap: Overlap between chunks for context preservation (default: 500)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.text_splitter = self._create_text_splitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=DEFAULT_SEPARATORS,
        )

        logger.info(
            f"Document processor initialized with chunk_size={chunk_size}, "
            f"chunk_overlap={chunk_overlap}"
        )

    def split_documents(self, documents: List[Document]) -> List[Document]:
        """Split documents into chunks for RAG processing.

        Args:
            documents: List of LangChain Document objects to split

        Returns:
            List of split Document chunks with preserved metadata
        """
        if not documents:
            logger.warning("No documents provided for splitting")
            return []

        logger.info(f"Splitting {len(documents)} documents into chunks...")
        splits = self.text_splitter.split_documents(documents)
        logger.info(f"Created {len(splits)} document chunks")

        return splits

    def update_chunk_settings(self, chunk_size: int, chunk_overlap: int) -> None:
        """Update chunk size and overlap settings.

        Args:
            chunk_size: New chunk size
            chunk_overlap: New chunk overlap
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Recreate text splitter with new settings
        self.text_splitter = self._create_text_splitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=list(
                self.text_splitter._separators
            ),  # Reuse existing separators
        )

        logger.info(
            f"Updated chunk settings: chunk_size={chunk_size}, chunk_overlap={chunk_overlap}"
        )

    def get_chunk_settings(self) -> dict:
        """Get current chunk settings.

        Returns:
            Dictionary with chunk_size and chunk_overlap
        """
        return {
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    def _create_text_splitter(
        self, chunk_size: int, chunk_overlap: int, separators: List[str]
    ) -> Any:
        """Create langchain splitter when available, otherwise use fallback."""
        if os.getenv("BISQ_DISABLE_TRANSFORMERS", "").lower() in ("1", "true", "yes"):
            logger.info("Using fallback text splitter (BISQ_DISABLE_TRANSFORMERS set)")
            return _SimpleCharacterTextSplitter(chunk_size, chunk_overlap, separators)

        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=separators,
            )
        except Exception as e:
            logger.warning(
                f"Falling back to simple splitter due to import/init error: {e}"
            )
            return _SimpleCharacterTextSplitter(chunk_size, chunk_overlap, separators)
