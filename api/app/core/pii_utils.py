"""Centralized PII (Personally Identifiable Information) utilities.

This module provides a single source of truth for PII pattern definitions
and context-specific redaction/detection functions.

Pattern categories:
- PII_CORE_PATTERNS: Common identifiers used across all contexts
- PII_LOGGING_PATTERNS: Aggressive redaction for log safety
- PII_DETECTION_PATTERNS: Comprehensive patterns for monitoring
- PII_LLM_PATTERNS: Minimal-loss anonymization for LLM input

Usage:
    from app.core.pii_utils import redact_for_logs, redact_for_llm, detect_pii

    # For logging (aggressive)
    safe_log = redact_for_logs(user_message)

    # For LLM input (preserves useful context)
    anonymized = redact_for_llm(chat_message)

    # For monitoring/detection
    found_pii = detect_pii(text)
    if contains_pii(text):
        handle_pii_detected()
"""

import re
from typing import Dict, List, Pattern

# =============================================================================
# CORE PATTERNS - Common identifiers used by multiple contexts
# =============================================================================

PII_CORE_PATTERNS: Dict[str, str] = {
    # Email addresses
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    # IPv4 addresses
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    # Bitcoin addresses (legacy, segwit, taproot)
    "btc_address": r"\b(?:bc1[a-z0-9]{38,58}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})\b",
}

# =============================================================================
# LOGGING PATTERNS - Aggressive redaction for log safety
# =============================================================================

PII_LOGGING_PATTERNS: Dict[str, str] = {
    **PII_CORE_PATTERNS,
    # Matrix access tokens (syt_*)
    "matrix_token": r"syt_[a-zA-Z0-9_-]+",
    # Phone numbers (various formats)
    "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
    # Credit card numbers
    "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
    # IPv6 addresses
    "ipv6_address": r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
    # API keys (generic pattern)
    "api_key": r"api[_-]?key[_-]?[:=]\s*['\"]?[\w\-]{20,}['\"]?",
    # Passwords in URLs or config
    "password": r"(password|passwd|pwd)[:=][^\s&]+",
}

# =============================================================================
# DETECTION PATTERNS - Comprehensive patterns for monitoring
# =============================================================================

PII_DETECTION_PATTERNS: Dict[str, str] = {
    **PII_LOGGING_PATTERNS,
    # Matrix user IDs
    "matrix_id": r"@[a-zA-Z0-9._-]+:[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    # UUIDs
    "uuid": r"\b[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\b",
    # Social Security Numbers (US)
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
}

# =============================================================================
# LLM PATTERNS - Minimal-loss anonymization for LLM input
# =============================================================================

PII_LLM_PATTERNS: Dict[str, str] = {
    # Focus on high-risk PII that should never reach LLM
    "email": PII_CORE_PATTERNS["email"],
    "btc_address": PII_CORE_PATTERNS["btc_address"],
    "ip_address": PII_CORE_PATTERNS["ip_address"],
}

# =============================================================================
# COMPILED PATTERN CACHES
# =============================================================================

_compiled_logging: Dict[str, Pattern] = {}
_compiled_llm: Dict[str, Pattern] = {}
_compiled_detection: Dict[str, Pattern] = {}


def _get_compiled_patterns(
    patterns: Dict[str, str], cache: Dict[str, Pattern]
) -> Dict[str, Pattern]:
    """Get or create compiled regex patterns."""
    if not cache:
        for name, pattern in patterns.items():
            # Apply case-insensitive matching for credential-related patterns
            flags = re.IGNORECASE if name.lower() in {"api_key", "password"} else 0
            cache[name] = re.compile(pattern, flags)
    return cache


# =============================================================================
# REDACTION FUNCTIONS
# =============================================================================


def redact_for_logs(text: str) -> str:
    """Aggressively redact PII from text for safe logging.

    Uses PII_LOGGING_PATTERNS for comprehensive redaction.

    Args:
        text: Text potentially containing PII

    Returns:
        Text with all detected PII replaced with [TYPE] placeholders
    """
    if not text:
        return text

    patterns = _get_compiled_patterns(PII_LOGGING_PATTERNS, _compiled_logging)
    result = text

    for name, pattern in patterns.items():
        placeholder = f"[{name.upper()}]"
        # Special handling for password pattern (capture group)
        if name == "password":
            result = pattern.sub(r"\1=[REDACTED]", result)
        else:
            result = pattern.sub(placeholder, result)

    return result


def redact_for_llm(text: str) -> str:
    """Minimally redact PII from text for LLM input.

    Uses PII_LLM_PATTERNS for minimal-loss anonymization that preserves
    useful context while removing high-risk identifiers.

    Args:
        text: Text potentially containing PII

    Returns:
        Text with high-risk PII replaced with [TYPE] placeholders
    """
    if not text:
        return text

    patterns = _get_compiled_patterns(PII_LLM_PATTERNS, _compiled_llm)
    result = text

    for name, pattern in patterns.items():
        placeholder = f"[{name.upper()}]"
        result = pattern.sub(placeholder, result)

    return result


# =============================================================================
# DETECTION FUNCTIONS
# =============================================================================


def detect_pii(text: str) -> Dict[str, List[str]]:
    """Detect all PII patterns in text.

    Uses PII_DETECTION_PATTERNS for comprehensive detection.

    Args:
        text: Text to scan for PII

    Returns:
        Dictionary mapping PII type to list of detected instances
    """
    if not text:
        return {}

    patterns = _get_compiled_patterns(PII_DETECTION_PATTERNS, _compiled_detection)
    detections: Dict[str, List[str]] = {}

    for name, pattern in patterns.items():
        matches = pattern.findall(text)
        if matches:
            # Handle tuple results from patterns with groups
            if matches and isinstance(matches[0], tuple):
                matches = [m[0] if m[0] else m[-1] for m in matches]
            detections[name] = list(set(matches))

    return detections


def contains_pii(text: str) -> bool:
    """Check if text contains any PII.

    Fast boolean check using PII_DETECTION_PATTERNS.

    Args:
        text: Text to check

    Returns:
        True if any PII pattern is detected
    """
    if not text:
        return False

    patterns = _get_compiled_patterns(PII_DETECTION_PATTERNS, _compiled_detection)

    for pattern in patterns.values():
        if pattern.search(text):
            return True

    return False
