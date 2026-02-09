"""PII filtering middleware hook.

Implements PII detection and redaction in responses.
"""

import logging
from typing import Optional

from app.channels.hooks import BasePostProcessingHook, HookPriority
from app.channels.models import (
    DocumentReference,
    GatewayError,
    IncomingMessage,
    OutgoingMessage,
)
from app.channels.security import ErrorFactory, PIIDetector

logger = logging.getLogger(__name__)


class PIIFilterHook(BasePostProcessingHook):
    """Post-processing hook for PII filtering.

    Detects and redacts personally identifiable information from responses.

    Args:
        mode: 'redact' to replace PII, 'block' to return error.
        replacement: Text to replace PII with (default: "[REDACTED]").
    """

    _VALID_MODES = {"redact", "block"}

    def __init__(
        self,
        mode: str = "redact",
        replacement: str = "[REDACTED]",
    ):
        """Initialize PII filter hook.

        Args:
            mode: Operating mode - 'redact' or 'block'.
            replacement: Replacement text for redacted PII.
        """
        if mode not in self._VALID_MODES:
            raise ValueError(
                f"Invalid PII filter mode '{mode}'. Must be one of {self._VALID_MODES}"
            )
        super().__init__(name="pii_filter", priority=HookPriority.HIGH)
        self.mode = mode
        self.replacement = replacement
        self._detector = PIIDetector()

    async def execute(
        self, incoming: IncomingMessage, outgoing: OutgoingMessage
    ) -> Optional[GatewayError]:
        """Filter PII from outgoing response.

        Args:
            incoming: Original incoming message.
            outgoing: Response message to filter.

        Returns:
            None if clean/redacted, GatewayError if blocked.
        """
        # Detect PII in response text and source metadata.
        findings = self._detector.detect(outgoing.answer)
        source_fields_with_pii: list[tuple[DocumentReference, str, str]] = []

        for source in outgoing.sources:
            for field_name in ("document_id", "title", "url", "category"):
                raw_value = getattr(source, field_name)
                if not isinstance(raw_value, str) or not raw_value:
                    continue
                field_findings = self._detector.detect(raw_value)
                if field_findings:
                    findings.extend(field_findings)
                    source_fields_with_pii.append((source, field_name, raw_value))

        if not findings:
            return None

        pii_types = list(set(pii_type.value for pii_type, _ in findings))

        self._logger.warning(
            f"PII detected in response for message {incoming.message_id}: {pii_types}"
        )

        if self.mode == "block":
            return ErrorFactory.pii_detected(pii_types)

        # Redact mode: replace PII with replacement text
        outgoing.answer = self._detector.redact(outgoing.answer, self.replacement)
        for source, field_name, raw_value in source_fields_with_pii:
            setattr(
                source, field_name, self._detector.redact(raw_value, self.replacement)
            )

        self._logger.info(
            f"PII redacted from response for message {incoming.message_id}"
        )

        return None
