"""Channel security protocols and handlers.

Security infrastructure for channel plugin architecture.
"""

import logging
import os
import re
import threading
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Protocol, Tuple

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.channels.models import GatewayError

logger = logging.getLogger(__name__)


# =============================================================================
# Secret Store Protocol
# =============================================================================


class SecretStore(Protocol):
    """Protocol for secure secret storage backends."""

    async def get_secret(self, key: str) -> str:
        """Retrieve secret by key."""
        ...

    async def set_secret(self, key: str, value: str) -> None:
        """Store secret."""
        ...

    async def rotate_secret(self, key: str) -> str:
        """Rotate secret and return new value."""
        ...


class EnvironmentSecretStore:
    """Secret store using environment variables (development only)."""

    async def get_secret(self, key: str) -> str:
        """Retrieve secret from environment variable."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Secret {key} not found in environment")
        return value

    async def set_secret(self, key: str, value: str) -> None:
        """Set environment variable (ephemeral)."""
        os.environ[key] = value

    async def rotate_secret(self, key: str) -> str:
        """Generate new secret and store it."""
        import secrets

        new_value = secrets.token_hex(32)
        await self.set_secret(key, new_value)
        return new_value


# =============================================================================
# PII Detection
# =============================================================================


class PIIType(str, Enum):
    """Types of personally identifiable information."""

    EMAIL = "email"
    BITCOIN_ADDRESS = "bitcoin_address"
    TRADE_ID = "trade_id"
    IBAN = "iban"
    CREDIT_CARD = "credit_card"
    PHONE_NUMBER = "phone_number"
    IP_ADDRESS = "ip_address"


class PIIDetector:
    """Detect personally identifiable information in text."""

    PATTERNS: ClassVar[Dict[PIIType, re.Pattern[str]]] = {
        PIIType.EMAIL: re.compile(
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", re.IGNORECASE
        ),
        PIIType.BITCOIN_ADDRESS: re.compile(
            r"\b(?:bc1|[13])[a-zA-HJ-NP-Z0-9]{25,39}\b"
        ),
        PIIType.TRADE_ID: re.compile(
            r"\b[A-Z0-9]{8}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{12}\b",
            re.IGNORECASE,
        ),
        PIIType.IBAN: re.compile(r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b", re.IGNORECASE),
        PIIType.CREDIT_CARD: re.compile(
            r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"
        ),
        PIIType.PHONE_NUMBER: re.compile(
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
        PIIType.IP_ADDRESS: re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    }

    def detect(self, text: str) -> List[Tuple[PIIType, str]]:
        """Detect PII in text.

        Returns:
            List of (pii_type, matched_value) tuples
        """
        findings: List[Tuple[PIIType, str]] = []
        for pii_type, pattern in self.PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append((pii_type, match.group(0)))
        return findings

    def redact(self, text: str, replacement: str = "[REDACTED]") -> str:
        """Redact PII from text."""
        for pattern in self.PATTERNS.values():
            text = pattern.sub(replacement, text)
        return text

    def contains_pii(self, text: str) -> bool:
        """Check if text contains any PII."""
        return len(self.detect(text)) > 0


# =============================================================================
# Security Incident Handling
# =============================================================================


class SecurityIncidentType(str, Enum):
    """Types of security incidents."""

    RATE_LIMIT_ABUSE = "rate_limit_abuse"
    PII_LEAKAGE = "pii_leakage"
    AUTHENTICATION_FAILURE = "authentication_failure"
    INJECTION_ATTEMPT = "injection_attempt"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    SIGNATURE_MISMATCH = "signature_mismatch"


class SecurityIncident(BaseModel):
    """Record of a security incident."""

    incident_type: SecurityIncidentType
    message_id: Optional[str] = None
    channel: Optional[str] = None
    user_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    severity: str = "warning"  # info, warning, error, critical


class SecurityIncidentHandler:
    """Handle security incidents with appropriate responses."""

    def __init__(self) -> None:
        self.incident_logger = logging.getLogger("security")
        # In-memory only (resets on process restart and is not shared across workers).
        self.abuse_counts: Dict[str, int] = {}

    async def report_incident(
        self,
        incident_type: SecurityIncidentType,
        message_id: Optional[str] = None,
        channel: Optional[str] = None,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        severity: str = "warning",
    ) -> SecurityIncident:
        """Report and log a security incident."""
        incident = SecurityIncident(
            incident_type=incident_type,
            message_id=message_id,
            channel=channel,
            user_id=user_id,
            details=details or {},
            severity=severity,
        )

        self.incident_logger.log(
            self._severity_to_level(severity),
            f"Security incident: {incident_type}",
            extra={
                "incident_type": incident_type,
                "message_id": message_id,
                "channel": channel,
                "user_id": user_id,
                "details": details,
            },
        )

        # Track abuse patterns
        if user_id and incident_type == SecurityIncidentType.RATE_LIMIT_ABUSE:
            self.abuse_counts[user_id] = self.abuse_counts.get(user_id, 0) + 1

        return incident

    def get_abuse_count(self, user_id: str) -> int:
        """Get the abuse count for a user."""
        return self.abuse_counts.get(user_id, 0)

    def reset_abuse_count(self, user_id: str) -> None:
        """Reset abuse count for a user."""
        if user_id in self.abuse_counts:
            del self.abuse_counts[user_id]

    def _severity_to_level(self, severity: str) -> int:
        """Convert severity string to logging level."""
        levels = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        return levels.get(severity, logging.WARNING)


# =============================================================================
# Sensitive Data Logging Filter
# =============================================================================


class SensitiveDataFilter(logging.Filter):
    """Filter sensitive data from logs."""

    SENSITIVE_KEYS = {
        "api_key",
        "password",
        "secret",
        "token",
        "auth",
        "credit_card",
        "ssn",
        "bitcoin_address",
        "private_key",
    }

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive data from log record."""
        if hasattr(record, "msg") and isinstance(record.msg, str):
            for key in self.SENSITIVE_KEYS:
                pattern = rf"{key}[\"']?\s*[:=]\s*[\"']?[^\s\"']+[\"']?"
                record.msg = re.sub(
                    pattern, f"{key}=[REDACTED]", record.msg, flags=re.IGNORECASE
                )
        return True


