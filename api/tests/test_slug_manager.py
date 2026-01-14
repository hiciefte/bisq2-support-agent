"""Tests for SlugManager."""

import pytest
from app.services.faq.slug_manager import SlugManager


class TestSlugGeneration:
    """Tests for slug generation functionality."""

    @pytest.fixture
    def slug_manager(self):
        return SlugManager()

    def test_basic_slug_generation(self, slug_manager):
        """Test basic slug generation from simple question."""
        slug = slug_manager.generate_slug("How do I trade?", "faq-123")
        # Should contain the question text as slug plus hash suffix
        assert slug.startswith("how-do-i-trade-")
        assert len(slug) <= 60

    def test_special_characters_removed(self, slug_manager):
        """Test that special characters are removed from slugs."""
        slug = slug_manager.generate_slug("What's the fee (in %)?", "faq-123")
        assert "'" not in slug
        assert "(" not in slug
        assert ")" not in slug
        assert "%" not in slug
        assert slug.startswith("whats-the-fee-in-")

    def test_unicode_normalized(self, slug_manager):
        """Test that unicode characters are normalized to ASCII."""
        slug = slug_manager.generate_slug("Où est la réponse?", "faq-123")
        # Accented characters should be stripped or normalized
        assert "ù" not in slug
        assert "é" not in slug
        assert slug.startswith("ou-est-la-reponse-") or slug.startswith("faq-")

    def test_long_slug_truncated(self, slug_manager):
        """Test that long slugs are truncated at word boundary."""
        long_question = "How do I " + "really " * 20 + "trade?"
        slug = slug_manager.generate_slug(long_question, "faq-123")
        assert len(slug) <= 60

    def test_hash_suffix_added(self, slug_manager):
        """Test that slugs have a hash suffix for uniqueness."""
        slug = slug_manager.generate_slug("How do I trade?", "faq-123")
        # Should end with 8 character hex hash
        parts = slug.rsplit("-", 1)
        assert len(parts) == 2
        hash_part = parts[1]
        assert len(hash_part) == 8
        # Verify it's a valid hex string
        int(hash_part, 16)  # Should not raise ValueError

    def test_same_question_different_id_different_hash(self, slug_manager):
        """Test that same question with different ID produces different hash."""
        slug1 = slug_manager.generate_slug("How do I trade?", "faq-123")
        slug2 = slug_manager.generate_slug("How do I trade?", "faq-456")
        assert slug1 != slug2
        # But the base slug should be the same
        base1 = slug1.rsplit("-", 1)[0]
        base2 = slug2.rsplit("-", 1)[0]
        assert base1 == base2

    def test_empty_question_uses_faq_prefix(self, slug_manager):
        """Test that empty questions fall back to faq-{hash} format."""
        slug = slug_manager.generate_slug("", "faq-123")
        assert slug.startswith("faq-")

    def test_reserved_slug_uses_faq_prefix(self, slug_manager):
        """Test that reserved slugs fall back to faq-{hash} format."""
        slug = slug_manager.generate_slug("admin", "faq-123")
        assert slug.startswith("faq-")

    def test_question_only_special_chars(self, slug_manager):
        """Test question with only special characters."""
        slug = slug_manager.generate_slug("???!!!", "faq-123")
        assert slug.startswith("faq-")

    def test_consecutive_hyphens_collapsed(self, slug_manager):
        """Test that consecutive hyphens are collapsed."""
        slug = slug_manager.generate_slug("How   do   I   trade?", "faq-123")
        assert "--" not in slug


class TestSlugValidation:
    """Tests for slug validation functionality."""

    @pytest.fixture
    def slug_manager(self):
        return SlugManager()

    def test_valid_slug(self, slug_manager):
        """Test that valid slugs are accepted."""
        assert slug_manager.validate_slug("how-do-i-trade-abc12345") is True

    def test_empty_slug_rejected(self, slug_manager):
        """Test that empty slugs are rejected."""
        assert slug_manager.validate_slug("") is False

    def test_too_long_slug_rejected(self, slug_manager):
        """Test that slugs over 100 chars are rejected."""
        long_slug = "a" * 101
        assert slug_manager.validate_slug(long_slug) is False

    def test_reserved_slug_rejected(self, slug_manager):
        """Test that reserved slugs are rejected."""
        assert slug_manager.validate_slug("admin") is False
        assert slug_manager.validate_slug("api") is False
        assert slug_manager.validate_slug("login") is False

    def test_double_hyphen_rejected(self, slug_manager):
        """Test that double hyphens are rejected (injection indicator)."""
        assert slug_manager.validate_slug("how--to-trade") is False

    def test_path_traversal_rejected(self, slug_manager):
        """Test that path traversal attempts are rejected."""
        assert slug_manager.validate_slug("../admin") is False
        assert slug_manager.validate_slug("..\\admin") is False
        assert slug_manager.validate_slug("some/path") is False

    def test_slug_with_uppercase_rejected(self, slug_manager):
        """Test that uppercase characters are rejected."""
        assert slug_manager.validate_slug("How-To-Trade") is False

    def test_slug_starting_with_hyphen_rejected(self, slug_manager):
        """Test that slugs starting with hyphen are rejected."""
        assert slug_manager.validate_slug("-how-to-trade") is False


class TestSlugCache:
    """Tests for slug cache management."""

    @pytest.fixture
    def slug_manager(self):
        return SlugManager()

    def test_add_to_cache(self, slug_manager):
        """Test adding slugs to cache."""
        slug_manager.add_to_cache("test-slug")
        assert "test-slug" in slug_manager._slug_cache

    def test_remove_from_cache(self, slug_manager):
        """Test removing slugs from cache."""
        slug_manager.add_to_cache("test-slug")
        slug_manager.remove_from_cache("test-slug")
        assert "test-slug" not in slug_manager._slug_cache

    def test_remove_nonexistent_from_cache(self, slug_manager):
        """Test removing non-existent slug from cache (should not error)."""
        slug_manager.remove_from_cache("nonexistent")
        assert "nonexistent" not in slug_manager._slug_cache

    def test_load_cache(self, slug_manager):
        """Test loading slugs into cache."""
        slugs = {"slug-1", "slug-2", "slug-3"}
        slug_manager.load_cache(slugs)
        assert slug_manager._slug_cache == slugs

    def test_clear_cache(self, slug_manager):
        """Test clearing the slug cache."""
        slug_manager.add_to_cache("test-slug")
        slug_manager.clear_cache()
        assert len(slug_manager._slug_cache) == 0
