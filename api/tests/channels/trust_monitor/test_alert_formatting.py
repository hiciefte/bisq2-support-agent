"""Tests for the trust monitor Matrix alert formatter."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.channels.trust_monitor.alert_formatting import format_trust_alert_for_matrix


def _make_finding(**overrides):
    base = dict(
        id=42,
        detector_key="user_directory_impersonation",
        channel_id="matrix",
        space_id="proactive_scan",
        suspect_actor_id="@casaamigis:matrix.org",
        suspect_display_name="suddenwhipvapor",
        score=0.95,
        status="open",
        alert_surface="admin_ui",
        evidence_summary={
            "detection_method": "user_directory_search",
            "matched_staff_name": "suddenwhipvapor",
            "user_id": "@casaamigis:matrix.org",
            "display_name": "suddenwhipvapor",
            "suspect_avatar_url": "mxc://matrix.org/abc",
            "staff_avatar_url": "mxc://matrix.org/xyz",
        },
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        last_notified_at=None,
        notification_count=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_format_omits_mxc_avatar_urls() -> None:
    text = format_trust_alert_for_matrix(_make_finding())
    assert "mxc://" not in text
    assert "suspect_avatar_url" not in text


def test_format_uses_friendly_detector_label() -> None:
    text = format_trust_alert_for_matrix(_make_finding())
    assert "User directory impersonation" in text
    assert "user_directory_impersonation" not in text


def test_format_includes_suspect_and_collision_target() -> None:
    text = format_trust_alert_for_matrix(_make_finding())
    assert "@casaamigis:matrix.org" in text
    assert "Collides with staff" in text
    assert "suddenwhipvapor" in text


def test_format_shows_risk_label_for_high_score() -> None:
    text = format_trust_alert_for_matrix(_make_finding(score=0.95))
    assert "0.95" in text
    assert "immediate review" in text


def test_format_shows_other_signals_when_present() -> None:
    finding = _make_finding(
        evidence_summary={
            "detection_method": "user_directory_search",
            "heuristic_version": "v3",
            "early_read_hits": 12,
        }
    )
    text = format_trust_alert_for_matrix(finding)
    assert "Other signals:" in text
    assert "Heuristic version" in text
    assert "Early read hits" in text


def test_format_skips_other_signals_section_when_empty() -> None:
    finding = _make_finding(
        evidence_summary={
            "matched_staff_name": "alice",
            "detection_method": "user_directory_search",
            "user_id": "@x:matrix.org",
            "display_name": "alice",
            "suspect_avatar_url": "mxc://matrix.org/x",
            "staff_avatar_url": "mxc://matrix.org/y",
        }
    )
    text = format_trust_alert_for_matrix(finding)
    assert "Other signals:" not in text


def test_format_handles_missing_display_name() -> None:
    finding = _make_finding(suspect_display_name="")
    text = format_trust_alert_for_matrix(finding)
    assert "(no display name)" in text


def test_format_friendly_detection_method_label() -> None:
    finding = _make_finding(
        evidence_summary={
            "detection_method": "user_directory_search",
            "matched_staff_name": "alice",
        }
    )
    text = format_trust_alert_for_matrix(finding)
    assert "User directory search" in text
    assert "user_directory_search" not in text


def test_format_starts_with_bold_alert_header() -> None:
    text = format_trust_alert_for_matrix(_make_finding())
    first_line = text.splitlines()[0]
    assert first_line.startswith("**") and first_line.endswith("**")
    assert "Trust monitor alert" in first_line


def test_format_strips_newlines_from_display_name() -> None:
    finding = _make_finding(suspect_display_name="alice\nbob")
    text = format_trust_alert_for_matrix(finding)
    assert "**Suspect:** alice bob" in text or "**Suspect:** alice  bob" in text


def test_format_neutralizes_room_mention_in_display_name() -> None:
    finding = _make_finding(suspect_display_name="@room everyone")
    text = format_trust_alert_for_matrix(finding)
    assert "@room" not in text


def test_format_neutralizes_room_mention_in_evidence_value() -> None:
    finding = _make_finding(
        evidence_summary={
            "matched_staff_name": "@room please",
            "detection_method": "user_directory_search",
        }
    )
    text = format_trust_alert_for_matrix(finding)
    assert "@room" not in text


def test_format_strips_newlines_from_extra_signal_value() -> None:
    finding = _make_finding(
        evidence_summary={
            "detection_method": "user_directory_search",
            "matched_staff_name": "alice",
            "notes": "line one\nline two",
        }
    )
    text = format_trust_alert_for_matrix(finding)
    notes_lines = [line for line in text.splitlines() if "Notes" in line]
    assert notes_lines, "Notes line missing from output"
    for line in notes_lines:
        assert "line one" in line and "line two" in line
