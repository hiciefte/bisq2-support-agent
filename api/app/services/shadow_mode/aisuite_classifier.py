"""AISuite LLM classifier with security hardening.

This module provides LLM-based message classification using AISuite for
provider-agnostic LLM access, with comprehensive security features:
- Input validation (Pydantic schemas)
- Per-user rate limiting
- Circuit breaker pattern
- PII redaction
- Hash-only caching (GDPR compliant)
- Error sanitization
"""

import hashlib
import json
import logging
import unicodedata
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Tuple

import aisuite as ai  # type: ignore[import-untyped]
from app.core.config import Settings
from app.core.pii_filter import PIIFilter
from app.services.shadow_mode.classification_prompts import (
    ClassificationPromptBuilder,
    get_system_prompt,
)
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for Input/Output Validation
# ============================================================================


class ClassificationInput(BaseModel):
    """Validated input for message classification."""

    message: str = Field(..., min_length=1, max_length=2000)
    sender_id: str = Field(..., min_length=1, max_length=100)
    prev_messages: List[str] = Field(default_factory=list, max_length=5)

    @field_validator("message", "sender_id")
    @classmethod
    def normalize_unicode(cls, v: str) -> str:
        """Normalize Unicode to prevent homograph attacks.

        Args:
            v: Input string

        Returns:
            NFKC-normalized string
        """
        return unicodedata.normalize("NFKC", v)


class ConfidenceBreakdown(BaseModel):
    """Multidimensional confidence score with hierarchical dependencies."""

    keyword_match: int = Field(..., ge=0, le=25)
    syntax_pattern: int = Field(..., ge=0, le=25)
    semantic_clarity: int = Field(..., ge=0, le=30)
    context_alignment: int = Field(..., ge=0, le=20)

    @property
    def total(self) -> int:
        """Calculate total confidence (0-100).

        Returns:
            Sum of all confidence components
        """
        return (
            self.keyword_match
            + self.syntax_pattern
            + self.semantic_clarity
            + self.context_alignment
        )


class ClassificationResult(BaseModel):
    """Validated classification result."""

    role: Literal["USER_QUESTION", "STAFF_RESPONSE"]
    confidence_breakdown: ConfidenceBreakdown
    confidence: float = Field(..., ge=0.0, le=1.0)


# ============================================================================
# Security Components
# ============================================================================


class RateLimiter:
    """Per-user token bucket rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, deque] = defaultdict(deque)

    def is_allowed(self, user_id: str) -> bool:
        """Check if user is allowed to make request.

        Args:
            user_id: User identifier

        Returns:
            True if allowed, False if rate limited
        """
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.window)

        # Remove expired requests
        while self.requests[user_id] and self.requests[user_id][0] < cutoff:
            self.requests[user_id].popleft()

        # Check limit
        if len(self.requests[user_id]) >= self.max_requests:
            return False

        # Allow and record
        self.requests[user_id].append(now)
        return True


class CircuitBreaker:
    """Circuit breaker to prevent cascade failures."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None

    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests).

        Returns:
            True if circuit is open, False if closed
        """
        if self.failure_count < self.failure_threshold:
            return False

        # Check if recovery timeout has passed
        if self.last_failure_time:
            elapsed = (datetime.now() - self.last_failure_time).total_seconds()
            if elapsed >= self.recovery_timeout:
                # Reset for recovery attempt
                self.failure_count = 0
                self.last_failure_time = None
                return False

        return True

    def record_success(self):
        """Record successful request."""
        self.failure_count = 0
        self.last_failure_time = None

    def record_failure(self):
        """Record failed request."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()


# ============================================================================
# Main Classifier
# ============================================================================


