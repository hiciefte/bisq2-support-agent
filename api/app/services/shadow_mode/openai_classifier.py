"""
OpenAI-based message classifier for Matrix support messages.

Provides efficient batching, error handling, caching, and cost optimization.
"""

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from .classification_prompts import adjust_confidence, build_classification_prompt

logger = logging.getLogger(__name__)


class ClassificationCache:
    """
    LRU cache for message classifications to reduce API costs.

    Cache key: SHA256 hash of message content
    Cache invalidation: TTL-based (default 24 hours)
    """

    def __init__(self, max_size: int = 10000, ttl_hours: int = 24):
        self.cache: OrderedDict[str, Tuple[dict, datetime]] = OrderedDict()
        self.max_size = max_size
        self.ttl = timedelta(hours=ttl_hours)
        self.hits = 0
        self.misses = 0

    def _make_key(self, message: str) -> str:
        """Generate cache key from message content."""
        return hashlib.sha256(message.encode()).hexdigest()

    def get(self, message: str) -> Optional[dict]:
        """Retrieve classification from cache if valid."""
        key = self._make_key(message)

        if key not in self.cache:
            self.misses += 1
            return None

        classification, timestamp = self.cache[key]

        # Check TTL
        if datetime.now() - timestamp > self.ttl:
            del self.cache[key]
            self.misses += 1
            return None

        # Move to end (LRU)
        self.cache.move_to_end(key)
        self.hits += 1
        return classification

    def set(self, message: str, classification: dict):
        """Store classification in cache."""
        key = self._make_key(message)

        # Evict oldest if at capacity
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)

        self.cache[key] = (classification, datetime.now())

    def get_stats(self) -> dict:
        """Return cache performance statistics."""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate_percent": round(hit_rate, 2),
            "ttl_hours": self.ttl.total_seconds() / 3600,
        }

    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0


