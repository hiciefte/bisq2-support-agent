"""Language Detector for identifying input language.

Uses fast heuristics for English detection and LLM fallback for other languages.
"""

from typing import Any, Optional, Tuple

# Supported languages (ISO 639-1 codes)
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


class LanguageDetector:
    """Detects language of input text using heuristics and LLM fallback.

    Fast path: Check for common English patterns first (high accuracy for English).
    Slow path: Use LLM for non-English language detection.
    """

    DETECTION_PROMPT = """Detect the language of the following text. Return ONLY the ISO 639-1 two-letter language code (e.g., "en" for English, "de" for German, "es" for Spanish, "fr" for French).

Text: {text}

Language code:"""

    # Common English words/patterns for fast detection
    ENGLISH_MARKERS = [
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

    def __init__(self, llm_provider: Optional[Any] = None):
        """Initialize the LanguageDetector.

        Args:
            llm_provider: Optional LLM provider for non-English detection.
                         Should have an async generate(prompt) method.
        """
        self.llm = llm_provider

    def _is_likely_english(self, text: str) -> bool:
        """Quick heuristic check for English text.

        Returns True if text appears to be English based on common word patterns.
        This is a fast-path optimization to avoid LLM calls for English input.
        """
        text_lower = text.lower()
        matches = sum(1 for marker in self.ENGLISH_MARKERS if marker in text_lower)
        # Require at least 2 matches for confidence
        return matches >= 2

    async def detect(self, text: str) -> Tuple[str, float]:
        """Detect the language of the given text.

        Args:
            text: Input text to analyze.

        Returns:
            Tuple of (language_code, confidence) where:
            - language_code: ISO 639-1 two-letter code
            - confidence: Float between 0 and 1
        """
        # Fast path: check for English
        if self._is_likely_english(text):
            return ("en", 0.95)

        # If no LLM provider, default to English with low confidence
        if self.llm is None:
            return ("en", 0.5)

        # Use LLM for non-English detection
        try:
            prompt = self.DETECTION_PROMPT.format(text=text[:500])
            response = await self.llm.generate(prompt)
            lang_code = response.strip().lower()[:2]

            if lang_code in SUPPORTED_LANGUAGES:
                return (lang_code, 0.9)
            else:
                # Unknown language code, default to English
                return ("en", 0.5)
        except Exception:
            # On error, default to English with low confidence
            return ("en", 0.3)
