"""Language detector with local-model first, then LLM tie-break fallback."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Optional, Tuple

from app.metrics.translation_metrics import (
    language_detection_confidence,
    language_detection_llm_tiebreak_total,
    language_detection_total,
    mixed_language_detection_total,
)

logger = logging.getLogger(__name__)

# Supported languages (ISO 639-1 two-letter and ISO 639-2/3 three-letter codes)
SUPPORTED_LANGUAGES = {
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
    "cs": "Czech",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "el": "Greek",
    "he": "Hebrew",
    "hu": "Hungarian",
    "ro": "Romanian",
    "uk": "Ukrainian",
    "bg": "Bulgarian",
    "hr": "Croatian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "et": "Estonian",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "ms": "Malay",
    "fa": "Persian",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
    "sw": "Swahili",
    "af": "Afrikaans",
    "ca": "Catalan",
    "eu": "Basque",
    "gl": "Galician",
    "cy": "Welsh",
    "ga": "Irish",
    "is": "Icelandic",
    "mt": "Maltese",
    "sq": "Albanian",
    "mk": "Macedonian",
    "bs": "Bosnian",
    "sr": "Serbian",
    "ka": "Georgian",
    "hy": "Armenian",
    "az": "Azerbaijani",
    "kk": "Kazakh",
    "uz": "Uzbek",
    "mn": "Mongolian",
    "ne": "Nepali",
    "si": "Sinhala",
    "km": "Khmer",
    "lo": "Lao",
    "my": "Myanmar",
    "am": "Amharic",
    "ti": "Tigrinya",
    "yo": "Yoruba",
    "ig": "Igbo",
    "zu": "Zulu",
    "xh": "Xhosa",
    "st": "Sesotho",
    "tn": "Setswana",
    "sn": "Shona",
    "ny": "Chichewa",
    "mg": "Malagasy",
    "eo": "Esperanto",
    "la": "Latin",
    "jv": "Javanese",
    "su": "Sundanese",
    "tl": "Tagalog",
    "ceb": "Cebuano",
    "haw": "Hawaiian",
    "sm": "Samoan",
    "mi": "Maori",
    "ht": "Haitian Creole",
    "co": "Corsican",
    "fy": "Frisian",
    "gd": "Scottish Gaelic",
    "lb": "Luxembourgish",
    "yi": "Yiddish",
}


@dataclass
class LanguageDetectionDetails:
    """Detailed language detection result."""

    language_code: str
    confidence: float
    backend: str
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    is_mixed: bool = False
    llm_tiebreak_used: bool = False
    local_model_used: bool = False


class LanguageDetector:
    """Detect language via local LID model, with optional LLM tie-break."""

    DETECTION_PROMPT = """Detect the language of the following text. Return ONLY the ISO 639-1 or ISO 639-2/3 language code (2-3 letters, e.g., "en" for English, "de" for German, "es" for Spanish, "ceb" for Cebuano).

Text: {text}

