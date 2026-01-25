"""Tests for centralized PII utility module."""

from app.core.pii_utils import (
    PII_CORE_PATTERNS,
    PII_DETECTION_PATTERNS,
    PII_LLM_PATTERNS,
    PII_LOGGING_PATTERNS,
    contains_pii,
    detect_pii,
    redact_for_llm,
    redact_for_logs,
)


class TestPIIPatternDefinitions:
    """Test that all pattern sets are properly defined."""

    def test_core_patterns_exist(self):
        """Core patterns should include common identifiers."""
        assert "email" in PII_CORE_PATTERNS
        assert "ip_address" in PII_CORE_PATTERNS
        assert "btc_address" in PII_CORE_PATTERNS

    def test_logging_patterns_superset_of_core(self):
        """Logging patterns should include all core patterns plus more."""
        for key in PII_CORE_PATTERNS:
            assert key in PII_LOGGING_PATTERNS

    def test_detection_patterns_comprehensive(self):
        """Detection patterns should be comprehensive for monitoring."""
        required = ["email", "ip_address", "btc_address", "phone", "credit_card"]
        for key in required:
            assert key in PII_DETECTION_PATTERNS

    def test_llm_patterns_minimal(self):
        """LLM patterns should be minimal to preserve useful info."""
        # LLM patterns focus on high-risk PII only
        assert "email" in PII_LLM_PATTERNS
        assert "btc_address" in PII_LLM_PATTERNS


class TestRedactForLogs:
    """Test aggressive PII redaction for logging."""

    def test_redacts_email(self):
        """Should redact email addresses."""
        text = "Contact user@example.com for help"
        result = redact_for_logs(text)
        assert "user@example.com" not in result
        assert "[EMAIL]" in result

    def test_redacts_ip_address(self):
        """Should redact IP addresses."""
        text = "User connected from 192.168.1.100"
        result = redact_for_logs(text)
        assert "192.168.1.100" not in result
        assert "[IP_ADDRESS]" in result

    def test_redacts_btc_address(self):
        """Should redact Bitcoin addresses."""
        text = "Send to bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        result = redact_for_logs(text)
        assert "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq" not in result
        assert "[BTC_ADDRESS]" in result

    def test_redacts_matrix_token(self):
        """Should redact Matrix access tokens."""
        text = "Token: syt_abc123xyz789_test"
        result = redact_for_logs(text)
        assert "syt_abc123xyz789_test" not in result
        assert "[MATRIX_TOKEN]" in result

    def test_redacts_phone_number(self):
        """Should redact phone numbers."""
        text = "Call me at 555-123-4567"
        result = redact_for_logs(text)
        assert "555-123-4567" not in result
        assert "[PHONE]" in result

    def test_preserves_safe_text(self):
        """Should preserve text without PII."""
        text = "How do I start trading on Bisq Easy?"
        result = redact_for_logs(text)
        assert result == text


class TestRedactForLLM:
    """Test minimal PII redaction for LLM input (preserves useful info)."""

    def test_redacts_email(self):
        """Should redact email for LLM."""
        text = "My email is test@bisq.network"
        result = redact_for_llm(text)
        assert "test@bisq.network" not in result

    def test_redacts_btc_address(self):
        """Should redact BTC address for LLM."""
        text = "Pay to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        result = redact_for_llm(text)
        assert "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" not in result

    def test_preserves_ip_for_context(self):
        """LLM redaction may preserve IPs if not in high-risk category."""
        # This test documents the behavior - LLM patterns may be less aggressive
        text = "Server at 192.168.1.1"
        result = redact_for_llm(text)
        # LLM patterns should include IP for privacy
        assert "192.168.1.1" not in result


class TestDetectPII:
    """Test PII detection functionality."""

    def test_detects_email(self):
        """Should detect email addresses."""
        text = "Contact admin@example.org"
        result = detect_pii(text)
        assert "email" in result
        assert "admin@example.org" in result["email"]

    def test_detects_multiple_types(self):
        """Should detect multiple PII types."""
        text = "Email me@test.com from 10.0.0.1"
        result = detect_pii(text)
        assert "email" in result
        assert "ip_address" in result

    def test_returns_empty_for_clean_text(self):
        """Should return empty dict for text without PII."""
        text = "How do I use Bisq Easy?"
        result = detect_pii(text)
        assert result == {} or len(result) == 0


class TestContainsPII:
    """Test boolean PII check."""

    def test_returns_true_for_email(self):
        """Should return True when email present."""
        assert contains_pii("Send to user@domain.com") is True

    def test_returns_true_for_btc(self):
        """Should return True when BTC address present."""
        # Valid-length segwit address
        assert contains_pii("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq") is True

    def test_returns_false_for_clean(self):
        """Should return False for clean text."""
        assert contains_pii("What is Bisq Easy?") is False


class TestBackwardCompatibility:
    """Test that sync services can use the new module."""

    def test_patterns_usable_by_sync_services(self):
        """PII_LLM_PATTERNS should be usable like old PII_PATTERNS."""
        import re

        # Simulate what sync services do
        # Use valid-length BTC address (segwit bech32)
        btc_addr = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        text = f"Contact user@example.com about {btc_addr}"
        anonymized = text

        for pattern_name, pattern in PII_LLM_PATTERNS.items():
            regex = re.compile(pattern)
            anonymized = regex.sub(f"[{pattern_name.upper()}]", anonymized)

        assert "user@example.com" not in anonymized
        assert btc_addr not in anonymized
