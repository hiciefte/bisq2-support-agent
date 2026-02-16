"""Tests for escalation feedback metrics utilities."""

import pytest
from app.services.escalation.feedback_metrics import (
    compute_edit_distance,
    compute_hybrid_distance,
)


def test_compute_edit_distance_identical_is_zero() -> None:
    assert compute_edit_distance("Same", "Same") == 0.0


def test_compute_edit_distance_whitespace_only_diff_is_zero() -> None:
    assert compute_edit_distance("Hello world", "  Hello world  ") == 0.0


def test_compute_edit_distance_typo_is_small() -> None:
    value = compute_edit_distance("wallet", "wallett")
    assert 0.0 < value < 0.2


@pytest.mark.asyncio
async def test_compute_hybrid_distance_without_embeddings_falls_back_to_char() -> None:
    char_value = compute_edit_distance("abc", "xyz")
    hybrid_value = await compute_hybrid_distance("abc", "xyz", embeddings=None)
    assert hybrid_value == char_value
