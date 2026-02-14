"""Pre-retrieval query rewriter with two-track strategy.

Track 1 (Heuristic): Pronoun resolution + entity substitution (<1ms, $0)
Track 2 (LLM): Context-aware rewrite via gpt-4o-mini (~300ms, ~$0.00004)

Pattern: Matches comparison_engine.py — AISuite via asyncio.to_thread().
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.services.rag.bisq_entities import (
    BISQ1_ENTITY_MAP,
    BISQ2_ENTITY_MAP,
    build_llm_entity_examples,
)
from app.services.rag.query_context import (
    extract_last_topic,
    is_anaphoric,
)

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Histogram

    QUERY_REWRITE_LATENCY = Histogram(
        "rag_query_rewrite_latency_seconds",
        "Query rewrite latency",
    )
    QUERY_REWRITE_STRATEGY = Counter(
        "rag_query_rewrite_strategy_total",
        "Query rewrite strategy used",
        ["strategy"],
    )
    QUERY_REWRITE_CACHE_HITS = Counter(
        "rag_query_rewrite_cache_hits_total",
        "Query rewrite cache hits",
    )
    QUERY_REWRITE_ERRORS = Counter(
        "rag_query_rewrite_errors_total",
        "Query rewrite errors",
        ["error_type"],
    )
except ImportError:
    QUERY_REWRITE_LATENCY = None
    QUERY_REWRITE_STRATEGY = None
    QUERY_REWRITE_CACHE_HITS = None
    QUERY_REWRITE_ERRORS = None


@dataclass
class RewriteResult:
    rewritten_query: str
    rewritten: bool
    strategy: str  # "none" | "heuristic" | "llm" | "timeout_fallback"
    original_query: str
    latency_ms: float
    confidence: float  # 0-1


class QueryRewriter:
    """Two-track query rewriter for RAG retrieval improvement."""

    def __init__(self, settings: Settings, ai_client: Any):
        self.settings = settings
        self.ai_client = ai_client
        self.model = settings.QUERY_REWRITE_MODEL
        self.timeout = settings.QUERY_REWRITE_TIMEOUT_SECONDS
        self.max_history_turns = settings.QUERY_REWRITE_MAX_HISTORY_TURNS
        self._cache: OrderedDict[str, RewriteResult] = OrderedDict()
        self._cache_max = 256

    async def rewrite(
        self, query: str, chat_history: List[Dict[str, str]]
    ) -> RewriteResult:
        """Rewrite a query for better retrieval.

        Returns RewriteResult with rewritten=False if no rewrite needed.
        """
        start = time.monotonic()

        # Empty query guard
        if not query or not query.strip():
            return RewriteResult(
                rewritten_query=query,
                rewritten=False,
                strategy="none",
                original_query=query,
                latency_ms=0.0,
                confidence=0.0,
            )

        # Gate: should we rewrite?
        if not self._needs_rewrite(query, chat_history):
            return RewriteResult(
                rewritten_query=query,
                rewritten=False,
                strategy="none",
                original_query=query,
                latency_ms=0.0,
                confidence=0.0,
            )

        # Cache check
        cache_key = self._cache_key(query, chat_history)
        if cache_key in self._cache:
            if QUERY_REWRITE_CACHE_HITS:
                QUERY_REWRITE_CACHE_HITS.inc()
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # Track 1: Heuristic
        heuristic_result = self._heuristic_rewrite(query, chat_history)
        if heuristic_result:
            elapsed = (time.monotonic() - start) * 1000
            heuristic_result.latency_ms = elapsed
            self._cache_put(cache_key, heuristic_result)
            if QUERY_REWRITE_STRATEGY:
                QUERY_REWRITE_STRATEGY.labels(strategy="heuristic").inc()
            return heuristic_result

        # Track 2: LLM
        try:
            llm_result = await self._llm_rewrite(query, chat_history)
            elapsed = (time.monotonic() - start) * 1000
            llm_result.latency_ms = elapsed
            self._cache_put(cache_key, llm_result)
            if QUERY_REWRITE_STRATEGY:
                QUERY_REWRITE_STRATEGY.labels(strategy=llm_result.strategy).inc()
            if QUERY_REWRITE_LATENCY:
                QUERY_REWRITE_LATENCY.observe(elapsed / 1000)
            return llm_result
        except Exception as e:
            logger.warning(f"LLM rewrite failed: {e}")
            if QUERY_REWRITE_ERRORS:
                QUERY_REWRITE_ERRORS.labels(error_type="llm_error").inc()
            elapsed = (time.monotonic() - start) * 1000
            return RewriteResult(
                rewritten_query=query,
                rewritten=False,
                strategy="error_fallback",
                original_query=query,
                latency_ms=elapsed,
                confidence=0.0,
            )

    # Follow-up phrases that indicate context-dependent queries
    _FOLLOWUP_RE = re.compile(
        r"^(what about|how about|and |but what|what if|can i also)\b",
        re.IGNORECASE,
    )

    def _needs_rewrite(self, query: str, chat_history: list) -> bool:
        """Gate: decide if rewrite is needed."""
        if not chat_history:
            return False
        word_count = len(query.split())
        if word_count > 12 and not is_anaphoric(query) and "bisq" in query.lower():
            return False
        if word_count < 5:
            return True
        if is_anaphoric(query):
            return True
        # Detect follow-up phrasing ("What about...", "And ...", etc.)
        if self._FOLLOWUP_RE.search(query):
            return True
        # Short-ish queries (5-8 words) without Bisq context likely need rewrite
        if word_count <= 8 and "bisq" not in query.lower():
            return True
        return False

    def _heuristic_rewrite(
        self, query: str, chat_history: list
    ) -> Optional[RewriteResult]:
        """Track 1: Heuristic pronoun resolution + entity substitution.

        Prepends the conversation topic for rich semantic context,
        and applies entity substitution to the combined result.
        """
        if not is_anaphoric(query) and len(query.split()) >= 5:
            return None  # Defer to LLM track

        topic = extract_last_topic(chat_history)
        if not topic:
            return None

        rewritten = f"Regarding {topic}: {query}"

        # Apply entity substitution to the full rewritten query
        for entity_map in (BISQ1_ENTITY_MAP, BISQ2_ENTITY_MAP):
            for informal, canonical in entity_map.items():
                if informal in rewritten.lower():
                    rewritten = re.sub(
                        re.escape(informal),
                        canonical,
                        rewritten,
                        flags=re.IGNORECASE,
                    )
                    break

        return RewriteResult(
            rewritten_query=rewritten,
            rewritten=True,
            strategy="heuristic",
            original_query=query,
            latency_ms=0.0,
            confidence=0.7,
        )

    def _build_system_prompt(self) -> str:
        """Build system prompt for LLM rewriter."""
        entity_examples = build_llm_entity_examples()
        return f"""You are a query rewriter for a Bisq cryptocurrency support system.