# =============================================================================
# Input Validation
# =============================================================================


class InputValidator:
    """Validate and sanitize input data."""

    # Patterns that may indicate injection attempts
    DANGEROUS_PATTERNS = [
        r"<script[^>]*>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe",
        r"<object",
        r"<embed",
    ]

    # Patterns that may indicate prompt injection
    PROMPT_INJECTION_PATTERNS = [
        r"(?i)\bignore\s+(previous|above|prior)\s+instructions?\b",
        r"(?i)\byou\s+are\s+now\b",
        r"(?i)\bsystem:",
        r"(?i)\badmin:",
        r"(?i)\b<\|system\|>",
    ]

    def __init__(self) -> None:
        self.dangerous_compiled = [
            re.compile(p, re.IGNORECASE) for p in self.DANGEROUS_PATTERNS
        ]
        self.injection_compiled = [
            re.compile(p, re.IGNORECASE) for p in self.PROMPT_INJECTION_PATTERNS
        ]

    def contains_dangerous_content(self, text: str) -> bool:
        """Check if text contains dangerous patterns (XSS, etc.)."""
        for pattern in self.dangerous_compiled:
            if pattern.search(text):
                return True
        return False

    def contains_prompt_injection(self, text: str) -> bool:
        """Check if text contains prompt injection patterns."""
        for pattern in self.injection_compiled:
            if pattern.search(text):
                return True
        return False

    def sanitize_html(self, text: str) -> str:
        """Escape HTML entities in text."""
        from html import escape

        return escape(text)

    def validate_and_sanitize(self, text: str) -> Tuple[str, List[str]]:
        """Validate and sanitize text, returning cleaned text and list of issues found."""
        issues: List[str] = []

        # Check for null bytes
        if "\x00" in text:
            issues.append("null_bytes")
            text = text.replace("\x00", "")

        # Check for control characters
        control_chars = "".join(chr(i) for i in range(32) if i not in (9, 10, 13))
        if any(c in text for c in control_chars):
            issues.append("control_characters")
            for c in control_chars:
                text = text.replace(c, "")

        # Check for dangerous content
        if self.contains_dangerous_content(text):
            issues.append("dangerous_content")
            text = self.sanitize_html(text)

        # Check for prompt injection (log but don't modify)
        if self.contains_prompt_injection(text):
            issues.append("prompt_injection_detected")

        return text.strip(), issues


