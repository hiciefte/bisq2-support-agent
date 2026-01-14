"""Secure wiki URL generator with domain validation.

This module generates MediaWiki-compatible URLs from article metadata
with security measures to prevent URL injection and open redirect vulnerabilities.
"""

import logging
from typing import FrozenSet, Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


class WikiUrlGenerator:
    """Secure wiki URL generation with domain whitelist."""

    # Immutable whitelist of allowed wiki domains
    ALLOWED_DOMAINS: FrozenSet[str] = frozenset(
        {
            "bisq.wiki",
            "wiki.bisq.network",
            "docs.bisq.network",
        }
    )

    DEFAULT_BASE_URL = "https://bisq.wiki"
    MAX_TITLE_LENGTH = 200  # Prevent excessively long URLs
    MAX_SECTION_LENGTH = 100  # Reasonable section length limit

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        """
        Initialize with validated base URL.

        Args:
            base_url: Base wiki URL (must be in whitelist)

        Raises:
            ValueError: If base_url domain is not in whitelist
        """
        parsed = urlparse(base_url)
        if parsed.netloc not in self.ALLOWED_DOMAINS:
            raise ValueError(
                f"Base URL domain '{parsed.netloc}' not in allowed domains: "
                f"{self.ALLOWED_DOMAINS}"
            )
        self.base_url = base_url.rstrip("/")

    def generate_url(
        self,
        title: str,
        section: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate validated wiki URL.

        Follows MediaWiki URL conventions:
        - Spaces -> underscores in page titles
        - Special characters URL encoded (except underscores)
        - Section anchors use # prefix with underscores

        Args:
            title: Article title (validated for length and characters)
            section: Optional section anchor

        Returns:
            Validated URL or None if validation fails

        Examples:
            >>> generator = WikiUrlGenerator()
            >>> generator.generate_url("Bisq Easy Overview")
            'https://bisq.wiki/Bisq_Easy_Overview'

            >>> generator.generate_url("Bisq Easy Overview", "Key Features")
            'https://bisq.wiki/Bisq_Easy_Overview#Key_Features'
        """
        # Input validation
        if not title or not isinstance(title, str):
            logger.warning("Invalid title: empty or not a string")
            return None

        if len(title) > self.MAX_TITLE_LENGTH:
            logger.warning(
                f"Title exceeds max length: {len(title)} > {self.MAX_TITLE_LENGTH}"
            )
            return None

        # Sanitize: remove potential URL injection characters
        invalid_chars = ["<", ">", '"', "'", "\n", "\r", "\0"]
        if any(char in title for char in invalid_chars):
            logger.warning(f"Title contains invalid characters: {title[:50]}")
            return None

        # MediaWiki convention: spaces -> underscores
        normalized_title = title.replace(" ", "_")

        # URL encode special characters but preserve underscores
        encoded_title = quote(normalized_title, safe="_")

        # Build URL
        url = f"{self.base_url}/{encoded_title}"

        # Add section anchor if provided
        if section:
            if len(section) > self.MAX_SECTION_LENGTH:
                section = section[: self.MAX_SECTION_LENGTH]
            # Validate section for invalid characters
            if any(char in section for char in invalid_chars):
                logger.warning(f"Section contains invalid characters: {section[:50]}")
                # Continue without section rather than fail completely
            else:
                normalized_section = section.replace(" ", "_")
                encoded_section = quote(normalized_section, safe="_")
                url = f"{url}#{encoded_section}"

        return url

    @classmethod
    def is_valid_wiki_url(cls, url: str) -> bool:
        """
        Validate that a URL points to an allowed wiki domain.

        Use this when processing URLs from external sources.

        Args:
            url: URL to validate

        Returns:
            True if URL points to allowed wiki domain, False otherwise
        """
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and (
                parsed.netloc in cls.ALLOWED_DOMAINS
            )
        except Exception:
            return False


# Convenience function for simple use cases
def generate_wiki_url(
    title: str,
    section: Optional[str] = None,
    base_url: str = WikiUrlGenerator.DEFAULT_BASE_URL,
) -> Optional[str]:
    """
    Generate MediaWiki URL from article title and optional section.

    This is a convenience function that creates a WikiUrlGenerator instance
    and generates a URL. For repeated use, create a WikiUrlGenerator instance
    directly to avoid repeated validation.

    Args:
        title: Article title (e.g., "Bisq Easy Overview")
        section: Section header (e.g., "Key Features")
        base_url: Base wiki URL (default: https://bisq.wiki)

    Returns:
        Full wiki URL with optional section anchor, or None if validation fails

    Raises:
        ValueError: If base_url domain is not in whitelist

    Examples:
        >>> generate_wiki_url("Bisq Easy Overview")
        'https://bisq.wiki/Bisq_Easy_Overview'

        >>> generate_wiki_url("Bisq Easy Overview", "Key Features")
        'https://bisq.wiki/Bisq_Easy_Overview#Key_Features'

        >>> generate_wiki_url("Security & Privacy", "2FA Setup")
        'https://bisq.wiki/Security_%26_Privacy#2FA_Setup'
    """
    generator = WikiUrlGenerator(base_url=base_url)
    return generator.generate_url(title=title, section=section)
