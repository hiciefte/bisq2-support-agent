"""Unavailable reranking must not masquerade as ranked, truncated Staff evidence."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver
from app.services.rag.colbert_reranker import ColBERTReranker
from app.services.rag.document_retriever import DocumentRetriever

from tests.rag.test_unknown_product_retrieval import scoped_documents

pytestmark = pytest.mark.unit


def setup(mode):
    settings = NS(
        ENABLE_COLBERT_RERANK=mode != "disabled",
        COLBERT_MODEL="synthetic-local",
        COLBERT_TOP_N=5,
    )
    reranker = ColBERTReranker(settings)
    reranker._ensure_model_loaded = Mock(return_value=mode != "unavailable")
    reranker._model = NS(rerank=Mock())
    if mode == "exception":
        reranker._model.rerank.side_effect = RuntimeError("synthetic failure")
    elif mode == "empty":
        reranker._model.rerank.return_value = []
    elif mode == "unknown":
        reranker._model.rerank.return_value = [{"content": "invented", "score": 0.9}]
    elif mode == "nan":
        reranker._model.rerank.return_value = [
            {"content": "Evidence all 0", "score": float("nan")}
        ]
    elif mode == "missing_score":
        reranker._model.rerank.return_value = [{"content": "Evidence all 0"}]
    elif mode == "short_tuple":
        reranker._model.rerank.return_value = [("Evidence all 0",)]
    elif mode == "duplicate":
        reranker._model.rerank.return_value = [
            {"content": "Evidence all 0", "score": 0.9},
            {"content": "Evidence all 0", "score": 0.8},
        ]
    else:
        reranker._model.rerank.return_value = [
            {"content": "Evidence multisig_v1 1", "score": 0.99}
        ]
    backend = Mock()
    backend.retrieve.side_effect = scoped_documents
    backend.retrieve_with_scores.side_effect = scoped_documents
    backend.retrieve_semantic_with_scores.return_value = []
    return DocumentRetriever(backend, reranker=reranker, rerank_top_n=5), reranker


@pytest.mark.parametrize(
    "mode",
    [
        "disabled",
        "unavailable",
        "exception",
        "empty",
        "unknown",
        "nan",
        "missing_score",
        "short_tuple",
        "duplicate",
    ],
)
def test_staff_retains_all_candidates_and_scores_when_ranking_not_proven(mode):
    retriever, _ = setup(mode)
    docs, scores = retriever.retrieve_with_scores(
        "My trade protocol fails at market price.",
        detect_from_query=False,
        require_reranker_success=True,
    )
    assert len(docs) == 12
    assert [doc.metadata["protocol"] for doc in docs] == [
        "all",
        "multisig_v1",
        "bisq_easy",
    ] * 4
    assert not any(doc.metadata.get("_reranked") for doc in docs)
    assert not any("_colbert_score" in doc.metadata for doc in docs)
    assert scores == pytest.approx([s for s in (0.9, 0.8, 0.7, 0.6) for _ in range(3)])


def test_verified_staff_ranking_preserves_original_retrieval_score():
    retriever, _ = setup("success")
    docs, scores = retriever.retrieve_with_scores(
        "A transfer failed", detect_from_query=False, require_reranker_success=True
    )
    assert len(docs) == 12
    assert docs[0].metadata["_retrieved_id"] == "multisig_v1-1"
    assert docs[0].metadata["_reranked"] is True
    assert docs[0].metadata["_colbert_score"] == 0.99
    assert scores[0] == pytest.approx(0.8)
    assert not any(doc.metadata.get("_reranked") for doc in docs[1:])


def test_default_unavailable_reranker_retains_existing_behavior():
    retriever, _ = setup("unavailable")
    docs, _ = retriever.retrieve_with_scores("A transfer failed")
    assert len(docs) == 5


@pytest.mark.asyncio
async def test_successful_staff_rank_backfills_after_product_applicability_filter():
    retriever, reranker = setup("success")

    def titled_documents(query, k, filter_dict=None):
        rows = scoped_documents(query, k, filter_dict)
        for row in rows:
            row.metadata.update(
                type="wiki",
                title=(
                    "Bisq 2 applicable guide"
                    if row.id == "bisq_easy-3"
                    else "Bisq 1 wallet recovery"
                ),
                url=f"https://bisq.wiki/Guide_{row.id}",
            )
        return rows

    retriever.retriever.retrieve_with_scores.side_effect = titled_documents
    reranker._model.rerank.return_value = [
        {"content": f"Evidence all {index}", "score": 0.99 - index / 100}
        for index in range(4)
    ] + [{"content": "Evidence bisq_easy 0", "score": 0.9}]
    docs, _ = retriever.retrieve_with_scores(
        "Which procedure applies?",
        detect_from_query=False,
        require_reranker_success=True,
    )
    assert len(docs) == 12
    assert all(doc.metadata.get("_reranked") for doc in docs[:5])
    assert docs[-1].metadata["_retrieved_id"] == "bisq_easy-3"
    result = await StaffEvidenceResolver().resolve(
        question="I use Bisq 2; which procedure applies?",
        documents=docs,
    )
    assert [entry.content for entry in result.evidence] == ["Evidence bisq_easy 3"]
    assert len(result.excluded_evidence) == 11


def test_ambiguous_equal_bodies_cannot_attach_the_wrong_source_provenance():
    retriever, reranker = setup("success")
    original = scoped_documents

    def duplicate_bodies(query, k, filter_dict=None):
        docs = original(query, k, filter_dict)
        for doc in docs:
            doc.content = "A shared excerpt with different provenance"
        return docs

    retriever.retriever.retrieve_with_scores.side_effect = duplicate_bodies
    reranker._model.rerank.return_value = [
        {"content": "A shared excerpt with different provenance", "score": 0.9}
    ]
    docs, _ = retriever.retrieve_with_scores(
        "A transfer failed", detect_from_query=False, require_reranker_success=True
    )
    assert len(docs) == 12
    assert len({doc.metadata["_retrieved_id"] for doc in docs}) == 12
    assert not any(doc.metadata.get("_reranked") for doc in docs)


def test_staff_scope_remains_exact_during_reranking_failure():
    retriever, _ = setup("unavailable")
    docs, _ = retriever.retrieve_with_scores(
        "Helper mentions Bisq 2",
        detected_version="Bisq 1",
        detect_from_query=False,
        require_reranker_success=True,
    )
    assert {doc.metadata["protocol"] for doc in docs} == {"all", "multisig_v1"}
