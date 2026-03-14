"""Shared ingress contract for locale resolution and live classification."""

from __future__ import annotations

import inspect
import re
from typing import Any, Literal

from app.channels.models import (
    ChannelType,
    ClassificationDecision,
    IncomingMessage,
    LocaleContext,
)
from app.channels.question_prefilter import QuestionPrefilter, QuestionPrefilterProtocol

_ACK_ONLY_TOKENS = {
    "ok",
    "okay",
    "thanks",
    "thank you",
    "thx",
    "ty",
    "danke",
    "merci",
    "gracias",
    "super",
    "great",
}

_HIGH_RISK_PATTERNS = (
    r"\bscam\b",
    r"\bfraud\b",
    r"\bseed phrase\b",
    r"\bprivate key\b",
    r"\bstolen\b",
    r"\bchargeback\b",
    r"\bdispute\b",
    r"\barbitrator\b",
    r"\bdid not receive\b",
    r"\bnicht erhalten\b",
    r"\bbetrug\b",
)

_ELEVATED_RISK_PATTERNS = (
    r"\bpayment sent\b",
    r"\bpayment received\b",
    r"\bescrow\b",
    r"\bsecurity deposit\b",
    r"\bsecurity\b",
    r"\bsicher\b",
    r"\bzahlung\b",
)

_EXPLICIT_INVOCATION_PATTERNS = (
    r"@bisq",
    r"@support",
    r"\bai\b",
    r"\bassistant\b",
    r"\bbot\b",
)


