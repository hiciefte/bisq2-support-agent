"""Regression coverage for wiki protocol labels used by retrieval filters."""

import json
from pathlib import Path

import pytest
from app.scripts.process_wiki_dump import WikiDumpProcessor
from app.services.wiki_service import WikiService


@pytest.fixture
def funding_article():
    corpus = (
        Path(__file__).resolve().parents[2]
        / "app/resources/wiki/processed_wiki.seed.jsonl"
    )
    return next(
        entry
        for entry in map(json.loads, corpus.read_text().splitlines())
        if entry["title"] == "Funding your wallet"
    )


def test_dump_classification_keeps_legacy_wallet_requirements_out_of_bisq_easy(
    funding_article,
):
    processor = WikiDumpProcessor("unused.xml", "unused.jsonl")
    assert "Bisq Easy" in funding_article["content"]
    assert "multisignature" in funding_article["content"]
    assert (
        processor.categorize_content(
            funding_article["title"], funding_article["content"]
        )
        == "bisq1"
    )


def test_comparison_page_is_not_reclassified_by_legacy_mentions():
    processor = WikiDumpProcessor("unused.xml", "unused.jsonl")
    assert (
        processor.categorize_content(
            "Bisq 2", "Bisq Easy differs from the legacy 2-of-2 multisig protocol."
        )
        == "bisq2"
    )


@pytest.mark.parametrize("prior_category", ["bisq1", "bisq2"])
def test_mixed_introduction_loads_for_all_protocols_without_changing_text(
    tmp_path, prior_category
):
    """Correct old exclusive metadata without changing historical source text."""
    body = "Classic Bisq 1 arbitration and Bisq Easy use different protocols."
    entry = {"title": "Introduction", "content": body, "category": prior_category}
    (tmp_path / "processed_wiki.jsonl").write_text(json.dumps(entry) + "\n")
    (document,) = WikiService().load_wiki_data(str(tmp_path))
    assert document.metadata["category"] == "general"
    assert document.metadata["protocol"] == "all"
    assert document.page_content == body


@pytest.mark.parametrize("title", ["Funding your wallet", "Funding_your_wallet"])
def test_existing_mislabeled_wiki_loads_with_correct_retrieval_metadata(
    tmp_path, funding_article, title
):
    funding_article.update(title=title, category="bisq2")
    easy_article = {
        "title": "Bisq Easy",
        "content": "Buy bitcoin without security deposits.",
        "category": "bisq2",
    }
    (tmp_path / "processed_wiki.jsonl").write_text(
        "\n".join(map(json.dumps, [funding_article, easy_article]))
    )

    funding, easy = WikiService().load_wiki_data(str(tmp_path))

    assert funding.metadata["category"] == "bisq1"
    assert funding.metadata["protocol"] == "multisig_v1"
    assert funding.page_content == funding_article["content"]
    assert easy.metadata["protocol"] == "bisq_easy"
    # Protocol-priority searches must not treat the legacy deposit article as
    # Bisq Easy evidence. The article remains available to legacy searches.
    assert [
        doc.metadata["title"]
        for doc in [funding, easy]
        if doc.metadata["protocol"] == "bisq_easy"
    ] == ["Bisq Easy"]


def test_classic_v1_introduction_chunk_keeps_reviewed_general_context(tmp_path):
    """Preserve the audited mixed-page label despite its incidental Bisq 2 step."""
    from unittest.mock import Mock

    from app.services.rag.document_retriever import DocumentRetriever
    from langchain_core.documents import Document

    corpus = (
        Path(__file__).resolve().parents[2]
        / "app/resources/wiki/processed_wiki.seed.jsonl"
    )
    article = next(
        entry
        for entry in map(json.loads, corpus.read_text().splitlines())
        if entry["title"] == "Introduction"
    )
    body = article["content"]
    chunk = body[
        body.index("## = In a nutshell") : body.index(
            "## = How trading with Bisq is different"
        )
    ]
    assert "classic v1 trading protocol" in chunk
    assert "Bisq 2 desktop application" in chunk
    assert "locking BTC from both parties into escrow" in chunk
    (tmp_path / "processed_wiki.jsonl").write_text(json.dumps(article) + "\n")
    (loaded,) = WikiService().load_wiki_data(str(tmp_path))
    document = Document(page_content=chunk, metadata=dict(loaded.metadata))
    original_metadata = dict(document.metadata)

    context = DocumentRetriever(Mock()).format_documents([document])

    assert context.startswith("[General] [WIKI] Introduction\n")
    assert not context.startswith("[Bisq Easy]")
    assert chunk in context
    assert document.page_content == chunk
    assert document.metadata == original_metadata


@pytest.mark.parametrize(
    "source_type,title,protocol,content,label",
    [
        ("wiki", "Introduction", "all", "Bisq Easy uses another protocol.", "General"),
        ("wiki", "Other article", "all", "Bisq 2 instructions.", "Bisq Easy"),
        (
            "wiki",
            "Other article",
            "all",
            "Bisq 1 multisig instructions.",
            "Multisig v1",
        ),
        ("wiki", "Other article", "all", "Common documentation.", "General"),
        (
            "wiki",
            "Other article",
            "multisig_v1",
            "Compare with Bisq Easy.",
            "Multisig v1",
        ),
        ("wiki", "Other article", "bisq_easy", "Compare with Bisq 1.", "Bisq Easy"),
        ("wiki", "Other article", "musig", "Compare with Bisq 2.", "MuSig"),
        ("faq", "Introduction", "all", "Bisq 2 instructions.", "Bisq Easy"),
    ],
)
def test_reviewed_general_guard_preserves_other_protocol_labeling(
    source_type, title, protocol, content, label
):
    """Scope the exception to reviewed general wiki pages, preserving other rules."""
    from unittest.mock import Mock

    from app.services.rag.document_retriever import DocumentRetriever
    from langchain_core.documents import Document

    document = Document(
        page_content=content,
        metadata={"type": source_type, "title": title, "protocol": protocol},
    )
    context = DocumentRetriever(Mock()).format_documents([document])
    assert context.startswith(f"[{label}] [{source_type.upper()}] {title}\n")