# =============================================================================
# Rate Limiting
# =============================================================================


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    requests_per_minute_per_user: int = Field(default=10, ge=1, le=100)
    requests_per_hour_per_user: int = Field(default=100, ge=10, le=1000)
    requests_per_minute_per_channel: int = Field(default=60, ge=1, le=1000)
    bucket_capacity: int = Field(default=20, description="Burst capacity")
    refill_rate: float = Field(default=1.0, description="Tokens per second")


class TokenBucket:
    """Token bucket for rate limiting."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = datetime.now(timezone.utc)
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> Tuple[bool, Dict[str, Any]]:
        """Try to consume tokens from the bucket.

        Returns:
            (allowed, metadata) tuple
        """

        with self._lock:
            now = datetime.now(timezone.utc)
            elapsed = (now - self.last_refill).total_seconds()

            # Refill tokens
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, {"tokens_remaining": int(self.tokens)}

            tokens_needed = tokens - self.tokens
            retry_after = int(tokens_needed / self.refill_rate) + 1
            return False, {"retry_after_seconds": retry_after, "tokens_remaining": 0}


# =============================================================================
# Error Factory
# =============================================================================


class ErrorFactory:
    """Factory for creating standardized gateway errors."""

    @staticmethod
    def rate_limit_exceeded(
        limit: int, window_seconds: int, retry_after_seconds: int
    ) -> "GatewayError":
        from app.channels.models import ErrorCode, GatewayError

        return GatewayError(
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            error_message=f"Rate limit exceeded. Max {limit} per {window_seconds}s.",
            details={
                "limit": limit,
                "window": window_seconds,
                "retry_after": retry_after_seconds,
            },
            recoverable=True,
        )

    @staticmethod
    def invalid_message(reason: str) -> "GatewayError":
        from app.channels.models import ErrorCode, GatewayError

        return GatewayError(
            error_code=ErrorCode.INVALID_MESSAGE,
            error_message=f"Invalid message: {reason}",
            details={"reason": reason},
            recoverable=False,
        )

    @staticmethod
    def authentication_failed(reason: str) -> "GatewayError":
        from app.channels.models import ErrorCode, GatewayError

        return GatewayError(
            error_code=ErrorCode.AUTHENTICATION_FAILED,
            error_message=f"Authentication failed: {reason}",
            details={"reason": reason},
            recoverable=False,
        )

    @staticmethod
    def rag_service_error(original_error: str) -> "GatewayError":
        from app.channels.models import ErrorCode, GatewayError

        logger.error("RAG service failure: %s", original_error)
        return GatewayError(
            error_code=ErrorCode.RAG_SERVICE_ERROR,
            error_message="Failed to generate response",
            details={"reason": "internal_service_error"},
            recoverable=True,
        )

    @staticmethod
    def pii_detected(pii_types: List[str]) -> "GatewayError":
        from app.channels.models import ErrorCode, GatewayError

        return GatewayError(
            error_code=ErrorCode.PII_DETECTED,
            error_message="Personal information detected. Please remove sensitive data.",
            details={"pii_types": pii_types},
            recoverable=False,
        )

    @staticmethod
    def service_unavailable(reason: str) -> "GatewayError":
        from app.channels.models import ErrorCode, GatewayError

        return GatewayError(
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            error_message=f"Service unavailable: {reason}",
            details={"reason": reason},
            recoverable=True,
        )