Language code:"""

    ENGLISH_MARKERS: ClassVar[list[str]] = [
        "the ",
        "is ",
        "are ",
        "how ",
        "what ",
        "can ",
        "do ",
        "does ",
        "have ",
        "has ",
        "will ",
        "would ",
        "could ",
        "should ",
        "this ",
        "that ",
        "with ",
        "for ",
        "from ",
        "about ",
        "which ",
        "where ",
        "when ",
        "why ",
        "who ",
        " i ",
        " my ",
        " you ",
        " your ",
        "please ",
        "help ",
        "need ",
        " to ",
        " of ",
        " and ",
        " in ",
        " on ",
        " at ",
    ]

    ISO_639_3_TO_1: ClassVar[dict[str, str]] = {
        "eng": "en",
        "deu": "de",
        "ger": "de",
        "spa": "es",
        "fra": "fr",
        "fre": "fr",
        "ita": "it",
        "por": "pt",
        "nld": "nl",
        "dut": "nl",
        "pol": "pl",
        "rus": "ru",
        "zho": "zh",
        "chi": "zh",
        "jpn": "ja",
        "kor": "ko",
        "ara": "ar",
        "hin": "hi",
        "tur": "tr",
        "vie": "vi",
        "tha": "th",
        "ind": "id",
        "ces": "cs",
        "cze": "cs",
        "swe": "sv",
        "dan": "da",
        "fin": "fi",
        "nor": "no",
        "ell": "el",
        "gre": "el",
        "heb": "he",
        "hun": "hu",
        "ron": "ro",
        "rum": "ro",
        "ukr": "uk",
        "bul": "bg",
        "hrv": "hr",
        "slk": "sk",
        "slo": "sk",
        "slv": "sl",
        "est": "et",
        "lav": "lv",
        "lit": "lt",
        "msa": "ms",
        "may": "ms",
        "fas": "fa",
        "per": "fa",
        "ben": "bn",
        "tam": "ta",
        "tel": "te",
        "mar": "mr",
    }

    LANGUAGE_HINTS: ClassVar[dict[str, set[str]]] = {
        "de": {
            "wie",
            "ich",
            "kann",
            "kaufen",
            "verkaufen",
            "hilfe",
            "problem",
            "handel",
            "mit",
            "und",
            "nicht",
            "bitte",
        },
        "es": {
            "como",
            "cómo",
            "puedo",
            "comprar",
            "vender",
            "ayuda",
            "problema",
            "tengo",
            "quiero",
            "con",
            "gracias",
        },
        "fr": {
            "comment",
            "acheter",
            "vendre",
            "aide",
            "probleme",
            "problème",
            "avec",
            "bonjour",
        },
        "it": {"come", "comprare", "vendere", "aiuto", "problema", "con", "ciao"},
        "pt": {"como", "comprar", "vender", "ajuda", "problema", "com", "obrigado"},
    }

    SCRIPT_HINTS: ClassVar[list[tuple[re.Pattern[str], str, float]]] = [
        (re.compile(r"[\u3040-\u30ff]"), "ja", 0.98),  # Hiragana/Katakana
        (re.compile(r"[\uac00-\ud7af]"), "ko", 0.98),  # Hangul
        (re.compile(r"[\u4e00-\u9fff]"), "zh", 0.94),  # Han ideographs
        (re.compile(r"[\u0600-\u06ff]"), "ar", 0.88),  # Arabic script family
        (re.compile(r"[\u0400-\u04ff]"), "ru", 0.88),  # Cyrillic script family
        (re.compile(r"[\u0370-\u03ff]"), "el", 0.96),  # Greek
        (re.compile(r"[\u0590-\u05ff]"), "he", 0.96),  # Hebrew
        (re.compile(r"[\u0900-\u097f]"), "hi", 0.88),  # Devanagari script family
    ]

    def __init__(
        self,
        llm_provider: Optional[Any] = None,
        local_backend: str = "langdetect",
        local_confidence_threshold: float = 0.80,
        short_text_chars: int = 24,
        mixed_margin_threshold: float = 0.20,
        mixed_secondary_min: float = 0.25,
        enable_llm_tiebreaker: bool = True,
    ):
        self.llm = llm_provider
        self.local_backend = (local_backend or "none").strip().lower()
        self.local_confidence_threshold = max(0.0, min(1.0, local_confidence_threshold))
        self.short_text_chars = max(1, short_text_chars)
        self.mixed_margin_threshold = max(0.0, min(1.0, mixed_margin_threshold))
        self.mixed_secondary_min = max(0.0, min(1.0, mixed_secondary_min))
        self.enable_llm_tiebreaker = bool(enable_llm_tiebreaker)

        self._local_detect_langs: Optional[Callable[[str], list[Any]]] = None
        self._init_local_backend()

    def _init_local_backend(self) -> None:
        if self.local_backend != "langdetect":
            return
        try:
            from langdetect import (  # type: ignore[import-not-found]
                DetectorFactory,
                detect_langs,
            )

            DetectorFactory.seed = 0
            self._local_detect_langs = detect_langs
            logger.info("Language detector local backend initialized: langdetect")
        except Exception:
            self._local_detect_langs = None
            logger.warning(
                "Local language detector backend 'langdetect' unavailable; falling back to heuristics/LLM",
                exc_info=True,
            )

    @staticmethod
    def _normalize_lang_code(code: str) -> Optional[str]:
        normalized = (code or "").strip().lower()
        if not normalized:
            return None
        if "-" in normalized:
            normalized = normalized.split("-", 1)[0]
        if normalized in SUPPORTED_LANGUAGES:
            return normalized
        if normalized in LanguageDetector.ISO_639_3_TO_1:
            return LanguageDetector.ISO_639_3_TO_1[normalized]
        if len(normalized) >= 2 and normalized[:2] in SUPPORTED_LANGUAGES:
            return normalized[:2]
        return None

    def _is_likely_english(self, text: str) -> bool:
        text_lower = text.lower()
        matches = sum(1 for marker in self.ENGLISH_MARKERS if marker in text_lower)
        return matches >= 2

    def _detect_non_english_hint(self, text: str) -> Optional[Tuple[str, float]]:
        for pattern, language, confidence in self.SCRIPT_HINTS:
            if pattern.search(text):
                return (language, confidence)

        if "¿" in text or "¡" in text:
            return ("es", 0.96)

        text_lower = text.lower()
        tokens = set(re.findall(r"[a-zA-ZÀ-ÿ']+", text_lower))
        if not tokens:
            return None

        best_lang: Optional[str] = None
        best_score = 0
        second_score = 0
        for language, hints in self.LANGUAGE_HINTS.items():
            score = sum(1 for token in tokens if token in hints)
            if score > best_score:
                second_score = best_score
                best_score = score
                best_lang = language
            elif score > second_score:
                second_score = score

        if best_lang and best_score >= 2 and best_score >= (second_score + 1):
            confidence = 0.9 if best_score >= 3 else 0.85
            return (best_lang, confidence)
        return None

    async def _llm_text(self, prompt: str) -> str:
        if self.llm is None:
            raise ValueError("No LLM provider configured")

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

    def _emit_metrics(self, details: LanguageDetectionDetails) -> None:
        language_detection_total.labels(
            backend=details.backend,
            result=details.language_code,
        ).inc()
        language_detection_confidence.labels(backend=details.backend).observe(
            max(0.0, min(1.0, float(details.confidence)))
        )
        if details.is_mixed and details.alternatives:
            secondary = details.alternatives[0][0]
            mixed_language_detection_total.labels(
                primary=details.language_code,
                secondary=secondary,
            ).inc()

    async def _detect_with_local_model(
        self, text: str
    ) -> Optional[LanguageDetectionDetails]:
        if self._local_detect_langs is None:
            return None
        try:
            raw = await asyncio.to_thread(self._local_detect_langs, text[:2000])
        except Exception:
            logger.debug("Local LID model failed", exc_info=True)
            return None

        if not raw:
            return None

        parsed: list[tuple[str, float]] = []
        for item in raw:
            lang = self._normalize_lang_code(getattr(item, "lang", ""))
            prob = float(getattr(item, "prob", 0.0))
            if lang is None:
                continue
            parsed.append((lang, max(0.0, min(1.0, prob))))

        if not parsed:
            return None

        primary, primary_prob = parsed[0]
        alternatives = parsed[1:3]
        is_mixed = False
        if alternatives:
            secondary_prob = alternatives[0][1]
            gap = primary_prob - secondary_prob
            is_mixed = (
                secondary_prob >= self.mixed_secondary_min
                and gap <= self.mixed_margin_threshold
            )

        return LanguageDetectionDetails(
            language_code=primary,
            confidence=primary_prob,
            backend="local_model",
            alternatives=alternatives,
            is_mixed=is_mixed,
            local_model_used=True,
        )

    async def _detect_with_llm(
        self, text: str, reason: str
    ) -> Optional[LanguageDetectionDetails]:
        if self.llm is None:
            return None
        language_detection_llm_tiebreak_total.labels(reason=reason).inc()
        try:
            prompt = self.DETECTION_PROMPT.format(text=text[:500])
            response = await self._llm_text(prompt)
            raw_response = response.strip().lower()
            matches = re.findall(r"\b([a-z]{2,3}(?:-[a-z]{2,3})?)\b", raw_response)
            candidate_codes = [raw_response]
            if matches:
                candidate_codes = list(reversed(matches))

            for code in candidate_codes:
                normalized = self._normalize_lang_code(code)
                if normalized is not None:
                    return LanguageDetectionDetails(
                        language_code=normalized,
                        confidence=0.86,
                        backend="llm_tiebreak",
                        llm_tiebreak_used=True,
                    )
            return None
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("LLM language tie-break failed", exc_info=True)
            return None

    async def detect_with_metadata(self, text: str) -> LanguageDetectionDetails:
        text = (text or "").strip()
        if not text:
            details = LanguageDetectionDetails(
                language_code="en",
                confidence=1.0,
                backend="empty_input",
            )
            self._emit_metrics(details)
            return details

        text_len = len(text)
        non_english_hint = self._detect_non_english_hint(text)

        # Trust only highest-confidence script hints immediately.
        if non_english_hint is not None and non_english_hint[1] >= 0.97:
            details = LanguageDetectionDetails(
                language_code=non_english_hint[0],
                confidence=non_english_hint[1],
                backend="script_hint",
            )
            self._emit_metrics(details)
            return details

        # Keep a cheap English bypass to avoid unnecessary model/LLM work.
        if (
            non_english_hint is None
            and text_len > self.short_text_chars
            and self._is_likely_english(text)
        ):
            details = LanguageDetectionDetails(
                language_code="en",
                confidence=0.95,
                backend="english_heuristic",
            )
            self._emit_metrics(details)
            return details

        local = await self._detect_with_local_model(text)
        if (
            local is not None
            and local.confidence >= self.local_confidence_threshold
            and not local.is_mixed
        ):
            if (
                local.language_code == "en"
                and non_english_hint is not None
                and non_english_hint[1] >= 0.85
            ):
                details = LanguageDetectionDetails(
                    language_code=non_english_hint[0],
                    confidence=non_english_hint[1],
                    backend="hint_override",
                    alternatives=local.alternatives,
                    local_model_used=True,
                )
                self._emit_metrics(details)
                return details
            self._emit_metrics(local)
            return local

        llm_reason: Optional[str] = None
        if self.enable_llm_tiebreaker and self.llm is not None:
            if local is None:
                llm_reason = "no_local_signal"
            elif local.is_mixed:
                llm_reason = "mixed_language"
            elif local.confidence < self.local_confidence_threshold:
                llm_reason = "low_local_confidence"
            elif text_len <= self.short_text_chars:
                llm_reason = "short_text"

        if llm_reason is not None:
            llm_result = await self._detect_with_llm(text, llm_reason)
            if llm_result is not None:
                if (
                    llm_result.language_code == "en"
                    and non_english_hint is not None
                    and non_english_hint[1] >= 0.85
                ):
                    details = LanguageDetectionDetails(
                        language_code=non_english_hint[0],
                        confidence=non_english_hint[1],
                        backend="hint_override",
                        llm_tiebreak_used=True,
                        alternatives=llm_result.alternatives,
                    )
                    self._emit_metrics(details)
                    return details
                self._emit_metrics(llm_result)
                return llm_result

        if local is not None:
            self._emit_metrics(local)
            return local

        if non_english_hint is not None:
            details = LanguageDetectionDetails(
                language_code=non_english_hint[0],
                confidence=non_english_hint[1],
                backend="lexical_hint",
            )
            self._emit_metrics(details)
            return details

        if self._is_likely_english(text):
            details = LanguageDetectionDetails(
                language_code="en",
                confidence=0.8,
                backend="english_heuristic",
            )
            self._emit_metrics(details)
            return details

        details = LanguageDetectionDetails(
            language_code="en",
            confidence=0.5,
            backend="default_fallback",
        )
        self._emit_metrics(details)
        return details

    async def detect(self, text: str) -> Tuple[str, float]:
        details = await self.detect_with_metadata(text)
        return (details.language_code, details.confidence)