class AISuiteClassifier:
    """LLM-based classifier with security hardening."""

    def __init__(self, ai_client: ai.Client, settings: Settings):
        """Initialize classifier.

        Args:
            ai_client: AISuite client instance
            settings: Application settings
        """
        self.client = ai_client
        self.settings = settings
        self.model = settings.LLM_CLASSIFICATION_MODEL
        self.temperature = settings.LLM_CLASSIFICATION_TEMPERATURE
        self.threshold = settings.LLM_CLASSIFICATION_THRESHOLD

        # Security components
        self.rate_limiter = RateLimiter(
            max_requests=settings.LLM_CLASSIFICATION_RATE_LIMIT_REQUESTS,
            window_seconds=settings.LLM_CLASSIFICATION_RATE_LIMIT_WINDOW,
        )
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        self.pii_filter = PIIFilter()

        # Prompt builder
        self.prompt_builder = ClassificationPromptBuilder(include_few_shot=True)

        # Hash-only cache (GDPR compliant)
        self._cache: Dict[str, Tuple[dict, datetime]] = {}
        self.cache_size = settings.LLM_CLASSIFICATION_CACHE_SIZE
        self.cache_ttl_hours = settings.LLM_CLASSIFICATION_CACHE_TTL_HOURS

    def _build_cache_key(
        self, message: str, prev_messages: Optional[List[str]] = None
    ) -> str:
        """Build privacy-preserving cache key using SHA-256.

        Args:
            message: Message to classify
            prev_messages: Optional previous messages for context

        Returns:
            SHA-256 hash of message+context (no plaintext stored)
        """
        content = message
        if prev_messages:
            content += "|" + "|".join(prev_messages)

        return hashlib.sha256(content.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> Optional[dict]:
        """Get classification from cache if not expired.

        Args:
            cache_key: SHA-256 hash key

        Returns:
            Cached result if exists and not expired, None otherwise
        """
        if cache_key not in self._cache:
            return None

        result, timestamp = self._cache[cache_key]
        age = (datetime.now() - timestamp).total_seconds() / 3600  # Hours

        if age > self.cache_ttl_hours:
            # Expired - remove
            del self._cache[cache_key]
            return None

        return result

    def _add_to_cache(self, cache_key: str, result: dict):
        """Add classification result to cache.

        Args:
            cache_key: SHA-256 hash key
            result: Classification result
        """
        # Evict oldest if cache full
        if len(self._cache) >= self.cache_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        self._cache[cache_key] = (result, datetime.now())

    async def classify(
        self,
        message: str,
        sender_id: str,
        prev_messages: Optional[List[str]] = None,
    ) -> dict:
        """Classify message with security hardening.

        Args:
            message: Message to classify
            sender_id: User identifier for rate limiting
            prev_messages: Optional previous messages for context

        Returns:
            Classification result dict

        Raises:
            ValueError: If input validation fails
            Exception: If rate limited or circuit breaker open
        """
        # 1. Input validation
        validated_input = ClassificationInput(
            message=message,
            sender_id=sender_id,
            prev_messages=prev_messages or [],
        )

        # 2. Rate limit check
        if not self.rate_limiter.is_allowed(sender_id):
            raise Exception(f"Rate limit exceeded for user {sender_id}")

        # 3. Circuit breaker check
        if self.circuit_breaker.is_open():
            raise Exception("Circuit breaker open - service temporarily unavailable")

        # 4. Check cache
        cache_key = self._build_cache_key(validated_input.message, prev_messages)
        if cached := self._get_from_cache(cache_key):
            logger.debug(f"Cache hit for message hash: {cache_key[:16]}...")
            return cached

        # 5. PII redaction
        sanitized_message = self.pii_filter._redact_string(validated_input.message)

        # 6. Build prompt
        prompt = self.prompt_builder.build_prompt(
            sanitized_message, prev_messages=prev_messages
        )

        # 7. Call LLM with retry
        try:
            response_text = await self._call_llm_with_retry(prompt)
            self.circuit_breaker.record_success()
        except Exception as e:
            self.circuit_breaker.record_failure()
            logger.exception(f"LLM classification failed: {e}")
            raise

        # 8. Parse and validate result
        result = self._parse_response(response_text)

        # 9. Cache result
        self._add_to_cache(cache_key, result)

        return result

    async def _call_llm_with_retry(self, prompt: str, max_retries: int = 2) -> str:
        """Call LLM with exponential backoff retry.

        Args:
            prompt: Prompt to send
            max_retries: Maximum retry attempts

        Returns:
            LLM response text

        Raises:
            Exception: If all retries fail
        """
        import asyncio
        import inspect

        for attempt in range(max_retries + 1):
            try:
                messages = [
                    {"role": "system", "content": get_system_prompt()},
                    {"role": "user", "content": prompt},
                ]

                # Call LLM - handle both sync and async clients (for testing)
                create_func = self.client.chat.completions.create
                if inspect.iscoroutinefunction(create_func):
                    response = await create_func(
                        model=self.model,
                        messages=messages,
                        temperature=self.temperature,
                    )
                else:
                    response = await asyncio.to_thread(
                        create_func,
                        model=self.model,
                        messages=messages,
                        temperature=self.temperature,
                    )

                return response.choices[0].message.content

            except Exception as e:
                if attempt == max_retries:
                    raise

                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2**attempt
                logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {wait_time}s: {e}"
                )
                await asyncio.sleep(wait_time)

        raise Exception("Max retries exceeded")

    def _parse_response(self, response_text: str) -> dict:
        """Parse and validate LLM response.

        Args:
            response_text: Raw LLM response

        Returns:
            Validated classification dict

        Raises:
            ValueError: If response cannot be parsed or validated
        """
        try:
            # Parse JSON
            data = json.loads(response_text)

            # Validate with Pydantic
            result = ClassificationResult(**data)

            return {
                "role": result.role,
                "confidence_breakdown": {
                    "keyword_match": result.confidence_breakdown.keyword_match,
                    "syntax_pattern": result.confidence_breakdown.syntax_pattern,
                    "semantic_clarity": result.confidence_breakdown.semantic_clarity,
                    "context_alignment": result.confidence_breakdown.context_alignment,
                },
                "confidence": result.confidence,
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            raise ValueError(f"Invalid JSON response from LLM: {response_text[:100]}")
        except Exception as e:
            logger.error(f"Failed to validate LLM response: {e}")
            raise ValueError(f"Invalid classification format: {e}")
