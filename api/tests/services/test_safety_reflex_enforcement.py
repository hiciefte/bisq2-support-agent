"""Service-path tests for deterministic scam-safety warning enforcement."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.services.simplified_rag_service import SimplifiedRAGService
from langchain_core.documents import Document


@pytest.fixture
def safety_service(test_settings):
    service = SimplifiedRAGService(settings=test_settings)
    service.rag_chain = MagicMock(return_value="Evidence-backed essential answer.")

    document = Document(
        page_content="Reviewed Bisq Easy support context.",
        metadata={
            "type": "wiki",
            "title": "Support context",
            "section": "Safety",
            "protocol": "bisq_easy",
        },
    )
    service.document_retriever = MagicMock()
    service.document_retriever.retrieve_with_scores.return_value = ([document], [0.9])
    service.document_retriever.deduplicate_sources.side_effect = lambda sources: sources

    service.confidence_scorer = MagicMock()
    service.confidence_scorer.calculate_confidence = AsyncMock(return_value=0.9)
    service.auto_send_router = MagicMock()
    service.auto_send_router.route_response = AsyncMock(
        return_value=SimpleNamespace(action="auto_send", queue_for_review=False)
    )
    service.routing_reason_generator = MagicMock()
    service.routing_reason_generator.generate.return_value = "test-reason"
    return service


@pytest.mark.asyncio
async def test_document_backed_answer_leads_with_exact_static_warning(
    safety_service,
):
    response = await safety_service.query(
        "A support agent asked me for my seed.",
        chat_history=[],
        override_version="Bisq 2",
    )

    assert response["answer"].startswith(SAFETY_REFLEX_WARNING)
    assert response["answer"].count(SAFETY_REFLEX_WARNING) == 1
    assert "Evidence-backed essential answer" in response["answer"]
    assert response["canonical_answer_en"].startswith(SAFETY_REFLEX_WARNING)


@pytest.mark.asyncio
async def test_translated_answer_preserves_exact_static_warning(safety_service):
    safety_service.translation_service = MagicMock()
    safety_service.language_handler.prepare_question = AsyncMock(
        return_value=SimpleNamespace(
            localized_question="Eine Supportperson fragte nach meinem Seed.",
            preprocessed_question="A support agent asked me for my seed.",
            canonical_question_en="A support agent asked me for my seed.",
            original_language="de",
            was_translated=True,
        )
    )
    safety_service.language_handler.translate_text_for_user = AsyncMock(
        return_value="Lokalisierte wesentliche Antwort."
    )

    response = await safety_service.query(
        "Eine Supportperson fragte nach meinem Seed.",
        chat_history=[],
        override_version="Bisq 2",
    )

    assert response["answer"] == (
        f"{SAFETY_REFLEX_WARNING}\n\nLokalisierte wesentliche Antwort."
    )
    safety_service.language_handler.translate_text_for_user.assert_awaited_once_with(
        "Evidence-backed essential answer.",
        "de",
        label="response",
    )


@pytest.mark.asyncio
async def test_generation_failure_returns_static_warning(safety_service):
    safety_service.rag_chain = MagicMock(side_effect=RuntimeError("synthetic failure"))

    response = await safety_service.query(
        "This website asks me to enter my seed.",
        chat_history=[],
        override_version="Bisq 2",
    )

    assert response["answer"] == SAFETY_REFLEX_WARNING
    assert response["forwarded_to_human"] is True
    assert response["error"] == "synthetic failure"
