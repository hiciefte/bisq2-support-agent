"""
VectorStore Manager for RAG system change detection and rebuild management.

This module handles:
- Source file metadata tracking and persistence
- Change detection for automatic vector store rebuilds
- Runtime update triggering via callback pattern
- Build metadata management
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class VectorStoreManager:
    """Manager for vector store lifecycle and change detection.

    This class handles:
    - Tracking source file modifications (FAQs, wiki)
    - Determining when vector store rebuild is needed
    - Persisting build metadata for change detection
    - Runtime update notifications via callback pattern
    """

    def __init__(
        self,
        vectorstore_path: Path,
        data_dir: Path,
    ):
        """Initialize the VectorStore Manager.

        Args:
            vectorstore_path: Path to the vector store directory
            data_dir: Path to the data directory containing source files
        """
        self.vectorstore_path = Path(vectorstore_path)
        self.data_dir = Path(data_dir)
        self._update_callbacks: List[Callable[[str], None]] = []

        logger.info(
            f"VectorStore Manager initialized: "
            f"vectorstore_path={vectorstore_path}, data_dir={data_dir}"
        )

    def get_metadata_path(self) -> Path:
        """Get the path to the build metadata file.

        Returns:
            Path to build_metadata.json
        """
        return self.vectorstore_path / "build_metadata.json"

    def collect_source_metadata(self) -> Dict[str, Any]:
        """Collect metadata about source files for change detection.

        Returns:
            Dictionary containing timestamp and source file information
        """
        import time

        # Explicitly type sources dict to avoid mypy indexed assignment errors
        sources: Dict[str, Dict[str, Any]] = {}
        metadata = {"last_build": time.time(), "sources": sources}

        # Track wiki file
        wiki_file = self.data_dir / "wiki" / "processed_wiki.jsonl"
        if wiki_file.exists():
            st = wiki_file.stat()
            sources["wiki"] = {
                "path": str(wiki_file),
                "mtime": st.st_mtime,
                "size": st.st_size,
            }

        # Track FAQ file
        faq_file = self.data_dir / "extracted_faq.jsonl"
        if faq_file.exists():
            st = faq_file.stat()
            sources["faq"] = {
                "path": str(faq_file),
                "mtime": st.st_mtime,
                "size": st.st_size,
            }

        return metadata

    def save_metadata(self, metadata: Dict[str, Any]) -> None:
        """Save build metadata to disk.

        Args:
            metadata: Metadata dictionary to persist
        """
        metadata_path = self.get_metadata_path()
        try:
            # Ensure directory exists
            metadata_path.parent.mkdir(parents=True, exist_ok=True)

            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Saved vector store metadata to {metadata_path}")
        except OSError as e:
            logger.warning(f"Failed to save build metadata to {metadata_path}: {e}")

    def load_metadata(self) -> Dict[str, Any]:
        """Load build metadata from disk.

        Returns:
            Metadata dictionary or empty dict if not found
        """
        metadata_path = self.get_metadata_path()
        if not metadata_path.exists():
            return {}

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"Corrupted build metadata at {metadata_path}: {e}")
            return {}
        except OSError as e:
            logger.warning(f"Failed to read build metadata at {metadata_path}: {e}")
            return {}

    def should_rebuild(self) -> bool:
        """Check if vector store should be rebuilt due to source changes.

        Returns:
            True if rebuild is needed, False otherwise
        """
        # Check if metadata file exists
        metadata = self.load_metadata()
        if not metadata:
            logger.info("No build metadata found, rebuild required")
            return True

        # Check if ChromaDB files exist
        chroma_db_path = self.vectorstore_path / "chroma.sqlite3"
        if not chroma_db_path.exists():
            logger.info("ChromaDB database not found, rebuild required")
            return True

        # Get current source file metadata
        current_metadata = self.collect_source_metadata()

        # Compare each source file
        for source_name, current_info in current_metadata.get("sources", {}).items():
            old_info = metadata.get("sources", {}).get(source_name, {})

            if not old_info:
                logger.info(
                    f"New source file detected: {source_name}, rebuild required"
                )
                return True

            # Check modification time
            if current_info.get("mtime", 0) > old_info.get("mtime", 0):
                logger.info(
                    f"Source file {source_name} modified "
                    f"(old: {old_info.get('mtime')}, new: {current_info.get('mtime')}), "
                    f"rebuild required"
                )
                return True

            # Check file size as additional safety check
            if current_info.get("size", 0) != old_info.get("size", 0):
                logger.info(
                    f"Source file {source_name} size changed "
                    f"(old: {old_info.get('size')}, new: {current_info.get('size')}), "
                    f"rebuild required"
                )
                return True

        # Check for deleted sources (present in metadata, missing now)
        old_sources = set(metadata.get("sources", {}).keys())
        current_sources = set(current_metadata.get("sources", {}).keys())
        removed_sources = old_sources - current_sources
        if removed_sources:
            logger.info(
                f"Source file(s) removed: {', '.join(sorted(removed_sources))}, "
                f"rebuild required"
            )
            return True

        logger.info("No source file changes detected, using cached vector store")
        return False

    def get_rebuild_reason(self) -> Optional[str]:
        """Get a human-readable reason for rebuild decision.

        Returns:
            String describing why rebuild is needed, or None if not needed
        """
        # Check if metadata file exists
        metadata = self.load_metadata()
        if not metadata:
            return "No build metadata found"

        # Check if ChromaDB files exist
        chroma_db_path = self.vectorstore_path / "chroma.sqlite3"
        if not chroma_db_path.exists():
            return "ChromaDB database not found"

        # Get current source file metadata
        current_metadata = self.collect_source_metadata()

        # Compare each source file
        for source_name, current_info in current_metadata.get("sources", {}).items():
            old_info = metadata.get("sources", {}).get(source_name, {})

            if not old_info:
                return f"New source file detected: {source_name}"

            # Check modification time
            if current_info.get("mtime", 0) > old_info.get("mtime", 0):
                return f"Source file {source_name} modified"

            # Check file size
            if current_info.get("size", 0) != old_info.get("size", 0):
                return f"Source file {source_name} size changed"

        # Check for deleted sources (present in metadata, missing now)
        old_sources = set(metadata.get("sources", {}).keys())
        current_sources = set(current_metadata.get("sources", {}).keys())
        removed_sources = old_sources - current_sources
        if removed_sources:
            return f"Source file(s) removed: {', '.join(sorted(removed_sources))}"

        return None

    def register_update_callback(self, callback: Callable[[str], None]) -> None:
        """Register a callback to be called when updates are triggered.

        Args:
            callback: Function to call with source name when update triggered
        """
        if callback not in self._update_callbacks:
            self._update_callbacks.append(callback)
            callback_name = getattr(callback, "__name__", repr(callback))
            logger.debug(f"Registered update callback: {callback_name}")

    def unregister_update_callback(self, callback: Callable[[str], None]) -> None:
        """Unregister a previously registered callback.

        Args:
            callback: Function to unregister
        """
        if callback in self._update_callbacks:
            self._update_callbacks.remove(callback)
            callback_name = getattr(callback, "__name__", repr(callback))
            logger.debug(f"Unregistered update callback: {callback_name}")

    def trigger_update(self, source_name: str) -> None:
        """Trigger update callbacks for a specific source.

        This should be called when source files are updated at runtime
        (e.g., new FAQs extracted, wiki updated).

        Args:
            source_name: Name of the source that was updated ("faq" or "wiki")
        """
        logger.info(f"Triggering update for source: {source_name}")

        # Snapshot callbacks to avoid mutation during iteration
        for callback in tuple(self._update_callbacks):
            try:
                callback(source_name)
            except Exception as e:
                cb_name = getattr(callback, "__name__", repr(callback))
                logger.error(
                    f"Error calling update callback {cb_name}: {e}",
                    exc_info=True,
                )
