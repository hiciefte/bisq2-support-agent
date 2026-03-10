"""Tests for answer style normalization."""

from app.services.simplified_rag_service import (
    apply_group_channel_answer_style,
    apply_support_answer_style,
)


def test_group_channel_style_strips_markdown_headings() -> None:
    text = "### Quick answer\nUse the Trade tab."
    normalized = apply_group_channel_answer_style(text, detection_source="matrix")
    assert "###" not in normalized
    assert normalized.startswith("Quick answer")


def test_group_channel_style_truncates_long_answers() -> None:
    text = "A" * 900
    normalized = apply_group_channel_answer_style(text, detection_source="bisq2")
    assert len(normalized) <= 500
    assert normalized.endswith("...")


def test_web_channel_style_strips_headings_without_truncation() -> None:
    text = "### Detailed answer\n\n" + ("B" * 700)
    normalized = apply_group_channel_answer_style(text, detection_source="web")
    assert "###" not in normalized
    assert normalized.startswith("Detailed answer")
    assert len(normalized) == len(text) - 4


def test_support_answer_style_compresses_simple_fact_answers() -> None:
    text = (
        "Bisq Easy is the simpler Bisq 2 trading mode for buying BTC with fiat. "
        "It uses reputation instead of the Bisq 1 security deposit model. "
        "It is designed to make onboarding easier for new users."
    )
    normalized = apply_support_answer_style(
        text,
        question_text="What is Bisq Easy?",
        detection_source="web",
    )
    assert normalized.count(".") <= 2
    assert "onboarding easier" not in normalized


def test_support_answer_style_keeps_step_answers_for_how_questions() -> None:
    text = "1. Open the Trade tab.\n2. Select Bisq Easy.\n3. Choose an offer."
    normalized = apply_support_answer_style(
        text,
        question_text="How do I start trading?",
        detection_source="web",
    )
    assert normalized == text


def test_support_answer_style_does_not_compress_yes_no_questions() -> None:
    text = (
        "Bisq Easy is designed for buying and selling Bitcoin with fiat. "
        "It focuses on BTC trades and uses reputation instead of security deposits. "
        "Use Bisq 1 for broader market types."
    )
    normalized = apply_support_answer_style(
        text,
        question_text="Is Bisq Easy BTC-only?",
        detection_source="web",
    )
    assert normalized == text
