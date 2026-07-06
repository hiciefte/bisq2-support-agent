"""Service-level tests for SimplifiedRAGService review fixes (A2, A3, A9).

- A2: query() passes already-retrieved docs into the RAG chain (no second,
  version-blind retrieval), and generation context matches the sources docs.
- A3: the context-only fallback threads detected_version to the prompt.
- A9: comparison-token misfire — generic comparison wording without version
  tokens must not trigger Bisq 1 vs Bisq 2 comparison handling.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.rag.document_retriever import (
    _classify_query_protocol,
    is_bisq_version_comparison_query,
)
from app.services.rag.llm_provider import LLMResponse
from app.services.simplified_rag_service import SimplifiedRAGService
from langchain_core.documents import Document


def _make_docs():
    return [
        Document(
            page_content="Bisq Easy trades settle via chat. DOC_ALPHA",
            metadata={
                "type": "wiki",
                "title": "Trading",
                "section": "Intro",
                "protocol": "bisq_easy",
            },
        ),
        Document(
            page_content="Reputation matters in Bisq 2. DOC_BETA",
            metadata={
                "type": "wiki",
                "title": "Reputation",
                "section": None,
                "protocol": "bisq_easy",
            },
        ),
    ]


def _llm_invocation_text(llm) -> str:
    """Concatenate everything the mocked LLM saw across invoke() calls."""
    parts: list[str] = []
    for call in llm.invoke.call_args_list:
        parts.extend(str(a) for a in call.args)
        parts.extend(str(v) for v in call.kwargs.values())
    return " ".join(parts)


@pytest.fixture
def service(test_settings):
    svc = SimplifiedRAGService(settings=test_settings)

    # Mocked LLM capturing prompts
    llm = MagicMock()
    llm.invoke.return_value = LLMResponse(
        content="SEPA Instant settles faster than SEPA."
    )
    svc.llm = llm

    # Real prompt manager + real RAG chain wired with a retrieve_func that
    # must NOT be called when docs are passed in (A2).
    svc.prompt = svc.prompt_manager.create_rag_prompt()
    svc._chain_retrieve_func = MagicMock(return_value=_make_docs())
    svc.rag_chain = svc.prompt_manager.create_rag_chain(
        llm=llm,
        retrieve_func=svc._chain_retrieve_func,
        format_docs_func=lambda docs: "\n\n".join(d.page_content for d in docs),
    )

    # Authoritative retrieval used by query() for sources + confidence
    document_retriever = MagicMock()
    document_retriever.retrieve_with_scores.return_value = (_make_docs(), [0.9, 0.8])
    document_retriever.deduplicate_sources.side_effect = lambda sources: sources
    svc.document_retriever = document_retriever

    # Deterministic confidence/routing
    svc.confidence_scorer = MagicMock()
    svc.confidence_scorer.calculate_confidence = AsyncMock(return_value=0.9)
    svc.auto_send_router = MagicMock()
    svc.auto_send_router.route_response = AsyncMock(
        return_value=SimpleNamespace(action="auto_send", queue_for_review=False)
    )
    svc.routing_reason_generator = MagicMock()
    svc.routing_reason_generator.generate.return_value = "test-reason"

    return svc


class TestChainUsesPreRetrievedDocs:
    """A2: no version-blind duplicate retrieval in the answer path."""

    @pytest.mark.asyncio
    async def test_query_offloads_retrieval_and_generation(self, service, monkeypatch):
        """F8: sync retriever and LLM chain calls must not block the event loop."""
        offloaded = []
        retrieve_func = service.document_retriever.retrieve_with_scores
        rag_chain_func = service.rag_chain

        async def fake_to_thread(func, /, *args, **kwargs):
            offloaded.append(func)
            return func(*args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

        await service.query("How does reputation work in Bisq 2?", chat_history=[])

        assert any(func is retrieve_func for func in offloaded)
        assert any(func is rag_chain_func for func in offloaded)

    @pytest.mark.asyncio
    async def test_retriever_called_once_and_chain_does_not_re_retrieve(self, service):
        response = await service.query(
            "How does reputation work in Bisq 2?", chat_history=[]
        )

        assert service.document_retriever.retrieve_with_scores.call_count == 1
        service._chain_retrieve_func.assert_not_called()
        assert response["answer"]
        assert response["answered_from"] == "documents"

    @pytest.mark.asyncio
    async def test_generation_context_matches_source_docs(self, service):
        response = await service.query(
            "How does reputation work in Bisq 2?", chat_history=[]
        )

        invoked = _llm_invocation_text(service.llm)
        assert "DOC_ALPHA" in invoked
        assert "DOC_BETA" in invoked
        source_titles = {source["title"] for source in response["sources"]}
        assert source_titles == {"Trading", "Reputation"}


class TestContextOnlyFallbackVersion:
    """A3: detected version must survive into the context-only prompt."""

    @pytest.mark.asyncio
    async def test_bisq1_detected_version_reaches_context_only_prompt(self, service):
        service.document_retriever.retrieve_with_scores.return_value = ([], [])
        service.llm.invoke.return_value = LLMResponse(
            content="From context: reopen the dispute from the trade screen."
        )
        history = [
            {"role": "user", "content": "I'm using Bisq 1"},
            {"role": "assistant", "content": "OK, how can I help?"},
        ]

        response = await service.query(
            "How do I reopen my dispute?", chat_history=history
        )

        assert response.get("answered_from") == "context"
        invoked = _llm_invocation_text(service.llm)
        assert "The user asked about Bisq 1" in invoked
        assert "The user asked about Bisq 2/Bisq Easy" not in invoked


class TestComparisonClassification:
    """A9: comparison handling requires explicit version/protocol tokens."""

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("What is the difference between SEPA and SEPA Instant in Bisq?", False),
            ("difference between bisq 1 and bisq 2", True),
            ("compare the two bisq versions", True),
            ("bisq 1 vs bisq 2", True),
            ("What is the difference between Bisq Easy and multisig?", True),
            ("What payment methods are different in Europe?", False),
            # A bare "version(s)" token must not turn generic comparisons
            # into a Bisq 1 vs Bisq 2 comparison.
            (
                "difference between the old version and new version of the wallet",
                False,
            ),
            ("compare the app versions", False),
            ("what are the differences between both versions?", True),
            ("compare the versions of bisq", True),
        ],
    )
    def test_is_bisq_version_comparison_query(self, query, expected):
        assert is_bisq_version_comparison_query(query) is expected

    def test_classify_sepa_query_is_not_comparison_or_multisig(self):
        is_multisig, _mentions_easy, is_comparison = _classify_query_protocol(
            "What is the difference between SEPA and SEPA Instant in Bisq?"
        )
        assert is_comparison is False
        assert is_multisig is False

    def test_classify_explicit_version_comparison(self):
        is_multisig, mentions_easy, is_comparison = _classify_query_protocol(
            "What is the difference between Bisq 1 and Bisq 2?"
        )
        assert is_comparison is True

    @pytest.mark.asyncio
    async def test_sepa_question_not_forced_into_version_comparison(self, service):
        response = await service.query(
            "What is the difference between SEPA and SEPA Instant in Bisq?",
            chat_history=[],
            override_version="Bisq 2",
        )
        assert not response["answer"].startswith(
            "Difference between Bisq 1 and Bisq 2:"
        )

    @pytest.mark.asyncio
    async def test_real_version_comparison_still_gets_stable_heading(self, service):
        service.llm.invoke.return_value = LLMResponse(
            content="They use different trade protocols."
        )
        response = await service.query(
            "What is the difference between Bisq 1 and Bisq 2?",
            chat_history=[],
            override_version="Bisq 2",
        )
        assert response["answer"].startswith("Difference between Bisq 1 and Bisq 2:")
