"""Public FAQ service with thread-safe caching and cache invalidation."""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from app.services.faq.slug_manager import SlugManager
from app.services.faq_service import FAQService

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with TTL."""

    data: Any
    expires_at: datetime

    def is_expired(self) -> bool:
        """Check if this cache entry has expired."""
        return datetime.utcnow() > self.expires_at


class PublicFAQService:
    """Thread-safe public FAQ service with caching and cache invalidation."""

    _instance: Optional["PublicFAQService"] = None
    _lock = threading.Lock()
    _initialized: bool = False

    # Fields allowed in public responses (sanitization allowlist)
    ALLOWED_FIELDS: Set[str] = {
        "id",
        "slug",
        "question",
        "answer",
        "category",
        "created_at",
        "updated_at",
        "source",
        "protocol",
    }

    # Cache TTLs
    FAQ_LIST_TTL = timedelta(minutes=5)
    FAQ_DETAIL_TTL = timedelta(minutes=15)
    CATEGORIES_TTL = timedelta(minutes=30)

    def __new__(cls, *args: Any, **kwargs: Any) -> "PublicFAQService":
        """Thread-safe singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, faq_service: FAQService) -> None:
        """Initialize the public FAQ service.

        Args:
            faq_service: The FAQService instance to delegate to
        """
        # Ensure init only runs once
        if hasattr(self, "_initialized") and self._initialized:
            return

        with self._lock:
            if hasattr(self, "_initialized") and self._initialized:
                return

            self.faq_service = faq_service
            self.slug_manager = SlugManager()
            self._slug_to_id: Dict[str, str] = {}
            self._id_to_slug: Dict[str, str] = {}
            self._cache: Dict[str, CacheEntry] = {}
            self._cache_version = 0
            self._initialize_slugs()
            self._initialized = True
            logger.info("PublicFAQService initialized")

    def _get_cache_key(self, prefix: str, *args: Any) -> str:
        """Generate cache key with version."""
        return f"{prefix}:{self._cache_version}:{':'.join(str(a) for a in args)}"

    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired."""
        entry = self._cache.get(key)
        if entry and not entry.is_expired():
            return entry.data
        return None

    def _set_cache(self, key: str, data: Any, ttl: timedelta) -> None:
        """Set cache entry with TTL."""
        self._cache[key] = CacheEntry(data=data, expires_at=datetime.utcnow() + ttl)

    def _get_faq_by_id_from_service(self, faq_id: str) -> Any:
        """Get FAQ by ID from the FAQService.

        Args:
            faq_id: The FAQ identifier

        Returns:
            FAQIdentifiedItem or None if not found
        """
        return next(
            (faq for faq in self.faq_service.get_all_faqs() if faq.id == faq_id), None
        )

    def _initialize_slugs(self) -> None:
        """Generate slugs for all FAQs on startup."""
        try:
            faqs = self.faq_service.get_all_faqs()
            existing_slugs: Set[str] = set()

            for faq in faqs:
                faq_id = faq.id
                question = faq.question or ""

                slug = self.slug_manager.generate_slug(question, faq_id, existing_slugs)
                existing_slugs.add(slug)
                self._slug_to_id[slug] = faq_id
                self._id_to_slug[faq_id] = slug

            self.slug_manager.load_cache(existing_slugs)
            logger.info(f"Initialized {len(self._slug_to_id)} FAQ slugs")
        except Exception as e:
            logger.error(f"Failed to initialize slugs: {e}")

    def invalidate_cache(self, faq_id: Optional[str] = None) -> None:
        """Invalidate cache on FAQ mutations.

        Args:
            faq_id: Specific FAQ ID to invalidate, or None for full invalidation
        """
        with self._lock:
            if faq_id:
                # Invalidate specific FAQ and related caches
                keys_to_remove = []
                for key in self._cache.keys():
                    if (
                        faq_id in key
                        or key.startswith("list:")
                        or key.startswith("categories:")
                    ):
                        keys_to_remove.append(key)
                for key in keys_to_remove:
                    del self._cache[key]

                # Refresh slug for this FAQ
                faq = self._get_faq_by_id_from_service(faq_id)
                if faq:
                    # Remove old slug mapping
                    old_slug = self._id_to_slug.get(faq_id)
                    if old_slug:
                        self._slug_to_id.pop(old_slug, None)
                        self.slug_manager.remove_from_cache(old_slug)

                    # Generate new slug
                    new_slug = self.slug_manager.generate_slug(
                        faq.question, faq_id, set(self._slug_to_id.keys())
                    )
                    self._slug_to_id[new_slug] = faq_id
                    self._id_to_slug[faq_id] = new_slug
                    self.slug_manager.add_to_cache(new_slug)

                logger.info(
                    f"Invalidated cache for FAQ {faq_id} ({len(keys_to_remove)} entries)"
                )
            else:
                # Full cache invalidation
                self._cache.clear()
                self._cache_version += 1
                self._slug_to_id.clear()
                self._id_to_slug.clear()
                self.slug_manager.clear_cache()
                self._initialize_slugs()
                logger.info(
                    f"Full cache invalidation, version now {self._cache_version}"
                )

    def _sanitize_faq(self, faq: Any) -> Dict[str, Any]:
        """Remove internal fields before public exposure.

        Args:
            faq: FAQIdentifiedItem or dict to sanitize

        Returns:
            Dict containing only allowed public fields
        """
        # Handle both dict and Pydantic model
        if hasattr(faq, "model_dump"):
            faq_dict = faq.model_dump()
        elif hasattr(faq, "dict"):
            faq_dict = faq.dict()
        elif isinstance(faq, dict):
            faq_dict = faq
        else:
            faq_dict = dict(faq)

        sanitized = {k: v for k, v in faq_dict.items() if k in self.ALLOWED_FIELDS}

        # Add slug if not present
        if "slug" not in sanitized and "id" in faq_dict:
            sanitized["slug"] = self._id_to_slug.get(faq_dict["id"], "")

        # Convert datetime objects to ISO format strings
        for key in ["created_at", "updated_at"]:
            if key in sanitized and sanitized[key]:
                if isinstance(sanitized[key], datetime):
                    sanitized[key] = sanitized[key].isoformat()

        return sanitized

    def get_faq_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get single FAQ by slug with caching.

        Args:
            slug: The URL-safe slug identifier

        Returns:
            Sanitized FAQ dict or None if not found
        """
        # Validate slug before lookup
        if not self.slug_manager.validate_slug(slug):
            logger.warning(f"Invalid slug format rejected: {slug[:50]}")
            return None

        cache_key = self._get_cache_key("detail", slug)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        faq_id = self._slug_to_id.get(slug)
        if not faq_id:
            return None

        # Get FAQ from repository
        faq = self._get_faq_by_id_from_service(faq_id)
        if not faq:
            return None

        result = self._sanitize_faq(faq)
        self._set_cache(cache_key, result, self.FAQ_DETAIL_TTL)
        return result

    def get_faq_by_id(self, faq_id: str) -> Optional[Dict[str, Any]]:
        """Get single FAQ by ID with caching.

        Args:
            faq_id: The FAQ identifier

        Returns:
            Sanitized FAQ dict or None if not found
        """
        cache_key = self._get_cache_key("detail_id", faq_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        faq = self._get_faq_by_id_from_service(faq_id)
        if not faq:
            return None

        result = self._sanitize_faq(faq)
        self._set_cache(cache_key, result, self.FAQ_DETAIL_TTL)
        return result

    def get_slug_for_id(self, faq_id: str) -> Optional[str]:
        """Get slug for a FAQ ID.

        Args:
            faq_id: The FAQ identifier

        Returns:
            The slug or None if not found
        """
        return self._id_to_slug.get(faq_id)

    def get_faqs_paginated(
        self,
        page: int = 1,
        limit: int = 20,
        search: str = "",
        category: str = "",
    ) -> Dict[str, Any]:
        """Get paginated FAQs with optional filtering.

        Args:
            page: Page number (1-indexed)
            limit: Items per page (max 50)
            search: Search query for full-text search
            category: Category filter

        Returns:
            Dict with 'data' (list of FAQs) and 'pagination' metadata
        """
        # Clamp limit to reasonable bounds
        limit = max(1, min(limit, 50))

        cache_key = self._get_cache_key("list", page, limit, search, category)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Use existing pagination from FAQService
        result = self.faq_service.get_faqs_paginated(
            page=page,
            page_size=limit,
            search_text=search if search else None,
            categories=[category] if category else None,
        )

        # Sanitize each FAQ and add slugs
        sanitized_faqs = []
        for faq in result.faqs:
            sanitized = self._sanitize_faq(faq)
            sanitized_faqs.append(sanitized)

        response = {
            "data": sanitized_faqs,
            "pagination": {
                "page": result.page,
                "limit": limit,
                "total_items": result.total_count,
                "total_pages": result.total_pages,
                "has_next": result.page < result.total_pages,
                "has_prev": result.page > 1,
            },
        }

        self._set_cache(cache_key, response, self.FAQ_LIST_TTL)
        return response

    def get_categories(self) -> List[Dict[str, Any]]:
        """Get all categories with counts.

        Returns:
            List of category dicts with name, count, and slug
        """
        cache_key = self._get_cache_key("categories")
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        faqs = self.faq_service.get_all_faqs()
        category_counts: Dict[str, int] = {}

        for faq in faqs:
            cat = faq.category or "Uncategorized"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        result = [
            {
                "name": name,
                "count": count,
                "slug": name.lower().replace(" ", "-"),
            }
            for name, count in sorted(category_counts.items())
        ]

        self._set_cache(cache_key, result, self.CATEGORIES_TTL)
        return result

    def search_faqs(
        self, query: str, limit: int = 10, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search FAQs by text query.

        Args:
            query: Search query
            limit: Maximum results to return
            category: Optional category filter

        Returns:
            List of matching FAQ dicts
        """
        result = self.get_faqs_paginated(
            page=1, limit=limit, search=query, category=category or ""
        )
        return result.get("data", [])
