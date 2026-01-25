"""Multi-tier caching for translation results.

L1: In-memory LRU cache for fast access (default: 1000 entries)
L3: SQLite persistent cache with TTL (default: 7 days)
"""

import logging
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LRUCache:
    """In-memory LRU (Least Recently Used) cache.

    Fast access for frequently used translations.
    Automatically evicts least recently used entries when full.
    """

    def __init__(self, maxsize: int = 1000):
        """Initialize the LRU cache.

        Args:
            maxsize: Maximum number of entries to store.
        """
        self.cache: OrderedDict[str, str] = OrderedDict()
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[str]:
        """Get a value from the cache.

        Args:
            key: Cache key to look up.

        Returns:
            Cached value if found, None otherwise.
        """
        if key in self.cache:
            self.hits += 1
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            return self.cache[key]
        self.misses += 1
        return None

    def set(self, key: str, value: str) -> None:
        """Set a value in the cache.

        Args:
            key: Cache key.
            value: Value to cache.
        """
        if key in self.cache:
            self.cache.move_to_end(key)
        else:
            if len(self.cache) >= self.maxsize:
                # Remove oldest (first) item
                self.cache.popitem(last=False)
        self.cache[key] = value

    def clear(self) -> None:
        """Clear all entries from the cache."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, size, and hit_ratio.
        """
        total = self.hits + self.misses
        hit_ratio = self.hits / total if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self.cache),
            "maxsize": self.maxsize,
            "hit_ratio": hit_ratio,
        }


class SQLiteCache:
    """Persistent SQLite cache with TTL support.

    Stores translations in SQLite for persistence across restarts.
    Automatically expires entries based on TTL.
    """

    DEFAULT_TTL = 604800  # 7 days in seconds

    def __init__(self, db_path: str = "/data/translation_cache.db"):
        """Initialize the SQLite cache.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        # Ensure parent directory exists
        db_path = Path(self.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    cache_key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at
                ON translations(expires_at)
            """)
            conn.commit()
        finally:
            conn.close()

    def get(self, key: str) -> Optional[str]:
        """Get a value from the cache.

        Args:
            key: Cache key to look up.

        Returns:
            Cached value if found and not expired, None otherwise.
        """
        now = int(time.time())
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM translations WHERE cache_key = ? AND expires_at > ?",
                (key, now),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set(self, key: str, value: str, ttl: int = DEFAULT_TTL) -> None:
        """Set a value in the cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live in seconds (default: 7 days).
        """
        now = int(time.time())
        expires_at = now + ttl
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO translations
                (cache_key, value, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, value, now, expires_at),
            )
            conn.commit()
        finally:
            conn.close()

    def cleanup_expired(self) -> int:
        """Remove expired entries from the cache.

        Returns:
            Number of entries removed.
        """
        now = int(time.time())
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM translations WHERE expires_at <= ?", (now,))
            deleted = cursor.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with total entries and expired count.
        """
        now = int(time.time())
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM translations")
            total = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM translations WHERE expires_at <= ?", (now,)
            )
            expired = cursor.fetchone()[0]
            return {
                "total_entries": total,
                "expired_entries": expired,
                "active_entries": total - expired,
            }
        finally:
            conn.close()


class TieredCache:
    """Two-tier cache combining LRU (L1) and SQLite (L3).

    L1: Fast in-memory access for hot entries
    L3: Persistent storage for all translations

    On cache miss in L1, promotes from L3 to L1.
    On cache set, writes to both L1 and L3.
    """

    def __init__(
        self,
        l1_size: int = 1000,
        db_path: str = "/data/translation_cache.db",
    ):
        """Initialize the tiered cache.

        Args:
            l1_size: Maximum entries in L1 cache.
            db_path: Path to L3 SQLite database.
        """
        self.l1 = LRUCache(maxsize=l1_size)
        self.l3 = SQLiteCache(db_path=db_path)

    async def get(self, key: str) -> Optional[str]:
        """Get a value from the cache.

        Checks L1 first, then L3. Promotes L3 hits to L1.

        Args:
            key: Cache key to look up.

        Returns:
            Cached value if found, None otherwise.
        """
        # Try L1 first
        result = self.l1.get(key)
        if result is not None:
            return result

        # Try L3
        result = self.l3.get(key)
        if result is not None:
            # Promote to L1
            self.l1.set(key, result)
            return result

        return None

    async def set(
        self, key: str, value: str, ttl: int = SQLiteCache.DEFAULT_TTL
    ) -> None:
        """Set a value in the cache.

        Writes to both L1 and L3.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: Time-to-live for L3 cache in seconds.
        """
        self.l1.set(key, value)
        self.l3.set(key, value, ttl=ttl)

    def get_stats(self) -> dict:
        """Get combined cache statistics.

        Returns:
            Dict with L1 and L3 stats, plus combined metrics.
        """
        l1_stats = self.l1.get_stats()
        l3_stats = self.l3.get_stats()

        # Combined hit ratio calculation:
        # L3 cache doesn't track individual hits, only entry counts.
        # L1 hit ratio represents the actual user-visible cache performance.
        # For more accurate combined stats, L3 would need hit/miss tracking.
        total_requests = l1_stats["hits"] + l1_stats["misses"]
        combined_hits = l1_stats["hits"]

        return {
            "l1": l1_stats,
            "l3": l3_stats,
            "total_requests": total_requests,
            "combined_hit_ratio": (
                combined_hits / total_requests if total_requests > 0 else 0
            ),
        }

    def cleanup(self) -> int:
        """Cleanup expired entries from L3 cache.

        Returns:
            Number of entries removed.
        """
        return self.l3.cleanup_expired()
