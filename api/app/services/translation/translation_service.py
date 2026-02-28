"""Translation Service for multilingual support.

Orchestrates language detection, term protection, translation, and caching.
Supports 100+ languages with a single English knowledge base.
"""

import asyncio
import hashlib
import inspect
import logging
import time
from typing import Any, Dict, Optional

from app.metrics.translation_metrics import (
    translation_errors_total,
    translation_operation_duration_seconds,
    translation_query_decisions_total,
)
from app.services.translation.cache import TieredCache
from app.services.translation.glossary_manager import GlossaryManager
from app.services.translation.language_detector import (
    SUPPORTED_LANGUAGES,
    LanguageDetectionDetails,
    LanguageDetector,
)

logger = logging.getLogger(__name__)


class TranslationService:
    """Main orchestrator for multilingual translation.

    Flow:
    1. Detect input language
    2. If not English, translate query to English (for RAG)
    3. After RAG response, translate response back to user's language
    4. Preserve Bisq terminology throughout

    Features:
    - Glossary-based term protection
    - Multi-tier caching (L1 + L3)
    - Graceful degradation on failures
    - Statistics tracking
    """

    TRANSLATION_PROMPT = """Translate the following text from {source_lang} to {target_lang}.
Preserve any terms enclosed in __BISQ_TERM_X__ placeholders exactly as they are.
Maintain the original tone and technical accuracy.

Text to translate:
{text}

Translation:"""

    UNKNOWN_LANGUAGE_CODES: frozenset[str] = frozenset({"und", "unknown"})

    def __init__(
        self,
        llm_provider: Optional[Any] = None,
        cache_backend: Optional["TieredCache"] = None,
        glossary_manager: Optional["GlossaryManager"] = None,
        language_detector: Optional["LanguageDetector"] = None,
        cache_l1_size: int = 1000,
        cache_db_path: str = "/data/translation_cache.db",
        additional_glossary_terms: Optional[Dict[str, str]] = None,
        translation_skip_en_confidence: float = 0.85,
        lid_backend: str = "langdetect",
        lid_confidence_threshold: float = 0.80,
        lid_short_text_chars: int = 24,
        lid_mixed_margin_threshold: float = 0.20,
        lid_mixed_secondary_min: float = 0.25,
        lid_enable_llm_tiebreaker: bool = True,
    ):
        """Initialize the TranslationService.

        Args:
            llm_provider: LLM provider with async generate(prompt) method.
            cache_backend: Optional pre-configured TieredCache instance.
            glossary_manager: Optional pre-configured GlossaryManager instance.
            language_detector: Optional pre-configured LanguageDetector instance.
            cache_l1_size: Size of L1 LRU cache (if cache_backend not provided).
            cache_db_path: Path to L3 SQLite cache database (if cache_backend not provided).
            additional_glossary_terms: Extra terms to protect from translation.
            translation_skip_en_confidence: Skip query translation if detected English
                confidence is at or above this threshold.
            lid_backend: Local language ID backend to use.
            lid_confidence_threshold: Confidence threshold for local LID acceptance.
            lid_short_text_chars: Short-text threshold for LID tie-break policy.
            lid_mixed_margin_threshold: Margin threshold for mixed-language detection.
            lid_mixed_secondary_min: Secondary confidence threshold for mixed-language detection.
            lid_enable_llm_tiebreaker: Enable LLM tie-break for uncertain LID results.
        """
        self.llm = llm_provider
        self.translation_skip_en_confidence = max(
            0.0, min(1.0, float(translation_skip_en_confidence))
        )

        # Use injected dependencies or create new instances
        self.glossary = glossary_manager or GlossaryManager(
            additional_terms=additional_glossary_terms
        )
        self.detector = language_detector or LanguageDetector(
            llm_provider=llm_provider,
            local_backend=lid_backend,
            local_confidence_threshold=lid_confidence_threshold,
            short_text_chars=lid_short_text_chars,
            mixed_margin_threshold=lid_mixed_margin_threshold,
            mixed_secondary_min=lid_mixed_secondary_min,
            enable_llm_tiebreaker=lid_enable_llm_tiebreaker,
        )
        self.cache = cache_backend or TieredCache(
            l1_size=cache_l1_size, db_path=cache_db_path
        )

        # Statistics
        self.stats = {
            "queries_processed": 0,
            "responses_processed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "translations_performed": 0,
            "translation_errors": 0,
            "english_passthrough": 0,
        }

    def _make_cache_key(self, text: str, source_lang: str, target_lang: str) -> str:
        """Generate a cache key for a translation.

        Args:
            text: Text to translate.
            source_lang: Source language code.
            target_lang: Target language code.

        Returns:
            MD5 hash-based cache key.
        """
        content = f"{source_lang}:{target_lang}:{text}"
        return hashlib.md5(content.encode()).hexdigest()

    async def _llm_text(self, prompt: str) -> str:
        """Call configured LLM and normalize response text.

        Supports both async `generate(prompt)` and sync `invoke(prompt)` interfaces.
        """
        if self.llm is None:
            raise ValueError("No LLM provider configured for translation")

        if hasattr(self.llm, "generate"):
            result = self.llm.generate(prompt)
            if inspect.isawaitable(result):
                result = await result
        elif hasattr(self.llm, "invoke"):
            result = await asyncio.to_thread(self.llm.invoke, prompt)
        else:
            raise AttributeError("LLM provider must expose generate() or invoke()")

        if hasattr(result, "content"):
            return str(result.content).strip()
        return str(result).strip()

    async def _translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """Perform the actual translation using LLM.

        Args:
            text: Text to translate (may contain placeholders).
            source_lang: Source language code.
            target_lang: Target language code.

        Returns:
            Translated text.

        Raises:
            Exception: If translation fails and no fallback available.
        """
        if self.llm is None:
            raise ValueError("No LLM provider configured for translation")

        source_name = (
            "auto-detected language"
            if source_lang == "auto"
            else SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        )
        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        prompt = self.TRANSLATION_PROMPT.format(
            source_lang=source_name,
            target_lang=target_name,
            text=text,
        )

        response = await self._llm_text(prompt)
        self.stats["translations_performed"] += 1
        return response.strip()

    @staticmethod
    def _record_query_decision(decision: str, source_lang: str) -> None:
        translation_query_decisions_total.labels(
            decision=decision,
            source_lang=(source_lang or "unknown"),
        ).inc()

    async def translate_query(
        self,
        query: str,
        source_lang: Optional[str] = None,
        prior_language: Optional[str] = None,
        target_lang: str = "en",
    ) -> Dict[str, Any]:
        """Translate a user query to English for RAG processing.

        This should be called BEFORE sending the query to the RAG pipeline.

        Args:
            query: User's query in any language.
            source_lang: Optional source language code. If None, auto-detected.
            target_lang: Target language (default: "en" for RAG).

        Returns:
            Dict with:
            - translated_text: The translated query
            - source_lang: Detected/provided source language
            - cached: Whether result came from cache
            - skipped: Whether translation was skipped (already English)
            - confidence: Detection confidence (if auto-detected)
        """
        start_time = time.perf_counter()
        self.stats["queries_processed"] += 1

        if not (query or "").strip():
            result = {
                "translated_text": query,
                "source_lang": "und",
                "skipped": True,
                "cached": False,
                "confidence": 0.0,
                "detection_backend": "empty_input",
            }
            translation_operation_duration_seconds.labels(direction="query").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        # Detect language if not provided
        detection_details: Optional[LanguageDetectionDetails] = None
        confidence = 1.0
        if source_lang is None:
            detection_details = await self.detector.detect_with_metadata(
                query, prior_language=prior_language
            )
            source_lang = detection_details.language_code
            confidence = detection_details.confidence
        source_lang = (source_lang or "en").strip().lower() or "en"
        if source_lang in self.UNKNOWN_LANGUAGE_CODES:
            source_lang = "und"

        if source_lang == "en" and confidence >= self.translation_skip_en_confidence:
            self.stats["english_passthrough"] += 1
            self._record_query_decision("skip_english", source_lang)
            result = {
                "translated_text": query,
                "source_lang": "en",
                "skipped": True,
                "cached": False,
                "confidence": confidence,
                "detection_backend": (
                    detection_details.backend if detection_details else "provided"
                ),
                "is_mixed_language": (
                    detection_details.is_mixed if detection_details else False
                ),
                "llm_tiebreak_used": (
                    detection_details.llm_tiebreak_used if detection_details else False
                ),
            }
            translation_operation_duration_seconds.labels(direction="query").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        # For low-confidence English detections, ask translation LLM to auto-detect source.
        source_lang_for_translation = source_lang
        if source_lang == "en" and confidence < self.translation_skip_en_confidence:
            source_lang_for_translation = "auto"
        elif source_lang == "und":
            source_lang_for_translation = "auto"

        # Check cache
        cache_key = self._make_cache_key(
            query, source_lang_for_translation, target_lang
        )
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            self.stats["cache_hits"] += 1
            cache_decision = (
                "translate_cache_hit_auto"
                if source_lang_for_translation == "auto"
                else "translate_cache_hit"
            )
            self._record_query_decision(cache_decision, source_lang)
            result = {
                "translated_text": cached_result,
                "source_lang": source_lang,
                "skipped": False,
                "cached": True,
                "confidence": confidence,
                "detection_backend": (
                    detection_details.backend if detection_details else "provided"
                ),
                "is_mixed_language": (
                    detection_details.is_mixed if detection_details else False
                ),
                "llm_tiebreak_used": (
                    detection_details.llm_tiebreak_used if detection_details else False
                ),
            }
            translation_operation_duration_seconds.labels(direction="query").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        self.stats["cache_misses"] += 1

        # Protect Bisq terms before translation
        protected_query, placeholder_map = self.glossary.protect_terms(query)

        try:
            # Translate
            translated = await self._translate(
                protected_query, source_lang_for_translation, target_lang
            )

            # Restore Bisq terms
            final_text = self.glossary.restore_terms(translated, placeholder_map)

            # Cache the result
            await self.cache.set(cache_key, final_text)
            if source_lang_for_translation == "auto":
                decision = (
                    "translate_unknown_source"
                    if source_lang == "und"
                    else "translate_low_confidence_en"
                )
            else:
                decision = "translate_performed"
            self._record_query_decision(decision, source_lang)

            return {
                "translated_text": final_text,
                "source_lang": source_lang,
                "skipped": False,
                "cached": False,
                "confidence": confidence,
                "detection_backend": (
                    detection_details.backend if detection_details else "provided"
                ),
                "is_mixed_language": (
                    detection_details.is_mixed if detection_details else False
                ),
                "llm_tiebreak_used": (
                    detection_details.llm_tiebreak_used if detection_details else False
                ),
            }

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            self.stats["translation_errors"] += 1
            self._record_query_decision("translate_error", source_lang)
            translation_errors_total.labels(direction="query").inc()
            # Graceful degradation: return original query
            return {
                "translated_text": query,
                "source_lang": source_lang,
                "skipped": False,
                "cached": False,
                "confidence": 0.0,
                "error": str(e),
            }
        finally:
            translation_operation_duration_seconds.labels(direction="query").observe(
                max(0.0, time.perf_counter() - start_time)
            )

    async def translate_response(
        self,
        response: str,
        target_lang: str,
        source_lang: str = "en",
    ) -> Dict[str, Any]:
        """Translate a RAG response back to the user's language.

        This should be called AFTER receiving the response from RAG.

        Args:
            response: RAG response in English.
            target_lang: User's language code.
            source_lang: Response language (default: "en").

        Returns:
            Dict with:
            - translated_text: The translated response
            - skipped: Whether translation was skipped
            - cached: Whether result came from cache
        """
        start_time = time.perf_counter()
        self.stats["responses_processed"] += 1

        normalized_target_lang = (target_lang or "").strip().lower() or "en"

        # Skip if target is English
        if normalized_target_lang == "en" or normalized_target_lang == source_lang:
            self.stats["english_passthrough"] += 1
            result = {
                "translated_text": response,
                "target_lang": normalized_target_lang,
                "skipped": True,
                "cached": False,
            }
            translation_operation_duration_seconds.labels(direction="response").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        if normalized_target_lang in self.UNKNOWN_LANGUAGE_CODES:
            result = {
                "translated_text": response,
                "target_lang": normalized_target_lang,
                "skipped": True,
                "cached": False,
                "reason": "unknown_target_language",
            }
            translation_operation_duration_seconds.labels(direction="response").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        # Check cache
        cache_key = self._make_cache_key(response, source_lang, normalized_target_lang)
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            self.stats["cache_hits"] += 1
            result = {
                "translated_text": cached_result,
                "target_lang": normalized_target_lang,
                "skipped": False,
                "cached": True,
            }
            translation_operation_duration_seconds.labels(direction="response").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        self.stats["cache_misses"] += 1

        # Protect Bisq terms before translation
        protected_response, placeholder_map = self.glossary.protect_terms(response)

        try:
            # Translate
            translated = await self._translate(
                protected_response, source_lang, normalized_target_lang
            )

            # Restore Bisq terms
            final_text = self.glossary.restore_terms(translated, placeholder_map)

            # Cache the result
            await self.cache.set(cache_key, final_text)

            result = {
                "translated_text": final_text,
                "target_lang": normalized_target_lang,
                "skipped": False,
                "cached": False,
            }
            translation_operation_duration_seconds.labels(direction="response").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

        except Exception as e:
            logger.error(f"Response translation failed: {e}")
            self.stats["translation_errors"] += 1
            translation_errors_total.labels(direction="response").inc()
            # Graceful degradation: return original response
            result = {
                "translated_text": response,
                "target_lang": normalized_target_lang,
                "skipped": False,
                "cached": False,
                "error": str(e),
            }
            translation_operation_duration_seconds.labels(direction="response").observe(
                max(0.0, time.perf_counter() - start_time)
            )
            return result

    def get_stats(self) -> Dict[str, Any]:
        """Get translation service statistics.

        Returns:
            Dict with service and cache statistics.
        """
        total_cache = self.stats["cache_hits"] + self.stats["cache_misses"]
        cache_hit_ratio = (
            self.stats["cache_hits"] / total_cache if total_cache > 0 else 0
        )

        return {
            **self.stats,
            "cache_hit_ratio": cache_hit_ratio,
            "cache_stats": self.cache.get_stats(),
        }

    def cleanup_cache(self) -> int:
        """Cleanup expired cache entries.

        Returns:
            Number of entries removed.
        """
        return self.cache.cleanup()
