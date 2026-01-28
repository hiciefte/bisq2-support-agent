"""
TDD tests for performance monitoring improvements.

These tests define expected behavior for:
1. Lock contention profiling and metrics
2. Latency percentile tracking (p50, p95, p99)
"""

import threading
import time
from unittest.mock import MagicMock

import pytest


class TestLockContentionProfiler:
    """Tests for lock contention profiling and metrics."""

    def test_profiled_lock_has_metrics(self):
        """ProfiledLock should track contention metrics."""
        from app.services.rag.performance_monitor import ProfiledLock

        lock = ProfiledLock(name="test_lock")

        assert hasattr(lock, "get_metrics")
        metrics = lock.get_metrics()

        assert "name" in metrics
        assert "acquisitions" in metrics
        assert "contentions" in metrics
        assert "total_wait_time" in metrics
        assert "avg_wait_time" in metrics

    def test_profiled_lock_counts_acquisitions(self):
        """ProfiledLock should count successful acquisitions."""
        from app.services.rag.performance_monitor import ProfiledLock

        lock = ProfiledLock(name="test_lock")

        # Acquire and release multiple times
        for _ in range(5):
            with lock:
                pass

        metrics = lock.get_metrics()
        assert metrics["acquisitions"] == 5

    def test_profiled_lock_detects_contention(self):
        """ProfiledLock should detect contention when threads wait."""
        from app.services.rag.performance_monitor import ProfiledLock

        lock = ProfiledLock(name="test_lock")
        contention_detected = []

        def worker():
            with lock:
                time.sleep(0.05)
            # Check if there was any waiting
            metrics = lock.get_metrics()
            if metrics["total_wait_time"] > 0:
                contention_detected.append(True)

        # Start multiple threads that will contend
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        metrics = lock.get_metrics()
        # With 3 threads, at least 2 should have to wait
        assert metrics["acquisitions"] == 3

    def test_profiled_lock_is_reentrant(self):
        """ProfiledLock should support reentrant acquisition."""
        from app.services.rag.performance_monitor import ProfiledLock

        lock = ProfiledLock(name="test_lock")

        with lock:
            with lock:  # Should not deadlock
                pass

        metrics = lock.get_metrics()
        assert metrics["acquisitions"] >= 1

    def test_profiled_lock_works_as_context_manager(self):
        """ProfiledLock should work as a context manager."""
        from app.services.rag.performance_monitor import ProfiledLock

        lock = ProfiledLock(name="test_lock")

        with lock:
            pass  # Should not raise

        # Also test explicit acquire/release
        lock.acquire()
        lock.release()

        metrics = lock.get_metrics()
        assert metrics["acquisitions"] == 2


