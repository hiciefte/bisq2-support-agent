"""Query result caching for RAG pipeline.

This module provides caching for complete query results to avoid
redundant processing for identical queries.
"""

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueryCacheEntry:
    """A cache entry for query results."""

    result: dict[str, Any]
    timestamp: float


class QueryCacheManager:
    """Manages caching of complete query results.

    Provides LRU caching with TTL for query results, considering
    both the query text and optional context (e.g., protocol version).
    """

    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: float = 300.0,
    ):
        """Initialize query cache manager.

        Args:
            max_size: Maximum number of cached query results
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds

        # LRU cache using OrderedDict
        self._cache: OrderedDict[str, QueryCacheEntry] = OrderedDict()
        self._lock = threading.RLock()

        # Statistics
        self._hits = 0
        self._misses = 0

        logger.info(
            f"QueryCacheManager initialized: max_size={max_size}, ttl={ttl_seconds}s"
        )

    def _get_cache_key(self, query: str, context: dict[str, Any] | None = None) -> str:
        """Generate a cache key for query and context.

        Args:
            query: Query text
            context: Optional context dict (e.g., protocol version)

        Returns:
            SHA256 hash key
        """
        key_data: dict[str, Any] = {"query": query}
        if context:
            key_data["context"] = context

        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

    def _is_expired(self, entry: QueryCacheEntry) -> bool:
        """Check if a cache entry has expired."""
        return (time.time() - entry.timestamp) > self._ttl_seconds

    def get(
        self, query: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Get cached query result if available and not expired.

        Args:
            query: Query text
            context: Optional context dict

        Returns:
            Cached result or None if not found/expired
        """
        key = self._get_cache_key(query, context)

        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if not self._is_expired(entry):
                    # Move to end for LRU ordering
                    self._cache.move_to_end(key)
                    self._hits += 1
                    logger.debug(f"Cache hit for query: {query[:50]}...")
                    return entry.result
                else:
                    # Remove expired entry
                    del self._cache[key]
                    logger.debug(f"Cache expired for query: {query[:50]}...")

            self._misses += 1
            return None

    def set(
        self,
        query: str,
        result: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> None:
        """Store query result in cache.

        Args:
            query: Query text
            result: Result dict to cache
            context: Optional context dict
        """
        key = self._get_cache_key(query, context)

        with self._lock:
            # Remove oldest entries if at capacity
            while len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)

            self._cache[key] = QueryCacheEntry(
                result=result,
                timestamp=time.time(),
            )
            logger.debug(f"Cached result for query: {query[:50]}...")

    def warm(self, queries: list[tuple[str, dict[str, Any]]]) -> None:
        """Pre-warm cache with common queries.

        Args:
            queries: List of (query, result) tuples
        """
        for query, result in queries:
            self.set(query, result)

        logger.info(f"Cache warmed with {len(queries)} queries")

    def clear(self) -> None:
        """Clear all cached results."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
        logger.info("Query cache cleared")

    def get_statistics(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, hit_rate, size, max_size
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl_seconds,
            }

    @property
    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)
