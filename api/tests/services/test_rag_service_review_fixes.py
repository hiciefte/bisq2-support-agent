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
from app.prompts import error_messages
from app.services.rag.auto_send_router import AutoSendRouter
from app.services.rag.canonical_fixes import CANONICAL_FIXES
from app.services.rag.document_retriever import (
    DocumentRetriever,
    _classify_query_protocol,
    is_bisq_version_comparison_query,
)
from app.services.rag.llm_provider import LLMResponse, ToolCallResult
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
                "_score_type": "absolute_cosine",
            },
        ),
        Document(
            page_content="Reputation matters in Bisq 2. DOC_BETA",
            metadata={
                "type": "wiki",
                "title": "Reputation",
                "section": None,
                "protocol": "bisq_easy",
                "_score_type": "absolute_cosine",
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
    async def test_setup_applies_learned_source_weights_before_loading(
        self, test_settings
    ):
        """F5: rebuilt document payloads should carry learned source weights."""
        events: list[str] = []
        feedback_service = MagicMock()
        feedback_service.get_source_weights.return_value = {
            "wiki": 0.8,
            "faq": 1.15,
            "llm_wiki": 1.05,
        }
        wiki_service = MagicMock()
        wiki_service.update_source_weights.side_effect = lambda weights: events.append(
            f"wiki:update:{weights['wiki']}"
        )
        wiki_service.load_wiki_data.side_effect = lambda: events.append(
            "wiki:load"
        ) or [
            Document(
                page_content="wiki",
                metadata={"type": "wiki", "source_weight": 0.8},
            )
        ]
        faq_service = MagicMock()
        faq_service.update_source_weights.side_effect = lambda weights: events.append(
            f"faq:update:{weights['faq']}"
        )
        faq_service.load_faq_data.side_effect = lambda: events.append("faq:load") or [
            Document(
                page_content="faq",
                metadata={"type": "faq", "source_weight": 1.15},
            )
        ]

        svc = SimplifiedRAGService(
            settings=test_settings,
            feedback_service=feedback_service,
            wiki_service=wiki_service,
            faq_service=faq_service,
        )
        llm_loader = MagicMock()
        llm_loader.update_source_weights.side_effect = lambda weights: events.append(
            f"llm:update:{weights['llm_wiki']}"
        )
        llm_loader.load_documents.side_effect = lambda _path: events.append(
            "llm:load"
        ) or [
            Document(
                page_content="llm",
                metadata={"type": "llm_wiki", "source_weight": 1.05},
            )
        ]
        svc.llm_wiki_loader = llm_loader
        svc.document_processor.split_documents = MagicMock(
            side_effect=lambda docs: docs
        )
        svc.initialize_embeddings = MagicMock()
        svc.initialize_embeddings.side_effect = lambda: setattr(
            svc, "embeddings", MagicMock()
        )
        svc.index_manager.rebuild_index = MagicMock(return_value={"status": "ok"})
        svc._initialize_retriever = MagicMock()
        svc._initialize_retriever.side_effect = lambda: setattr(
            svc, "retriever", MagicMock()
        )
        svc.initialize_llm = MagicMock()
        svc.initialize_llm.side_effect = lambda: setattr(svc, "llm", MagicMock())

        events.clear()
        assert await svc.setup() is True

        assert events.index("wiki:update:0.8") < events.index("wiki:load")
        assert events.index("faq:update:1.15") < events.index("faq:load")
        assert events.index("llm:update:1.05") < events.index("llm:load")

    def test_query_time_source_weights_reorder_retrieved_docs(self, test_settings):
        """F5: learned weight changes affect retrieval output without rebuild."""
        feedback_service = MagicMock()
        feedback_service.get_source_weights.return_value = {"wiki": 0.5, "faq": 2.0}
        svc = SimplifiedRAGService(
            settings=test_settings,
            feedback_service=feedback_service,
        )
        docs = [
            Document(page_content="wiki", metadata={"type": "wiki"}),
            Document(page_content="faq", metadata={"type": "faq"}),
        ]

        weighted_docs, weighted_scores = svc._apply_runtime_source_weights(
            docs, [0.9, 0.5]
        )

        assert [doc.metadata["type"] for doc in weighted_docs] == ["faq", "wiki"]
        assert weighted_scores == [0.5, 0.9]
        assert weighted_docs[0].metadata["source_weight"] == 2.0

    def test_query_time_source_weights_preserve_protocol_buckets(self, test_settings):
        """F5: source weights cannot undo protocol-aware retrieval buckets."""
        feedback_service = MagicMock()
        feedback_service.get_source_weights.return_value = {"wiki": 0.5, "faq": 2.0}
        svc = SimplifiedRAGService(
            settings=test_settings,
            feedback_service=feedback_service,
        )
        docs = [
            Document(
                page_content="wiki",
                metadata={"type": "wiki", "protocol": "bisq_easy"},
            ),
            Document(
                page_content="faq",
                metadata={"type": "faq", "protocol": "multisig_v1"},
            ),
        ]

        weighted_docs, weighted_scores = svc._apply_runtime_source_weights(
            docs, [0.9, 0.5]
        )

        assert [doc.metadata["protocol"] for doc in weighted_docs] == [
            "bisq_easy",
            "multisig_v1",
        ]
        assert weighted_scores == [0.9, 0.5]

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

    @pytest.mark.asyncio
    async def test_stream_query_bypasses_mcp_for_non_live_questions(self, service):
        """F30: MCP-enabled deployments should still stream ordinary RAG answers."""
        service.mcp_enabled = True
        service.llm.stream.return_value = iter(["Streamed ", "answer"])
        service.llm.invoke_with_tools = MagicMock(
            return_value=ToolCallResult(content="Buffered answer")
        )

        events = [
            event
            async for event in service.stream_query(
                "What is Bisq Easy?",
                chat_history=[],
            )
        ]

        assert [event["event"] for event in events] == ["token", "token", "final"]
        assert events[0]["data"] == "Streamed "
        assert events[1]["data"] == "answer"
        assert events[2]["data"]["answer"]
        service.llm.invoke_with_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_query_keeps_mcp_for_live_data_questions(self, service):
        """Live-data questions still use the buffered tool-enabled invocation."""
        service.mcp_enabled = True
        service.llm.stream = MagicMock(return_value=iter(["unexpected"]))
        service.llm.invoke_with_tools = MagicMock(
            return_value=ToolCallResult(
                content="BTC price is unavailable.",
                tool_calls_made=[
                    {"tool": "get_market_prices", "result": '{"BTC":null}'}
                ],
            )
        )

        events = [
            event
            async for event in service.stream_query(
                "What is the BTC price right now?",
                chat_history=[],
            )
        ]

        assert [event["event"] for event in events] == ["final"]
        assert events[0]["data"]["answer"]
        assert events[0]["data"]["mcp_tools_used"][0]["tool"] == "get_market_prices"
        service.llm.stream.assert_not_called()
        service.llm.invoke_with_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_query_emits_error_after_partial_generation_failure(
        self, service
    ):
        """Streaming failures after partial output surface an error event."""
        service.mcp_enabled = False

        def failing_stream(*args, **kwargs):
            yield "Partial "
            raise RuntimeError("stream failed")

        service.llm.stream.side_effect = failing_stream

        events = [
            event
            async for event in service.stream_query(
                "What is Bisq Easy?",
                chat_history=[],
            )
        ]

        assert [event["event"] for event in events] == ["token", "error"]
        assert events[0]["data"] == "Partial "
        assert "stream failed" in events[1]["data"]


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

    @pytest.mark.asyncio
    async def test_context_only_fallback_is_always_queued_for_review(self, service):
        service.document_retriever.retrieve_with_scores.return_value = ([], [])
        service.llm.invoke.return_value = LLMResponse(
            content="From context: reopen the dispute from the trade screen."
        )

        response = await service.query(
            "How do I reopen it?",
            chat_history=[
                {"role": "user", "content": "My dispute closed."},
                {"role": "assistant", "content": "Let's look at that."},
            ],
            override_version="Bisq 1",
        )

        assert response["answered_from"] == "context"
        assert response["routing_action"] == "needs_human"
        assert response["requires_human"] is True
        assert response["forwarded_to_human"] is True


class TestFailClosedAnswerRouting:
    @pytest.mark.asyncio
    async def test_sub_floor_retrieval_forces_existing_router_to_review(self, service):
        service.settings.RAG_RETRIEVAL_RELEVANCE_FLOOR = 0.65
        service.document_retriever.retrieve_with_scores.return_value = (
            _make_docs(),
            [0.64, 0.50],
        )
        service.confidence_scorer.calculate_confidence = AsyncMock(return_value=0.99)
        service.auto_send_router = AutoSendRouter()

        response = await service.query(
            "How does reputation work in Bisq 2?", chat_history=[]
        )

        assert response["confidence"] == 0.0
        assert response["routing_action"] == "needs_human"
        assert response["requires_human"] is True
        assert response["forwarded_to_human"] is True

    @pytest.mark.asyncio
    async def test_above_floor_retrieval_keeps_normal_router_decision(self, service):
        service.settings.RAG_RETRIEVAL_RELEVANCE_FLOOR = 0.65
        service.document_retriever.retrieve_with_scores.return_value = (
            _make_docs(),
            [0.90, 0.80],
        )
        service.confidence_scorer.calculate_confidence = AsyncMock(return_value=0.99)
        service.auto_send_router = AutoSendRouter()

        response = await service.query(
            "How does reputation work in Bisq 2?", chat_history=[]
        )

        assert response["confidence"] == 0.99
        assert response["routing_action"] == "auto_send"
        assert response["requires_human"] is False

    @pytest.mark.asyncio
    async def test_uncalibrated_retrieval_fails_closed_to_review(self, service):
        docs = _make_docs()
        for doc in docs:
            doc.metadata.pop("_score_type")
        service.document_retriever.retrieve_with_scores.return_value = (
            docs,
            [0.99, 0.98],
        )
        service.confidence_scorer.calculate_confidence = AsyncMock(return_value=0.99)
        service.auto_send_router = AutoSendRouter()

        response = await service.query(
            "How does reputation work in Bisq 2?", chat_history=[]
        )

        assert response["confidence"] == 0.0
        assert response["routing_action"] == "needs_human"
        assert "relevance" in response["routing_reason"].lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure_mode", ["timeout", "infrastructure", "tool_unavailable"]
    )
    async def test_live_data_failure_returns_deterministic_review_response(
        self, service, failure_mode
    ):
        service.mcp_enabled = True
        service.rag_chain = MagicMock(return_value="Static BTC price from documents")
        service.auto_send_router = AutoSendRouter()
        if failure_mode == "timeout":
            service.llm.invoke_with_tools = MagicMock(
                side_effect=TimeoutError("MCP request timed out")
            )
        elif failure_mode == "infrastructure":
            service.llm.invoke_with_tools = MagicMock(
                return_value=ToolCallResult(
                    content="MCP transport failed",
                    success=False,
                )
            )
        else:
            service.llm.invoke_with_tools = MagicMock(
                return_value=ToolCallResult(
                    content="A static-looking current price",
                    tool_calls_made=[
                        {
                            "tool": "get_market_prices",
                            "result": "[Live Price Data Unavailable: temporary failure]",
                        }
                    ],
                )
            )

        response = await service.query(
            "What is the BTC price right now?", chat_history=[]
        )

        assert response["answer"] == error_messages.LIVE_DATA_UNAVAILABLE
        assert response["routing_action"] == "needs_human"
        assert response["requires_human"] is True
        assert response["forwarded_to_human"] is True
        assert response["mcp_tools_used"] is None
        service.rag_chain.assert_not_called()


class TestCanonicalFixInjection:
    """G3: verified issue matches become Context and deterministic sources."""

    @pytest.mark.asyncio
    async def test_no_retrieved_docs_uses_canonical_fix_and_exact_source(self, service):
        service.document_retriever.retrieve_with_scores.return_value = ([], [])
        fix = CANONICAL_FIXES["payment-started-confirmation-loop"]

        response = await service.query(
            "Payment started keeps saying please send confirmation again",
            chat_history=[],
            override_version="Bisq 1",
        )

        assert response["answered_from"] == "documents"
        assert response["sources"][0]["url"] == fix.url
        assert response["sources"][0]["similarity_score"] is None
        assert fix.remedy in _llm_invocation_text(service.llm)

    def test_canonical_fix_is_not_injected_for_explicit_bisq2(self, service):
        docs, scores = service._inject_canonical_fix(
            [],
            [],
            "How do I open mediation in Bisq 2?",
            "Bisq 2",
        )

        assert docs == []
        assert scores == []

    def test_existing_exact_canonical_document_is_promoted_without_duplication(
        self, service
    ):
        fix = CANONICAL_FIXES["incomplete-spv-resync"]
        unrelated = Document(page_content="Other", metadata={"type": "wiki"})
        canonical = fix.to_document()

        docs, scores = service._inject_canonical_fix(
            [unrelated, canonical],
            [0.8, 0.7],
            "My SPV resync is stuck at zero",
            "Bisq 1",
        )

        assert docs == [canonical, unrelated]
        assert scores == [0.7, 0.8]
        assert [doc.metadata["_retrieval_rank"] for doc in docs] == [0, 1]
        assert sum(doc.metadata.get("canonical_fix_id") == fix.key for doc in docs) == 1

    def test_matching_url_without_registry_id_does_not_replace_curated_fix(
        self, service
    ):
        fix = CANONICAL_FIXES["incomplete-spv-resync"]
        untrusted = Document(
            page_content="Unreviewed content with copied metadata URL.",
            metadata={"type": "wiki", "url": fix.url},
        )

        docs, _ = service._inject_canonical_fix(
            [untrusted],
            [0.9],
            "My SPV resync is stuck at zero",
            "Bisq 1",
        )

        assert docs[0].metadata["canonical_fix_id"] == fix.key
        assert docs[0].metadata["_canonical_fix_injected"] is True
        assert docs[0].page_content != untrusted.page_content
        assert docs[1] is untrusted

    def test_canonical_fix_stays_first_when_ranked_docs_are_formatted(self, service):
        retrieved = Document(
            page_content="Retrieved context that must follow the canonical fix.",
            metadata={
                "type": "wiki",
                "protocol": "multisig_v1",
                "_retrieval_rank": 0,
            },
        )

        docs, _ = service._inject_canonical_fix(
            [retrieved],
            [0.9],
            "My SPV resync is stuck at zero",
            "Bisq 1",
        )
        formatted = DocumentRetriever(MagicMock()).format_documents(
            docs, detected_version="Bisq 1"
        )

        remedy = CANONICAL_FIXES["incomplete-spv-resync"].remedy
        assert formatted.index(remedy) < formatted.index("Retrieved context")


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
