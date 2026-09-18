"""Regression coverage for wiki protocol labels used by retrieval filters."""

import json
from pathlib import Path

import pytest
from app.scripts.process_wiki_dump import WikiDumpProcessor
from app.services.wiki_service import WikiService


@pytest.fixture
def funding_article():
    corpus = Path(__file__).resolve().parents[2] / "data/wiki/processed_wiki.jsonl"
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
