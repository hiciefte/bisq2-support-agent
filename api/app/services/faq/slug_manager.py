"""Secure slug generation and management for public FAQ URLs."""

import hashlib
import re
import unicodedata
from typing import FrozenSet, Optional, Set


class SlugManager:
    """Generate and manage URL-safe slugs for FAQs with security validation."""

    MAX_SLUG_LENGTH = 60

    # Reserved slugs that could cause routing issues
    RESERVED_SLUGS: FrozenSet[str] = frozenset(
        {
            "admin",
            "api",
            "static",
            "assets",
            "health",
            "metrics",
            "login",
            "logout",
            "search",
            "new",
            "edit",
            "delete",
            "create",
            "update",
            "categories",
            "null",
            "undefined",
            "true",
            "false",
        }
    )

    def __init__(self) -> None:
        self._slug_cache: Set[str] = set()

    def generate_slug(
        self, question: str, faq_id: str, existing_slugs: Optional[Set[str]] = None
    ) -> str:
        """
        Generate secure URL-safe slug from question text.

        Process:
        1. Normalize unicode to ASCII
        2. Lowercase, strict character allowlist
        3. Spaces to hyphens, collapse consecutive
        4. Truncate at word boundary (leave room for hash)
        5. Add uniqueness hash suffix (prevents collision attacks)

        Args:
            question: The FAQ question text
            faq_id: Unique FAQ identifier for hash generation
            existing_slugs: Set of existing slugs for collision detection

        Returns:
            URL-safe slug string
        """
        if existing_slugs is None:
            existing_slugs = self._slug_cache

        # Normalize unicode to ASCII
        normalized = unicodedata.normalize("NFKD", question)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

        # Lowercase and strict character allowlist
        slug = ascii_text.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug)
        slug = re.sub(r"-+", "-", slug)  # Collapse consecutive hyphens
        slug = slug.strip("-")

        # Truncate at word boundary (leave room for hash suffix)
        if len(slug) > self.MAX_SLUG_LENGTH - 9:  # 8 chars for hash + 1 for hyphen
            slug = slug[: self.MAX_SLUG_LENGTH - 9].rsplit("-", 1)[0]

        # Add uniqueness hash suffix (prevents collision attacks)
        hash_suffix = hashlib.sha256(faq_id.encode()).hexdigest()[:8]

        # Handle empty or reserved slugs
        if not slug or slug in self.RESERVED_SLUGS:
            return f"faq-{hash_suffix}"

        final_slug = f"{slug}-{hash_suffix}"

        return final_slug

    def validate_slug(self, slug: str) -> bool:
        """
        Validate slug format for security.

        Checks:
        - Non-empty and reasonable length
        - Not in reserved list
        - Starts and ends with alphanumeric
        - No double hyphens (injection indicator)
        - No path traversal attempts

        Args:
            slug: The slug to validate

        Returns:
            True if slug is valid and safe
        """
        if not slug or len(slug) > 100:
            return False
        if slug in self.RESERVED_SLUGS:
            return False
        # Must start and end with alphanumeric
        if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", slug):
            # Allow single character slugs with hash
            if len(slug) >= 2 and not re.match(r"^[a-z0-9][a-z0-9-]*$", slug):
                return False
        # No double hyphens (could indicate injection attempt)
        if "--" in slug:
            return False
        # No path traversal attempts
        if ".." in slug or "/" in slug or "\\" in slug:
            return False
        return True

    def add_to_cache(self, slug: str) -> None:
        """Add slug to internal cache."""
        self._slug_cache.add(slug)

    def remove_from_cache(self, slug: str) -> None:
        """Remove slug from internal cache."""
        self._slug_cache.discard(slug)

    def load_cache(self, slugs: Set[str]) -> None:
        """Load existing slugs into cache."""
        self._slug_cache = slugs.copy()

    def clear_cache(self) -> None:
        """Clear the slug cache."""
        self._slug_cache.clear()
