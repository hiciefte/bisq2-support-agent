"""Metrics helpers for escalation feedback-learning loop."""

import asyncio
from difflib import SequenceMatcher
from typing import Any, Optional

import numpy as np


def compute_edit_distance(original: str, modified: str) -> float:
    """Normalized character distance in [0.0, 1.0]."""
    original_clean = (original or "").strip()
    modified_clean = (modified or "").strip()
    if original_clean == modified_clean:
        return 0.0
    similarity = SequenceMatcher(None, original_clean, modified_clean).ratio()
    return round(max(0.0, min(1.0, 1.0 - similarity)), 4)


async def compute_semantic_distance(
    original: str,
    modified: str,
    embeddings: Any,
) -> float:
    """Embedding-based semantic distance in [0.0, 1.0]."""
    vec_a, vec_b = await asyncio.gather(
        asyncio.to_thread(embeddings.embed_query, (original or "").strip()),
        asyncio.to_thread(embeddings.embed_query, (modified or "").strip()),
    )
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 1.0
    cosine_sim = float(np.dot(a, b) / (norm_a * norm_b))
    return round(1.0 - max(0.0, min(1.0, cosine_sim)), 4)


async def compute_hybrid_distance(
    original: str,
    modified: str,
    embeddings: Optional[Any] = None,
) -> float:
    """Hybrid distance: char distance, optionally blended with semantic distance."""
    char_dist = compute_edit_distance(original, modified)
    if char_dist == 0.0:
        return 0.0
    if embeddings is None or char_dist < 0.30 or char_dist > 0.85:
        return char_dist

    sem_dist = await compute_semantic_distance(original, modified, embeddings)
    return round(max(0.0, min(1.0, (0.30 * char_dist) + (0.70 * sem_dist))), 4)
