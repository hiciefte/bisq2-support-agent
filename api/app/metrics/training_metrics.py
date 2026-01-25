"""Prometheus metrics for auto-training pipeline.

Provides observability into the training pipeline including:
- Training pairs processed by routing category
- Calibration progress tracking
- Answer comparison timing
- Auto-approval rates
- Per-source sync metrics (Bisq 2 / Matrix)
"""

from prometheus_client import Counter, Gauge, Histogram

# ============================================
# Sync-level metrics (per source: bisq2, matrix)
# ============================================

sync_last_status = Gauge(
    "training_sync_last_status",
    "Status of last sync by source (1=success, 0=failure)",
    ["source"],  # bisq2, matrix
)

sync_last_success_timestamp = Gauge(
    "training_sync_last_success_timestamp",
    "Unix timestamp of last successful sync by source",
    ["source"],
)

sync_duration_seconds = Histogram(
    "training_sync_duration_seconds",
    "Duration of sync operations by source",
    ["source"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

sync_pairs_processed = Counter(
    "training_sync_pairs_processed_total",
    "Q&A pairs processed per sync run by source",
    ["source"],
)

# ============================================
# Training pair processing metrics
# ============================================

# Training pair processing metrics
training_pairs_processed = Counter(
    "training_pairs_processed_total",
    "Total training pairs processed by the pipeline",
    ["routing"],  # FULL_REVIEW, SPOT_CHECK, AUTO_APPROVE
)

training_pairs_by_status = Counter(
    "training_pairs_by_status_total",
    "Training pairs by review status",
    ["status"],  # pending, approved, rejected
)

# Calibration metrics
calibration_progress = Gauge(
    "training_calibration_progress",
    "Number of calibration samples collected (0-100)",
)

calibration_complete = Gauge(
    "training_calibration_complete",
    "Whether calibration phase is complete (0 or 1)",
)

# Auto-approval metrics
training_auto_approvals = Counter(
    "training_auto_approvals_total",
    "Training pairs automatically approved to FAQ",
)

training_human_reviews = Counter(
    "training_human_reviews_total",
    "Training pairs requiring human review",
    ["outcome"],  # approved, rejected, skipped
)

# Score distribution metrics
training_final_scores = Histogram(
    "training_final_score",
    "Final comparison scores of training pairs",
    buckets=[0.0, 0.3, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0],
)

training_embedding_similarity = Histogram(
    "training_embedding_similarity",
    "Embedding similarity scores between staff and RAG answers",
    buckets=[0.0, 0.3, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0],
)

# Processing time metrics
training_comparison_duration = Histogram(
    "training_comparison_duration_seconds",
    "Time to compare staff answer with RAG answer",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

training_staff_answer_poll_duration = Histogram(
    "training_staff_answer_poll_duration_seconds",
    "Time to poll and process staff answers",
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

# Queue metrics
training_queue_size = Gauge(
    "training_queue_size",
    "Number of items in each review queue",
    ["routing"],  # FULL_REVIEW, SPOT_CHECK, AUTO_APPROVE
)

# Error metrics
training_errors = Counter(
    "training_errors_total",
    "Errors during training pipeline processing",
    ["stage"],  # comparison, storage, faq_creation, poll
)

# FAQ creation metrics
training_faqs_created = Counter(
    "training_faqs_created_total",
    "FAQs created from approved training pairs",
)


def update_calibration_metrics(status) -> None:
    """Update calibration-related metrics.

    Args:
        status: CalibrationStatus object with samples_collected and is_complete attributes
    """
    calibration_progress.set(status.samples_collected)
    calibration_complete.set(1 if status.is_complete else 0)


def update_queue_metrics(queue_counts: dict) -> None:
    """Update queue size metrics."""
    for routing, count in queue_counts.items():
        training_queue_size.labels(routing=routing).set(count)


# ============================================
# Learning Engine metrics
# ============================================

learning_threshold_updates = Counter(
    "learning_threshold_updates_total",
    "Number of threshold updates by the learning engine",
    ["threshold_type"],  # auto_send, queue_high, reject
)

learning_current_thresholds = Gauge(
    "learning_current_threshold",
    "Current value of learning engine thresholds",
    ["threshold_type"],  # auto_send, queue_high, reject
)

learning_reviews_total = Counter(
    "learning_reviews_total",
    "Admin reviews recorded by the learning engine",
    ["admin_action"],  # approved, edited, rejected
)


def update_learning_thresholds(
    auto_send: float,
    queue_high: float,
    reject: float,
) -> None:
    """Update learning threshold gauge values.

    Args:
        auto_send: Auto-approve threshold value
        queue_high: Spot-check/queue high threshold value
        reject: Reject threshold value
    """
    learning_current_thresholds.labels(threshold_type="auto_send").set(auto_send)
    learning_current_thresholds.labels(threshold_type="queue_high").set(queue_high)
    learning_current_thresholds.labels(threshold_type="reject").set(reject)


# ============================================
# Duplicate FAQ detection metrics
# ============================================

training_duplicate_detections = Counter(
    "training_duplicate_detections_total",
    "Number of duplicate FAQs detected during approval",
)

training_duplicate_similarity_scores = Histogram(
    "training_duplicate_similarity_score",
    "Similarity scores of detected duplicate FAQs",
    buckets=[0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.99, 1.0],
)


def record_duplicate_detection(similarity_score: float) -> None:
    """Record a duplicate FAQ detection.

    Args:
        similarity_score: The similarity score that triggered duplicate detection
    """
    training_duplicate_detections.inc()
    training_duplicate_similarity_scores.observe(similarity_score)


# ============================================
# Post-approval correction metrics
# ============================================

training_post_approval_corrections = Counter(
    "training_post_approval_corrections_total",
    "Number of post-approval corrections detected",
)

training_correction_resolutions = Counter(
    "training_correction_resolutions_total",
    "Number of correction resolutions by action type",
    ["action"],  # update, confirm, delete
)
