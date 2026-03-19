"""Source-of-truth locale list aligned with Bisq 2 language support."""

from __future__ import annotations

from typing import Final

# Aligned with bisq2/scripts/generate_transifex_batches.py (54 translated locales).
BISQ2_SUPPORTED_LOCALES_54: Final[tuple[str, ...]] = (
    "af-ZA",
    "am",
    "be",
    "bg",
    "bn",
    "ca",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "et",
    "fi",
    "fr",
    "ga",
    "ha",
    "hi",
    "hr",
    "hu",
    "id",
    "is",
    "it",
    "ja",
    "jv",
    "kk",
    "km",
    "ko",
    "lt",
    "lv",
    "mk",
    "ms",
    "nl",
    "no",
    "pa",
    "pcm",
    "pl",
    "pt-BR",
    "pt-PT",
    "ro",
    "ru",
    "sk",
    "sl",
    "sq",
    "sr",
    "sv",
    "sw",
    "ta",
    "th",
    "tl",
    "tr",
    "vi",
    "yo",
    "zh-Hans",
    "zh-Hant",
)

# English source locale + translated locales.
BISQ2_SUPPORTED_LOCALES_WITH_EN: Final[tuple[str, ...]] = (
    "en",
    *BISQ2_SUPPORTED_LOCALES_54,
)
