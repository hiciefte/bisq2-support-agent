"""Human-readable routing reason generator.

Produces concise explanations for why a query was routed to auto_send,
queue_medium, or needs_human. Rule-based, no LLM calls.
"""

from typing import Optional


class RoutingReasonGenerator:
    """Generates human-readable routing reason strings."""

    def generate(
        self,
        confidence: float,
        action: str,
        num_sources: int,
        detected_version: Optional[str] = None,
        version_confidence: Optional[float] = None,
    ) -> str:
        """Generate a routing reason from confidence, action, and source data.

        Returns a human-readable string (max 500 chars).
        """
        pct = round(confidence * 100)
        source_text = self._source_text(num_sources)
        version_text = self._version_text(detected_version, version_confidence)

        if action == "auto_send":
            level = self._confidence_level(confidence)
            reason = (
                f"{level} confidence ({pct}%) \u2014 " f"{source_text}{version_text}"
            )
        elif action == "queue_medium":
            reason = (
                f"Moderate confidence ({pct}%) \u2014 "
                f"{source_text}, review recommended{version_text}"
            )
        elif action == "needs_human":
            if num_sources == 0:
                reason = (
                    f"Low confidence ({pct}%) \u2014 "
                    f"no matching sources found{version_text}"
                )
            else:
                reason = (
                    f"Low confidence ({pct}%) \u2014 "
                    f"{source_text}, insufficient for auto-response"
                    f"{version_text}"
                )
        else:
            reason = (
                f"Confidence {pct}% \u2014 "
                f"{source_text}, action: {action}{version_text}"
            )

        return reason[:500]

    @staticmethod
    def _confidence_level(confidence: float) -> str:
        if confidence >= 0.95:
            return "High confidence"
        if confidence >= 0.85:
            return "High confidence"
        if confidence >= 0.70:
            return "Good confidence"
        return "Moderate confidence"

    @staticmethod
    def _source_text(num_sources: int) -> str:
        if num_sources == 0:
            return "no sources found"
        if num_sources == 1:
            return "1 source found"
        return f"{num_sources} sources found"

    @staticmethod
    def _version_text(
        detected_version: Optional[str],
        version_confidence: Optional[float],
    ) -> str:
        if not detected_version:
            return ""
        if version_confidence and version_confidence >= 0.7:
            return f", matched {detected_version} context"
        return f", detected {detected_version}"
