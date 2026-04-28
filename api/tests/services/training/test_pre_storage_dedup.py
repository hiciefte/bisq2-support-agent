"""Tests for pre-storage semantic deduplication.

1B: Before creating a candidate, check if a similar FAQ already exists.
Uses a stricter threshold (0.92) than the approval-time check (0.85)
to avoid suppressing legitimately different questions.
"""

from __future__ import annotations

from app.services.training.validation import is_pre_extraction_duplicate


def test_high_similarity_is_duplicate() -> None:
    assert is_pre_extraction_duplicate(0.95, threshold=0.92) is True


def test_moderate_similarity_is_not_duplicate() -> None:
    assert is_pre_extraction_duplicate(0.87, threshold=0.92) is False


def test_exact_threshold_is_not_duplicate() -> None:
    assert is_pre_extraction_duplicate(0.92, threshold=0.92) is False


def test_above_threshold_is_duplicate() -> None:
    assert is_pre_extraction_duplicate(0.921, threshold=0.92) is True


def test_zero_similarity() -> None:
    assert is_pre_extraction_duplicate(0.0, threshold=0.92) is False


def test_default_threshold_is_092() -> None:
    assert is_pre_extraction_duplicate(0.93) is True
    assert is_pre_extraction_duplicate(0.91) is False
