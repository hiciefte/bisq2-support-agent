"""Pre-LLM message filtering and normalization.

Filters obvious noise before sending to LLM and normalizes message formatting
for consistent processing. Includes security features to prevent ReDoS attacks.

Platform Compatibility:
    The regex timeout mechanism uses signal.SIGALRM which is Unix-only.
    On Windows or other non-Unix platforms, the timeout protection will not work
    and regexes will run without time limits. The module will still function
    but without ReDoS protection.

Thread Safety:
    The SIGALRM-based timeout is process-global and not thread-safe.
    In multi-threaded environments, use this module only from the main thread
    or consider alternative timeout mechanisms.
"""

import logging
import re
import signal
from functools import wraps
from typing import Any, Callable, Dict, List, Tuple

from app.core.config import get_settings
from app.services.llm_extraction.metrics import messages_filtered_total

logger = logging.getLogger(__name__)


class RegexTimeout(Exception):
    """Raised when regex execution exceeds timeout."""

    pass


def regex_with_timeout(timeout_seconds: float = 0.5) -> Callable:
    """Decorator for regex operations with timeout protection.

    Note:
        This decorator uses signal.SIGALRM which is Unix-only and not thread-safe.
        On non-Unix platforms, the function runs without timeout protection.

    Args:
        timeout_seconds: Maximum time allowed for regex execution

    Returns:
        Decorated function with timeout protection (Unix) or no-op wrapper (non-Unix)
    """

    def decorator(func: Callable) -> Callable:
        # Check if platform supports SIGALRM
        if not hasattr(signal, "SIGALRM"):
            # Non-Unix platform - return function as-is without timeout
            logger.warning(
                "SIGALRM not available on this platform. "
                "Regex timeout protection disabled."
            )
            return func

        @wraps(func)
        def wrapper(*args, **kwargs):
            def handler(signum, frame):  # noqa: ARG001
                raise RegexTimeout(f"Regex execution timeout after {timeout_seconds}s")

            # Store old handler and set new one
            old_handler = signal.signal(signal.SIGALRM, handler)
            # Use setitimer for sub-second precision
            signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
            try:
                return func(*args, **kwargs)
            finally:
                # Disable timer and restore handler
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old_handler)

        return wrapper

    return decorator


class SafeRegexMatcher:
    """Regex matcher with timeout and input limits.

    Note:
        The timeout mechanism uses SIGALRM which is process-global and not
        thread-safe. This class should only be used from the main thread in
        multi-threaded applications. On non-Unix platforms, timeout protection
        is disabled.
    """

    def __init__(
        self,
        patterns: List[Tuple[str, str]],
        max_input_length: int = 10000,
        timeout_seconds: float = 0.5,
    ):
        """Initialize matcher with patterns.

        Args:
            patterns: List of (pattern, reason) tuples
            max_input_length: Maximum input length before truncation
            timeout_seconds: Timeout per pattern match
        """
        self.max_input_length = max_input_length
        self.timeout_seconds = timeout_seconds
        self._compiled: List[Tuple[re.Pattern, str]] = []

        for pattern, reason in patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled.append((compiled, reason))
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}': {e}")

    def safe_match(self, text: str) -> Tuple[bool, str]:
        """Match text against patterns with input truncation and timeout.

        Args:
            text: Text to match against patterns

        Returns:
            Tuple of (matched, reason) - reason is empty if no match
        """
        # Truncate input to prevent DoS
        truncated = text[: self.max_input_length]

        for pattern, reason in self._compiled:
            try:
                if self._match_with_timeout(pattern, truncated):
                    return True, reason
            except RegexTimeout:
                logger.warning(f"Regex timeout for pattern: {pattern.pattern[:50]}...")
                continue

        return False, ""

    def _match_with_timeout(self, pattern: re.Pattern, text: str) -> bool:
        """Execute regex match with timeout.

        Uses instance-level timeout_seconds for timeout protection.

        Args:
            pattern: Compiled regex pattern
            text: Text to match

        Returns:
            True if pattern matches text

        Raises:
            RegexTimeout: If regex execution exceeds timeout_seconds
        """

        # Apply timeout wrapper with instance timeout
        @regex_with_timeout(self.timeout_seconds)
        def do_match() -> bool:
            return bool(pattern.search(text))

        return do_match()


