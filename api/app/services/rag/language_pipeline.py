"""Language detection and translation helpers for RAG queries."""

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from app.services.translation.language_detector import SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)


@dataclass
class QueryLanguageState:
    """Localized and canonical query text for one RAG request."""

    localized_question: str
    preprocessed_question: str
    canonical_question_en: str
    original_language: str
    was_translated: bool


class QueryLanguageHandler:
    """Handle language hints, query translation, and response translation."""

    def __init__(self, translation_service: Any = None) -> None:
        self.translation_service = translation_service

    @staticmethod
    def normalize_language_code(value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if "-" in normalized:
            normalized = normalized.split("-", 1)[0]
        if normalized in SUPPORTED_LANGUAGES and normalized != "und":
            return normalized
        return None

    def extract_prior_language_from_history(
        self, chat_history: list[Any]
    ) -> Optional[str]:
        for item in reversed(chat_history):
            candidates: list[Any] = []
            if isinstance(item, dict):
                candidates.extend(
                    [
                        item.get("original_language"),
                        item.get("user_language"),
                        item.get("language"),
                    ]
                )
                metadata = item.get("metadata")
                if isinstance(metadata, dict):
                    candidates.extend(
                        [
                            metadata.get("original_language"),
                            metadata.get("user_language"),
                            metadata.get("language"),
                        ]
                    )
            else:
                candidates.extend(
                    [
                        getattr(item, "original_language", None),
                        getattr(item, "user_language", None),
                        getattr(item, "language", None),
                    ]
                )
                metadata = getattr(item, "metadata", None)
                if isinstance(metadata, dict):
                    candidates.extend(
                        [
                            metadata.get("original_language"),
                            metadata.get("user_language"),
                            metadata.get("language"),
                        ]
                    )

            for candidate in candidates:
                normalized = self.normalize_language_code(candidate)
                if normalized is not None:
                    return normalized
        return None

    @staticmethod
    def is_short_ambiguous_follow_up(question: str) -> bool:
        """Return True for short follow-ups where language detection is ambiguous."""
        text = str(question or "").strip()
        if not text:
            return False
        if len(text) > 18:
            return False
        tokens = re.findall(r"[A-Za-zÀ-ÿ]+", text)
        if not tokens or len(tokens) > 3:
            return False
        return bool(re.fullmatch(r"[A-Za-zÀ-ÿ0-9\s\-_./]+", text))

    async def infer_language_hint_from_chat_history(
        self, chat_history: list[dict[str, str]]
    ) -> Optional[str]:
        """Infer a non-English language hint from recent user turns."""
        if not self.translation_service:
            return None
        detector = getattr(self.translation_service, "detector", None)
        detect_with_metadata = (
            getattr(detector, "detect_with_metadata", None) if detector else None
        )
        if not callable(detect_with_metadata):
            return None

        inspected = 0
        for raw_entry in reversed(chat_history[-8:]):
            role = str(raw_entry.get("role", "") or "").strip().lower()
            if role != "user":
                continue
            content = str(raw_entry.get("content", "") or "").strip()
            if len(content) < 6:
                continue

            inspected += 1
            if inspected > 3:
                break

            try:
                details = await detect_with_metadata(content)
            except Exception:
                logger.debug(
                    "Language hint detection failed for history turn",
                    exc_info=True,
                )
                continue

            language_code = (
                str(getattr(details, "language_code", "") or "").strip().lower()
            )
            confidence = float(getattr(details, "confidence", 0.0) or 0.0)
            if language_code and language_code != "en" and confidence >= 0.80:
                return language_code

        return None

    async def prepare_question(
        self,
        question: str,
        chat_history: list[dict[str, str]],
        language_hint: Optional[str],
    ) -> QueryLanguageState:
        """Translate a query to canonical English when translation is configured."""
        localized_question = question.strip()
        preprocessed_question = localized_question
        original_language = "en"
        was_translated = False

        if not self.translation_service:
            return QueryLanguageState(
                localized_question=localized_question,
                preprocessed_question=preprocessed_question,
                canonical_question_en=preprocessed_question,
                original_language=original_language,
                was_translated=was_translated,
            )

        try:
            prior_language = self.extract_prior_language_from_history(chat_history)
            source_lang_hint: str | None = None
            normalized_language_hint = str(language_hint or "").strip().lower()
            if normalized_language_hint and normalized_language_hint != "en":
                source_lang_hint = normalized_language_hint
            elif chat_history and self.is_short_ambiguous_follow_up(
                preprocessed_question
            ):
                source_lang_hint = await self.infer_language_hint_from_chat_history(
                    chat_history
                )

            translation_result = await self.translation_service.translate_query(
                preprocessed_question,
                source_lang=source_lang_hint,
                prior_language=prior_language,
            )
            original_language = translation_result.get("source_lang", "en")
            was_translated = not translation_result.get("skipped", True)
            detection_backend = (
                str(translation_result.get("detection_backend", "") or "")
                .strip()
                .lower()
            )
            if (
                original_language == "en"
                and not was_translated
                and detection_backend == "english_heuristic"
            ):
                history_lang_hint = normalized_language_hint or None
                if history_lang_hint in {"", "en"}:
                    history_lang_hint = None
                if history_lang_hint is None and chat_history:
                    history_lang_hint = (
                        await self.infer_language_hint_from_chat_history(chat_history)
                    )
                if history_lang_hint and history_lang_hint != "en":
                    original_language = history_lang_hint
                    logger.info(
                        "Overriding english_heuristic language with chat history hint: %s",
                        history_lang_hint,
                    )
            if was_translated:
                preprocessed_question = translation_result["translated_text"]
                logger.info(
                    "Translated query from %s to English",
                    original_language,
                )
        except Exception as exc:
            logger.warning("Translation failed, using original: %s", exc)

        return QueryLanguageState(
            localized_question=localized_question,
            preprocessed_question=preprocessed_question,
            canonical_question_en=preprocessed_question,
            original_language=original_language,
            was_translated=was_translated,
        )

    async def translate_text_for_user(
        self, text: str, target_language: str, *, label: str
    ) -> str:
        """Translate response text back to the user's language when possible."""
        if not self.translation_service or target_language == "en":
            return text
        try:
            result = await self.translation_service.translate_response(
                text,
                target_lang=target_language,
            )
            if not result.get("error"):
                logger.info("Translated %s to %s", label, target_language)
                return result["translated_text"]
        except Exception as exc:
            logger.warning("%s translation failed, using English: %s", label, exc)
        return text
