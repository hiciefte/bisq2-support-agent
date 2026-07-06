"""Shared enrichment for RAG responses before channel dispatch."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.channels.constants import REVIEW_QUEUE_ACTIONS
from app.channels.models import IncomingMessage
from app.channels.traits import channel_supports_staff_grounding

logger = logging.getLogger(__name__)


def enrich_staff_code_grounding(
    *,
    runtime: Any,
    channel_id: str,
    message: IncomingMessage,
    rag_response: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach staff-only grounding evidence for channels that support it."""
    response = dict(rag_response)
    if not channel_supports_staff_grounding(channel_id):
        return response

    resolve_optional = getattr(runtime, "resolve_optional", None)
    if not callable(resolve_optional):
        return response

    try:
        grounding_service = resolve_optional("staff_grounding_brief_service")
    except Exception:
        logger.debug(
            "Failed resolving staff grounding service for channel=%s",
            channel_id,
            exc_info=True,
        )
        return response

    build = getattr(grounding_service, "build", None)
    if not callable(build):
        return response

    question = str(
        response.get("canonical_question_en") or getattr(message, "question", "") or ""
    ).strip()
    if not question:
        return response

    try:
        brief = build(
            question=question,
            knowledge_sources=list(response.get("sources") or []),
            draft_answer=str(
                response.get("canonical_answer_en") or response.get("answer") or ""
            ).strip(),
        )
    except Exception:
        logger.exception(
            "Failed attaching staff-only code grounding for channel=%s",
            channel_id,
        )
        return response

    if not isinstance(brief, dict):
        return response

    enriched_answer = str(brief.get("staff_enriched_answer") or "").strip()
    if not enriched_answer:
        return response

    response["staff_grounding_brief"] = brief
    response["staff_enriched_answer"] = enriched_answer
    response["requires_human"] = True

    routing_action = str(response.get("routing_action") or "").strip().lower()
    if routing_action not in REVIEW_QUEUE_ACTIONS:
        response["routing_action"] = "queue_medium"
        response["routing_reason"] = "Codebase evidence attached for staff-room review."
    return response


class ChannelRAGResponseEnricher:
    """Runtime-backed callable used by ChannelGateway."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def __call__(
        self,
        incoming: IncomingMessage,
        rag_response: Mapping[str, Any],
    ) -> dict[str, Any]:
        return enrich_staff_code_grounding(
            runtime=self.runtime,
            channel_id=incoming.channel.value,
            message=incoming,
            rag_response=rag_response,
        )
