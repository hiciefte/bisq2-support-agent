"""Tests for wiki URL generation including security validation."""

import pytest
from app.utils.wiki_url_generator import WikiUrlGenerator, generate_wiki_url


class TestWikiUrlGenerator:
    """Tests for WikiUrlGenerator class."""

    def test_basic_title(self):
        """Generate URL from simple title."""
        url = generate_wiki_url("Bisq Easy Overview")
        assert url == "https://bisq.wiki/Bisq_Easy_Overview"

    def test_title_with_section(self):
        """Generate URL with section anchor."""
        url = generate_wiki_url("Bisq Easy Overview", "Key Features")
        assert url == "https://bisq.wiki/Bisq_Easy_Overview#Key_Features"

    def test_special_characters_encoded(self):
        """Special characters should be URL encoded."""
        url = generate_wiki_url("Security & Privacy")
        assert url == "https://bisq.wiki/Security_%26_Privacy"

    def test_multiple_spaces_become_underscores(self):
        """Multiple spaces become multiple underscores (MediaWiki convention)."""
        url = generate_wiki_url("How to  Trade  Safely")
        assert url == "https://bisq.wiki/How_to__Trade__Safely"

    def test_parentheses_encoded(self):
        """Parentheses should be URL encoded."""
        url = generate_wiki_url("Trading (Advanced)")
        assert url == "https://bisq.wiki/Trading_%28Advanced%29"

    def test_custom_base_url(self):
        """Custom base URL from allowed domains."""
        url = generate_wiki_url("Test", base_url="https://wiki.bisq.network")
        assert url == "https://wiki.bisq.network/Test"

    def test_section_with_special_chars(self):
        """Section with special characters should be encoded."""
        url = generate_wiki_url("Article", "Section (Part 1)")
        assert url == "https://bisq.wiki/Article#Section_%28Part_1%29"

    def test_empty_title_returns_none(self):
        """Empty title returns None."""
        assert generate_wiki_url("") is None
        assert generate_wiki_url(None) is None  # type: ignore

    def test_underscores_preserved(self):
        """Existing underscores should be preserved."""
        url = generate_wiki_url("Bisq_Easy_Overview")
        assert url == "https://bisq.wiki/Bisq_Easy_Overview"

    def test_mixed_spaces_and_underscores(self):
        """Mixed spaces and underscores handled correctly."""
        url = generate_wiki_url("Bisq Easy_Overview")
        assert url == "https://bisq.wiki/Bisq_Easy_Overview"

    def test_unicode_characters(self):
        """Unicode characters should be URL encoded."""
        url = generate_wiki_url("Tradeübersicht")
        assert url is not None
        assert "Trade" in url
        assert "%C3%BC" in url  # URL-encoded ü

    def test_numbers_in_title(self):
        """Numbers in title preserved."""
        url = generate_wiki_url("Bisq 2 Guide")
        assert url == "https://bisq.wiki/Bisq_2_Guide"

    def test_section_only_spaces(self):
        """Section with only spaces handled."""
        url = generate_wiki_url("Article", "Section Name")
        assert url == "https://bisq.wiki/Article#Section_Name"


