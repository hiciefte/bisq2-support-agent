"""
FAQ Repository for file-based CRUD operations.

This module provides a clean repository interface for FAQ data persistence,
handling file I/O with proper locking and stable ID generation.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import List, Optional

import portalocker
from app.models.faq import FAQIdentifiedItem, FAQItem, FAQListResponse

logger = logging.getLogger(__name__)


class FAQRepository:
    """Repository for FAQ CRUD operations with file-based storage.

    This repository handles all file-based persistence for FAQs, including:
    - Stable content-based ID generation (SHA-256)
    - Thread-safe file operations with locking
    - CRUD operations (Create, Read, Update, Delete)
    - Pagination and filtering support

    The repository is stateless and thread-safe when used with proper locking.
    """

    def __init__(self, faq_file_path: Path, file_lock: portalocker.Lock):
        """Initialize FAQ repository.

        Args:
            faq_file_path: Path to the JSONL FAQ file
            file_lock: Portalocker lock instance for thread-safe operations
        """
        self._faq_file_path = faq_file_path
        self._file_lock = file_lock
        self._ensure_faq_file_exists()

    def _ensure_faq_file_exists(self):
        """Creates the FAQ file if it doesn't exist."""
        if not self._faq_file_path.exists():
            logger.warning(
                f"FAQ file not found at {self._faq_file_path}. Creating an empty file."
            )
            try:
                # Use 'a' mode to create if it doesn't exist without truncating
                with self._file_lock, open(self._faq_file_path, "a"):
                    pass
            except IOError as e:
                logger.error(f"Could not create FAQ file at {self._faq_file_path}: {e}")

    def _generate_stable_id(self, faq_item: FAQItem) -> str:
        """Generates a stable SHA-256 hash ID from the FAQ's content.

        Args:
            faq_item: FAQ item to generate ID for

        Returns:
            SHA-256 hash of question and answer content
        """
        content = f"{faq_item.question.strip()}:{faq_item.answer.strip()}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _read_all_faqs_with_ids(self) -> List[FAQIdentifiedItem]:
        """Reads all FAQs from the JSONL file and assigns stable IDs.

        Returns:
            List of FAQs with their stable IDs
        """
        faqs: List[FAQIdentifiedItem] = []
        try:
            with self._file_lock, open(self._faq_file_path, "r") as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            faq_item = FAQItem(**data)
                            faq_id = self._generate_stable_id(faq_item)
                            faqs.append(
                                FAQIdentifiedItem(id=faq_id, **faq_item.model_dump())
                            )
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.warning(f"Skipping malformed line in FAQ file: {e}")
            return faqs
        except FileNotFoundError:
            logger.info("FAQ file not found on read, returning empty list.")
            return []
        except (IOError, OSError, UnicodeDecodeError) as e:
            logger.exception(f"Error reading FAQ file: {e}")
            return []

    def _write_all_faqs(self, faqs: List[FAQItem]):
        """Writes a list of core FAQ data to the JSONL file, overwriting existing content.

        Args:
            faqs: List of FAQ items to write
        """
        try:
            with self._file_lock, open(self._faq_file_path, "w") as f:
                for faq in faqs:
                    f.write(json.dumps(faq.model_dump()) + "\n")
        except IOError as e:
            logger.error(f"Failed to write FAQs to disk: {e}")

    def _apply_filters(
        self,
        faqs: List[FAQIdentifiedItem],
        search_text: Optional[str] = None,
        categories: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> List[FAQIdentifiedItem]:
        """Apply filters to FAQ list.

        Args:
            faqs: List of FAQs to filter
            search_text: Text to search in questions and answers
            categories: List of categories to filter by
            source: Source type to filter by

        Returns:
            Filtered list of FAQs
        """
        filtered_faqs = faqs

        # Text search filter
        if search_text and search_text.strip():
            search_lower = search_text.lower().strip()
            filtered_faqs = [
                faq
                for faq in filtered_faqs
                if search_lower in faq.question.lower()
                or search_lower in faq.answer.lower()
            ]

        # Category filter
        if categories:
            categories_set = {c.lower() for c in categories if isinstance(c, str)}
            filtered_faqs = [
                faq
                for faq in filtered_faqs
                if faq.category and faq.category.lower() in categories_set
            ]

        # Source filter
        if source and source.strip():
            source_lower = source.strip().lower()
            filtered_faqs = [
                faq
                for faq in filtered_faqs
                if faq.source and faq.source.lower() == source_lower
            ]

        return filtered_faqs

    def get_all_faqs(self) -> List[FAQIdentifiedItem]:
        """Get all FAQs with their stable IDs.

        Returns:
            List of all FAQ items with IDs
        """
        return self._read_all_faqs_with_ids()

    def get_faqs_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        search_text: Optional[str] = None,
        categories: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> FAQListResponse:
        """Get FAQs with pagination and filtering support.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            search_text: Optional text search filter
            categories: Optional category filter
            source: Optional source filter

        Returns:
            Paginated FAQ response with metadata
        """
        import math

        # Get all FAQs
        all_faqs = self._read_all_faqs_with_ids()

        # Reverse order to show newest FAQs first (since they are appended to the file)
        all_faqs = list(reversed(all_faqs))

        # Apply filters
        filtered_faqs = self._apply_filters(all_faqs, search_text, categories, source)
        total_count = len(filtered_faqs)

        # Calculate pagination
        total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

        # Validate page number
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages

        # Calculate offset
        offset = (page - 1) * page_size

        # Get the page of FAQs
        paginated_faqs = filtered_faqs[offset : offset + page_size]

        return FAQListResponse(
            faqs=paginated_faqs,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def add_faq(self, faq_item: FAQItem) -> FAQIdentifiedItem:
        """Adds a new FAQ to the FAQ file after checking for duplicates.

        Args:
            faq_item: FAQ item to add

        Returns:
            FAQ item with generated ID

        Raises:
            ValueError: If duplicate FAQ already exists
        """
        new_id = self._generate_stable_id(faq_item)

        # Prevent duplicates
        all_faqs = self._read_all_faqs_with_ids()
        if any(faq.id == new_id for faq in all_faqs):
            raise ValueError(f"Duplicate FAQ with ID: {new_id} already exists.")

        try:
            with self._file_lock, open(self._faq_file_path, "a") as f:
                f.write(json.dumps(faq_item.model_dump()) + "\n")

            logger.info(f"Added new FAQ with ID: {new_id}")
            return FAQIdentifiedItem(id=new_id, **faq_item.model_dump())
        except IOError as e:
            logger.error(f"Failed to add FAQ: {e}")
            raise

    def update_faq(
        self, faq_id: str, updated_data: FAQItem
    ) -> Optional[FAQIdentifiedItem]:
        """Updates an existing FAQ by finding it via its stable ID.

        Args:
            faq_id: ID of FAQ to update
            updated_data: New FAQ data

        Returns:
            Updated FAQ with new ID, or None if not found
        """
        all_faqs_with_ids = self._read_all_faqs_with_ids()
        updated = False

        core_faqs_to_write: List[FAQItem] = []
        updated_faq_with_id: Optional[FAQIdentifiedItem] = None

        for faq in all_faqs_with_ids:
            if faq.id == faq_id:
                core_faqs_to_write.append(updated_data)
                new_id = self._generate_stable_id(updated_data)
                updated_faq_with_id = FAQIdentifiedItem(
                    id=new_id, **updated_data.model_dump()
                )
                updated = True
            else:
                core_faqs_to_write.append(FAQItem(**faq.model_dump(exclude={"id"})))

        if updated:
            self._write_all_faqs(core_faqs_to_write)
            logger.info(
                f"Updated FAQ. Old ID: {faq_id}, New ID: {updated_faq_with_id.id if updated_faq_with_id else 'N/A'}"
            )
            return updated_faq_with_id

        logger.warning(f"Update failed: FAQ with ID {faq_id} not found.")
        return None

    def delete_faq(self, faq_id: str) -> bool:
        """Deletes an FAQ by finding it via its stable ID.

        Args:
            faq_id: ID of FAQ to delete

        Returns:
            True if deleted, False if not found
        """
        all_faqs_with_ids = self._read_all_faqs_with_ids()

        # Keep all faqs except the one with the matching ID
        faqs_to_keep = [faq for faq in all_faqs_with_ids if faq.id != faq_id]

        if len(faqs_to_keep) < len(all_faqs_with_ids):
            # We need to strip the IDs before writing.
            core_faqs_to_write = [
                FAQItem(**faq.model_dump(exclude={"id"})) for faq in faqs_to_keep
            ]
            self._write_all_faqs(core_faqs_to_write)
            logger.info(f"Deleted FAQ with ID: {faq_id}")
            return True

        logger.warning(f"Delete failed: FAQ with ID {faq_id} not found.")
        return False
