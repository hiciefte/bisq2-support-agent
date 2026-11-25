"""Staff-established uncertainty must survive real retrieval and its fallback."""

from unittest.mock import Mock

import pytest
from app.services.rag.document_retriever import DocumentRetriever

from tests.rag.test_unknown_product_retrieval import scoped_documents

pytestmark = pytest.mark.unit


def backend():
    value = Mock()
    value.retrieve.side_effect = scoped_documents
    value.retrieve_with_scores.side_effect = scoped_documents
    value.retrieve_semantic_with_scores.return_value = []
    return value


@pytest.mark.parametrize("scored", [True, False])
@pytest.mark.parametrize(
    "query",
    [
        "Someone mentioned Bisq 1. Which application do I need?",
        "My trade protocol fails at market price.",
        "I am not using Bisq 1. Which steps apply?",
    ],
)
def test_staff_unknown_scope_is_not_overridden_by_query_keywords(query, scored):
    store = backend()
    retriever = DocumentRetriever(store)
    if scored:
        docs, _ = retriever.retrieve_with_scores(query, detect_from_query=False)
    else:
        docs = retriever.retrieve_with_version_priority(query, detect_from_query=False)
    assert {doc.metadata["protocol"] for doc in docs} == {
        "all",
        "multisig_v1",
        "bisq_easy",
    }


def test_staff_explicit_scope_wins_over_helper_product_in_enriched_query():
    store = backend()
    docs, _ = DocumentRetriever(store).retrieve_with_scores(
        "My connection fails. Helper: this is how Bisq 2 works.",
        detected_version="Bisq 1",
        detect_from_query=False,
    )
    assert docs[0].metadata["protocol"] == "multisig_v1"
    assert all(doc.metadata["protocol"] != "bisq_easy" for doc in docs)


def test_scored_failure_keeps_staff_scope_in_standard_fallback():
    store = backend()
    store.retrieve_with_scores.side_effect = RuntimeError("score lookup unavailable")
    docs, scores = DocumentRetriever(store).retrieve_with_scores(
        "My trade protocol fails at market price.", detect_from_query=False
    )
    assert {doc.metadata["protocol"] for doc in docs} == {
        "all",
        "multisig_v1",
        "bisq_easy",
    }
    assert scores == [0.5] * len(docs)


def test_default_routing_keeps_the_existing_non_staff_contract():
    store = backend()
    docs, _ = DocumentRetriever(store).retrieve_with_scores(
        "My trade protocol fails at market price."
    )
    assert {doc.metadata["protocol"] for doc in docs} == {"bisq_easy"}
