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
        sorted(docs, key=lambda doc: formatted.index(doc.page_content))[:2] == docs[:2]
    )


def test_default_easy_preserves_threshold_behavior():
    backend = Mock(
        retrieve_with_scores=Mock(side_effect=scoped_documents),
        retrieve_semantic_with_scores=Mock(return_value=[]),
    )
    docs, _ = DocumentRetriever(backend).retrieve_with_scores("I use Bisq 2.", "Bisq 2")
    backend.retrieve_with_scores.assert_called_once_with(
        "I use Bisq 2.", k=6, filter_dict={"protocol": "bisq_easy"}
    )
    assert [doc.page_content for doc in docs] == [
        f"Evidence bisq_easy {index}" for index in range(4)
    ]
    assert all(
        call.kwargs["filter_dict"]["protocol"] != "all"
        for call in backend.retrieve_with_scores.call_args_list
    )


@pytest.mark.parametrize("scored", [False, True])
def test_staff_supplemental_failure_keeps_completed_primary_hits(scored):
    """A failed supplemental lookup preserves valid scoped hits and their scores."""
    backend = Mock()

    def records(query, k, filter_dict=None):
        if filter_dict == {"protocol": "all"}:
            raise RuntimeError("supplemental store unavailable")
        assert filter_dict == {"protocol": "bisq_easy"}
        return scoped_documents(query, k, filter_dict)

    backend.retrieve.side_effect = records
    backend.retrieve_with_scores.side_effect = records
    backend.retrieve_semantic_with_scores.return_value = []
    retriever = DocumentRetriever(backend)
    if scored:
        docs, scores = retriever.retrieve_with_scores(
            "I use Bisq 2.", "Bisq 2", detect_from_query=False
        )
        assert scores == pytest.approx([0.9, 0.8, 0.7, 0.6])
        backend.retrieve.assert_not_called()
        calls = backend.retrieve_with_scores.call_args_list
    else:
        docs = retriever.retrieve_with_version_priority(
            "I use Bisq 2.", "Bisq 2", detect_from_query=False
        )
        calls = backend.retrieve.call_args_list
    assert [doc.page_content for doc in docs] == [
        f"Evidence bisq_easy {index}" for index in range(4)
    ]
    assert [call.kwargs["filter_dict"]["protocol"] for call in calls] == [
        "bisq_easy",
        "all",
    ]