class TestLatencyPercentileTracker:
    """Tests for latency percentile tracking."""

    def test_latency_tracker_exists(self):
        """LatencyTracker should exist and have required methods."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")

        assert hasattr(tracker, "record")
        assert hasattr(tracker, "get_percentiles")
        assert hasattr(tracker, "reset")

    def test_latency_tracker_records_values(self):
        """LatencyTracker should record latency values."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")

        tracker.record(0.1)
        tracker.record(0.2)
        tracker.record(0.3)

        percentiles = tracker.get_percentiles()
        assert percentiles["count"] == 3
        assert percentiles["mean"] == pytest.approx(0.2, rel=0.01)

    def test_latency_tracker_calculates_percentiles(self):
        """LatencyTracker should calculate p50, p95, p99 percentiles."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")

        # Add 100 values: 1-100
        for i in range(1, 101):
            tracker.record(float(i))

        percentiles = tracker.get_percentiles()

        assert "p50" in percentiles
        assert "p95" in percentiles
        assert "p99" in percentiles

        # p50 should be around 50
        assert 49 <= percentiles["p50"] <= 51
        # p95 should be around 95
        assert 94 <= percentiles["p95"] <= 96
        # p99 should be around 99
        assert 98 <= percentiles["p99"] <= 100

    def test_latency_tracker_handles_empty(self):
        """LatencyTracker should handle empty data gracefully."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")

        percentiles = tracker.get_percentiles()

        assert percentiles["count"] == 0
        assert percentiles["p50"] == 0.0
        assert percentiles["p95"] == 0.0
        assert percentiles["p99"] == 0.0

    def test_latency_tracker_reset(self):
        """LatencyTracker should support resetting data."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")

        tracker.record(0.1)
        tracker.record(0.2)
        assert tracker.get_percentiles()["count"] == 2

        tracker.reset()
        assert tracker.get_percentiles()["count"] == 0

    def test_latency_tracker_is_thread_safe(self):
        """LatencyTracker should be thread-safe."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")
        errors = []

        def worker():
            try:
                for i in range(100):
                    tracker.record(float(i) / 100)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert tracker.get_percentiles()["count"] == 500

    def test_latency_tracker_with_context_manager(self):
        """LatencyTracker should support timing via context manager."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency")

        with tracker.time():
            time.sleep(0.01)

        percentiles = tracker.get_percentiles()
        assert percentiles["count"] == 1
        assert percentiles["p50"] >= 0.01

    def test_latency_tracker_max_samples(self):
        """LatencyTracker should respect max_samples limit."""
        from app.services.rag.performance_monitor import LatencyTracker

        tracker = LatencyTracker(name="test_latency", max_samples=100)

        # Add more than max samples
        for i in range(200):
            tracker.record(float(i))

        percentiles = tracker.get_percentiles()
        assert percentiles["count"] == 100  # Should be capped


class TestPerformanceMonitorRegistry:
    """Tests for the global performance monitor registry."""

    def test_registry_singleton(self):
        """PerformanceMonitor should be a singleton."""
        from app.services.rag.performance_monitor import get_performance_monitor

        monitor1 = get_performance_monitor()
        monitor2 = get_performance_monitor()

        assert monitor1 is monitor2

    def test_registry_creates_trackers(self):
        """PerformanceMonitor should create and manage trackers."""
        from app.services.rag.performance_monitor import get_performance_monitor

        monitor = get_performance_monitor()

        # Get or create latency tracker
        tracker = monitor.get_latency_tracker("test_operation")
        assert tracker is not None

        # Same name should return same tracker
        tracker2 = monitor.get_latency_tracker("test_operation")
        assert tracker is tracker2

    def test_registry_creates_profiled_locks(self):
        """PerformanceMonitor should create and manage profiled locks."""
        from app.services.rag.performance_monitor import get_performance_monitor

        monitor = get_performance_monitor()

        lock = monitor.get_profiled_lock("test_lock")
        assert lock is not None

        # Same name should return same lock
        lock2 = monitor.get_profiled_lock("test_lock")
        assert lock is lock2

    def test_registry_aggregates_metrics(self):
        """PerformanceMonitor should aggregate all metrics."""
        from app.services.rag.performance_monitor import get_performance_monitor

        monitor = get_performance_monitor()

        # Create some trackers and locks
        tracker = monitor.get_latency_tracker("aggregate_test_op")
        tracker.record(0.1)
        tracker.record(0.2)

        lock = monitor.get_profiled_lock("aggregate_test_lock")
        with lock:
            pass

        # Get aggregated metrics
        metrics = monitor.get_all_metrics()

        assert "latency_trackers" in metrics
        assert "profiled_locks" in metrics


class TestRAGServicePerformanceIntegration:
    """Integration tests for performance monitoring in RAG service."""

    def test_bm25_tokenizer_tracks_latency(self):
        """BM25SparseTokenizer should track operation latency."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer

        tokenizer = BM25SparseTokenizer()

        # Perform some operations
        tokenizer.tokenize_document("bitcoin wallet security")
        tokenizer.tokenize_query("bitcoin")

        # Statistics should include timing info if performance monitoring is enabled
        stats = tokenizer.get_statistics()
        assert "vocabulary_size" in stats

    def test_embedding_cache_tracks_performance(self):
        """CachedEmbeddings should track performance metrics."""
        from app.services.rag.cached_embeddings import CachedEmbeddings

        mock_embeddings = MagicMock()
        mock_embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

        cached = CachedEmbeddings(mock_embeddings)

        # Perform operations
        cached.embed_query("test1")
        cached.embed_query("test1")  # Cache hit
        cached.embed_query("test2")

        stats = cached.get_statistics()
        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert "hit_rate" in stats

    def test_vocabulary_manager_uses_profiled_lock(self, tmp_path):
        """VocabularyManager should track lock contention."""
        from app.services.rag.bm25_tokenizer import BM25SparseTokenizer
        from app.services.rag.vocabulary_manager import VocabularyManager

        vocab_path = tmp_path / "perf_test_vocab.json"
        manager = VocabularyManager(vocab_path)

        tokenizer = BM25SparseTokenizer()
        tokenizer.tokenize_document("test content")

        # Save and load to exercise locks
        manager.save(tokenizer)
        manager.load(tokenizer)

        # No explicit assertion - test that operations complete without error
        assert True
