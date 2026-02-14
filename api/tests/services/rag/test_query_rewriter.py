"""Tests for QueryRewriter — gate, heuristic, LLM, cache.

TDD: These tests define the contract. QueryRewriter implementation
in Stage 5 must make all these tests pass.
"""

import time
from unittest.mock import MagicMock

import pytest
from app.services.rag.query_rewriter import QueryRewriter

# ── Gate tests ──────────────────────────────────────────────────


class TestNeedsRewrite:
    """Test the _needs_rewrite gate logic."""

    @pytest.mark.asyncio
    async def test_no_history_no_rewrite(self, rewriter_settings, mock_ai_client):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite("How do I trade?", chat_history=[])
        assert result.rewritten is False
        assert result.strategy == "none"

    @pytest.mark.asyncio
    async def test_self_contained_query_no_rewrite(
        self, rewriter_settings, mock_ai_client, sample_chat_history_dicts
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        query = (
            "How do I create a new Bisq Easy trade offer with reputation requirements?"
        )
        result = await rewriter.rewrite(query, chat_history=sample_chat_history_dicts)
        assert result.rewritten is False
        assert result.strategy == "none"

    @pytest.mark.asyncio
    async def test_pronoun_with_history_needs_rewrite(
        self, rewriter_settings, mock_ai_client, sample_chat_history_dicts
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite(
            "How do I do that?", chat_history=sample_chat_history_dicts
        )
        assert result.rewritten is True

    @pytest.mark.asyncio
    async def test_short_query_with_history_needs_rewrite(
        self, rewriter_settings, mock_ai_client, sample_chat_history_dicts
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite(
            "And fees?", chat_history=sample_chat_history_dicts
        )
        assert result.rewritten is True

    @pytest.mark.asyncio
    async def test_empty_query_no_rewrite(
        self, rewriter_settings, mock_ai_client, sample_chat_history_dicts
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite("", chat_history=sample_chat_history_dicts)
        assert result.rewritten is False
        assert result.strategy == "none"


# ── Heuristic track tests ──────────────────────────────────────


class TestHeuristicRewrite:
    """Test Track 1: heuristic pronoun resolution + entity substitution."""

    @pytest.mark.asyncio
    async def test_pronoun_resolution_includes_topic(
        self, rewriter_settings, mock_ai_client
    ):
        history = [
            {"role": "user", "content": "I want to trade on Bisq Easy"},
            {"role": "assistant", "content": "Sure, here's how..."},
        ]
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite("How do I do that?", chat_history=history)
        assert result.rewritten is True
        assert result.strategy == "heuristic"
        # Context-first format: "Regarding {topic}: {query}"
        assert "Regarding" in result.rewritten_query
        assert "How do I do that?" in result.rewritten_query
        assert "bisq" in result.rewritten_query.lower()
        assert "easy" in result.rewritten_query.lower()

    @pytest.mark.asyncio
    async def test_entity_substitution_old_bisq(
        self, rewriter_settings, mock_ai_client
    ):
        history = [
            {"role": "user", "content": "I'm using the old bisq"},
            {"role": "assistant", "content": "Bisq 1 requires..."},
        ]
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite("How do I fix it?", chat_history=history)
        assert result.rewritten is True
        # The heuristic should have resolved "old bisq" → "Bisq 1"
        assert (
            "Bisq 1" in result.rewritten_query
            or "old bisq" in result.rewritten_query.lower()
        )

    @pytest.mark.asyncio
    async def test_heuristic_result_fields(self, rewriter_settings, mock_ai_client):
        history = [
            {"role": "user", "content": "Tell me about SPV resync"},
            {"role": "assistant", "content": "SPV resync is..."},
        ]
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        result = await rewriter.rewrite("How do I do that?", chat_history=history)
        assert result.strategy == "heuristic"
        assert result.confidence > 0
        assert result.original_query == "How do I do that?"
        assert result.latency_ms >= 0


# ── LLM track tests ────────────────────────────────────────────


class TestLLMRewrite:
    """Test Track 2: LLM-based rewrite with mocked AISuite."""

    @pytest.mark.asyncio
    async def test_successful_llm_rewrite(self, rewriter_settings, mock_ai_client):
        # Non-anaphoric but short, so gate passes, heuristic defers → LLM
        history = [
            {"role": "user", "content": "I set up a trade on Bisq Easy yesterday"},
            {"role": "assistant", "content": "Great, the trade should..."},
        ]
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        # Ensure heuristic won't handle this (non-anaphoric, >=5 words)
        result = await rewriter.rewrite(
            "What about the security deposit stuff?",
            chat_history=history,
        )
        # Should have attempted LLM (mocked to return rewritten)
        assert result.rewritten is True
        assert result.strategy in ("llm", "heuristic")

    @pytest.mark.asyncio
    async def test_llm_timeout_falls_back(self, rewriter_settings):
        slow_client = MagicMock()
        slow_client.chat.completions.create.side_effect = lambda **_kwargs: (
            time.sleep(10)
        )
        rewriter_settings.QUERY_REWRITE_TIMEOUT_SECONDS = 0.1
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=slow_client)
        history = [
            {"role": "user", "content": "I'm trading on Bisq Easy"},
            {"role": "assistant", "content": "OK..."},
        ]
        result = await rewriter.rewrite(
            "What about the security deposit stuff?",
            chat_history=history,
        )
        # On timeout, should fall back gracefully
        assert result.strategy in (
            "timeout_fallback",
            "error_fallback",
            "parse_error_fallback",
            "heuristic",
        )

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back(self, rewriter_settings):
        bad_client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message = MagicMock()
        response.choices[0].message.content = "not valid json at all"
        bad_client.chat.completions.create.return_value = response
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=bad_client)
        history = [
            {"role": "user", "content": "Trading on Bisq Easy"},
            {"role": "assistant", "content": "OK..."},
        ]
        result = await rewriter.rewrite(
            "What about the deposit stuff?",
            chat_history=history,
        )
        # Should fall back, not crash
        assert result.strategy in (
            "timeout_fallback",
            "error_fallback",
            "parse_error_fallback",
            "heuristic",
        )
        assert result.original_query == "What about the deposit stuff?"

    @pytest.mark.asyncio
    async def test_system_prompt_contains_entity_examples(
        self, rewriter_settings, mock_ai_client
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        prompt = rewriter._build_system_prompt()
        assert "\u2192" in prompt
        assert "Bisq" in prompt


# ── Cache tests ─────────────────────────────────────────────────


class TestRewriteCache:
    @pytest.mark.asyncio
    async def test_cache_hit_same_query_and_history(
        self, rewriter_settings, mock_ai_client
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        history = [
            {"role": "user", "content": "I want to trade on Bisq Easy"},
            {"role": "assistant", "content": "Sure..."},
        ]
        result1 = await rewriter.rewrite("How do I do that?", chat_history=history)
        result2 = await rewriter.rewrite("How do I do that?", chat_history=history)
        assert result1.rewritten_query == result2.rewritten_query

    @pytest.mark.asyncio
    async def test_cache_miss_different_history(
        self, rewriter_settings, mock_ai_client
    ):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        history1 = [{"role": "user", "content": "Bisq Easy trading"}]
        history2 = [{"role": "user", "content": "Bisq 1 multisig"}]
        await rewriter.rewrite("How do I do that?", chat_history=history1)
        await rewriter.rewrite("How do I do that?", chat_history=history2)
        # Different history → different cache key → different result possible
        # (at minimum, the function was called twice without crashing)
        assert len(rewriter._cache) == 2

    @pytest.mark.asyncio
    async def test_cache_eviction(self, rewriter_settings, mock_ai_client):
        rewriter = QueryRewriter(settings=rewriter_settings, ai_client=mock_ai_client)
        rewriter._cache_max = 2  # Small cache for test
        history = [{"role": "user", "content": "trade on Bisq Easy"}]
        await rewriter.rewrite("How do I do that?", chat_history=history)
        await rewriter.rewrite("What about fees?", chat_history=history)
        await rewriter.rewrite("And the deposit?", chat_history=history)
        assert len(rewriter._cache) <= 2
