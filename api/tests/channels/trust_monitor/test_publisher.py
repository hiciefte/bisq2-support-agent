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
    started = asyncio.Event()
    release = asyncio.Event()

    async def notify(_finding: TrustFinding) -> bool:
        started.set()
        await release.wait()
        return True

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)
    publisher.bind_loop(asyncio.get_running_loop())

    publish_task = asyncio.create_task(asyncio.to_thread(publisher.publish, _finding()))
    await asyncio.wait_for(started.wait(), timeout=1)

    assert publish_task.done() is False
    release.set()
    assert await asyncio.wait_for(publish_task, timeout=1) is True


@pytest.mark.asyncio
async def test_bound_publisher_rejects_blocking_publish_on_owner_loop() -> None:
    delivered = False

    async def notify(_finding: TrustFinding) -> bool:
        nonlocal delivered
        delivered = True
        return True

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)
    publisher.bind_loop(asyncio.get_running_loop())

    assert publisher.publish(_finding()) is False
    await asyncio.sleep(0)
    assert delivered is False


@pytest.mark.asyncio
async def test_staff_alert_reports_false_when_delivery_returns_false() -> None:
    async def notify(_finding: TrustFinding) -> bool:
        return False

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)
    publisher.bind_loop(asyncio.get_running_loop())

    delivered = await asyncio.to_thread(publisher.publish, _finding())

    assert delivered is False


@pytest.mark.asyncio
async def test_staff_alert_times_out_without_marking_delivery_success() -> None:
    release = asyncio.Event()
    finished = asyncio.Event()

    async def notify(_finding: TrustFinding) -> bool:
        try:
            await release.wait()
            return True
        finally:
            finished.set()

    publisher = CompositeTrustAlertPublisher(
        matrix_notifier=notify,
        delivery_timeout_seconds=0.01,
    )
    publisher.bind_loop(asyncio.get_running_loop())

    delivered = await asyncio.to_thread(publisher.publish, _finding())

    assert delivered is False
    release.set()
    await asyncio.wait_for(finished.wait(), timeout=1)


def test_staff_alert_reports_unscheduled_without_bound_running_loop() -> None:
    async def notify(_finding: TrustFinding) -> bool:
        return True

    publisher = CompositeTrustAlertPublisher(matrix_notifier=notify)

    assert publisher.publish(_finding()) is False


def test_admin_surface_is_delivered_by_the_durable_finding_store() -> None:
    publisher = CompositeTrustAlertPublisher(admin_publisher=None)

    assert publisher.publish(_finding(TrustAlertSurface.ADMIN_UI)) is True