class ChannelIngressContextService:
    """Resolve locale and classification once for all channel ingress paths."""

    def __init__(
        self,
        *,
        language_detector: Any | None = None,
        translation_service: Any | None = None,
        question_prefilter: QuestionPrefilterProtocol | None = None,
        ambiguous_short_message_chars: int = 24,
        low_confidence_threshold: float = 0.80,
    ) -> None:
        self.translation_service = translation_service
        self.language_detector = language_detector or getattr(
            translation_service, "detector", None
        )
        self.question_prefilter = question_prefilter or QuestionPrefilter()
        self.ambiguous_short_message_chars = max(1, int(ambiguous_short_message_chars))
        self.low_confidence_threshold = max(
            0.0, min(1.0, float(low_confidence_threshold))
        )

    async def prepare_incoming(
        self,
        message: IncomingMessage,
        *,
        thread_language_hint: str | None = None,
    ) -> IncomingMessage:
        locale_context = await self._resolve_locale_context(
            message,
            thread_language_hint=thread_language_hint,
        )
        classification = self._classify(message)
        return message.model_copy(
            update={
                "locale_context": locale_context,
                "classification": classification,
            }
        )

    def _classify(self, message: IncomingMessage) -> ClassificationDecision:
        text = str(message.question or "").strip()
        normalized = text.lower()
        reasons: list[str] = []

        is_explicit_invocation = self._is_explicit_invocation(
            message.channel, normalized
        )
        is_substantive_message = self._is_substantive_message(normalized)
        topic_risk = self._topic_risk(normalized)

        if message.channel == ChannelType.WEB:
            should_process = True
            is_question_candidate = True
        else:
            prefilter = self.question_prefilter.evaluate_text(text)
            should_process = prefilter.should_process
            is_question_candidate = prefilter.should_process
            if prefilter.reason:
                reasons.append(prefilter.reason)

        if not is_substantive_message and not reasons:
            reasons.append("non_substantive_message")
        if is_explicit_invocation:
            reasons.append("explicit_invocation")
        if topic_risk != "low":
            reasons.append(f"topic_risk:{topic_risk}")

        return ClassificationDecision(
            should_process=should_process,
            is_question_candidate=is_question_candidate,
            is_explicit_invocation=is_explicit_invocation,
            is_substantive_message=is_substantive_message,
            topic_risk=topic_risk,
            reasons=reasons,
        )

    async def _resolve_locale_context(
        self,
        message: IncomingMessage,
        *,
        thread_language_hint: str | None,
    ) -> LocaleContext:
        if self.language_detector is None:
            return self._locale_context(language_code=thread_language_hint or "en")

        detection = await self._detect(message.question)
        language_code = (
            self._normalize_language_code(getattr(detection, "language_code", None))
            or "en"
        )
        confidence = float(getattr(detection, "confidence", 0.0) or 0.0)
        backend = str(getattr(detection, "backend", "unknown") or "unknown")
        source = "detected_message"
        inherited_from_history = False

        history_hint = await self._infer_history_language(message)
        ambiguous = self._is_ambiguous_follow_up(message.question)
        low_confidence = confidence < self.low_confidence_threshold

        if history_hint and (
            ambiguous or backend == "english_heuristic" or low_confidence
        ):
            language_code = history_hint
            source = "chat_history_hint"
            inherited_from_history = True
            confidence = max(confidence, 0.9)
        elif thread_language_hint and (
            ambiguous or backend == "english_heuristic" or low_confidence
        ):
            language_code = (
                self._normalize_language_code(thread_language_hint) or language_code
            )
            source = "thread_state_hint"
            inherited_from_history = True
            confidence = max(confidence, 0.9)

        return self._locale_context(
            language_code=language_code,
            confidence=confidence,
            source=source,
            inherited_from_history=inherited_from_history,
        )

    async def _infer_history_language(self, message: IncomingMessage) -> str | None:
        if not message.chat_history or self.language_detector is None:
            return None

        current_question = str(message.question or "").strip()
        skipped_current_turn = False

        for entry in reversed(message.chat_history):
            if getattr(entry, "role", None) != "user":
                continue
            text = str(getattr(entry, "content", "") or "").strip()
            if not text:
                continue
            if (
                not skipped_current_turn
                and current_question
                and text.casefold() == current_question.casefold()
            ):
                skipped_current_turn = True
                continue
            detection = await self._detect(text)
            code = self._normalize_language_code(
                getattr(detection, "language_code", None)
            )
            confidence = float(getattr(detection, "confidence", 0.0) or 0.0)
            if code and code != "en" and confidence >= self.low_confidence_threshold:
                return code
        return None

    async def _detect(self, text: str) -> Any:
        detect_with_metadata = getattr(
            self.language_detector, "detect_with_metadata", None
        )
        if callable(detect_with_metadata):
            result = detect_with_metadata(text)
            if inspect.isawaitable(result):
                return await result
            return result
        detect = getattr(self.language_detector, "detect", None)
        if callable(detect):
            result = detect(text)
            if inspect.isawaitable(result):
                result = await result
            language_code, confidence = result
            return type(
                "DetectionResult",
                (),
                {
                    "language_code": language_code,
                    "confidence": confidence,
                    "backend": "legacy_detect",
                },
            )()
        raise RuntimeError(
            "language detector must expose detect_with_metadata() or detect()"
        )

    @staticmethod
    def _normalize_language_code(value: str | None) -> str | None:
        code = str(value or "").strip().lower()
        if not code:
            return None
        if len(code) > 8:
            return None
        return code

    def _locale_context(
        self,
        *,
        language_code: str,
        confidence: float = 1.0,
        source: str = "unknown",
        inherited_from_history: bool = False,
    ) -> LocaleContext:
        normalized = self._normalize_language_code(language_code) or "en"
        return LocaleContext(
            language_code=normalized,
            confidence=max(0.0, min(1.0, float(confidence))),
            source=source,
            inherited_from_history=inherited_from_history,
            translation_target_language=normalized,
            fallback_policy="preserve_detected_language",
        )

    def _is_explicit_invocation(self, channel: ChannelType, normalized: str) -> bool:
        if channel == ChannelType.WEB:
            return True
        return any(
            re.search(pattern, normalized) for pattern in _EXPLICIT_INVOCATION_PATTERNS
        )

    @staticmethod
    def _is_substantive_message(normalized: str) -> bool:
        compact = re.sub(r"\s+", " ", normalized).strip()
        if not compact:
            return False
        if compact in _ACK_ONLY_TOKENS:
            return False
        return len(compact) >= 4

    def _topic_risk(self, normalized: str) -> Literal["low", "elevated", "high"]:
        if any(re.search(pattern, normalized) for pattern in _HIGH_RISK_PATTERNS):
            return "high"
        if any(re.search(pattern, normalized) for pattern in _ELEVATED_RISK_PATTERNS):
            return "elevated"
        return "low"

    def _is_ambiguous_follow_up(self, text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return True
        token_count = len([token for token in normalized.split() if token.strip()])
        return len(normalized) <= self.ambiguous_short_message_chars or token_count <= 3
