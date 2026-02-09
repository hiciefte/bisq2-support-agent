"""Shared helpers for constructing gateway/channel response models."""

import uuid
from typing import Any, List, Mapping, Optional

from app.channels.models import DocumentReference, ResponseMetadata


def build_sources(rag_response: Mapping[str, Any]) -> List[DocumentReference]:
    """Build DocumentReference list from a RAG response payload."""
    return [
        DocumentReference(
            document_id=source.get("document_id", str(uuid.uuid4())),
            title=source.get("title", "Unknown"),
            url=source.get("url"),
            relevance_score=source.get("relevance_score", 0.5),
            category=source.get("category"),
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
        emotion=rag_response.get("emotion"),
        emotion_intensity=rag_response.get("emotion_intensity"),
        hooks_executed=hooks_executed or [],
    )
