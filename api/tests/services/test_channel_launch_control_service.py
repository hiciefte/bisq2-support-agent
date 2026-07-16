"""Tests for persistent shadow, kill-switch, and canary controls."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from app.services.channel_launch_control_service import (
    ChannelLaunchControlService,
)


def _service(tmp_path, *, enabled: bool = False) -> ChannelLaunchControlService:
    return ChannelLaunchControlService(
        str(tmp_path / "feedback.db"),
        environment_enabled=enabled,
    )


def test_defaults_keep_autonomous_channels_stopped(tmp_path) -> None:
    service = _service(tmp_path)

    assert service.get_global_control().autonomous_delivery_enabled is False
    assert service.get_channel_policy("matrix").shadow_mode is True
    assert service.get_channel_policy("bisq2").shadow_mode is True
    assert service.supported_channels == ("bisq2", "matrix")
    assert all(
        policy.canary_hourly_limit == 0
        and policy.canary_daily_limit == 0
        and policy.canary_enabled is False
        for policy in service.list_channel_policies()
    )


def test_fresh_state_stays_disabled_when_environment_permits_enable(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)

    assert service.get_global_control().autonomous_delivery_enabled is False
    assert all(
        policy.shadow_mode is True
        and policy.canary_enabled is False
        and policy.canary_hourly_limit == 0
        and policy.canary_daily_limit == 0
        for policy in service.list_channel_policies()
    )


def test_admin_kill_switch_changes_next_authorization(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy("matrix", shadow_mode=False)

    allowed = service.authorize_autonomous_delivery("matrix", "event-1")
    service.set_autonomous_delivery_enabled(False)
    blocked = service.authorize_autonomous_delivery("matrix", "event-2")

    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.reason == "kill_switch"


def test_environment_state_is_reapplied_on_restart(tmp_path) -> None:
    db_path = str(tmp_path / "feedback.db")
    first = ChannelLaunchControlService(db_path, environment_enabled=True)
    first.set_autonomous_delivery_enabled(True)

    restarted = ChannelLaunchControlService(db_path, environment_enabled=False)

    assert restarted.get_global_control().autonomous_delivery_enabled is False


def test_admin_stop_survives_restart_when_environment_allows_delivery(tmp_path) -> None:
    db_path = str(tmp_path / "feedback.db")
    first = ChannelLaunchControlService(db_path, environment_enabled=True)
    first.set_autonomous_delivery_enabled(False)

    restarted = ChannelLaunchControlService(db_path, environment_enabled=True)

    assert restarted.get_global_control().autonomous_delivery_enabled is False


def test_environment_guard_blocks_admin_enable(tmp_path) -> None:
    service = _service(tmp_path, enabled=False)

    with pytest.raises(ValueError, match="must permit delivery"):
        service.set_autonomous_delivery_enabled(True)

    assert service.get_global_control().autonomous_delivery_enabled is False


def test_shadow_mode_blocks_without_consuming_canary_quota(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "matrix",
        shadow_mode=True,
        canary_enabled=True,
        canary_hourly_limit=1,
        canary_daily_limit=1,
    )

    decision = service.authorize_autonomous_delivery("matrix", "event-1")

    assert decision.allowed is False
    assert decision.reason == "shadow_mode"
    assert service.reservation_count("matrix") == 0


def test_canary_enforces_rolling_hour_and_day_limits(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "matrix",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=2,
        canary_daily_limit=3,
    )
    start = datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc)

    assert service.authorize_autonomous_delivery("matrix", "event-1", now=start).allowed
    assert service.authorize_autonomous_delivery("matrix", "event-2", now=start).allowed
    hourly = service.authorize_autonomous_delivery("matrix", "event-3", now=start)
    assert hourly.allowed is False
    assert hourly.reason == "canary_hourly_limit"

    after_hour = start + timedelta(hours=1, seconds=1)
    assert service.authorize_autonomous_delivery(
        "matrix", "event-3", now=after_hour
    ).allowed
    daily = service.authorize_autonomous_delivery("matrix", "event-4", now=after_hour)
    assert daily.allowed is False
    assert daily.reason == "canary_daily_limit"

    after_day = start + timedelta(days=1, seconds=1)
    assert service.authorize_autonomous_delivery(
        "matrix", "event-4", now=after_day
    ).allowed


def test_canary_blocks_unreserved_secondary_delivery_without_reserving(
    tmp_path,
) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "matrix",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=1,
        canary_daily_limit=1,
    )

    assert service.secondary_delivery_block_reason("matrix") == (
        "canary_requires_reservation"
    )
    assert service.reservation_count("matrix") == 0

    primary = service.authorize_autonomous_delivery("matrix", "event-1")
    assert primary.allowed is True
    assert service.reservation_count("matrix") == 1


def test_fully_enabled_mode_allows_unreserved_secondary_delivery(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "bisq2",
        shadow_mode=False,
        canary_enabled=False,
    )

    assert service.secondary_delivery_block_reason("bisq2") is None


def test_canary_rejects_duplicate_message_reservations(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "bisq2",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=2,
        canary_daily_limit=2,
    )

    first = service.authorize_autonomous_delivery("bisq2", "event-1")
    duplicate = service.authorize_autonomous_delivery("bisq2", "event-1")

    assert first.allowed is True
    assert duplicate.allowed is False
    assert duplicate.reason == "duplicate_reservation"
    assert service.reservation_count("bisq2") == 1

    conn = sqlite3.connect(service.db_path)
    try:
        stored_key = conn.execute(
            "SELECT message_key FROM channel_delivery_reservations"
        ).fetchone()[0]
    finally:
        conn.close()
    assert stored_key != "event-1"
    assert len(stored_key) == 64


def test_concurrent_canary_reservations_cannot_exceed_cap(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "matrix",
        shadow_mode=False,
        canary_enabled=True,
        canary_hourly_limit=3,
        canary_daily_limit=3,
    )
    services = [
        ChannelLaunchControlService(service.db_path, environment_enabled=True)
        for _ in range(10)
    ]

    with ThreadPoolExecutor(max_workers=10) as executor:
        decisions = list(
            executor.map(
                lambda number: services[number].authorize_autonomous_delivery(
                    "matrix", f"event-{number}"
                ),
                range(10),
            )
        )

    assert sum(decision.allowed for decision in decisions) == 3
    assert service.reservation_count("matrix") == 3


def test_reservation_cleanup_has_reserved_at_index(tmp_path) -> None:
    service = _service(tmp_path)

    conn = sqlite3.connect(service.db_path)
    try:
        columns = conn.execute(
            "PRAGMA index_info(idx_channel_delivery_reservations_reserved_at)"
        ).fetchall()
    finally:
        conn.close()

    assert [column[2] for column in columns] == ["reserved_at"]


def test_readiness_validates_persisted_controls(tmp_path) -> None:
    service = _service(tmp_path)

    assert service.check_readiness() is True

    conn = sqlite3.connect(service.db_path)
    try:
        conn.execute(
            "UPDATE channel_launch_policy "
            "SET shadow_mode = 2 WHERE channel_id = 'matrix'"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="Persisted channel launch field"):
        service.check_readiness()


def test_corrupt_global_control_fails_closed(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)

    conn = sqlite3.connect(service.db_path)
    try:
        conn.execute(
            "UPDATE channel_launch_global "
            "SET autonomous_delivery_enabled = 2 WHERE singleton_id = 1"
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="Persisted channel launch field"):
        service.authorize_autonomous_delivery("matrix", "event-1")


@pytest.mark.parametrize(
    ("shadow_mode", "canary_enabled", "hourly_limit", "daily_limit"),
    [
        (2, 0, 0, 0),
        (0, 2, 0, 0),
        (0, 1, -1, 1),
        (0, 1, 10_001, 10_001),
        (0, 1, 1, 100_001),
        (0, 1, 2, 1),
    ],
)
def test_corrupt_channel_policy_fails_closed(
    tmp_path,
    shadow_mode: int,
    canary_enabled: int,
    hourly_limit: int,
    daily_limit: int,
) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)

    conn = sqlite3.connect(service.db_path)
    try:
        conn.execute(
            """
            UPDATE channel_launch_policy
            SET shadow_mode = ?, canary_enabled = ?,
                canary_hourly_limit = ?, canary_daily_limit = ?
            WHERE channel_id = 'matrix'
            """,
            (shadow_mode, canary_enabled, hourly_limit, daily_limit),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="Persisted channel launch"):
        service.authorize_autonomous_delivery("matrix", "event-1")


def test_canary_limits_must_be_ordered(tmp_path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="must not exceed"):
        service.set_channel_policy(
            "matrix",
            canary_hourly_limit=2,
            canary_daily_limit=1,
        )


def test_zero_limit_canary_routes_everything_to_review(tmp_path) -> None:
    service = _service(tmp_path, enabled=True)
    service.set_autonomous_delivery_enabled(True)
    service.set_channel_policy(
        "matrix",
        shadow_mode=False,
        canary_enabled=True,
    )

    decision = service.authorize_autonomous_delivery("matrix", "event-1")

    assert decision.allowed is False
    assert decision.reason == "canary_hourly_limit"
