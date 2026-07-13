from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from app.channels.trust_monitor.models import (
    TrustAlertSurface,
    TrustFinding,
    TrustFindingStatus,
)
from app.channels.trust_monitor.publisher import CompositeTrustAlertPublisher


def _finding(surface: TrustAlertSurface = TrustAlertSurface.STAFF_ROOM) -> TrustFinding:
    now = datetime.now(UTC)
    return TrustFinding(
        id=1,
        detector_key="staff_name_collision",
        channel_id="matrix",
        space_id="!support:matrix.org",
        suspect_actor_key="actor-key",
        suspect_actor_id="@suspect:matrix.org",
        suspect_display_name="Support",
        score=0.95,
        status=TrustFindingStatus.OPEN,
        alert_surface=surface,
        evidence_summary={},
        created_at=now,
        updated_at=now,
        last_notified_at=None,
        notification_count=0,
    )


@pytest.mark.asyncio
async def test_bound_publisher_schedules_staff_alert_from_worker_thread() -> None:
    delivered = asyncio.Event()

    async def notify(_finding: TrustFinding) -> None:
        delivered.set()

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)
    publisher.bind_loop(asyncio.get_running_loop())

    scheduled = await asyncio.to_thread(publisher.publish, _finding())

    assert scheduled is True
    await asyncio.wait_for(delivered.wait(), timeout=1)


@pytest.mark.asyncio
async def test_bound_publisher_uses_owner_loop_when_publishing_on_loop() -> None:
    delivered = asyncio.Event()

    async def notify(_finding: TrustFinding) -> None:
        delivered.set()

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)
    publisher.bind_loop(asyncio.get_running_loop())

    assert publisher.publish(_finding()) is True
    await asyncio.wait_for(delivered.wait(), timeout=1)


def test_staff_alert_reports_unscheduled_without_bound_running_loop() -> None:
    async def notify(_finding: TrustFinding) -> None:
        return None

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)

    assert publisher.publish(_finding()) is False


def test_admin_surface_is_delivered_by_the_durable_finding_store() -> None:
    publisher = CompositeTrustAlertPublisher(admin_publisher=None)

    assert publisher.publish(_finding(TrustAlertSurface.ADMIN_UI)) is True
