"""Prometheus metrics for LLM extraction pipeline.

Provides observability into the question extraction process including:
- Pre-LLM filtering statistics
- Question extraction counts by type
- Confidence score distribution
- Processing time tracking
"""

from prometheus_client import Counter, Histogram

# Pre-LLM filtering metrics
messages_filtered_total = Counter(
    "llm_extraction_messages_filtered_total",
    "Total messages filtered by pre-LLM filters",
    ["reason"],  # empty_message, url_only, greeting, emoji_only, etc.
)

messages_processed_total = Counter(
    "llm_extraction_messages_processed_total",
    "Total messages processed by LLM extraction",
)

# Question extraction metrics
questions_extracted_total = Counter(
    "llm_extraction_questions_extracted_total",
    "Total questions extracted by LLM",
    ["question_type"],  # initial_question, follow_up, acknowledgment, not_question
)

questions_rejected_total = Counter(
    "llm_extraction_questions_rejected_total",
    "Questions rejected by post-validation or confidence threshold",
    ["reason"],  # too_short, low_confidence, no_question_indicators
)

# Quality tracking
extraction_confidence_score = Histogram(
    "llm_extraction_confidence_score",
    "Confidence scores of extracted questions",
    buckets=[0.0, 0.3, 0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0],
)

extraction_processing_time = Histogram(
    "llm_extraction_processing_seconds",
    "Time spent on LLM extraction per batch",
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

# Pre-filter pass rate (for monitoring filtering effectiveness)
pre_filter_pass_rate = Histogram(
    "llm_extraction_pre_filter_pass_rate",
    "Percentage of messages passing pre-LLM filtering per batch",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)
