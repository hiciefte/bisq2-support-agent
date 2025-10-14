"""
Feedback Filters for data filtering, sorting, and pagination.

This module handles:
- Multi-criteria filtering
- Date range filtering
- Text search functionality
- Sorting by various fields
- Pagination logic
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from app.models.feedback import FeedbackFilterRequest, FeedbackItem

logger = logging.getLogger(__name__)


class FeedbackFilters:
    """Filters for feedback data processing.

    This class handles:
    - Applying multiple filter criteria
    - Date range filtering
    - Text search across multiple fields
    - Sorting by timestamp or rating
    """

    def __init__(self):
        """Initialize the feedback filters."""
        logger.info("Feedback filters initialized")

    def apply_filters(
        self, feedback_items: List[FeedbackItem], filters: FeedbackFilterRequest
    ) -> List[FeedbackItem]:
        """Apply various filters to feedback items.

        Args:
            feedback_items: List of feedback items to filter
            filters: Filter criteria to apply

        Returns:
            Filtered list of feedback items
        """
        filtered_items = feedback_items

        # Filter by rating
        if filters.rating == "positive":
            filtered_items = [item for item in filtered_items if item.is_positive]
        elif filters.rating == "negative":
            filtered_items = [item for item in filtered_items if item.is_negative]

        # Filter by date range
        if filters.date_from or filters.date_to:
            filtered_items = self.filter_by_date(
                filtered_items, filters.date_from, filters.date_to
            )

        # Filter by issues
        if filters.issues:
            filtered_items = [
                item
                for item in filtered_items
                if any(issue in item.issues for issue in filters.issues)
            ]

        # Filter by source types
        if filters.source_types:
            filtered_items = [
                item
                for item in filtered_items
                if self.has_source_type(item, filters.source_types)
            ]

        # Filter by search text
        if filters.search_text:
            filtered_items = self.filter_by_text_search(
                filtered_items, filters.search_text
            )

        # Filter for items that need FAQ creation
        if filters.needs_faq:
            filtered_items = [
                item
                for item in filtered_items
                if item.is_negative
                and (item.has_no_source_response or item.explanation)
            ]

        # Filter by processed status
        if filters.processed is not None:
            if filters.processed:
                # Show only processed feedback
                filtered_items = [item for item in filtered_items if item.is_processed]
            else:
                # Show only unprocessed feedback
                filtered_items = [
                    item for item in filtered_items if not item.is_processed
                ]

        return filtered_items

    def filter_by_date(
        self,
        items: List[FeedbackItem],
        date_from: Optional[str],
        date_to: Optional[str],
    ) -> List[FeedbackItem]:
        """Filter items by date range.

        Args:
            items: List of feedback items
            date_from: Start date (ISO format)
            date_to: End date (ISO format)

        Returns:
            Filtered list of feedback items
        """
        filtered = []
        for item in items:
            try:
                # Parse timestamp and normalize to timezone-aware UTC
                if "T" in item.timestamp:
                    item_date = datetime.fromisoformat(
                        item.timestamp.replace("Z", "+00:00")
                    )
                else:
                    item_date = datetime.fromisoformat(item.timestamp)

                # Normalize timezone-naive datetime to UTC
                if item_date.tzinfo is None:
                    item_date = item_date.replace(tzinfo=timezone.utc)

                # Check date bounds (handle timezone indicators in filter dates)
                if date_from:
                    from_date = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
                    if from_date.tzinfo is None:
                        from_date = from_date.replace(tzinfo=timezone.utc)
                    if item_date < from_date:
                        continue

                if date_to:
                    to_date = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
                    if to_date.tzinfo is None:
                        to_date = to_date.replace(tzinfo=timezone.utc)
                    if item_date > to_date:
                        continue

                filtered.append(item)
            except ValueError as e:
                logger.warning(f"Error parsing timestamp {item.timestamp}: {e}")
                # Include items with unparseable timestamps to avoid losing data
                filtered.append(item)

        return filtered

    def has_source_type(self, item: FeedbackItem, source_types: List[str]) -> bool:
        """Check if item has any of the specified source types.

        Args:
            item: Feedback item to check
            source_types: List of source types to match

        Returns:
            True if item has any of the specified source types
        """
        sources = (
            item.sources_used
            if item.sources_used
            else (item.sources if item.sources else [])
        )
        if not sources:
            return "unknown" in source_types

        for source in sources:
            if source.get("type", "unknown") in source_types:
                return True
        return False

    def filter_by_text_search(
        self, items: List[FeedbackItem], search_text: str
    ) -> List[FeedbackItem]:
        """Filter items by text search in questions, answers, and explanations.

        Args:
            items: List of feedback items
            search_text: Text to search for

        Returns:
            Filtered list of feedback items
        """
        search_lower = search_text.lower()
        filtered = []

        for item in items:
            # Search in question
            if search_lower in item.question.lower():
                filtered.append(item)
                continue

            # Search in answer
            if search_lower in item.answer.lower():
                filtered.append(item)
                continue

            # Search in explanation if available
            if item.explanation and search_lower in item.explanation.lower():
                filtered.append(item)
                continue

        return filtered

    def apply_sorting(
        self, items: List[FeedbackItem], sort_by: Optional[str]
    ) -> List[FeedbackItem]:
        """Apply sorting to feedback items.

        Args:
            items: List of feedback items
            sort_by: Sorting criterion (newest, oldest, rating_desc, rating_asc)

        Returns:
            Sorted list of feedback items
        """
        if not sort_by or sort_by == "newest":
            return sorted(items, key=lambda x: x.timestamp, reverse=True)
        elif sort_by == "oldest":
            return sorted(items, key=lambda x: x.timestamp)
        elif sort_by == "rating_desc":
            return sorted(items, key=lambda x: x.rating, reverse=True)
        elif sort_by == "rating_asc":
            return sorted(items, key=lambda x: x.rating)
        else:
            return items