Given conversation history and the user's current question, produce a
SELF-CONTAINED search query. Rules:

1. If already self-contained, return it UNCHANGED.
2. Expand anaphoric references using conversation context.
3. PRESERVE Bisq version identifiers:
   - Bisq 1 context (multisig/DAO/BSQ/arbitration) \u2192 include "Bisq 1"
   - Bisq 2 context (Bisq Easy/reputation/trade protocol) \u2192 include "Bisq 2"
4. Replace vague language with domain terms:
{entity_examples}
5. Keep it to 1-2 sentences. Do NOT answer the question.

Respond with ONLY JSON:
{{"rewritten_query": "...", "was_rewritten": true/false, "confidence": 0.0-1.0}}"""

    def _format_history(self, chat_history: list) -> list:
        """Format chat history for LLM, truncated to max turns."""
        turns = chat_history[-(self.max_history_turns * 2) :]
        return [{"role": m["role"], "content": m["content"]} for m in turns]

    async def _llm_rewrite(self, query: str, chat_history: list) -> RewriteResult:
        """Track 2: LLM-based rewrite via AISuite."""
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            *self._format_history(chat_history),
            {"role": "user", "content": query},
        ]

        def _sync_call():
            return self.ai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=150,
            )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_sync_call),
                timeout=self.timeout,
            )
            return self._parse_llm_response(response, query)
        except asyncio.TimeoutError:
            logger.warning("Query rewrite LLM timeout")
            if QUERY_REWRITE_ERRORS:
                QUERY_REWRITE_ERRORS.labels(error_type="timeout").inc()
            return RewriteResult(
                rewritten_query=query,
                rewritten=False,
                strategy="timeout_fallback",
                original_query=query,
                latency_ms=self.timeout * 1000,
                confidence=0.0,
            )

    def _parse_llm_response(self, response: Any, original_query: str) -> RewriteResult:
        """Parse LLM JSON response into RewriteResult."""
        try:
            content = response.choices[0].message.content.strip()
            data = json.loads(content)
            was_rewritten = data.get("was_rewritten", False)
            return RewriteResult(
                rewritten_query=data.get("rewritten_query", original_query),
                rewritten=was_rewritten,
                strategy="llm" if was_rewritten else "none",
                original_query=original_query,
                latency_ms=0.0,
                confidence=data.get("confidence", 0.5),
            )
        except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
            logger.warning(f"Failed to parse LLM rewrite response: {e}")
            if QUERY_REWRITE_ERRORS:
                QUERY_REWRITE_ERRORS.labels(error_type="parse_error").inc()
            return RewriteResult(
                rewritten_query=original_query,
                rewritten=False,
                strategy="parse_error_fallback",
                original_query=original_query,
                latency_ms=0.0,
                confidence=0.0,
            )

    def _cache_key(self, query: str, chat_history: list) -> str:
        """Generate cache key from query + recent history."""
        recent = chat_history[-2:] if chat_history else []
        key_data = json.dumps({"q": query, "h": recent}, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()

    def _cache_put(self, key: str, result: RewriteResult) -> None:
        """Add result to cache with LRU eviction."""
        self._cache[key] = result
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
