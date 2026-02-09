"""
FAQ service for loading and managing FAQ data for the Bisq Support Assistant.

This service handles loading FAQ documentation from SQLite database,
processing the documents, and preparing them for use in the RAG system.
"""

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.models.faq import FAQIdentifiedItem, FAQItem, FAQListResponse
from app.services.faq.faq_rag_loader import FAQRAGLoader
from app.services.faq.faq_repository_sqlite import FAQRepositorySQLite
from fastapi import Request
from langchain_core.documents import Document

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FAQService:
    """Service for managing FAQs using SQLite storage with JSONL for RAG integration."""

    _instance: Optional["FAQService"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super(FAQService, cls).__new__(cls)
        return cls._instance

    def __init__(self, settings: Any):
        """Initialize the FAQ service."""
        if not hasattr(self, "initialized"):
            self.settings = settings
            data_dir = Path(self.settings.DATA_DIR)

            # Ensure data directory exists before creating data files.
            data_dir.mkdir(parents=True, exist_ok=True)

            # Initialize SQLite FAQ repository for CRUD operations
            logger.info("Using SQLite FAQ storage")
            db_path = Path(settings.FAQ_DB_PATH)
            self.repository = FAQRepositorySQLite(str(db_path))

            # Initialize FAQ RAG loader for document preparation
            self.rag_loader = FAQRAGLoader(source_weights={"faq": 1.2})

            # Callback mechanism for vector store updates
            self._update_callbacks: List[
                Callable[[bool, Optional[str], Optional[str], Optional[Dict]], None]
            ] = []

            self.initialized = True
            logger.info("FAQService initialized with SQLite storage backend.")

    def register_update_callback(
        self,
        callback: Callable[[bool, Optional[str], Optional[str], Optional[Dict]], None],
    ) -> None:
        """Register a callback to be called when FAQs are updated.

        Args:
            callback: Function to call when FAQs are updated with signature:
                     callback(rebuild: bool, operation: str, faq_id: str, metadata: Dict)
        """
        if callback not in self._update_callbacks:
            self._update_callbacks.append(callback)
            callback_name = getattr(callback, "__name__", repr(callback))
            logger.debug(f"Registered FAQ update callback: {callback_name}")

    def unregister_update_callback(
        self,
        callback: Callable[[bool, Optional[str], Optional[str], Optional[Dict]], None],
    ) -> None:
        """Unregister a previously registered FAQ update callback.

        Args:
            callback: Function to unregister
        """
        if callback in self._update_callbacks:
            self._update_callbacks.remove(callback)
            callback_name = getattr(callback, "__name__", repr(callback))
            logger.debug(f"Unregistered FAQ update callback: {callback_name}")

    def _trigger_update(
        self,
        rebuild: bool = False,
        operation: Optional[str] = None,
        faq_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Trigger all registered update callbacks when FAQs are modified.

        Args:
            rebuild: Whether to trigger immediate rebuild (False = mark for manual rebuild)
            operation: Type of operation (add, update, delete)
            faq_id: ID of the FAQ that changed
            metadata: Additional context about the change
        """
        logger.info(
            f"FAQ data updated, triggering update callbacks (rebuild={rebuild}, operation={operation})..."
        )
        # Snapshot callbacks to avoid mutation during iteration
        for callback in tuple(self._update_callbacks):
            try:
                callback(rebuild, operation, faq_id, metadata)
            except Exception as e:
                callback_name = getattr(callback, "__name__", repr(callback))
                logger.error(
                    f"Error calling FAQ update callback {callback_name}: {e}",
                    exc_info=True,
                )

    # CRUD operations - delegated to repository
    def get_all_faqs(self) -> List[FAQIdentifiedItem]:
        """Get all FAQs with their stable IDs."""
        return self.repository.get_all_faqs()

    def get_filtered_faqs(
        self,
        search_text: Optional[str] = None,
        categories: Optional[List[str]] = None,
        source: Optional[str] = None,
        verified: Optional[bool] = None,
        protocol: Optional[str] = None,
        verified_from: Optional[str] = None,
        verified_to: Optional[str] = None,
    ) -> List[FAQIdentifiedItem]:
        """Get all FAQs matching the specified filters without pagination.

        This method is designed for aggregation operations (e.g., statistics)
        where all matching FAQs are needed without pagination limits.

        Args:
            search_text: Optional text search filter
            categories: Optional category filter
            source: Optional source filter
            verified: Optional verification status filter
            protocol: Optional protocol filter (multisig_v1, bisq_easy, musig, all)
            verified_from: ISO 8601 date string for start of verified_at range
            verified_to: ISO 8601 date string for end of verified_at range

        Returns:
            List of all FAQs matching the specified filters
        """
        from datetime import datetime, timezone

        # Parse date strings to datetime objects if provided
        verified_from_dt = None
        if verified_from:
            try:
                verified_from_dt = datetime.fromisoformat(
                    verified_from.replace("Z", "+00:00")
                )
                if verified_from_dt.tzinfo is None:
                    verified_from_dt = verified_from_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(f"Invalid verified_from date format: {verified_from}")

        verified_to_dt = None
        if verified_to:
            try:
                verified_to_dt = datetime.fromisoformat(
                    verified_to.replace("Z", "+00:00")
                )
                if verified_to_dt.tzinfo is None:
                    verified_to_dt = verified_to_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(f"Invalid verified_to date format: {verified_to}")

        return self.repository.get_filtered_faqs(
            search_text=search_text,
            categories=categories,
            source=source,
            verified=verified,
            protocol=protocol,
            verified_from=verified_from_dt,
            verified_to=verified_to_dt,
        )

    def get_faqs_paginated(
        self,
        page: int = 1,
        page_size: int = 10,
        search_text: Optional[str] = None,
        categories: Optional[List[str]] = None,
        source: Optional[str] = None,
        verified: Optional[bool] = None,
        protocol: Optional[str] = None,
        verified_from: Optional[str] = None,
        verified_to: Optional[str] = None,
    ) -> FAQListResponse:
        """Get FAQs with pagination and filtering support.

        IMPORTANT: Multi-category filtering limitation
        -------------------------------------------
        The SQLite backend currently supports only a SINGLE category filter.
        If the categories list contains multiple values, only the FIRST category
        will be used, and the rest will be silently ignored.

        This is a known limitation for backward API compatibility. If multi-category
        filtering is required, the repository layer needs to be enhanced to support
        IN (...) predicates.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            search_text: Text search across questions and answers
            categories: Category filters (ONLY first category used if multiple provided)
            source: Source filter (e.g., "Manual", "Extracted")
            verified: Verification status filter
            protocol: Protocol filter (multisig_v1, bisq_easy, musig, all)
            verified_from: ISO 8601 date string for start of verified_at range
            verified_to: ISO 8601 date string for end of verified_at range

        Returns:
            FAQ list response with pagination metadata
        """
        from datetime import datetime, timezone

        # Parse date strings to datetime objects if provided
        # IMPORTANT: Convert to timezone-aware datetime (UTC) for comparison with FAQ timestamps
        verified_from_dt = None
        verified_to_dt = None

        if verified_from:
            try:
                # Parse the date string
                parsed_date = datetime.fromisoformat(
                    verified_from.replace("Z", "+00:00")
                )
                # If timezone-naive (no timezone info), assume UTC
                if parsed_date.tzinfo is None:
                    verified_from_dt = parsed_date.replace(tzinfo=timezone.utc)
                else:
                    verified_from_dt = parsed_date
            except ValueError:
                logger.warning(f"Invalid verified_from date format: {verified_from}")

        if verified_to:
            try:
                # Parse the date string
                parsed_date = datetime.fromisoformat(verified_to.replace("Z", "+00:00"))
                # If timezone-naive (no timezone info), assume UTC
                # For end date, set time to end of day (23:59:59.999999)
                if parsed_date.tzinfo is None:
                    verified_to_dt = parsed_date.replace(
                        hour=23,
                        minute=59,
                        second=59,
                        microsecond=999999,
                        tzinfo=timezone.utc,
                    )
                else:
                    verified_to_dt = parsed_date
            except ValueError:
                logger.warning(f"Invalid verified_to date format: {verified_to}")

        # Get response from repository (returns Dict)
        # Note: Repository accepts single category, not list
        # If categories list provided, use first category (for backward compatibility)
        category = categories[0] if categories else None

        result = self.repository.get_faqs_paginated(
            page=page,
            page_size=page_size,
            category=category,
            verified=verified,
            source=source,
            search_text=search_text,
            protocol=protocol,
            verified_from=verified_from_dt,
            verified_to=verified_to_dt,
        )

        # Wrap in FAQListResponse for API compatibility
        # Map repository dict keys to FAQListResponse field names
        # Ensure total_pages is at least 1 (FAQListResponse validation requires >= 1)
        total_pages = result["total_pages"] if result["total_pages"] > 0 else 1

        return FAQListResponse(
            faqs=result["items"],
            total_count=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=total_pages,
        )

    def add_faq(self, faq_item: FAQItem) -> FAQIdentifiedItem:
        """Adds a new FAQ to the FAQ file after checking for duplicates."""
        result = self.repository.add_faq(faq_item)

        # Only mark for rebuild if FAQ is verified
        if result and result.verified:
            self._trigger_update(
                rebuild=False,
                operation="add",
                faq_id=result.id,
                metadata={"question": result.question[:50]},
            )

        return result

    def update_faq(
        self, faq_id: str, updated_data: FAQItem, rebuild_vectorstore: bool = True
    ) -> Optional[FAQIdentifiedItem]:
        """Updates an existing FAQ by finding it via its stable ID.

        Args:
            faq_id: The FAQ ID to update
            updated_data: The new FAQ data
            rebuild_vectorstore: Whether to rebuild the vector store (default: True).
                               Set to False for metadata-only updates (verified, source, category)
                               that don't affect embeddings.
        """
        # Get current FAQ to check verification status before update
        current_faq = next(
            (faq for faq in self.repository.get_all_faqs() if faq.id == faq_id), None
        )

        result = self.repository.update_faq(faq_id, updated_data)

        # Only mark for rebuild if:
        # 1. Update succeeded AND rebuild_vectorstore=True
        # 2. AND either FAQ was verified OR is becoming verified
        if result is not None and rebuild_vectorstore:
            was_verified = current_faq.verified if current_faq else False
            is_verified = result.verified

            # Mark for rebuild if FAQ was verified (needs update) or is becoming verified (needs addition)
            if was_verified or is_verified:
                logger.info(
                    f"Marking FAQ {faq_id} for rebuild: "
                    f"was_verified={was_verified}, is_verified={is_verified}"
                )
                self._trigger_update(
                    rebuild=False,
                    operation="update",
                    faq_id=faq_id,
                    metadata={"question": result.question[:50]},
                )
            else:
                logger.debug(
                    f"Skipping vector store rebuild for unverified FAQ {faq_id}"
                )

        return result

    def delete_faq(self, faq_id: str) -> bool:
        """Deletes an FAQ by finding it via its stable ID.

        Only marks for rebuild if the deleted FAQ was verified,
        as unverified FAQs are not included in the vector store.
        """
        # Get FAQ before deletion to check verification status
        faq = next(
            (faq for faq in self.repository.get_all_faqs() if faq.id == faq_id), None
        )

        result = self.repository.delete_faq(faq_id)

        # Only mark for rebuild if deletion succeeded AND FAQ was verified
        if result and faq and faq.verified:
            logger.info(f"Marking FAQ {faq_id} for rebuild after deletion")
            self._trigger_update(
                rebuild=False,
                operation="delete",
                faq_id=faq_id,
                metadata={"question": faq.question[:50]},
            )
        elif result and faq and not faq.verified:
            logger.debug(
                f"Skipping vector store rebuild for unverified FAQ {faq_id} deletion"
            )

        return result

    def bulk_delete_faqs(self, faq_ids: List[str]) -> tuple[int, int, List[str]]:
        """
        Delete multiple FAQs in a single operation with one vector store rebuild.

        Only marks for rebuild if at least one deleted FAQ was verified.

        Args:
            faq_ids: List of FAQ IDs to delete

        Returns:
            Tuple of (success_count, failed_count, failed_ids)
        """
        # Get all FAQs once to check verification status
        all_faqs = {faq.id: faq for faq in self.repository.get_all_faqs()}

        success_count = 0
        failed_ids = []
        deleted_verified_count = 0

        for faq_id in faq_ids:
            try:
                # Check if FAQ was verified before deletion
                faq = all_faqs.get(faq_id)
                was_verified = faq.verified if faq else False

                result = self.repository.delete_faq(faq_id)
                if result:
                    success_count += 1
                    if was_verified:
                        deleted_verified_count += 1
                else:
                    failed_ids.append(faq_id)
            except Exception:
                logger.exception("Failed to delete FAQ %s", faq_id)
                failed_ids.append(faq_id)

        # Mark for rebuild if at least one verified FAQ was deleted
        if deleted_verified_count > 0:
            logger.info(
                f"Marking {deleted_verified_count} verified FAQ(s) for rebuild after bulk deletion"
            )
            self._trigger_update(
                rebuild=False,
                operation="bulk_delete",
                faq_id=f"{deleted_verified_count}_faqs",
                metadata={"count": deleted_verified_count, "total": len(faq_ids)},
            )
        elif success_count > 0:
            logger.debug(
                f"Skipping vector store rebuild: deleted {success_count} unverified FAQ(s)"
            )

        failed_count = len(failed_ids)
        return success_count, failed_count, failed_ids

    def bulk_verify_faqs(self, faq_ids: List[str]) -> tuple[int, int, List[str]]:
        """
        Verify multiple FAQs in a single operation without vector store rebuild.

        Verification only updates metadata (verified flag) and doesn't change FAQ content,
        so the vector store embeddings remain valid and don't need to be rebuilt.

        Args:
            faq_ids: List of FAQ IDs to verify

        Returns:
            Tuple of (success_count, failed_count, failed_ids)
        """
        success_count = 0
        failed_ids = []
        promotion_count = 0  # Track FAQs that changed from unverified to verified

        # Cache FAQs once to avoid O(n²) file I/O
        faqs_by_id = {faq.id: faq for faq in self.repository.get_all_faqs()}

        for faq_id in faq_ids:
            try:
                # Get the current FAQ from cache
                current_faq = faqs_by_id.get(faq_id)

                if not current_faq:
                    failed_ids.append(faq_id)
                    continue

                # Track if this FAQ is being promoted from unverified to verified
                was_unverified = not current_faq.verified

                # Update only the verification status to True
                faq_item = FAQItem(
                    **current_faq.model_dump(exclude={"id"}, exclude_none=False)
                )
                # Skip vector store rebuild for metadata-only update
                result = self.update_faq(
                    faq_id,
                    faq_item.model_copy(update={"verified": True}, deep=False),
                    rebuild_vectorstore=False,
                )

                if result:
                    success_count += 1
                    # Update cache with verified FAQ
                    faqs_by_id[result.id] = result
                    # Increment promotion count if FAQ was unverified and is now verified
                    if was_unverified and result.verified:
                        promotion_count += 1
                else:
                    failed_ids.append(faq_id)
            except Exception:
                logger.exception("Failed to verify FAQ %s", faq_id)
                failed_ids.append(faq_id)

        # Trigger vector store rebuild if any FAQs were promoted from unverified to verified
        if promotion_count > 0:
            logger.info(
                f"Triggering vector store rebuild after verifying {promotion_count} FAQ(s)"
            )
            self._trigger_update(
                rebuild=False,
                operation="bulk_verify",
                faq_id=f"{promotion_count}_faqs",
                metadata={"count": promotion_count, "total": len(faq_ids)},
            )

        failed_count = len(failed_ids)
        return success_count, failed_count, failed_ids

    def update_source_weights(self, new_weights: Dict[str, float]) -> None:
        """Update source weights for FAQ content using the RAG loader.

        Args:
            new_weights: Dictionary with updated weights
        """
        self.rag_loader.update_source_weights(new_weights)

    def load_faq_data(self) -> List[Document]:
        """Load FAQ data from SQLite repository using the RAG loader.

        Returns:
            List of Document objects prepared for RAG system
        """
        return self.rag_loader.load_faq_data(self.repository, only_verified=True)


def get_faq_service(request: Request) -> FAQService:
    """Get the FAQ service from the request state."""
    return request.app.state.faq_service
