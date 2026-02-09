"""PII filtering middleware hook.

Implements PII detection and redaction in responses.
"""

import logging
from typing import Optional

from app.channels.hooks import BasePostProcessingHook, HookPriority
from app.channels.models import GatewayError, IncomingMessage, OutgoingMessage
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
        # Detect PII in response
        findings = self._detector.detect(outgoing.answer)

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

        self._logger.info(
            f"PII redacted from response for message {incoming.message_id}"
        )

        return None
