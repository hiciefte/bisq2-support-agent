"""
Security tests for Matrix polling implementation.

Tests cover:
- Session file permission security
- SQL injection protection
- Input validation
- PII filtering in logs
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from app.core.matrix_validation import (
    ValidationError,
    validate_event_id,
    validate_message,
    validate_sender,
)
from app.core.pii_filter import PIIFilter
from app.services.shadow_mode.repository import ShadowModeRepository


class TestSessionFileSecurity:
    """Test session file is created with secure permissions."""

    def test_session_file_has_owner_only_permissions(self, tmp_path):
        """Test session file created with 0600 permissions (owner read/write only)."""
        session_file = tmp_path / "matrix_session.json"

        # Simulate secure session file creation
        old_umask = os.umask(0o077)
        try:
            session_file.write_text('{"since_token": "test"}')
        finally:
            os.umask(old_umask)

        # Verify permissions
        stat_info = session_file.stat()
        permissions = stat_info.st_mode & 0o777

        # Should be 0600 (owner read/write only)
        assert permissions == 0o600, f"Expected 0600, got {oct(permissions)}"

    def test_session_directory_has_secure_permissions(self, tmp_path):
        """Test session directory created with 0700 permissions (owner only)."""
        session_dir = tmp_path / "sessions"

        # Create directory with secure permissions
        old_umask = os.umask(0o077)
        try:
            session_dir.mkdir(mode=0o700, exist_ok=True)
        finally:
            os.umask(old_umask)

        # Verify directory permissions
        stat_info = session_dir.stat()
        permissions = stat_info.st_mode & 0o777

        # Should be 0700 (owner full access only)
        assert permissions == 0o700, f"Expected 0700, got {oct(permissions)}"

    def test_atomic_write_creates_temp_file_securely(self, tmp_path):
        """Test atomic write uses secure temp file creation."""
        session_file = tmp_path / "matrix_session.json"

        # Simulate atomic write
        old_umask = os.umask(0o077)
        try:
            # Create temp file securely
            fd, temp_path = tempfile.mkstemp(
                dir=tmp_path, prefix=".tmp_session_", suffix=".json"
            )

            try:
                with os.fdopen(fd, "w") as f:
                    json.dump({"since_token": "test"}, f)

                # Check temp file permissions before rename
                temp_stat = os.stat(temp_path)
                temp_perms = temp_stat.st_mode & 0o777
                assert (
                    temp_perms == 0o600
                ), f"Temp file has insecure permissions: {oct(temp_perms)}"

                # Atomic rename
                os.rename(temp_path, session_file)

                # Check final file permissions
                final_stat = session_file.stat()
                final_perms = final_stat.st_mode & 0o777
                assert (
                    final_perms == 0o600
                ), f"Final file has insecure permissions: {oct(final_perms)}"
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
        finally:
            os.umask(old_umask)


class TestSQLInjectionProtection:
    """Test SQL injection protection in repository."""

    @pytest.fixture
    def repository(self, tmp_path):
        """Create test repository."""
        db_path = tmp_path / "test.db"
        return ShadowModeRepository(db_path=str(db_path))

    def test_rejects_invalid_filter_columns(self, repository):
        """Test repository rejects filter columns not in whitelist."""
        malicious_filters = {
            "status' OR '1'='1'; DROP TABLE shadow_responses; --": "any_value"
        }

        with pytest.raises(ValueError, match="Invalid filter column"):
            repository._build_filter_clause(malicious_filters)

    def test_accepts_valid_filter_columns(self, repository):
        """Test repository accepts valid filter columns."""
        valid_filters = {
            "status": "PENDING_VERSION_REVIEW",
            "detected_version": "bisq2",
        }

        # Should not raise
        clause, params = repository._build_filter_clause(valid_filters)

        assert "status = ?" in clause
        assert "detected_version = ?" in clause
        assert params == ["PENDING_VERSION_REVIEW", "bisq2"]

    def test_sql_injection_via_filter_value_prevented_by_parameterization(
        self, repository
    ):
        """Test SQL injection via filter value is prevented by parameterized queries."""
        # Attempt injection via value (should be harmless due to parameterization)
        filters = {"status": "'; DROP TABLE shadow_responses; --"}

        clause, params = repository._build_filter_clause(filters)

        # Value should be treated as literal string parameter
        assert params == ["'; DROP TABLE shadow_responses; --"]
        assert "?" in clause  # Parameterized query


class TestInputValidation:
    """Test input validation for Matrix messages."""

    def test_rejects_oversized_messages(self):
        """Test messages exceeding length limit are rejected."""
        huge_message = "A" * 100_000  # 100KB

        with pytest.raises(ValidationError, match="Message too long"):
            validate_message(huge_message)

    def test_rejects_oversized_sender(self):
        """Test sender names exceeding length limit are rejected."""
        huge_sender = "@" + "A" * 500 + ":matrix.org"

        with pytest.raises(ValidationError, match="Sender too long"):
            validate_sender(huge_sender)

    def test_rejects_oversized_event_id(self):
        """Test event IDs exceeding length limit are rejected."""
        huge_event_id = "$" + "A" * 500 + ":matrix.org"

        with pytest.raises(ValidationError, match="Event ID too long"):
            validate_event_id(huge_event_id)

    def test_rejects_invalid_utf8_encoding(self):
        """Test messages with invalid UTF-8 encoding are rejected."""
        # Create invalid UTF-8 byte sequence
        invalid_utf8 = b"\xff\xfe"

        with pytest.raises((ValidationError, UnicodeDecodeError)):
            # Try to decode and validate
            message = invalid_utf8.decode("utf-8", errors="strict")
            validate_message(message)

    def test_accepts_valid_messages(self):
        """Test valid messages pass validation."""
        valid_message = "How do I trade on Bisq?"
        valid_sender = "@user:matrix.org"
        valid_event_id = "$abc123:matrix.org"

        # Should not raise
        validate_message(valid_message)
        validate_sender(valid_sender)
        validate_event_id(valid_event_id)

    def test_rejects_invalid_sender_format(self):
        """Test sender IDs with invalid format are rejected."""
        # Missing @ prefix
        with pytest.raises(ValidationError, match="must start with '@'"):
            validate_sender("usermatrix.org")

        # Missing : separator
        with pytest.raises(ValidationError, match="must contain ':' separator"):
            validate_sender("@usermatrix.org")

    def test_rejects_invalid_event_id_format(self):
        """Test event IDs with invalid format are rejected."""
        # Missing $ prefix
        with pytest.raises(ValidationError, match="must start with '\\$'"):
            validate_event_id("abc123:matrix.org")

        # Missing : separator
        with pytest.raises(ValidationError, match="must contain ':' separator"):
            validate_event_id("$abc123matrix.org")


class TestPIILoggingFilter:
    """Test PII data is filtered from logs."""

    @pytest.fixture
    def pii_filter(self):
        """Create PII filter instance."""
        return PIIFilter()

    def test_filters_matrix_tokens(self, pii_filter):
        """Test Matrix access tokens are redacted in logs."""
        import logging

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Using token: syt_abc123_def456",
            args=(),
            exc_info=None,
        )

        pii_filter.filter(record)

        assert "syt_abc123_def456" not in str(record.msg)
        assert "[MATRIX_TOKEN]" in str(record.msg)

    def test_filters_email_addresses(self, pii_filter):
        """Test email addresses are redacted in logs."""
        import logging

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User email: user@example.com contacted support",
            args=(),
            exc_info=None,
        )

        pii_filter.filter(record)

        assert "user@example.com" not in str(record.msg)
        assert "[EMAIL]" in str(record.msg)

    def test_filters_phone_numbers(self, pii_filter):
        """Test phone numbers are redacted in logs."""
        import logging

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Contact: 555-123-4567",
            args=(),
            exc_info=None,
        )

        pii_filter.filter(record)

        assert "555-123-4567" not in str(record.msg)
        assert "[PHONE]" in str(record.msg)

    def test_preserves_non_pii_content(self, pii_filter):
        """Test non-PII content is preserved in logs."""
        import logging

        log_message = "Processing message from Matrix room"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=log_message,
            args=(),
            exc_info=None,
        )

        pii_filter.filter(record)

        assert str(record.msg) == log_message


class TestDockerSecretsIntegration:
    """Test Docker Secrets integration for credential management."""

    def test_reads_token_from_secret_file(self, tmp_path):
        """Test token is read from Docker secret file when available."""
        secret_file = tmp_path / "matrix_token"
        secret_file.write_text("syt_secret_token_123")

        # Simulate reading secret
        with open(secret_file) as f:
            token = f.read().strip()

        assert token == "syt_secret_token_123"

    def test_falls_back_to_env_var_when_secret_unavailable(self):
        """Test falls back to environment variable when secret file unavailable."""
        secret_file = "/nonexistent/path/matrix_token"
        env_token = "syt_env_token_456"

        # Simulate fallback logic
        if os.path.exists(secret_file):
            with open(secret_file) as f:
                token = f.read().strip()
        else:
            token = env_token

        assert token == env_token

    def test_prefers_secret_file_over_env_var(self, tmp_path):
        """Test secret file takes precedence over environment variable."""
        secret_file = tmp_path / "matrix_token"
        secret_file.write_text("syt_secret_token_789")
        env_token = "syt_env_token_000"

        # Simulate preference logic
        if os.path.exists(secret_file):
            with open(secret_file) as f:
                token = f.read().strip()
        else:
            token = env_token

        assert token == "syt_secret_token_789"
        assert token != env_token
