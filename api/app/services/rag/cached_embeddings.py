"""Caching wrapper for embeddings providers.

This module provides a caching layer for embedding providers to reduce
API calls and improve latency for repeated queries.
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cache entry with value and timestamp."""

    value: list[float]
    timestamp: float


class CachedEmbeddings(Embeddings):
    """Caching wrapper for any LangChain-compatible embeddings provider.

    Provides LRU caching with TTL for embedding results to reduce
    expensive API calls for repeated queries.
    """

    def __init__(
        self,
        base_embeddings: Embeddings,
        max_cache_size: int = 10000,
        ttl_seconds: float = 3600.0,
    ):
        """Initialize cached embeddings wrapper.

        Args:
            base_embeddings: Underlying embeddings provider
            max_cache_size: Maximum number of cached embeddings
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self._base_embeddings = base_embeddings
        self._max_cache_size = max_cache_size
        self._ttl_seconds = ttl_seconds

        # LRU cache using OrderedDict
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()

        # Statistics
        self._hits = 0
        self._misses = 0

        logger.info(
            f"CachedEmbeddings initialized: max_size={max_cache_size}, ttl={ttl_seconds}s"
        )

    def _get_cache_key(self, text: str) -> str:
        """Generate a cache key for text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _is_expired(self, entry: CacheEntry) -> bool:
        """Check if a cache entry has expired."""
        return (time.time() - entry.timestamp) > self._ttl_seconds

    def _get_from_cache(self, text: str) -> list[float] | None:
        """Get embedding from cache if available and not expired."""
        key = self._get_cache_key(text)

        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if not self._is_expired(entry):
                    # Move to end for LRU ordering
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return entry.value
                else:
                    # Remove expired entry
                    del self._cache[key]

            self._misses += 1
            return None

    def _add_to_cache(self, text: str, embedding: list[float]) -> None:
        """Add embedding to cache, evicting oldest if necessary."""
        key = self._get_cache_key(text)

        with self._lock:
            # Remove oldest entries if at capacity
            while len(self._cache) >= self._max_cache_size:
                self._cache.popitem(last=False)

            self._cache[key] = CacheEntry(value=embedding, timestamp=time.time())

    @property
    def cache_size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)

    def embed_query(self, text: str) -> list[float]:
        """Embed a query with caching.

        Args:
            text: Query text to embed

        Returns:
            Embedding vector
        """
        # Check cache first
        cached = self._get_from_cache(text)
        if cached is not None:
            logger.debug(f"Cache hit for query: {text[:50]}...")
            return cached

        # Cache miss - call underlying embeddings
        logger.debug(f"Cache miss for query: {text[:50]}...")
        embedding = self._base_embeddings.embed_query(text)
        self._add_to_cache(text, embedding)
        return embedding

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents with per-document caching.

        Args:
            texts: List of document texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        uncached_texts: list[str] = []
        uncached_indices: list[int] = []

        # Check cache for each document
        for i, text in enumerate(texts):
            cached = self._get_from_cache(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_texts.append(text)
                uncached_indices.append(i)

        # Embed uncached documents
        if uncached_texts:
            new_embeddings = self._base_embeddings.embed_documents(uncached_texts)

            # Store results and update cache
            for idx, text, embedding in zip(
                uncached_indices, uncached_texts, new_embeddings
            ):
                results[idx] = embedding
                self._add_to_cache(text, embedding)

        logger.debug(
            f"Embedded {len(texts)} documents: "
            f"{len(texts) - len(uncached_texts)} cached, {len(uncached_texts)} new"
        )

        # Type assertion - all results should be filled now
        return [r for r in results if r is not None]

    def get_statistics(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache_size, cache_hits, cache_misses, hit_rate
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0

            return {
                "cache_size": len(self._cache),
                "cache_hits": self._hits,
                "cache_misses": self._misses,
                "hit_rate": hit_rate,
                "max_cache_size": self._max_cache_size,
                "ttl_seconds": self._ttl_seconds,
            }

    def clear_cache(self) -> None:
        """Clear all cached embeddings."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
        logger.info("Embedding cache cleared")
