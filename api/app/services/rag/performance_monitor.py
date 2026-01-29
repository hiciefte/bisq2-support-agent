"""Performance monitoring for RAG pipeline.

This module provides:
- ProfiledLock: Thread lock with contention metrics
- LatencyTracker: Percentile-based latency tracking
- PerformanceMonitor: Global registry for performance metrics
"""

import logging
import statistics
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


@dataclass
class LockMetrics:
    """Metrics for a profiled lock."""

    name: str
    acquisitions: int = 0
    contentions: int = 0
    total_wait_time: float = 0.0
    max_wait_time: float = 0.0


class ProfiledLock:
    """Thread lock with contention profiling.

    Tracks acquisition count, contention events, and wait times.
    """

    def __init__(self, name: str = "unnamed_lock"):
        """Initialize profiled lock.

        Args:
            name: Name for identification in metrics
        """
        self._lock = threading.RLock()
        self._name = name
        self._acquisitions = 0
        self._contentions = 0
        self._total_wait_time = 0.0
        self._max_wait_time = 0.0
        self._metrics_lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        """Acquire the lock with profiling.

        Args:
            blocking: Whether to block waiting for lock
            timeout: Maximum time to wait (-1 for unlimited)

        Returns:
            True if lock acquired, False otherwise
        """
        start_time = time.perf_counter()

        # Try non-blocking first to detect contention
        if not self._lock.acquire(blocking=False):
            if blocking:
                # There's contention - wait for lock
                with self._metrics_lock:
                    self._contentions += 1

                if timeout >= 0:
                    result = self._lock.acquire(blocking=True, timeout=timeout)
                else:
                    result = self._lock.acquire(blocking=True)

                if not result:
                    return False
            else:
                return False

        wait_time = time.perf_counter() - start_time

        with self._metrics_lock:
            self._acquisitions += 1
            self._total_wait_time += wait_time
            self._max_wait_time = max(self._max_wait_time, wait_time)

        return True

    def release(self) -> None:
        """Release the lock."""
        self._lock.release()

    def __enter__(self) -> "ProfiledLock":
        """Enter context manager."""
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        self.release()

    def get_metrics(self) -> dict[str, Any]:
        """Get lock contention metrics.

        Returns:
            Dict with name, acquisitions, contentions, wait times
        """
        with self._metrics_lock:
            avg_wait = (
                self._total_wait_time / self._acquisitions
                if self._acquisitions > 0
                else 0.0
            )
            return {
                "name": self._name,
                "acquisitions": self._acquisitions,
                "contentions": self._contentions,
                "total_wait_time": self._total_wait_time,
                "max_wait_time": self._max_wait_time,
                "avg_wait_time": avg_wait,
            }


class LatencyTracker:
    """Tracks operation latency with percentile calculations.

    Uses a bounded deque to maintain recent samples for percentile
    calculations without unbounded memory growth.
    """

    def __init__(self, name: str = "unnamed_latency", max_samples: int = 10000):
        """Initialize latency tracker.

        Args:
            name: Name for identification
            max_samples: Maximum samples to keep for percentile calculation
        """
        self._name = name
        self._max_samples = max_samples
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._lock = threading.Lock()
        self._total_count = 0
        self._total_sum = 0.0

    def record(self, latency: float) -> None:
        """Record a latency value.

        Args:
            latency: Latency in seconds
        """
        with self._lock:
            self._samples.append(latency)
            self._total_count += 1
            self._total_sum += latency

    @contextmanager
    def time(self) -> Generator[None, None, None]:
        """Context manager for timing operations.

        Example:
            with tracker.time():
                # operation to time
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.record(elapsed)

    def get_percentiles(self) -> dict[str, Any]:
        """Calculate latency percentiles.

        Returns:
            Dict with count, mean, min, max, p50, p95, p99
        """
        with self._lock:
            if not self._samples:
                return {
                    "name": self._name,
                    "count": 0,
                    "mean": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "p50": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                }

            sorted_samples = sorted(self._samples)
            count = len(sorted_samples)

            def percentile(p: float) -> float:
                """Calculate percentile value."""
                idx = int((p / 100) * (count - 1))
                return sorted_samples[idx]

            return {
                "name": self._name,
                "count": count,
                "mean": statistics.mean(sorted_samples),
                "min": sorted_samples[0],
                "max": sorted_samples[-1],
                "p50": percentile(50),
                "p95": percentile(95),
                "p99": percentile(99),
            }

    def reset(self) -> None:
        """Reset all tracked data."""
        with self._lock:
            self._samples.clear()
            self._total_count = 0
            self._total_sum = 0.0


class PerformanceMonitor:
    """Global registry for performance monitoring.

    Provides centralized access to latency trackers and profiled locks.
    """

    def __init__(self):
        """Initialize performance monitor."""
        self._latency_trackers: dict[str, LatencyTracker] = {}
        self._profiled_locks: dict[str, ProfiledLock] = {}
        self._lock = threading.Lock()

    def get_latency_tracker(
        self, name: str, max_samples: int = 10000
    ) -> LatencyTracker:
        """Get or create a latency tracker.

        Args:
            name: Tracker name
            max_samples: Maximum samples for percentile calculation

        Returns:
            LatencyTracker instance
        """
        with self._lock:
            if name not in self._latency_trackers:
                self._latency_trackers[name] = LatencyTracker(
                    name=name, max_samples=max_samples
                )
            return self._latency_trackers[name]

    def get_profiled_lock(self, name: str) -> ProfiledLock:
        """Get or create a profiled lock.

        Args:
            name: Lock name

        Returns:
            ProfiledLock instance
        """
        with self._lock:
            if name not in self._profiled_locks:
                self._profiled_locks[name] = ProfiledLock(name=name)
            return self._profiled_locks[name]

    def get_all_metrics(self) -> dict[str, Any]:
        """Get aggregated metrics from all trackers and locks.

        Returns:
            Dict with latency_trackers and profiled_locks metrics
        """
        with self._lock:
            return {
                "latency_trackers": {
                    name: tracker.get_percentiles()
                    for name, tracker in self._latency_trackers.items()
                },
                "profiled_locks": {
                    name: lock.get_metrics()
                    for name, lock in self._profiled_locks.items()
                },
            }

    def reset_all(self) -> None:
        """Reset all trackers."""
        with self._lock:
            for tracker in self._latency_trackers.values():
                tracker.reset()


# Global singleton
_performance_monitor: Optional[PerformanceMonitor] = None
_monitor_lock = threading.Lock()


def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance.

    Returns:
        PerformanceMonitor singleton
    """
    global _performance_monitor

    with _monitor_lock:
        if _performance_monitor is None:
            _performance_monitor = PerformanceMonitor()
        return _performance_monitor
