"""
BM25 Vocabulary Manager for persistent vocabulary storage and updates.

This module provides a manager class that handles:
- Atomic file operations for vocabulary persistence
- Backup creation before updates
- File locking for concurrent access safety
- Integration hooks for FAQ/wiki updates
"""

import logging
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import portalocker

if TYPE_CHECKING:
    from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

logger = logging.getLogger(__name__)

# Global vocabulary manager instance
_vocabulary_manager: Optional["VocabularyManager"] = None
_manager_lock = threading.Lock()


class VocabularyManager:
    """Manages BM25 vocabulary persistence with atomic operations and locking."""

    def __init__(
        self,
        vocab_path: Path,
        backup_on_save: bool = False,
        max_backups: int = 5,
    ):
        """Initialize the vocabulary manager.

        Args:
            vocab_path: Path to the vocabulary JSON file
            backup_on_save: If True, create backup before overwriting
            max_backups: Maximum number of backup files to keep
        """
        self.vocab_path = Path(vocab_path)
        self.backup_on_save = backup_on_save
        self.max_backups = max_backups
        self._lock = threading.Lock()

    def save(self, tokenizer: "BM25SparseTokenizer") -> bool:
        """Save vocabulary to file atomically.

        Uses write-to-temp-then-rename pattern for atomic updates.

        Args:
            tokenizer: BM25SparseTokenizer with vocabulary to save

        Returns:
            True if save successful, False otherwise
        """
        with self._lock:
            try:
                # Create backup if file exists and backup enabled
                if self.backup_on_save and self.vocab_path.exists():
                    self._create_backup()

                # Ensure parent directory exists
                self.vocab_path.parent.mkdir(parents=True, exist_ok=True)

                # Write to temp file first, then rename (atomic)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=self.vocab_path.parent,
                    suffix=".tmp",
                    delete=False,
                ) as tmp_file:
                    vocab_json = tokenizer.export_vocabulary()
                    tmp_file.write(vocab_json)
                    tmp_path = Path(tmp_file.name)

                # Atomic rename
                tmp_path.replace(self.vocab_path)
                logger.info(
                    f"Saved vocabulary to {self.vocab_path} "
                    f"({tokenizer.vocabulary_size} tokens)"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to save vocabulary: {e}")
                # Clean up temp file if it exists
                if "tmp_path" in locals() and tmp_path.exists():
                    tmp_path.unlink()
                return False

    def load(self, tokenizer: "BM25SparseTokenizer") -> bool:
        """Load vocabulary from file into tokenizer.

        Args:
            tokenizer: BM25SparseTokenizer to load vocabulary into

        Returns:
            True if load successful, False if file doesn't exist or error
        """
        with self._lock:
            if not self.vocab_path.exists():
                logger.warning(f"Vocabulary file not found: {self.vocab_path}")
                return False

            try:
                # Use file locking for concurrent read safety
                with portalocker.Lock(self.vocab_path, "r", timeout=10) as f:
                    vocab_json = f.read()

                tokenizer.load_vocabulary(vocab_json)
                logger.info(
                    f"Loaded vocabulary from {self.vocab_path} "
                    f"({tokenizer.vocabulary_size} tokens)"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to load vocabulary: {e}")
                return False

    def update_and_save(
        self,
        tokenizer: "BM25SparseTokenizer",
        documents: List[str],
    ) -> Dict[str, Any]:
        """Update vocabulary with new documents and save.

        Args:
            tokenizer: BM25SparseTokenizer to update
            documents: List of new document texts

        Returns:
            Update statistics
        """
        with self._lock:
            # Update vocabulary
            stats = tokenizer.update_vocabulary(documents, return_stats=True) or {}

            # Save updated vocabulary
            if self.save(tokenizer):
                stats["saved"] = True
            else:
                stats["saved"] = False

            return stats

    def _create_backup(self) -> None:
        """Create a backup of the current vocabulary file."""
        if not self.vocab_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.vocab_path.with_suffix(f".json.bak.{timestamp}")

        shutil.copy2(self.vocab_path, backup_path)
        logger.debug(f"Created vocabulary backup: {backup_path}")

        # Clean up old backups
        self._cleanup_old_backups()

    def _cleanup_old_backups(self) -> None:
        """Remove old backup files beyond max_backups limit."""
        backup_pattern = f"{self.vocab_path.stem}.json.bak.*"
        backups = sorted(
            self.vocab_path.parent.glob(backup_pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        # Remove backups beyond the limit
        for backup in backups[self.max_backups :]:
            backup.unlink()
            logger.debug(f"Removed old backup: {backup}")


def get_vocabulary_manager(
    vocab_path: Optional[Path] = None,
) -> VocabularyManager:
    """Get or create the global vocabulary manager instance.

    Args:
        vocab_path: Optional path to vocabulary file. If None, uses default.

    Returns:
        VocabularyManager instance
    """
    global _vocabulary_manager

    with _manager_lock:
        if _vocabulary_manager is None:
            if vocab_path is None:
                # Use default path from settings
                from app.core.config import get_settings

                settings = get_settings()
                data_dir = Path(settings.DATA_DIR)
                vocab_path = data_dir / "bm25_vocabulary.json"

            _vocabulary_manager = VocabularyManager(
                vocab_path=vocab_path,
                backup_on_save=True,
                max_backups=5,
            )

        return _vocabulary_manager


def update_vocabulary_for_content(
    question: str,
    answer: str,
    additional_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Update vocabulary with new FAQ content.

    This function is designed to be called when new FAQs are added.

    Args:
        question: FAQ question text
        answer: FAQ answer text
        additional_content: Optional additional content (e.g., context)

    Returns:
        Update statistics
    """
    from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

    manager = get_vocabulary_manager()

    # Load existing vocabulary or create new
    tokenizer = BM25SparseTokenizer()
    manager.load(tokenizer)

    # Combine content
    documents = [f"{question} {answer}"]
    if additional_content:
        documents.append(additional_content)

    # Update and save
    return manager.update_and_save(tokenizer, documents)


def update_vocabulary_for_documents(
    documents: List[Dict[str, Any]],
    content_key: str = "content",
) -> Dict[str, Any]:
    """Update vocabulary with batch of documents.

    This function is designed to be called during wiki sync operations.

    Args:
        documents: List of document dictionaries
        content_key: Key to extract content from each document

    Returns:
        Update statistics
    """
    from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

    manager = get_vocabulary_manager()

    # Load existing vocabulary
    tokenizer = BM25SparseTokenizer()
    manager.load(tokenizer)

    # Extract content from documents
    contents = [doc.get(content_key, "") for doc in documents if doc.get(content_key)]

    # Update and save
    return manager.update_and_save(tokenizer, contents)
