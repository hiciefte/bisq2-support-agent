"""Translation package for multilingual support.

Phase 10: Multilingual Support (100+ languages, single knowledge base)

This package provides:
- GlossaryManager: Protects Bisq-specific terminology during translation
- LanguageDetector: Detects input language using heuristics + LLM
- TieredCache: Multi-tier caching (L1 memory + L3 SQLite)
- TranslationService: Main orchestrator for query/response translation
"""

from app.services.translation.cache import LRUCache, SQLiteCache, TieredCache
from app.services.translation.glossary_manager import GlossaryManager
from app.services.translation.language_detector import (
    SUPPORTED_LANGUAGES,
    LanguageDetector,
)
from app.services.translation.translation_service import TranslationService

__all__ = [
    "GlossaryManager",
    "LanguageDetector",
    "SUPPORTED_LANGUAGES",
    "LRUCache",
    "SQLiteCache",
    "TieredCache",
    "TranslationService",
]
