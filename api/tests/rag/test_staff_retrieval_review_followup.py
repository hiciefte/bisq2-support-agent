"""Strict Staff backfill preserves eligible sources and genuine ranked order."""

from unittest.mock import Mock

import pytest
from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver
from app.services.rag.document_retriever import DocumentRetriever

from tests.rag.test_staff_reranker_fallback import setup
from tests.rag.test_unknown_product_retrieval import scoped_documents

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("scored", [True, False])
async def test_explicit_easy_keeps_general_candidates_after_four_conflicting_hits(
    scored,
):
    backend = Mock()

    def records(query, k, filter_dict=None):
        rows = scoped_documents(query, k, filter_dict)
        for row in rows:
            row.metadata.update(
                type="wiki",
                title=(
                    "Bisq 1 wrong guide"
                    if row.metadata["protocol"] == "bisq_easy"
                    else "Bisq 2 general guide"
                ),
                url=f"https://bisq.wiki/Guide_{row.id}",
            )
        return rows

    backend.retrieve.side_effect = records
    backend.retrieve_with_scores.side_effect = records
    backend.retrieve_semantic_with_scores.return_value = []
    retriever = DocumentRetriever(backend)
    if scored:
        docs, _ = retriever.retrieve_with_scores(
            "I use Bisq 2.",
            "Bisq 2",
            detect_from_query=False,
            require_reranker_success=True,
        )
    else:
        docs = retriever.retrieve_with_version_priority(
            "I use Bisq 2.", "Bisq 2", detect_from_query=False
        )
    result = await StaffEvidenceResolver().resolve(
        question="I use Bisq 2.", documents=docs
    )
    assert result.evidence
    assert all(x.title == "Bisq 2 general guide" for x in result.evidence)


def test_ranked_prefix_stays_first_when_formatting_backfill():
    retriever, reranker = setup("success")
    reranker._model.rerank.return_value = [
        {"content": "Evidence multisig_v1 2", "score": 0.99},
        {"content": "Evidence bisq_easy 3", "score": 0.98},
    ]
    docs, _ = retriever.retrieve_with_scores(
        "Which step applies?", detect_from_query=False, require_reranker_success=True
    )
    assert [d.metadata["_retrieval_rank"] for d in docs] == list(range(len(docs)))
    assert all(d.metadata.get("_reranked") for d in docs[:2])
    assert not any(d.metadata.get("_reranked") for d in docs[2:])
    formatted = retriever.format_documents(docs)
    assert (
        formatted.index("Evidence multisig_v1 2")
        < formatted.index("Evidence bisq_easy 3")
        < formatted.index("Evidence all 0")
    )


def test_default_easy_preserves_threshold_behavior():
    backend = Mock(
        retrieve_with_scores=Mock(side_effect=scoped_documents),
        retrieve_semantic_with_scores=Mock(return_value=[]),
    )
    DocumentRetriever(backend).retrieve_with_scores("I use Bisq 2.", "Bisq 2")
    assert all(
        call.kwargs["filter_dict"]["protocol"] != "all"
        for call in backend.retrieve_with_scores.call_args_list
    )
