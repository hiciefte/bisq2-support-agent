"""Tests for the curated issue-to-canonical-fix registry."""

import pytest
from app.services.rag.canonical_fixes import (
    CANONICAL_FIXES,
    canonical_url_for_metadata,
    find_canonical_fix,
    validate_canonical_fixes,
)
from app.utils.wiki_url_generator import WikiUrlGenerator


@pytest.mark.parametrize(
    ("question", "expected_key"),
    [
        (
            "I clicked Payment started but it keeps saying please send confirmation again",
            "payment-started-confirmation-loop",
        ),
        ("My SPV resync is stuck at 0% after restart", "incomplete-spv-resync"),
        (
            "How do I move my Bisq data directory to a new computer?",
            "move-bisq1-data-directory",
        ),
        ("How does account signing change my buying limit?", "bisq1-account-signing"),
        ("What is account signing?", "bisq1-account-signing"),
        ("How do I open mediation for this trade?", "bisq1-open-mediation"),
    ],
)
def test_find_canonical_fix_matches_only_verified_signatures(
    question: str, expected_key: str
) -> None:
    fix = find_canonical_fix(question, detected_version="Bisq 1")

    assert fix is not None
    assert fix.key == expected_key


def test_find_canonical_fix_ignores_unrelated_question() -> None:
    assert (
        find_canonical_fix(
            "How do I create a Bisq Easy offer?", detected_version="Bisq 1"
        )
        is None
    )


def test_registry_requires_confirmed_protocol() -> None:
    assert find_canonical_fix("How do I open mediation for this trade?") is None
    assert find_canonical_fix("How do I move my data directory?") is None


def test_find_canonical_fix_respects_explicit_bisq2_protocol() -> None:
    assert (
        find_canonical_fix(
            "How do I open mediation in Bisq 2?", detected_version="Bisq 2"
        )
        is None
    )


def test_registry_uses_allowlisted_exact_urls_and_one_line_remedies() -> None:
    validate_canonical_fixes()

    assert CANONICAL_FIXES["payment-started-confirmation-loop"].url.endswith(
        ".22Please_send_confirmation_again.22"
    )
    assert CANONICAL_FIXES["move-bisq1-data-directory"].url.endswith(
        "#Restore_an_entire_data_directory"
    )
    for fix in CANONICAL_FIXES.values():
        assert WikiUrlGenerator.is_valid_wiki_url(fix.url)
        assert "\n" not in fix.remedy


def test_canonical_fix_document_preserves_exact_link_and_protocol() -> None:
    fix = CANONICAL_FIXES["incomplete-spv-resync"]

    document = fix.to_document()

    assert fix.remedy in document.page_content
    assert f"Canonical link: {fix.url}" in document.page_content
    assert document.metadata["url"] == fix.url
    assert document.metadata["protocol"] == "multisig_v1"


def test_canonical_url_requires_exact_registry_id_and_url() -> None:
    fix = CANONICAL_FIXES["incomplete-spv-resync"]

    assert (
        canonical_url_for_metadata({"canonical_fix_id": fix.key, "url": fix.url})
        == fix.url
    )
    assert (
        canonical_url_for_metadata(
            {"canonical_fix_id": fix.key, "url": "http://bisq.wiki/unsafe"}
        )
        is None
    )
    assert canonical_url_for_metadata({"url": fix.url}) is None
