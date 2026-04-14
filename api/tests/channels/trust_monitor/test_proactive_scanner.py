"""Regression tests for ProactiveImpersonationScanner side-effects.

The scanner must never post messages into the public observed rooms —
they are read-only. Staff-room delivery is handled exclusively by the
`CompositeTrustAlertPublisher.matrix_notifier` path, which honors the
operator policy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.channels.trust_monitor.detectors.base import DetectorResult
from app.channels.trust_monitor.models import TrustAlertSurface
from app.channels.trust_monitor.proactive_scanner import (
    ProactiveImpersonationScanner,
)


def _make_result() -> DetectorResult:
    return DetectorResult(
        detector_key="proactive_user_impersonation",
        suspect_actor_id="@bad:matrix.org",
        suspect_actor_key="@bad:matrix.org",
        suspect_display_name="suddenwhipvapor",
        score=0.95,
        evidence_summary={"matched_staff_name": "suddenwhipvapor"},
        alert_surface=TrustAlertSurface.BOTH,
        occurred_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_scanner_never_posts_into_monitored_public_rooms() -> None:
    matrix_client = SimpleNamespace(
        room_send=AsyncMock(),
        access_token="syt_test",
    )
    scanner = ProactiveImpersonationScanner(
        homeserver_url="https://matrix.org",
        access_token="syt_test",
        staff_resolver=SimpleNamespace(get_display_names=lambda: set()),
        trusted_staff_ids=set(),
        monitored_room_ids={"!kAbNUeIFukYxWXxyFY:bitcoin.kyoto"},
        matrix_client=matrix_client,
        on_finding=lambda _finding: None,
    )
    scanner._scan_user_directory = AsyncMock(return_value=[_make_result()])  # type: ignore[method-assign]
    scanner._scan_public_rooms = AsyncMock(return_value=[])  # type: ignore[method-assign]

    await scanner._run_scans()

    matrix_client.room_send.assert_not_called()


@pytest.mark.asyncio
async def test_scanner_forwards_findings_via_on_finding_callback() -> None:
    captured: list[DetectorResult] = []
    scanner = ProactiveImpersonationScanner(
        homeserver_url="https://matrix.org",
        access_token="syt_test",
        staff_resolver=SimpleNamespace(get_display_names=lambda: set()),
        trusted_staff_ids=set(),
        monitored_room_ids={"!room:matrix.org"},
        matrix_client=SimpleNamespace(room_send=AsyncMock()),
        on_finding=captured.append,
    )
    result = _make_result()
    scanner._scan_user_directory = AsyncMock(return_value=[result])  # type: ignore[method-assign]
    scanner._scan_public_rooms = AsyncMock(return_value=[])  # type: ignore[method-assign]

    await scanner._run_scans()

    assert captured == [result]
