"""Offline wiki-to-retrieval provenance tests; no embeddings, model or DB calls."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver
from app.channels.staff_assist.public_context import PublicContextRequest
from app.services.rag.colbert_reranker import ColBERTReranker
from app.services.rag.document_processor import DocumentProcessor
from app.services.rag.document_retriever import DocumentRetriever
from app.services.rag.interfaces import RetrievedDocument
from app.services.wiki_provenance import wiki_context_notice, wiki_source_provenance
from app.services.wiki_service import WikiService
from langchain_core.documents import Document

pytestmark = pytest.mark.unit


def load(tmp_path, entries):
    """Load isolated source records through the production wiki loader."""
    (tmp_path / "processed_wiki.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    return WikiService().load_wiki_data(str(tmp_path))


def test_optional_source_fields_survive_loading_without_changing_article(tmp_path):
    """Keep article bytes unchanged while preserving date, gaps and redirect provenance."""
    content = "Warning: do NOT share keys.\n```\n  keep = 'exact'\n\n```\n0.50 BTC"
    source = {
        "title": "SEPA",
        "content": content,
        "category": "bisq1",
        "source_revision": {"id": "44", "timestamp": "2023-07-01T12:00:00Z"},
        "source_gaps": [
            {"kind": "template", "template": "Missing", "invocation": "{{Missing}}"}
        ],
        "redirect_target": "Other article",
    }
    docs = load(
        tmp_path,
        [source, {"title": "Old seed", "content": "No date.", "category": "general"}],
    )
    assert docs[0].page_content == content
    for key in ("source_revision", "source_gaps", "redirect_target"):
        assert docs[0].metadata[key] == source[key]
    assert (
        docs[0].metadata["source_notices"][0]["id"]
        == "archived-bisq1-trade-limit-macros"
    )
    assert "source_revision" not in docs[1].metadata
    assert "date is unavailable" in wiki_context_notice(docs[1].metadata)
    assert "2026" not in wiki_context_notice(docs[1].metadata)
    notice = wiki_context_notice(docs[0].metadata)
    assert "2023-07-01T12:00:00Z" in notice
    assert "not all expanded templates" in notice
    assert "Unresolved source expansions: Missing" in notice
    assert "Original redirect target: Other article" in notice


def test_presentation_gaps_are_not_described_as_lost_warning_prose():
    """Distinguish missing presentation definitions from retained warning content."""
    notice = wiki_context_notice(
        {
            "type": "wiki",
            "title": "Unknown",
            "source_gaps": [
                {"kind": "presentation_wrapper_only", "template": "Admonition_Warn"}
            ],
        }
    )
    assert "argument prose was retained" in notice
    assert "Unresolved source expansions" not in notice


@pytest.mark.parametrize(
    "kind,title",
    [
        ("faq", "SEPA"),
        ("llm_wiki", "Bisq Easy"),
        ("wiki", "SEPA extra"),
        ("wiki", "sepa"),
    ],
)
def test_notices_are_exact_title_wiki_only(kind, title):
    """Prevent dated wiki annotations from leaking into FAQs or similarly named pages."""
    metadata = {"type": kind, "title": title}
    assert "source_notices" not in wiki_source_provenance(metadata)
    if kind != "wiki":
        assert wiki_context_notice(metadata) == ""
        assert (
            DocumentRetriever(Mock()).format_documents(
                [Document(page_content="Original FAQ body", metadata=metadata)]
            )
            == f"[General] [{kind.upper()}] {title}\nOriginal FAQ body\n"
        )


@pytest.mark.parametrize(
    "title,notice_id,phrase",
    [
        ("SEPA", "archived-bisq1-trade-limit-macros", "0.25 BTC"),
        (
            "Emergency Multisig payout tool",
            "local-signing-not-private-key-collection",
            "Sending a seed or private key",
        ),
        (
            "Backing up application data",
            "seed-is-not-application-backup",
            "copy is not encrypted",
        ),
        (
            "Restoring your wallet from seed",
            "seed-restore-preconditions",
            "requires a new password",
        ),
        (
            "Bisq Easy",
            "easy-payment-reference-conflict",
            "otherwise the buyer's own name",
        ),
        ("SWIFT", "bisq1-payment-reference", "not include the trade ID"),
        (
            "Reputation2",
            "easy-reputation-amount-eligibility",
            "1,200 reputation points",
        ),
        (
            "Wallet",
            "wallet-derivation-template-incomplete",
            "SegWit",
        ),
    ],
)
def test_reviewed_notice_cases_from_pinned_source_review(title, notice_id, phrase):
    """Tie each reviewed discrepancy to its dated, pinned public evidence."""
    metadata = {"type": "wiki", "title": title}
    notices = wiki_source_provenance(metadata)["source_notices"]
    notice = next(item for item in notices if item["id"] == notice_id)
    assert phrase in notice["body"]
    assert notice["checked_at"] == "2026-11-08"
    for source in notice["sources"]:
        assert "/blob/" in source["url"] and "#L" in source["url"]
        assert len(source["sha256"]) == 64
        assert "evidence_file" not in source  # No local/private acquisition paths.
    # Old indexes also receive the reviewed notice at context construction.
    assert notice_id in wiki_context_notice(metadata)


def test_chunk_rerank_context_and_staff_snapshot_preserve_source_attachment(
    tmp_path, monkeypatch
):
    """Carry the correct source annotations through chunking, reranking and staff evidence."""
    monkeypatch.setenv("BISQ_DISABLE_TRANSFORMERS", "1")
    entries = [
        {
            "title": "SEPA",
            "category": "bisq1",
            "content": "Historical limit: 0.50 BTC.\n\n"
            + "Retain this warning exactly. " * 25,
            "source_revision": {"id": "44", "timestamp": "2023-07-01T12:00:00Z"},
        },
        {
            "title": "Emergency Multisig payout tool",
            "category": "bisq1",
            "content": "Do not lose the original transaction details.",
            "source_revision": {"id": "55", "timestamp": "2021-01-01T12:00:00Z"},
        },
    ]
    originals = load(tmp_path, entries)
    chunks = DocumentProcessor(chunk_size=200, chunk_overlap=0).split_documents(
        originals
    )
    assert len(chunks) > 2
    for chunk in chunks:
        original = next(
            doc for doc in originals if doc.metadata["title"] == chunk.metadata["title"]
        )
        assert chunk.page_content in original.page_content
        assert chunk.metadata == original.metadata
    # Pick distinct chunks and run the real ColBERT adapter with a local fake model.
    selected = [chunks[0], chunks[-1]]
    backend_docs = [
        RetrievedDocument(
            content=doc.page_content,
            metadata=doc.metadata,
            id=str(i),
            score=0.9 - i * 0.1,
        )
        for i, doc in enumerate(selected)
    ]
    backend = Mock()
    backend.retrieve_with_scores.return_value = backend_docs
    backend.retrieve_semantic_with_scores.return_value = []
    reranker = ColBERTReranker(
        SimpleNamespace(
            COLBERT_MODEL="unused", COLBERT_TOP_N=2, ENABLE_COLBERT_RERANK=True
        )
    )
    reranker._model = Mock()
    reranker._model.rerank.return_value = [
        {"content": doc.page_content, "score": 0.8} for doc in reversed(selected)
    ]
    retriever = DocumentRetriever(backend, reranker=reranker)
    documents, _ = retriever.retrieve_with_scores("Bisq 1 wallet", "Bisq 1")
    assert [doc.metadata["title"] for doc in documents] == [
        "Emergency Multisig payout tool",
        "SEPA",
    ]
    for doc in documents:
        assert doc.page_content == next(
            item.page_content
            for item in selected
            if item.metadata["title"] == doc.metadata["title"]
        )
    context = retriever.format_documents(documents)
    first, second = context.split("[Multisig v1] [WIKI] SEPA", 1)
    assert "local-signing-not-private-key-collection" in first
    assert "archived-bisq1-trade-limit-macros" not in first
    assert "archived-bisq1-trade-limit-macros" in second
    assert "local-signing-not-private-key-collection" not in second
    assert second.index("0.25 BTC") < second.index("Historical limit: 0.50 BTC")
    bundle = asyncio.run(
        StaffEvidenceResolver().resolve(question="Bisq 1 wallet", documents=documents)
    )
    assert len(bundle.evidence) == 2
    # The actual runtime persists this model_dump as evidence_snapshot and sends
    # the same request model to the staff model; raw evidence content stays raw.
    request = PublicContextRequest(
        question="Bisq 1 wallet",
        recent_messages=[],
        evidence=bundle.evidence,
        audience="staff_only",
    )
    snapshot = request.model_dump()["evidence"]
    for evidence, document in zip(snapshot, documents, strict=True):
        assert evidence["content"] == document.page_content
        provenance = evidence["provenance"]
        assert provenance["source_revision"] == document.metadata["source_revision"]
        assert provenance["source_notices"] == document.metadata["source_notices"]
        assert provenance["source_context"] == wiki_context_notice(document.metadata)
        assert "2026-11-08" in provenance["source_context"]


def test_identical_rerank_chunks_keep_sources_and_rank_other_candidates():
    """Equal chunks share relevance without hiding a more relevant candidate."""
    docs = [
        RetrievedDocument(
            content="Identical quoted text.",
            metadata={"type": "wiki", "title": title},
            id=str(i),
            score=0.8 - i * 0.1,
        )
        for i, title in enumerate(["SEPA", "Emergency Multisig payout tool"])
    ]
    docs.append(
        RetrievedDocument("Relevant separate text.", {"title": "Wallet"}, 0.2, "2")
    )
    reranker = _test_reranker()
    reranker._model.rerank.return_value = [
        {"content": docs[2].content, "score": 0.99},
        {"content": docs[0].content, "score": 0.95},
    ]
    result = reranker.rerank("wallet", docs, top_n=3)
    assert [item.id for item in result] == ["2", "0", "1"]
    assert [item.score for item in result] == [0.99, 0.95, 0.95]
    assert [item.metadata["title"] for item in result] == [
        "Wallet",
        "SEPA",
        "Emergency Multisig payout tool",
    ]
    assert all(item.metadata["_reranked"] for item in result)
    assert all("_reranked" not in item.metadata for item in docs)
    reranker._model.rerank.assert_called_once_with(
        query="wallet", documents=[docs[0].content, docs[2].content], k=2
    )
    assert [item.id for item in reranker.rerank("wallet", docs, top_n=2)] == ["2", "0"]


def _test_reranker():
    """Use the real adapter with a local model double and no provider calls."""
    reranker = ColBERTReranker(
        SimpleNamespace(
            COLBERT_MODEL="unused", COLBERT_TOP_N=3, ENABLE_COLBERT_RERANK=True
        )
    )
    reranker._model = Mock()
    return reranker


def test_unmatched_rerank_result_cannot_become_undated_wiki_evidence():
    """An orphan model result falls back to explicitly unreranked source evidence."""
    docs = [
        RetrievedDocument(
            "Historical limit: 0.50 BTC.",
            {"type": "wiki", "title": "SEPA"},
            0.7,
            "original",
        )
    ]
    reranker = _test_reranker()
    reranker._model.rerank.return_value = [
        {"content": "Changed unknown text", "score": 0.99}
    ]
    result = reranker.rerank("limit", docs)
    assert len(result) == 1
    assert result[0].id == "original"
    assert result[0].content == docs[0].content
    assert result[0].score == 0.7
    assert result[0].metadata == {**docs[0].metadata, "_reranked": False}


def test_duplicate_fallback_retains_scores_through_retriever_and_threshold():
    """A failed model preserves per-source retrieval confidence and score meaning."""
    docs = [
        RetrievedDocument("Same text.", {"type": "wiki", "title": title}, score, str(i))
        for i, (title, score) in enumerate(
            [("SEPA", 0.9), ("Emergency Multisig payout tool", 0.3)]
        )
    ]
    backend = Mock()
    backend.retrieve_with_scores.return_value = docs
    backend.retrieve_semantic_with_scores.return_value = []
    reranker = _test_reranker()
    reranker._model.rerank.side_effect = RuntimeError("offline model failure")
    documents, scores = DocumentRetriever(
        backend, reranker=reranker
    ).retrieve_with_scores("wallet")
    assert scores == [0.9, 0.3]
    assert [doc.metadata["title"] for doc in documents] == [
        doc.metadata["title"] for doc in docs
    ]
    for doc, score in zip(documents, scores, strict=True):
        assert doc.metadata["_score_type"] == "relative_rank"
        assert doc.metadata["_retrieval_score"] == score
        assert doc.metadata["_reranked"] is False
        assert "_colbert_score" not in doc.metadata
    kept = reranker.rerank_with_threshold("wallet", docs, score_threshold=0.5)
    assert [(doc.id, doc.score) for doc in kept] == [("0", 0.9)]
    assert kept[0].metadata["_reranked"] is False


def test_context_shares_notices_only_within_same_article():
    """Notice bodies appear once per article while each chunk retains provenance."""
    docs = [
        Document(
            page_content="First chunk",
            metadata={
                "type": "wiki",
                "title": "SEPA",
                "source_revision": {"id": "1", "timestamp": "2020-01-01"},
            },
        ),
        Document(
            page_content="Second chunk",
            metadata={
                "type": "wiki",
                "title": "SEPA",
                "source_revision": {"id": "2", "timestamp": "2021-01-01"},
                "source_gaps": [{"kind": "template", "template": "Missing"}],
            },
        ),
        Document(
            page_content="Other article", metadata={"type": "wiki", "title": "Zelle"}
        ),
    ]
    retriever = DocumentRetriever(Mock())
    context = retriever.format_documents(docs)
    body = wiki_source_provenance(docs[0].metadata)["source_notices"][0]["body"]
    assert context.count(body) == 2  # Once for SEPA, separately for Zelle.
    assert (
        context.count(
            "applies to this chunk; see the full check above for this article."
        )
        == 1
    )
    assert "2020-01-01 (revision 1)" in context
    assert "2021-01-01 (revision 2)" in context
    assert "Unresolved source expansions: Missing" in context
    assert all(doc.page_content in context for doc in docs)
    assert retriever.format_documents(docs) == context  # No cross-query suppression.
    assert body in wiki_context_notice(
        docs[1].metadata
    )  # Standalone evidence stays complete.


def test_context_retains_distinct_checks_for_one_article(monkeypatch):
    """Deduplication must preserve separate notices rather than merge by article alone."""
    from app.services import wiki_provenance

    notices = [
        {
            "id": key,
            "checked_at": "2026-11-08",
            "body": body,
            "sources": [{"url": "https://example.invalid/" + key}],
        }
        for key, body in [
            ("one", "First distinct check"),
            ("two", "Second distinct check"),
        ]
    ]
    monkeypatch.setattr(
        wiki_provenance, "_reviewed_notices", lambda: {"Article": notices}
    )
    docs = [
        Document(
            page_content=f"Chunk {i}", metadata={"type": "wiki", "title": "Article"}
        )
        for i in range(2)
    ]
    context = DocumentRetriever(Mock()).format_documents(docs)
    for notice in notices:
        assert context.count(notice["body"]) == 1
        assert f"[{notice['id']}] applies to this chunk" in context
