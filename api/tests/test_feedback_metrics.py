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


def test_compute_edit_distance_handles_empty_and_none_inputs() -> None:
    assert compute_edit_distance("", "") == 0.0
    assert compute_edit_distance(None, "") == 0.0  # type: ignore[arg-type]
    assert compute_edit_distance("", None) == 0.0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_compute_hybrid_distance_without_embeddings_falls_back_to_char() -> None:
    char_value = compute_edit_distance("abc", "xyz")
    hybrid_value = await compute_hybrid_distance("abc", "xyz", embeddings=None)
    assert hybrid_value == char_value


@pytest.mark.asyncio
async def test_compute_hybrid_distance_handles_empty_and_none_inputs() -> None:
    assert await compute_hybrid_distance("", "", embeddings=None) == 0.0
    assert await compute_hybrid_distance(None, "", embeddings=None) == 0.0  # type: ignore[arg-type]
    assert await compute_hybrid_distance("", None, embeddings=None) == 0.0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_compute_hybrid_distance_blends_char_and_embedding_distances() -> None:
    class MockEmbeddings:
        def embed_query(self, text: str):
            return [1.0, 0.0] if text == "abcde" else [0.5, 0.8660254]

    original = "abcde"
    modified = "abxyz"
    char_distance = compute_edit_distance(original, modified)
    assert 0.30 <= char_distance <= 0.85

    hybrid = await compute_hybrid_distance(
        original, modified, embeddings=MockEmbeddings()
    )
    expected = round((0.30 * char_distance) + (0.70 * 0.5), 4)
    assert hybrid == expected
