"""Tests for shared channel question prefilter."""

from app.channels.question_prefilter import QuestionPrefilter


def test_prefilter_filters_greeting_noise() -> None:
    prefilter = QuestionPrefilter()

    decision = prefilter.evaluate_text("Hello")

    assert decision.should_process is False
    assert decision.reason == "greeting"


def test_prefilter_filters_acknowledgment_noise() -> None:
    prefilter = QuestionPrefilter()

    decision = prefilter.evaluate_text("thanks")

    assert decision.should_process is False
    assert decision.reason == "acknowledgment"


def test_prefilter_keeps_short_follow_up_by_default() -> None:
    prefilter = QuestionPrefilter()

    decision = prefilter.evaluate_text("USD")

    assert decision.should_process is True
    assert decision.reason == ""


def test_prefilter_keeps_regular_question() -> None:
    prefilter = QuestionPrefilter()

    decision = prefilter.evaluate_text("How do I back up my wallet?")

    assert decision.should_process is True
    assert decision.reason == ""