def validate_message_input(message: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize message input.

    Args:
        message: Message dictionary with 'body' field

    Returns:
        Sanitized message dictionary
    """
    settings = get_settings()
    body = message.get("body", "")

    # Enforce length limit
    if len(body) > settings.MAX_MESSAGE_LENGTH:
        logger.warning(
            f"Truncating message from {len(body)} to {settings.MAX_MESSAGE_LENGTH}"
        )
        body = body[: settings.MAX_MESSAGE_LENGTH]

    # Remove null bytes
    body = body.replace("\x00", "")

    # Validate UTF-8 encoding
    try:
        body.encode("utf-8").decode("utf-8")
    except UnicodeError:
        body = body.encode("utf-8", errors="ignore").decode("utf-8")

    return {**message, "body": body}


class MessagePreFilter:
    """Filter non-questions before sending to LLM."""

    # Patterns that indicate a message should be filtered
    EXCLUDE_PATTERNS: List[Tuple[str, str]] = [
        # Bot/system messages
        (r"^\[.+\] has joined", "system_join"),
        (r"^\[.+\] has left", "system_leave"),
        (r"^.+ invited .+ to the room", "system_invite"),
        (r"changed the room", "system_room_change"),
        # Standalone greetings (case-insensitive) - handles multi-word greetings
        (
            r"^(hi|hello|hey|gm|gn|sup|good morning|good evening|good afternoon)(\s+\w+)?[\s!.,]*$",
            "greeting",
        ),
        # Pure acknowledgments
        (
            r"^(thanks?|thx|ty|thank you|appreciated?|cheers)[\s!.,]*$",
            "acknowledgment",
        ),
        (
            r"^(ok|okay|alright|got it|understood|cool|nice|great)[\s!.,]*$",
            "acknowledgment",
        ),
        (r"^(yes|no|yep|nope|yeah|nah)[\s!.,]*$", "acknowledgment"),
        # Single emoji or reaction (common emoji ranges)
        (
            r"^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            r"\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF]+$",
            "emoji_only",
        ),
        # URL-only messages
        (r"^https?://[^\s]+$", "url_only"),
        # Punctuation only
        (r"^[.!?,\-_*#@&%$()]+$", "punctuation_only"),
    ]

    MIN_MESSAGE_LENGTH = 10  # Skip very short messages without question marks

    def __init__(self):
        """Initialize pre-filter with compiled patterns."""
        settings = get_settings()
        self._matcher = SafeRegexMatcher(
            self.EXCLUDE_PATTERNS,
            max_input_length=settings.MAX_MESSAGE_LENGTH,
            timeout_seconds=settings.REGEX_TIMEOUT_SECONDS,
        )

    def should_filter(self, message: Dict[str, Any]) -> Tuple[bool, str]:
        """Check if a message should be filtered out.

        Args:
            message: Message dictionary with 'body' field

        Returns:
            Tuple of (should_filter, reason)
        """
        # Validate and sanitize input first
        message = validate_message_input(message)
        body = message.get("body", "").strip()

        # Empty messages
        if not body:
            return True, "empty_message"

        # Check against exclusion patterns using safe matcher
        matched, reason = self._matcher.safe_match(body)
        if matched:
            return True, reason

        # Short messages without question indicators
        if len(body) < self.MIN_MESSAGE_LENGTH and "?" not in body:
            return True, "too_short"

        return False, ""

    def filter_messages(
        self, messages: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
        """Filter a list of messages.

        Args:
            messages: List of message dictionaries

        Returns:
            Tuple of (passed_messages, filtered_messages_with_reasons)
        """
        passed = []
        filtered = []

        for msg in messages:
            should_filter, reason = self.should_filter(msg)
            if should_filter:
                filtered.append((msg, reason))
                # Record metric for filtered message
                messages_filtered_total.labels(reason=reason).inc()
            else:
                passed.append(msg)

        return passed, filtered


class MessageNormalizer:
    """Normalize message text before LLM processing."""

    def __init__(self):
        """Initialize normalizer with compiled patterns."""
        # Pre-compile patterns for efficiency
        self._bold_pattern = re.compile(r"\*\*(.+?)\*\*")
        self._italic_pattern = re.compile(r"\*(.+?)\*")
        self._inline_code_pattern = re.compile(r"`(.+?)`")
        self._code_block_pattern = re.compile(r"```[\s\S]*?```")
        self._whitespace_pattern = re.compile(r"\s+")

    def normalize(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a message for consistent LLM processing.

        Handles:
        - Markdown formatting removal
        - Whitespace normalization
        - Quote normalization

        Args:
            message: Message dictionary with 'body' field

        Returns:
            Normalized message dictionary
        """
        # Validate input first
        message = validate_message_input(message)
        body = message.get("body", "")

        # Remove markdown formatting
        body = self._code_block_pattern.sub("", body)  # Remove code blocks first
        body = self._bold_pattern.sub(r"\1", body)
        body = self._italic_pattern.sub(r"\1", body)
        body = self._inline_code_pattern.sub(r"\1", body)

        # Normalize whitespace
        body = self._whitespace_pattern.sub(" ", body).strip()

        # Normalize smart quotes to ASCII (using explicit Unicode escapes)
        # LEFT DOUBLE QUOTATION MARK (\u201c) and RIGHT DOUBLE QUOTATION MARK (\u201d)
        body = body.replace("\u201c", '"').replace("\u201d", '"')
        # LEFT SINGLE QUOTATION MARK (\u2018) and RIGHT SINGLE QUOTATION MARK (\u2019)
        body = body.replace("\u2018", "'").replace("\u2019", "'")

        return {**message, "body": body}

    def normalize_batch(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Normalize a batch of messages.

        Args:
            messages: List of message dictionaries

        Returns:
            List of normalized message dictionaries
        """
        return [self.normalize(msg) for msg in messages]
