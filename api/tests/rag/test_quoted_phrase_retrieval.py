"""Quoted terms may recover a missing chunk without changing unrelated queries."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.interfaces import RetrievedDocument, RetrieverProtocol


def document(index, *, protocol="bisq_easy", content=None, score=None):
    return RetrievedDocument(
        id=f"{protocol}-{index}",
        content=content or f"Offer wizard passage {index}",
        metadata={"protocol": protocol, "title": f"Passage {index}"},
        score=score if score is not None else 0.9 - index * 0.01,
    )


def backend_for(baseline, expanded):
    backend = Mock()

    def retrieve(query, k, filter_dict):
        if filter_dict["protocol"] == "all":
            return []
        return baseline[:k]

    backend.retrieve.side_effect = retrieve
    backend.retrieve_with_scores.side_effect = retrieve
    backend.retrieve_semantic_with_scores.return_value = []
    backend.retrieve_hybrid.return_value = expanded
    return backend


def run(backend, query, with_scores):
    retriever = DocumentRetriever(backend)
    if with_scores:
        docs, scores = retriever.retrieve_with_scores(query, "Unknown")
        calls = backend.retrieve_with_scores.call_args_list
    else:
        docs = retriever.retrieve_with_version_priority(query, "Unknown")
        scores = None
        calls = backend.retrieve.call_args_list
    return docs, scores, calls


@pytest.mark.parametrize("with_scores", [False, True])
@pytest.mark.parametrize(
    "product,protocol,k", [("Bisq 2", "bisq_easy", 6), ("Bisq 1", "multisig_v1", 4)]
)
@pytest.mark.parametrize("quote", ['"Trade Terms"', "“TRADE   TERMS”"])
@pytest.mark.parametrize("sparse_score", [0.003, 38.5])
def test_recovers_missing_phrase_chunk_in_same_scope_with_original_scores(
    with_scores, product, protocol, k, quote, sparse_score
):
    baseline = [document(i, protocol=protocol) for i in range(k)]
    # Widened hybrid retrieval can reorder/rescale original hits. Do not replace
    # baseline scores or treat two candidate pools as one calibrated score list.
    expanded = [document(i, protocol=protocol, score=0.2) for i in range(12)]
    target = document(
        9,
        protocol=protocol,
        content="The maker defines the trade terms.",
        score=sparse_score,
    )
    expanded[9] = target
    backend = backend_for(baseline, expanded)
    docs, scores, calls = run(
        backend,
        f"What is the {quote} field in {product}?",
        with_scores,
    )
    assert [d.metadata["_retrieved_id"] for d in docs] == [target.id] + [
        d.id for d in baseline[: k - 1]
    ]
    assert docs[0].metadata["_quoted_phrase_candidate_rank"] == 9
    assert docs[0].metadata["_quoted_phrase_candidate_limit"] == 12
    assert docs[1].metadata["_quoted_phrase_candidate_rank"] == 0
    assert docs[1].metadata["_quoted_phrase_candidate_limit"] == k
    assert calls[0].kwargs == {"k": k, "filter_dict": {"protocol": protocol}}
    backend.retrieve_hybrid.assert_called_once_with(
        "trade terms",
        k=12,
        semantic_weight=0.0,
        keyword_weight=1.0,
        filter_dict={"protocol": protocol},
    )
    assert docs[0].metadata["_quoted_phrase_candidate_score"] == sparse_score
    assert docs[0].metadata["_quoted_phrase_candidate_score_type"] == "sparse_bm25"
    assert docs[0].metadata["_score_type"] == "keyword_only"
    assert "_relative_rank_score" not in docs[0].metadata
    if with_scores:
        assert scores == pytest.approx([0.0] + [d.score for d in baseline[: k - 1]])
        assert docs[0].metadata["_retrieval_score"] == 0.0
    assert all("_quoted_phrase_candidate_rank" not in d.metadata for d in baseline)


@pytest.mark.parametrize("with_scores", [False, True])
def test_no_exact_match_keeps_baseline_even_if_expansion_reorders_scores(with_scores):
    baseline = [document(i) for i in range(6)]
    expanded = [document(i, score=0.1) for i in reversed(range(12))]
    # Neither substring coincidence nor an unrelated quoted term promotes a hit.
    expanded[0].content = "The maker defines the trade terms."
    expanded[1].content = "The account feeschedule changed."
    docs, scores, calls = run(
        backend_for(baseline, expanded),
        'What does "account fees" mean in Bisq 2?',
        with_scores,
    )
    assert [d.metadata["_retrieved_id"] for d in docs] == [d.id for d in baseline]
    assert all("_quoted_phrase_candidate_rank" not in d.metadata for d in docs)
    assert [call.kwargs["k"] for call in calls] == [6]
    if with_scores:
        assert scores == pytest.approx([d.score for d in baseline])


@pytest.mark.parametrize("with_scores", [False, True])
@pytest.mark.parametrize(
    "term",
    [
        "Trade Terms",
        "'Trade Terms'",
        '"Terms"',
        '"Trade Terms" and "Payment Details"',
        '"Trade Terms" and an unmatched "',
        '"one two three four five six seven eight nine"',
        '"' + "long" * 21 + ' term"',
    ],
)
def test_absent_or_excessive_quotes_leave_default_budget_unchanged(with_scores, term):
    baseline = [document(i) for i in range(6)]
    backend = backend_for(baseline, [])
    docs, _, calls = run(backend, f"What is {term} in Bisq 2?", with_scores)
    assert [d.metadata["_retrieved_id"] for d in docs] == [d.id for d in baseline]
    assert [call.kwargs["k"] for call in calls] == [6]
    backend.retrieve_hybrid.assert_not_called()


@pytest.mark.parametrize("with_scores", [False, True])
@pytest.mark.parametrize(
    "query", ['What are "Trade Terms"?', 'Compare "Trade Terms" in Bisq 1 and Bisq 2.']
)
def test_unknown_and_comparison_scopes_do_not_expand_quoted_terms(with_scores, query):
    baseline = [document(i) for i in range(6)]
    backend = backend_for(baseline, [])
    _, _, calls = run(backend, query, with_scores)
    backend.retrieve_hybrid.assert_not_called()
    assert all(call.kwargs["k"] != 12 for call in calls)
    assert {call.kwargs["filter_dict"]["protocol"] for call in calls} == {
        "all",
        "multisig_v1",
        "bisq_easy",
    }


@pytest.mark.parametrize("with_scores", [False, True])
def test_baseline_phrase_matches_are_stable_without_extra_call(with_scores):
    baseline = [document(i) for i in range(6)]
    baseline[2].content = "Trade terms explain maker preferences."
    baseline[4].content = "The profile contains trade terms."
    backend = backend_for(baseline, [])
    docs, _, calls = run(backend, 'What are "Trade Terms" in Bisq 2?', with_scores)
    assert [d.metadata["_retrieved_id"] for d in docs] == [
        baseline[i].id for i in [2, 4, 0, 1, 3, 5]
    ]
    assert [call.kwargs["k"] for call in calls] == [6]
    backend.retrieve_hybrid.assert_not_called()


@pytest.mark.parametrize("with_scores", [False, True])
def test_optional_expansion_failure_preserves_baseline_without_scope_fallback(
    with_scores,
):
    baseline = [document(i) for i in range(6)]
    backend = backend_for(baseline, [])
    backend.retrieve_hybrid.side_effect = RuntimeError("optional sparse unavailable")
    docs, scores, calls = run(backend, 'What are "Trade Terms" in Bisq 2?', with_scores)
    assert [d.metadata["_retrieved_id"] for d in docs] == [d.id for d in baseline]
    assert len(calls) == 1
    backend.retrieve_hybrid.assert_called_once()
    assert all(
        call.kwargs["filter_dict"] == {"protocol": "bisq_easy"} for call in calls
    )
    if with_scores:
        assert scores == pytest.approx([d.score for d in baseline])


@pytest.mark.parametrize("with_scores", [False, True])
def test_expansion_cannot_promote_match_from_another_protocol(with_scores):
    baseline = [document(i) for i in range(6)]
    wrong_scope = document(9, protocol="multisig_v1", content="Trade terms")
    docs, _, _ = run(
        backend_for(baseline, [wrong_scope]),
        'What are "Trade Terms" in Bisq 2?',
        with_scores,
    )
    assert [d.metadata["_retrieved_id"] for d in docs] == [d.id for d in baseline]


@pytest.mark.parametrize("with_scores", [False, True])
@pytest.mark.parametrize("capability", ["missing", "noncallable"])
def test_unsupported_sparse_backend_returns_baseline(with_scores, capability):
    baseline = [document(i) for i in range(6)]
    backend = Mock(spec=RetrieverProtocol)
    backend.retrieve.return_value = baseline
    backend.retrieve_with_scores.return_value = baseline
    if capability == "noncallable":
        backend.retrieve_hybrid = None
    docs, scores, calls = run(backend, 'What are "Trade Terms" in Bisq 2?', with_scores)
    assert [d.metadata["_retrieved_id"] for d in docs] == [d.id for d in baseline]
    assert len(calls) == 1
    if with_scores:
        assert scores == pytest.approx([d.score for d in baseline])


@pytest.mark.parametrize("with_scores", [False, True])
def test_sparse_shared_ids_never_replace_baseline_payload_or_scores(with_scores):
    baseline = [document(i) for i in range(6)]
    # Simulate a repeated ID carrying a different snippet and raw BM25 score.
    # Its identity must keep the original full-query payload and score.
    shared = document(0, content="Trade terms in another snapshot", score=41.0)
    target = document(9, content="Maker defines trade terms", score=0.01)
    docs, scores, _ = run(
        backend_for(baseline, [shared, target]),
        'What are "Trade Terms" in Bisq 2?',
        with_scores,
    )
    assert [d.metadata["_retrieved_id"] for d in docs] == [target.id] + [
        d.id for d in baseline[:5]
    ]
    assert docs[1].page_content == baseline[0].content
    if with_scores:
        assert scores == pytest.approx([0.0] + [d.score for d in baseline[:5]])


def test_qdrant_sparse_capability_never_embeds_and_preserves_raw_score():
    from app.services.rag.qdrant_hybrid_retriever import QdrantHybridRetriever

    backend = QdrantHybridRetriever.__new__(QdrantHybridRetriever)
    backend._embeddings = Mock()
    backend._embeddings.embed_query.side_effect = AssertionError("no embedding allowed")
    backend._bm25_tokenizer = Mock()
    backend._bm25_tokenizer.tokenize_query.return_value = ([1, 2], [0.4, 0.2])
    backend._build_filter = Mock(return_value="same-protocol-filter")
    backend._query_points = Mock(
        return_value=[
            SimpleNamespace(
                id="target",
                score=38.5,
                payload={"content": "Trade terms", "protocol": "bisq_easy"},
            )
        ]
    )
    docs = backend.retrieve_hybrid(
        "trade terms",
        k=12,
        semantic_weight=0.0,
        keyword_weight=1.0,
        filter_dict={"protocol": "bisq_easy"},
    )
    assert [(doc.id, doc.score) for doc in docs] == [("target", 38.5)]
    backend._embeddings.embed_query.assert_not_called()
    backend._bm25_tokenizer.tokenize_query.assert_called_once_with("trade terms")
    assert backend._query_points.call_args.kwargs["using"] == "sparse"
    assert backend._query_points.call_args.kwargs["limit"] == 12
    assert (
        backend._query_points.call_args.kwargs["query_filter"] == "same-protocol-filter"
    )


def test_keyword_only_score_stays_uncalibrated_through_service_weighting():
    from app.services.simplified_rag_service import SimplifiedRAGService

    baseline = [document(i) for i in range(6)]
    target = document(9, content="Maker defines trade terms", score=38.5)
    docs, scores, _ = run(
        backend_for(baseline, [target]), 'What are "Trade Terms" in Bisq 2?', True
    )
    service = SimpleNamespace(
        source_weights={"wiki": 1.0},
        _refresh_source_weights=lambda: None,
        _source_type_for_document=lambda doc: "wiki",
    )
    weighted_docs, weighted_scores = SimplifiedRAGService._apply_runtime_source_weights(
        service, docs, scores
    )
    assert len(weighted_docs) == 6
    assert weighted_docs[-1].metadata["_retrieved_id"] == target.id
    assert weighted_docs[-1].metadata["_score_type"] == "keyword_only"
    assert weighted_scores[-1] == 0.0
    assert (
        SimplifiedRAGService._best_calibrated_retrieval_score(
            [weighted_docs[-1]], [weighted_scores[-1]]
        )
        is None
    )