class OpenAIMessageClassifier:
    """
    Classify Matrix support messages using OpenAI API.

    Features:
    - Async batch classification with configurable concurrency
    - Intelligent retry with exponential backoff
    - LRU caching to reduce API costs
    - Structured JSON output parsing
    - Comprehensive error handling
    - Cost tracking and optimization
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_retries: int = 3,
        timeout: int = 30,
        enable_cache: bool = True,
        cache_size: int = 10000,
        cache_ttl_hours: int = 24,
        max_concurrent: int = 5,
    ):
        self.client = AsyncOpenAI(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_concurrent = max_concurrent

        # Caching
        self.enable_cache = enable_cache
        self.cache = (
            ClassificationCache(max_size=cache_size, ttl_hours=cache_ttl_hours)
            if enable_cache
            else None
        )

        # Cost tracking
        self.total_requests = 0
        self.total_tokens = 0
        self.cache_savings = 0

        # Model pricing (per 1M tokens as of 2025-01)
        self.pricing = {
            "gpt-4o-mini": {
                "input": 0.150,
                "output": 0.600,
            },  # $0.15/$0.60 per 1M tokens
            "gpt-4o": {"input": 2.50, "output": 10.00},  # $2.50/$10 per 1M tokens
        }

    async def classify_message(
        self, message: str, use_few_shot: bool = True, skip_cache: bool = False
    ) -> Tuple[str, float, str]:
        """
        Classify a single message.

        Args:
            message: The message text to classify
            use_few_shot: Whether to include few-shot examples in prompt
            skip_cache: Force API call even if cached result exists

        Returns:
            Tuple of (role, confidence, reasoning)
            - role: "STAFF" or "USER"
            - confidence: 0-100 float
            - reasoning: Brief explanation from LLM

        Raises:
            ValueError: If message is empty or classification fails
        """
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")

        # Check cache first
        if self.enable_cache and not skip_cache:
            cached = self.cache.get(message)
            if cached:
                self.cache_savings += 1
                logger.debug(f"Cache hit for message: {message[:50]}...")
                return (
                    cached["role"],
                    cached["confidence"],
                    cached.get("reasoning", ""),
                )

        # Build prompt
        messages = build_classification_prompt(message, use_few_shot=use_few_shot)

        # Call OpenAI API with retries
        classification = await self._call_openai_with_retry(messages)

        # Adjust confidence based on reasoning quality
        classification = adjust_confidence(classification)

        # Cache result
        if self.enable_cache:
            self.cache.set(message, classification)

        return (
            classification["role"],
            classification["confidence"],
            classification.get("reasoning", ""),
        )

    async def classify_batch(
        self, messages: List[str], use_few_shot: bool = True, skip_cache: bool = False
    ) -> List[Tuple[str, float, str]]:
        """
        Classify multiple messages efficiently with batching.

        Uses asyncio.gather for parallel API calls with concurrency limiting.

        Args:
            messages: List of message texts to classify
            use_few_shot: Whether to include few-shot examples
            skip_cache: Force API calls even if cached results exist

        Returns:
            List of (role, confidence, reasoning) tuples matching input order
        """
        if not messages:
            return []

        # Remove duplicates while preserving order
        seen = set()
        unique_messages = []
        for msg in messages:
            if msg not in seen:
                seen.add(msg)
                unique_messages.append(msg)

        logger.info(
            f"Classifying batch of {len(unique_messages)} unique messages (from {len(messages)} total)"
        )

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def classify_with_semaphore(msg: str) -> Tuple[str, float, str]:
            async with semaphore:
                return await self.classify_message(
                    msg, use_few_shot=use_few_shot, skip_cache=skip_cache
                )

        # Execute in parallel with concurrency limit
        tasks = [classify_with_semaphore(msg) for msg in unique_messages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any errors in results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Classification failed for message {i}: {result}")
                # Fallback to USER with low confidence
                final_results.append(("USER", 50.0, f"Error: {str(result)}"))
            else:
                final_results.append(result)

        return final_results

    async def _call_openai_with_retry(
        self, messages: List[Dict], retry_count: int = 0
    ) -> dict:
        """
        Call OpenAI API with exponential backoff retry.

        Args:
            messages: Chat completion messages
            retry_count: Current retry attempt number

        Returns:
            Parsed classification dict with role, confidence, reasoning

        Raises:
            APIError: If all retries are exhausted
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=150,  # Short response (JSON only)
                response_format={"type": "json_object"},  # Force JSON output
            )

            # Track usage
            self.total_requests += 1
            if hasattr(response, "usage"):
                self.total_tokens += response.usage.total_tokens

            # Parse JSON response
            content = response.choices[0].message.content
            classification = json.loads(content)

            # Validate required fields
            if "role" not in classification or "confidence" not in classification:
                raise ValueError(f"Invalid classification response: {classification}")

            # Normalize role to uppercase
            classification["role"] = classification["role"].upper()

            # Ensure confidence is numeric
            classification["confidence"] = float(classification["confidence"])

            return classification

        except RateLimitError as e:
            if retry_count < self.max_retries:
                wait_time = 2**retry_count  # Exponential backoff: 1s, 2s, 4s
                logger.warning(
                    f"Rate limit hit, retrying in {wait_time}s (attempt {retry_count + 1}/{self.max_retries})"
                )
                await asyncio.sleep(wait_time)
                return await self._call_openai_with_retry(messages, retry_count + 1)
            raise

        except APITimeoutError as e:
            if retry_count < self.max_retries:
                wait_time = 2**retry_count
                logger.warning(
                    f"API timeout, retrying in {wait_time}s (attempt {retry_count + 1}/{self.max_retries})"
                )
                await asyncio.sleep(wait_time)
                return await self._call_openai_with_retry(messages, retry_count + 1)
            raise

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            # Return fallback classification
            return {
                "role": "USER",
                "confidence": 50,
                "reasoning": "JSON parse error, defaulting to USER",
            }

        except Exception as e:
            logger.error(f"Unexpected error in OpenAI classification: {e}")
            if retry_count < self.max_retries:
                wait_time = 2**retry_count
                await asyncio.sleep(wait_time)
                return await self._call_openai_with_retry(messages, retry_count + 1)
            raise

    def get_cost_estimate(self) -> dict:
        """
        Calculate estimated API costs based on usage.

        Returns:
            Dict with cost breakdown and savings from caching
        """
        if self.model not in self.pricing:
            return {"error": f"Pricing not available for model {self.model}"}

        # Estimate token distribution (rough average)
        avg_input_tokens = 600  # System prompt + few-shot + message
        avg_output_tokens = 50  # JSON response

        input_cost = (
            (self.total_tokens * 0.7) / 1_000_000 * self.pricing[self.model]["input"]
        )
        output_cost = (
            (self.total_tokens * 0.3) / 1_000_000 * self.pricing[self.model]["output"]
        )
        total_cost = input_cost + output_cost

        # Calculate savings from cache
        saved_requests = self.cache_savings
        saved_tokens = saved_requests * (avg_input_tokens + avg_output_tokens)
        saved_cost = (
            (saved_tokens * 0.7) / 1_000_000 * self.pricing[self.model]["input"]
        )
        saved_cost += (
            (saved_tokens * 0.3) / 1_000_000 * self.pricing[self.model]["output"]
        )

        return {
            "model": self.model,
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(total_cost, 4),
            "cache_savings": {
                "cached_requests": saved_requests,
                "estimated_saved_usd": round(saved_cost, 4),
                "cache_hit_rate_percent": (
                    self.cache.get_stats()["hit_rate_percent"] if self.cache else 0
                ),
            },
            "pricing_per_1m_tokens": self.pricing[self.model],
        }

    def get_cache_stats(self) -> dict:
        """Get cache performance statistics."""
        if not self.enable_cache:
            return {"enabled": False}

        stats = self.cache.get_stats()
        stats["enabled"] = True
        return stats

    def clear_cache(self):
        """Clear classification cache."""
        if self.cache:
            self.cache.clear()
            logger.info("Classification cache cleared")
