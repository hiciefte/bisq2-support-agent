"""Coordination primitives for deduplication, locking, and thread state."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Protocol


class CoordinationStore(Protocol):
    """Storage contract for inbound event coordination."""

    async def reserve_dedup(self, key: str, ttl_seconds: float) -> bool:
        """Reserve a deduplication key.

        Returns True when reservation succeeds; False if key is already active.
        """

    async def acquire_lock(self, key: str, ttl_seconds: float) -> str | None:
        """Acquire a lock lease and return its token.

        Returns None if the lock is currently held by another lease.
        """

    async def release_lock(self, key: str, token: str) -> None:
        """Release an active lock lease."""

    async def get_thread_state(self, key: str) -> dict[str, Any] | None:
        """Read thread state if present and not expired."""

    async def set_thread_state(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: float,
    ) -> None:
        """Persist thread state with TTL."""


class InMemoryCoordinationStore:
    """Process-local coordination store with TTL-backed entries."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._dedup: dict[str, float] = {}
        self._locks: dict[str, tuple[str, float]] = {}
        self._thread_state: dict[str, tuple[dict[str, Any], float]] = {}

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _prune_expired(self, now: float) -> None:
        self._dedup = {
            key: expires_at
            for key, expires_at in self._dedup.items()
            if expires_at > now
        }
        self._locks = {
            key: lease for key, lease in self._locks.items() if lease[1] > now
        }
        self._thread_state = {
            key: entry for key, entry in self._thread_state.items() if entry[1] > now
        }

    async def reserve_dedup(self, key: str, ttl_seconds: float) -> bool:
        ttl = max(0.001, float(ttl_seconds or 0.0))
        now = self._now()
        async with self._guard:
            self._prune_expired(now)
            expires_at = self._dedup.get(key)
            if expires_at is not None and expires_at > now:
                return False
            self._dedup[key] = now + ttl
            return True

    async def acquire_lock(self, key: str, ttl_seconds: float) -> str | None:
        ttl = max(0.001, float(ttl_seconds or 0.0))
        now = self._now()
        async with self._guard:
            self._prune_expired(now)
            existing = self._locks.get(key)
            if existing is not None and existing[1] > now:
                return None
            token = str(uuid.uuid4())
            self._locks[key] = (token, now + ttl)
            return token

    async def release_lock(self, key: str, token: str) -> None:
        if not token:
            return
        async with self._guard:
            existing = self._locks.get(key)
            if existing is None:
                return
            if existing[0] != token:
                return
            self._locks.pop(key, None)

    async def get_thread_state(self, key: str) -> dict[str, Any] | None:
        now = self._now()
        async with self._guard:
            self._prune_expired(now)
            entry = self._thread_state.get(key)
            if entry is None:
                return None
            return dict(entry[0])

    async def set_thread_state(
        self,
        key: str,
        value: dict[str, Any],
        ttl_seconds: float,
    ) -> None:
        ttl = max(0.001, float(ttl_seconds or 0.0))
        now = self._now()
        payload = dict(value)
        async with self._guard:
            self._prune_expired(now)
            self._thread_state[key] = (payload, now + ttl)
