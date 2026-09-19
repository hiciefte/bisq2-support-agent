"""Unknown-product retrieval must not silently use an Easy-only context."""

from unittest.mock import Mock

import pytest
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.interfaces import RetrievedDocument


def scoped_documents(query, k, filter_dict=None):
    protocol = (filter_dict or {}).get("protocol")
    return [
        RetrievedDocument(
            content=f"Evidence {protocol} {index}",
            metadata={"protocol": protocol, "title": f"{protocol}-{index}"},
            id=f"{protocol}-{index}",
            score=0.9 - index * 0.1,
        )
        for index in range(min(k, 4))
    ]


@pytest.mark.parametrize("with_scores", [False, True])
@pytest.mark.parametrize("version", [None, "Unknown"])
def test_unknown_searches_every_protocol_even_with_many_easy_results(
    with_scores, version
):
    backend = Mock()
    backend.retrieve.side_effect = scoped_documents
    backend.retrieve_with_scores.side_effect = scoped_documents
    backend.retrieve_semantic_with_scores.return_value = []
    retriever = DocumentRetriever(backend)

    if with_scores:
        docs, scores = retriever.retrieve_with_scores(
            "A transfer was rejected", version
        )
        calls = backend.retrieve_with_scores.call_args_list
        assert scores == pytest.approx(
            [score for score in (0.9, 0.8, 0.7, 0.6) for _ in range(3)]
        )
    else:
        docs = retriever.retrieve_with_version_priority(
            "A transfer was rejected", version
        )
        calls = backend.retrieve.call_args_list

    assert [call.kwargs["filter_dict"]["protocol"] for call in calls] == [
        "all",
        "multisig_v1",
        "bisq_easy",
    ]
    assert [doc.metadata["protocol"] for doc in docs] == [
        "all",
        "multisig_v1",
        "bisq_easy",
    ] * 4
    assert len({doc.metadata["_retrieved_id"] for doc in docs}) == 12
    formatted = retriever.format_documents(docs, version)
    assert formatted.index("Evidence all 0") < formatted.index("Evidence multisig_v1 0")
    assert formatted.index("Evidence multisig_v1 0") < formatted.index(
        "Evidence bisq_easy 0"
    )
    assert formatted.index("Evidence bisq_easy 0") < formatted.index("Evidence all 1")


@pytest.mark.parametrize(
    "version,first_scope", [("Bisq 1", "multisig_v1"), ("Bisq 2", "bisq_easy")]
)
def test_established_product_preserves_its_scored_retrieval_priority(
    version, first_scope
):
    backend = Mock()
    backend.retrieve_with_scores.side_effect = scoped_documents
    backend.retrieve_semantic_with_scores.return_value = []
    retriever = DocumentRetriever(backend)
    docs, _ = retriever.retrieve_with_scores("A transfer was rejected", version)
    assert docs[0].metadata["protocol"] == first_scope
    if version == "Bisq 1":
        assert all(doc.metadata["protocol"] != "bisq_easy" for doc in docs)
    else:
        assert all(doc.metadata["protocol"] == "bisq_easy" for doc in docs)


def test_unknown_fallback_preserves_relevance_order_without_product_bias():
    backend = Mock()
    fallback = [
        scoped_documents("", 1, {"protocol": protocol})[0]
        for protocol in ("all", "multisig_v1", "bisq_easy")
    ]
    backend.retrieve.side_effect = [RuntimeError("filter unavailable"), fallback]
    docs = DocumentRetriever(backend).retrieve_with_version_priority(
        "A transfer failed", "Unknown"
    )
    assert [doc.metadata["protocol"] for doc in docs] == [
        "all",
        "multisig_v1",
        "bisq_easy",
    ]


@pytest.mark.parametrize("with_scores", [False, True])
def test_imported_product_reference_retrieves_both_products(with_scores):
    question = (
        "After updating Bisq 2, my reputation no longer shows my imported "
        "Bisq 1 account age. What should I check?"
    )
    backend = Mock()
    backend.retrieve.side_effect = scoped_documents
    backend.retrieve_with_scores.side_effect = scoped_documents
    backend.retrieve_semantic_with_scores.return_value = []
    retriever = DocumentRetriever(backend)

    if with_scores:
        docs, _ = retriever.retrieve_with_scores(question, "Unknown")
        calls = backend.retrieve_with_scores.call_args_list
    else:
        docs = retriever.retrieve_with_version_priority(question, "Unknown")
        calls = backend.retrieve.call_args_list

    assert [call.kwargs["filter_dict"]["protocol"] for call in calls] == [
        "bisq_easy",
        "multisig_v1",
        "all",
    ]
    assert {doc.metadata["protocol"] for doc in docs} == {
        "bisq_easy",
        "multisig_v1",
        "all",
    }
