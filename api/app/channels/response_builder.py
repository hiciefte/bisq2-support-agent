"""Shared helpers for constructing gateway/channel response models."""

import uuid
from typing import Any, List, Mapping, Optional

from app.channels.models import DocumentReference, ResponseMetadata


def build_sources(rag_response: Mapping[str, Any]) -> List[DocumentReference]:
    """Build DocumentReference list from a RAG response payload."""
    return [
        DocumentReference(
            document_id=source.get("document_id") or str(uuid.uuid4()),
            title=source.get("title", "Unknown"),
            url=source.get("url"),
            # RAG service uses `similarity_score`; some older code uses `relevance_score`.
            relevance_score=(
                float(raw_score)
                if (
                    raw_score := source.get(
                        "relevance_score", source.get("similarity_score")
                    )
                )
                is not None
                else 0.5
            ),
            category=source.get("category") or source.get("type"),
            content=source.get("content"),
            protocol=source.get("protocol"),
            section=source.get("section"),
        )
        for source in rag_response.get("sources", [])
    ]


def build_metadata(
    rag_response: Mapping[str, Any],
    processing_time_ms: float,
    hooks_executed: Optional[List[str]] = None,
) -> ResponseMetadata:
    """Build ResponseMetadata from a RAG response payload."""
    return ResponseMetadata(
        processing_time_ms=processing_time_ms,
        rag_strategy=rag_response.get("rag_strategy", "retrieval"),
        model_name=rag_response.get("model_name", "unknown"),
        tokens_used=rag_response.get("tokens_used"),
        confidence_score=rag_response.get("confidence"),
        routing_action=rag_response.get("routing_action"),
        detected_version=rag_response.get("detected_version"),
        version_confidence=rag_response.get("version_confidence"),
        hooks_executed=hooks_executed if hooks_executed is not None else [],
    )
