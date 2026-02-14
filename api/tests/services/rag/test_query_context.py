"""Tests for query_context shared utilities."""

import pytest
from app.services.rag.query_context import (
    extract_last_topic,
    extract_topic_keywords,
    is_anaphoric,
)


class TestIsAnaphoric:
    @pytest.mark.parametrize(
        "query",
        [
            "How do I do that?",
            "Can you explain this?",
            "What about those fees?",
            "Tell me more about it",
            "Is that the same as before?",
            "Like that but different",
        ],
    )
    def test_anaphoric_queries_detected(self, query):
        assert is_anaphoric(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "How do I create a Bisq Easy trade offer?",
            "What is the security deposit in Bisq 1?",
            "Explain the reputation system",
            "How does multisig escrow work?",
        ],
    )
    def test_self_contained_queries_not_anaphoric(self, query):
        assert is_anaphoric(query) is False

    def test_empty_query(self):
        assert is_anaphoric("") is False

    def test_deictic_reference(self):
        assert is_anaphoric("what you said about fees") is True


class TestExtractLastTopic:
    def test_extracts_last_user_message(self):
        history = [
            {"role": "user", "content": "I want to trade on Bisq Easy"},
            {"role": "assistant", "content": "Sure, here's how..."},
        ]
        result = extract_last_topic(history)
        assert result == "I want to trade on Bisq Easy"

    def test_skips_assistant_messages(self):
        history = [
            {"role": "user", "content": "Tell me about Bisq 1"},
            {"role": "assistant", "content": "Bisq 1 uses multisig..."},
            {"role": "assistant", "content": "Anything else?"},
        ]
        result = extract_last_topic(history)
        assert result == "Tell me about Bisq 1"

    def test_empty_history(self):
        assert extract_last_topic([]) is None

    def test_no_user_messages(self):
        history = [{"role": "assistant", "content": "Hello!"}]
        assert extract_last_topic(history) is None

    def test_skips_short_messages(self):
        history = [
            {"role": "user", "content": "How do I set up the Bisq 1 data directory?"},
            {"role": "assistant", "content": "Here's how..."},
            {"role": "user", "content": "ok"},
        ]
        result = extract_last_topic(history)
        assert result == "How do I set up the Bisq 1 data directory?"

    def test_truncation_at_sentence_boundary(self):
        long_msg = "First sentence about trading. Second sentence about fees. Third sentence about security deposits that goes on and on."
        history = [{"role": "user", "content": long_msg}]
        result = extract_last_topic(history, max_chars=60)
        assert result.endswith(".")
        assert len(result) <= 60

    def test_truncation_hard_limit(self):
        no_periods = "A" * 200
        history = [{"role": "user", "content": no_periods}]
        result = extract_last_topic(history, max_chars=100)
        assert len(result) == 100

    def test_skips_acknowledgments(self):
        history = [
            {"role": "user", "content": "How do I create a trade offer?"},
            {"role": "assistant", "content": "Go to the Trade tab..."},
            {"role": "user", "content": "ok thanks"},
        ]
        result = extract_last_topic(history)
        assert result == "How do I create a trade offer?"

    @pytest.mark.parametrize(
        "ack",
        ["ok", "OK", "yes", "sure", "thanks", "thank you", "got it", "yep", "k"],
    )
    def test_skips_various_acknowledgments(self, ack):
        history = [
            {"role": "user", "content": "Tell me about Bisq Easy trading"},
            {"role": "assistant", "content": "Bisq Easy is..."},
            {"role": "user", "content": ack},
        ]
        result = extract_last_topic(history)
        assert result == "Tell me about Bisq Easy trading"

    def test_prefers_substantive_over_ack_in_multi_turn(self):
        history = [
            {"role": "user", "content": "I want to set up multisig on Bisq 1"},
            {"role": "assistant", "content": "First, you need to..."},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "Then configure..."},
            {"role": "user", "content": "got it"},
        ]
        result = extract_last_topic(history)
        assert result == "I want to set up multisig on Bisq 1"


class TestExtractTopicKeywords:
    def test_extracts_domain_terms(self):
        result = extract_topic_keywords("I want to trade on Bisq Easy")
        assert "trade" in result
        assert "bisq" in result
        assert "easy" in result

    def test_removes_stop_words(self):
        result = extract_topic_keywords("I want to create a new trade offer")
        assert "want" not in result
        assert "the" not in result

    def test_max_keywords(self):
        result = extract_topic_keywords(
            "trading security deposit multisig escrow arbitration mediation",
            max_keywords=3,
        )
        words = result.split()
        assert len(words) <= 3

    def test_empty_input(self):
        result = extract_topic_keywords("")
        assert result == ""

    def test_deduplicates(self):
        result = extract_topic_keywords("bisq bisq easy bisq trade")
        assert result.count("bisq") == 1
