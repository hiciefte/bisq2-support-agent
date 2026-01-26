"""Translation Service for multilingual support.

Orchestrates language detection, term protection, translation, and caching.
Supports 100+ languages with a single English knowledge base.
"""

import hashlib
import logging
from typing import Any, Dict, Optional

from app.services.translation.cache import TieredCache
from app.services.translation.glossary_manager import GlossaryManager
from app.services.translation.language_detector import (
    SUPPORTED_LANGUAGES,
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

    def __init__(
        self,
        llm_provider: Optional[Any] = None,
        cache_backend: Optional["TieredCache"] = None,
        glossary_manager: Optional["GlossaryManager"] = None,
        language_detector: Optional["LanguageDetector"] = None,
        cache_l1_size: int = 1000,
        cache_db_path: str = "/data/translation_cache.db",
        additional_glossary_terms: Optional[Dict[str, str]] = None,
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
        """
        self.llm = llm_provider

        # Use injected dependencies or create new instances
        self.glossary = glossary_manager or GlossaryManager(
            additional_terms=additional_glossary_terms
        )
        self.detector = language_detector or LanguageDetector(llm_provider=llm_provider)
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

        source_name = SUPPORTED_LANGUAGES.get(source_lang, source_lang)
        target_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)

        prompt = self.TRANSLATION_PROMPT.format(
            source_lang=source_name,
            target_lang=target_name,
            text=text,
        )

        response = await self.llm.generate(prompt)
        self.stats["translations_performed"] += 1
        return response.strip()

    async def translate_query(
        self,
        query: str,
        source_lang: Optional[str] = None,
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
        self.stats["queries_processed"] += 1

        # Detect language if not provided
        confidence = 1.0
        if source_lang is None:
            source_lang, confidence = await self.detector.detect(query)

        # Skip if already English
        if source_lang == "en":
            self.stats["english_passthrough"] += 1
            return {
                "translated_text": query,
                "source_lang": "en",
                "skipped": True,
                "cached": False,
                "confidence": confidence,
            }

        # Check cache
        cache_key = self._make_cache_key(query, source_lang, target_lang)
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            self.stats["cache_hits"] += 1
            return {
                "translated_text": cached_result,
                "source_lang": source_lang,
                "skipped": False,
                "cached": True,
                "confidence": confidence,
            }

        self.stats["cache_misses"] += 1

        # Protect Bisq terms before translation
        protected_query, placeholder_map = self.glossary.protect_terms(query)

        try:
            # Translate
            translated = await self._translate(
                protected_query, source_lang, target_lang
            )

            # Restore Bisq terms
            final_text = self.glossary.restore_terms(translated, placeholder_map)

            # Cache the result
            await self.cache.set(cache_key, final_text)

            return {
                "translated_text": final_text,
                "source_lang": source_lang,
                "skipped": False,
                "cached": False,
                "confidence": confidence,
            }

        except Exception as e:
            logger.error(f"Translation failed: {e}")
            self.stats["translation_errors"] += 1
            # Graceful degradation: return original query
            return {
                "translated_text": query,
                "source_lang": source_lang,
                "skipped": False,
                "cached": False,
                "confidence": 0.0,
                "error": str(e),
            }

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
        self.stats["responses_processed"] += 1

        # Skip if target is English
        if target_lang == "en":
            self.stats["english_passthrough"] += 1
            return {
                "translated_text": response,
                "skipped": True,
                "cached": False,
            }

        # Check cache
        cache_key = self._make_cache_key(response, source_lang, target_lang)
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            self.stats["cache_hits"] += 1
            return {
                "translated_text": cached_result,
                "skipped": False,
                "cached": True,
            }

        self.stats["cache_misses"] += 1

        # Protect Bisq terms before translation
        protected_response, placeholder_map = self.glossary.protect_terms(response)

        try:
            # Translate
            translated = await self._translate(
                protected_response, source_lang, target_lang
            )

            # Restore Bisq terms
            final_text = self.glossary.restore_terms(translated, placeholder_map)

            # Cache the result
            await self.cache.set(cache_key, final_text)

            return {
                "translated_text": final_text,
                "skipped": False,
                "cached": False,
            }

        except Exception as e:
            logger.error(f"Response translation failed: {e}")
            self.stats["translation_errors"] += 1
            # Graceful degradation: return original response
            return {
                "translated_text": response,
                "skipped": False,
                "cached": False,
                "error": str(e),
            }

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
