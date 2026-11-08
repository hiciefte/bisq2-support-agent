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
    (tmp_path / "processed_wiki.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )
    return WikiService().load_wiki_data(str(tmp_path))


def test_optional_source_fields_survive_loading_without_changing_article(tmp_path):
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


def test_identical_rerank_chunks_cannot_inherit_another_articles_notices():
    docs = [
        RetrievedDocument(
            content="Identical quoted text.",
            metadata={"type": "wiki", "title": title},
            id=str(i),
        )
        for i, title in enumerate(["SEPA", "Emergency Multisig payout tool"])
    ]
    reranker = ColBERTReranker(
        SimpleNamespace(
            COLBERT_MODEL="unused", COLBERT_TOP_N=2, ENABLE_COLBERT_RERANK=True
        )
    )
    reranker._model = Mock()
    result = reranker.rerank("wallet", docs)
    assert result == docs
    assert [item.id for item in result] == ["0", "1"]
    reranker._model.rerank.assert_not_called()


def test_unmatched_rerank_result_cannot_become_undated_wiki_evidence():
    docs = [
        RetrievedDocument(
            content="Historical limit: 0.50 BTC.",
            metadata={"type": "wiki", "title": "SEPA"},
            id="original",
        )
    ]
    reranker = ColBERTReranker(
        SimpleNamespace(
            COLBERT_MODEL="unused", COLBERT_TOP_N=2, ENABLE_COLBERT_RERANK=True
        )
    )
    reranker._model = Mock()
    reranker._model.rerank.return_value = [
        {"content": "Changed unknown text", "score": 0.99}
    ]
    assert reranker.rerank("limit", docs) == docs
