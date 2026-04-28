"""Tests for pre-extraction filters applied before LLM processing.

TDD: these tests define the contract for message-length and answer-
specificity filters that gate the extraction pipeline.
"""

from __future__ import annotations

from app.services.training.validation import (
    check_answer_specificity,
    filter_short_messages,
)


class TestFilterShortMessages:
    """1E: Skip user messages under MIN_TOKENS before LLM extraction."""

    def test_keeps_messages_above_threshold(self) -> None:
        messages = [
            {
                "id": "1",
                "author": "user1",
                "text": "How do I increase my trading limit in Bisq Easy?",
            },
            {
                "id": "2",
                "author": "staff1",
                "text": "Build reputation by completing trades.",
            },
        ]
        result = filter_short_messages(messages, min_tokens=5)
        assert len(result) == 2

    def test_removes_short_user_messages_but_keeps_staff(self) -> None:
        messages = [
            {"id": "1", "author": "user1", "text": "ok thanks"},
            {"id": "2", "author": "staff1", "text": "You're welcome!"},
            {
                "id": "3",
                "author": "user2",
                "text": "What is the maximum trade amount in Bisq?",
            },
        ]
        result = filter_short_messages(messages, min_tokens=5, staff_authors={"staff1"})
        ids = [m["id"] for m in result]
        assert "1" not in ids
        assert "2" in ids
        assert "3" in ids

    def test_keeps_all_staff_messages_regardless_of_length(self) -> None:
        messages = [
            {
                "id": "1",
                "author": "user1",
                "text": "How do I increase my trading limit?",
            },
            {"id": "2", "author": "staff1", "text": "Sure."},
        ]
        result = filter_short_messages(messages, min_tokens=5, staff_authors={"staff1"})
        assert len(result) == 2

    def test_empty_input(self) -> None:
        assert filter_short_messages([], min_tokens=5) == []

    def test_default_threshold_filters_greetings(self) -> None:
        messages = [
            {"id": "1", "author": "u", "text": "yes"},
            {"id": "2", "author": "u", "text": "ok thanks"},
            {"id": "3", "author": "u", "text": "How do I set up a Bisq account?"},
        ]
        result = filter_short_messages(messages)
        assert len(result) == 1
        assert result[0]["id"] == "3"


class TestCheckAnswerSpecificity:
    """3A: Reject answers that are only generic advice."""

    BISQ_TERMS = {
        "bisq",
        "spv",
        "mediation",
        "ctrl+o",
        "seed",
        "wallet",
        "trade",
        "offer",
        "security deposit",
    }

    def test_rejects_generic_answer(self) -> None:
        result = check_answer_specificity(
            "Try restarting the application and check your internet connection.",
            domain_terms=self.BISQ_TERMS,
        )
        assert result.is_generic is True

    def test_accepts_domain_specific_answer(self) -> None:
        result = check_answer_specificity(
            "Navigate to Settings > Network Info and click RESYNC SPV WALLET. This will re-download the blockchain headers.",
            domain_terms=self.BISQ_TERMS,
        )
        assert result.is_generic is False

    def test_rejects_very_short_answer(self) -> None:
        result = check_answer_specificity(
            "Check the docs.",
            domain_terms=self.BISQ_TERMS,
        )
        assert result.is_generic is True

    def test_accepts_short_but_specific_answer(self) -> None:
        result = check_answer_specificity(
            "Run: xattr -rd com.apple.quarantine /Applications/Bisq.app",
            domain_terms=self.BISQ_TERMS,
        )
        assert result.is_generic is False

    def test_empty_answer(self) -> None:
        result = check_answer_specificity("", domain_terms=self.BISQ_TERMS)
        assert result.is_generic is True
