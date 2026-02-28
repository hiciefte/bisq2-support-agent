"""Prometheus metrics for multilingual detection and translation pipeline."""

from prometheus_client import Counter, Histogram

language_detection_total = Counter(
    "translation_language_detection_total",
    "Total language detection outcomes by backend/result",
    ["backend", "result"],
)

language_detection_confidence = Histogram(
    "translation_language_detection_confidence",
    "Confidence of language detection outcomes",
    ["backend"],
    buckets=(0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0),
)

language_detection_llm_tiebreak_total = Counter(
    "translation_language_detection_llm_tiebreak_total",
    "Number of LLM tie-break attempts in language detection",
    ["reason"],
)

mixed_language_detection_total = Counter(
    "translation_mixed_language_detection_total",
    "Number of mixed-language detections",
    ["primary", "secondary"],
)

translation_query_decisions_total = Counter(
    "translation_query_decisions_total",
    "Translation decision outcomes for incoming queries",
    ["decision", "source_lang"],
)

translation_operation_duration_seconds = Histogram(
    "translation_operation_duration_seconds",
    "Duration of translation operations",
    ["direction"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

translation_errors_total = Counter(
    "translation_errors_total",
    "Translation errors by direction",
    ["direction"],
)