class TestWikiUrlSecurity:
    """Security-focused tests for URL generation."""

    def test_domain_whitelist_enforced(self):
        """Only whitelisted domains allowed."""
        with pytest.raises(ValueError, match="not in allowed domains"):
            WikiUrlGenerator(base_url="https://evil.com")

    def test_domain_whitelist_enforced_subdomain(self):
        """Subdomains of whitelisted domains not automatically allowed."""
        with pytest.raises(ValueError, match="not in allowed domains"):
            WikiUrlGenerator(base_url="https://evil.bisq.wiki")

    def test_javascript_scheme_blocked_in_base_url(self):
        """JavaScript URLs in base_url rejected."""
        with pytest.raises(ValueError):
            WikiUrlGenerator(base_url="javascript:alert(1)")

    def test_xss_in_title_sanitized(self):
        """XSS attempts in title must be sanitized."""
        generator = WikiUrlGenerator()
        url = generator.generate_url("<script>alert(1)</script>")
        assert url is None  # Should reject due to < and > characters

    def test_html_tags_rejected(self):
        """HTML tags in title rejected."""
        generator = WikiUrlGenerator()
        assert generator.generate_url("<b>Bold</b>") is None
        assert generator.generate_url("<img src=x>") is None

    def test_newline_injection_blocked(self):
        """Newline characters in title rejected."""
        generator = WikiUrlGenerator()
        assert generator.generate_url("Title\nInjected") is None
        assert generator.generate_url("Title\rInjected") is None

    def test_null_byte_injection_blocked(self):
        """Null byte characters in title rejected."""
        generator = WikiUrlGenerator()
        assert generator.generate_url("Title\0Injected") is None

    def test_quotes_in_title_rejected(self):
        """Quote characters in title rejected."""
        generator = WikiUrlGenerator()
        assert generator.generate_url('Title"Quoted') is None
        assert generator.generate_url("Title'Quoted") is None

    def test_url_validation_helper_valid(self):
        """URL validation helper accepts valid wiki URLs."""
        assert WikiUrlGenerator.is_valid_wiki_url("https://bisq.wiki/Test")
        assert WikiUrlGenerator.is_valid_wiki_url("https://wiki.bisq.network/Page")
        assert WikiUrlGenerator.is_valid_wiki_url("http://bisq.wiki/Test")  # HTTP ok

    def test_url_validation_helper_invalid(self):
        """URL validation helper rejects invalid URLs."""
        assert not WikiUrlGenerator.is_valid_wiki_url("https://evil.com/Test")
        assert not WikiUrlGenerator.is_valid_wiki_url("javascript:alert(1)")
        assert not WikiUrlGenerator.is_valid_wiki_url("data:text/html,<script>")
        assert not WikiUrlGenerator.is_valid_wiki_url("file:///etc/passwd")
        assert not WikiUrlGenerator.is_valid_wiki_url("")
        assert not WikiUrlGenerator.is_valid_wiki_url("not-a-url")

    def test_title_max_length_enforced(self):
        """Titles exceeding max length rejected."""
        generator = WikiUrlGenerator()
        long_title = "A" * 201  # Exceeds MAX_TITLE_LENGTH of 200
        assert generator.generate_url(long_title) is None

    def test_title_at_max_length_accepted(self):
        """Titles at exactly max length accepted."""
        generator = WikiUrlGenerator()
        max_title = "A" * 200  # Exactly MAX_TITLE_LENGTH
        url = generator.generate_url(max_title)
        assert url is not None
        assert "A" * 200 in url

    def test_section_truncated_at_max_length(self):
        """Sections exceeding max length truncated."""
        generator = WikiUrlGenerator()
        long_section = "B" * 150  # Exceeds MAX_SECTION_LENGTH of 100
        url = generator.generate_url("Article", long_section)
        assert url is not None
        # Section should be truncated to 100 chars
        assert url.endswith("#" + "B" * 100)

    def test_section_with_invalid_chars_skipped(self):
        """Section with invalid characters skipped but URL still generated."""
        generator = WikiUrlGenerator()
        url = generator.generate_url("Article", "<script>")
        # URL generated without section
        assert url == "https://bisq.wiki/Article"


class TestWikiUrlGeneratorInstance:
    """Tests for WikiUrlGenerator instance behavior."""

    def test_instance_reuse(self):
        """Generator instance can be reused for multiple URLs."""
        generator = WikiUrlGenerator()
        url1 = generator.generate_url("Article1")
        url2 = generator.generate_url("Article2")
        assert url1 == "https://bisq.wiki/Article1"
        assert url2 == "https://bisq.wiki/Article2"

    def test_base_url_trailing_slash_stripped(self):
        """Trailing slash in base URL stripped."""
        generator = WikiUrlGenerator(base_url="https://bisq.wiki/")
        url = generator.generate_url("Article")
        assert url == "https://bisq.wiki/Article"
        # Not double slash
        assert "bisq.wiki//Article" not in url

    def test_allowed_domains_immutable(self):
        """ALLOWED_DOMAINS cannot be modified."""
        # Attempting to add to frozenset should raise TypeError
        with pytest.raises(AttributeError):
            WikiUrlGenerator.ALLOWED_DOMAINS.add("new.domain")  # type: ignore

    def test_docs_domain_allowed(self):
        """docs.bisq.network is in allowed domains."""
        generator = WikiUrlGenerator(base_url="https://docs.bisq.network")
        url = generator.generate_url("API Guide")
        assert url == "https://docs.bisq.network/API_Guide"
