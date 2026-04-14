"""Human-readable formatting for trust monitor Matrix staff-room alerts.

Strips mxc:// URLs (clients can't render them inline) and produces
markdown bold/bullets that render natively in Element/Cinny/etc.
"""

from __future__ import annotations

from typing import Any

from app.channels.trust_monitor.models import TrustFinding

_DETECTOR_LABELS = {
    "staff_name_collision": "Staff name collision",
    "silent_early_observer": "Silent early observer",
    "user_directory_impersonation": "User directory impersonation",
}

_DETECTION_METHOD_LABELS = {
    "user_directory_search": "User directory search",
    "public_room_scan": "Public room scan",
    "message_event": "In-room message",
}

_HIDDEN_EVIDENCE_KEYS = {
    "suspect_avatar_url",
    "staff_avatar_url",
    "user_id",  # already shown via suspect_actor_id
    "display_name",  # already shown via suspect_display_name
    "detection_method",  # rendered as a labelled section
    "matched_staff_name",  # rendered as a labelled section
    "staff_display_name",
    "suspect_actor_id",
}


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _detector_label(detector_key: str) -> str:
    return _DETECTOR_LABELS.get(detector_key, _humanize_key(detector_key))


def _detection_method_label(value: str | None) -> str | None:
    if not value:
        return None
    return _DETECTION_METHOD_LABELS.get(value, _humanize_key(value))


def _risk_label(score: float) -> str:
    if score >= 0.9:
        return "immediate review"
    if score >= 0.75:
        return "high confidence"
    return "monitor closely"


def format_trust_alert_for_matrix(finding: TrustFinding) -> str:
    """Render a Matrix-friendly alert for the staff room.

    Output is markdown-light (Matrix clients render `**bold**` and bullets).
    """
    evidence = finding.evidence_summary or {}
    detector_label = _detector_label(finding.detector_key)
    risk_label = _risk_label(float(finding.score))
    matched_staff = (
        evidence.get("matched_staff_name") or evidence.get("staff_display_name") or None
    )
    detection_method = _detection_method_label(evidence.get("detection_method"))

    display_name = finding.suspect_display_name or "(no display name)"

    lines: list[str] = []
    lines.append(f"**🚨 Trust monitor alert — {detector_label}**")
    lines.append("")
    lines.append(f"**Suspect:** {display_name}")
    lines.append(f"`{finding.suspect_actor_id}`")
    if matched_staff:
        lines.append(f"**Collides with staff:** {matched_staff}")
    lines.append("")
    lines.append(f"**Risk score:** {finding.score:.2f} ({risk_label})")
    if detection_method:
        lines.append(f"**Detection method:** {detection_method}")
    lines.append(f"**Channel:** {finding.channel_id}")

    extra_signals = [
        (key, value)
        for key, value in evidence.items()
        if key not in _HIDDEN_EVIDENCE_KEYS
    ]
    if extra_signals:
        lines.append("")
        lines.append("**Other signals:**")
        for key, value in extra_signals:
            lines.append(f"- {_humanize_key(key)}: {_stringify(value)}")

    lines.append("")
    lines.append("Open in Admin UI to view avatars, take action, or mark as benign.")
    return "\n".join(lines)
