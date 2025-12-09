"""PII (Personally Identifiable Information) logging filter.

Redacts sensitive information from log messages to prevent PII leakage.
"""

import logging
import re
from typing import Pattern


class PIIFilter(logging.Filter):
    """Logging filter that redacts PII from log messages."""

    # Compiled regex patterns for performance
    PATTERNS: list[tuple[Pattern, str]] = [
        # Matrix access tokens (syt_*)
        (re.compile(r"syt_[a-zA-Z0-9_-]+"), "[MATRIX_TOKEN]"),
        # Email addresses
        (re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b"), "[EMAIL]"),
        # Phone numbers (various formats)
        (re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"), "[PHONE]"),
        # Credit card numbers (simple pattern, groups of 4 digits)
        (re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"), "[CARD]"),
        # IP addresses (both IPv4 and IPv6)
        (
            re.compile(
                r"\b(?:\d{1,3}\.){3}\d{1,3}\b|(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
            ),
            "[IP_ADDRESS]",
        ),
        # Bitcoin addresses (common formats)
        (
            re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b|bc1[a-z0-9]{39,87}\b"),
            "[BTC_ADDRESS]",
        ),
        # API keys (generic pattern for keys with alphanumeric and special chars)
        (
            re.compile(r"api[_-]?key[_-]?[:=]\s*['\"]?[\w\-]{20,}['\"]?", re.I),
            "[API_KEY]",
        ),
        # Passwords in URLs or config (password=... or pwd=...)
        (
            re.compile(r"(password|passwd|pwd)[:=][^\s&]+", re.I),
            r"\1=[REDACTED]",
        ),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log record by redacting PII from message.

        Args:
            record: The log record to filter

        Returns:
            True (always allow the record, but with redacted content)
        """
        if record.msg:
            # Apply all redaction patterns
            message = str(record.msg)
            for pattern, replacement in self.PATTERNS:
                message = pattern.sub(replacement, message)
            record.msg = message

        # Also redact from args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact_string(v) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact_string(arg) for arg in record.args)

        return True

    def _redact_string(self, value: any) -> any:
        """Redact PII from a string value.

        Args:
            value: The value to redact (if it's a string)

        Returns:
            Redacted value (unchanged if not a string)
        """
        if not isinstance(value, str):
            return value

        redacted = value
        for pattern, replacement in self.PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted


def add_pii_filter_to_logger(logger: logging.Logger) -> None:
    """Add PII filter to a logger instance.

    Args:
        logger: The logger to add the filter to
    """
    pii_filter = PIIFilter()
    logger.addFilter(pii_filter)


def add_pii_filter_to_all_loggers() -> None:
    """Add PII filter to all existing loggers and the root logger."""
    # Add to root logger
    root_logger = logging.getLogger()
    add_pii_filter_to_logger(root_logger)

    # Add to all existing loggers
    for logger_name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        if isinstance(logger, logging.Logger):
            add_pii_filter_to_logger(logger)
