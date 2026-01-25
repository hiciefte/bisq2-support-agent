"""Language Detector for identifying input language.

Uses fast heuristics for English detection and LLM fallback for other languages.
"""

import asyncio
from typing import Any, Optional, Tuple

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


class LanguageDetector:
    """Detects language of input text using heuristics and LLM fallback.

    Fast path: Check for common English patterns first (high accuracy for English).
    Slow path: Use LLM for non-English language detection.
    """

    DETECTION_PROMPT = """Detect the language of the following text. Return ONLY the ISO 639-1 or ISO 639-2/3 language code (2-3 letters, e.g., "en" for English, "de" for German, "es" for Spanish, "ceb" for Cebuano).

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
            import re

            prompt = self.DETECTION_PROMPT.format(text=text[:500])
            response = await self.llm.generate(prompt)

            # Extract language code token from response
            # Handles formats like "en", "Language: en", "The language is: en"
            raw_response = response.strip().lower()

            # Find all 2-3 letter tokens from the response
            # Use findall to get all matches, then prefer one in SUPPORTED_LANGUAGES
            code_matches = re.findall(r"\b([a-z]{2,3})\b", raw_response)

            # Select the best match: prefer a token in SUPPORTED_LANGUAGES,
            # otherwise use the last token (most likely to be the answer)
            lang_code = raw_response  # fallback if no tokens found
            if code_matches:
                # First, check if any token is in supported languages
                for token in code_matches:
                    if token in SUPPORTED_LANGUAGES:
                        lang_code = token
                        break
                else:
                    # No match in supported languages, use the last token
                    lang_code = code_matches[-1]

            # Handle 3-letter ISO 639-2/3 codes by mapping to 2-letter ISO 639-1
            iso_639_3_to_1 = {
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

            # First check exact match in SUPPORTED_LANGUAGES (handles both 2 and 3-letter codes)
            if lang_code in SUPPORTED_LANGUAGES:
                return (lang_code, 0.9)

            # Try 3-letter code mapping to 2-letter
            if lang_code in iso_639_3_to_1:
                return (iso_639_3_to_1[lang_code], 0.85)

            # Try first 2 characters as fallback (2-letter code)
            if len(lang_code) >= 2:
                two_letter = lang_code[:2]
                if two_letter in SUPPORTED_LANGUAGES:
                    return (two_letter, 0.85)

            # Unknown language code, default to English
            return ("en", 0.5)
        except asyncio.CancelledError:
            # Re-raise cancellations to support cooperative cancellation
            raise
        except Exception:
            # On error, default to English with low confidence
            return ("en", 0.3)
