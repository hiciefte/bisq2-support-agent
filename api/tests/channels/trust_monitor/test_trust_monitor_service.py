from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.channels.staff import StaffResolver
from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.models import (
    TrustAlertSurface,
    TrustEventType,
    TrustFindingStatus,
)
from app.channels.trust_monitor.publisher import InMemoryTrustAlertPublisher
from app.channels.trust_monitor.service import TrustMonitorService
from app.services.trust_monitor_policy_service import TrustMonitorPolicyService


def _settings(**overrides):
    values = {
        "TRUST_MONITOR_ENABLED": True,
        "TRUST_MONITOR_NAME_COLLISION_ENABLED": True,
        "TRUST_MONITOR_SILENT_OBSERVER_ENABLED": True,
        "TRUST_MONITOR_ALERT_SURFACE": "admin_ui",
        "TRUST_MONITOR_MATRIX_PUBLIC_ROOMS": ["!support:matrix.org"],
        "TRUST_MONITOR_MATRIX_STAFF_ROOM": "!staff:matrix.org",
        "TRUST_MONITOR_SILENT_OBSERVER_WINDOW_DAYS": 14,
        "TRUST_MONITOR_EARLY_READ_WINDOW_SECONDS": 30,
        "TRUST_MONITOR_MINIMUM_OBSERVATIONS": 3,
        "TRUST_MONITOR_MINIMUM_EARLY_READ_HITS": 2,
        "TRUST_MONITOR_READ_TO_REPLY_RATIO_THRESHOLD": 3.0,
        "TRUST_MONITOR_EVIDENCE_TTL_DAYS": 7,
        "TRUST_MONITOR_AGGREGATE_TTL_DAYS": 30,
        "TRUST_MONITOR_FINDING_TTL_DAYS": 30,
        "TRUST_MONITOR_ACTOR_KEY_SECRET": "secret-key",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _policy_service(tmp_path, settings: SimpleNamespace) -> TrustMonitorPolicyService:
    return TrustMonitorPolicyService(
        db_path=str(tmp_path / "feedback.db"),
        settings=settings,
    )


def _service(
    tmp_path, settings: SimpleNamespace | None = None
) -> tuple[TrustMonitorService, InMemoryTrustAlertPublisher]:
    settings = settings or _settings()
    publisher = InMemoryTrustAlertPublisher()
    policy_service = _policy_service(tmp_path, settings)
    service = TrustMonitorService(
        db_path=str(tmp_path / "feedback.db"),
        settings=settings,
        policy_service=policy_service,
        publisher=publisher,
        staff_resolver=StaffResolver(
            trusted_staff_ids=["@alice:matrix.org"],
            display_names=["Alice Support", "Core Team"],
        ),
    )
    return service, publisher


def test_actor_key_generation_is_stable(tmp_path) -> None:
    service, _ = _service(tmp_path)

    left = service.actor_key("matrix", "@user:matrix.org")
    right = service.actor_key("matrix", "@user:matrix.org")
    other = service.actor_key("matrix", "@other:matrix.org")

    assert left == right
    assert left != other


def test_name_collision_creates_finding_and_publishes_to_admin_ui(tmp_path) -> None:
    service, publisher = _service(tmp_path)

    finding = service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@scammer:matrix.org",
            actor_display_name=" Alice  Support ",
            event_type=TrustEventType.MEMBER_JOINED,
            occurred_at=datetime.now(UTC),
            external_event_id="$member-1",
        )
    )

    assert finding is not None
    assert finding.detector_key == "staff_name_collision"
    assert finding.status == TrustFindingStatus.OPEN
    assert publisher.published_findings[-1].id == finding.id

    stored = service.list_findings()
    assert len(stored.items) == 1
    assert stored.items[0].suspect_display_name == "Alice  Support"


def test_duplicate_name_collision_refreshes_finding_without_republishing(
    tmp_path,
) -> None:
    service, publisher = _service(tmp_path)
    event_time = datetime.now(UTC)

    first = service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@copycat:matrix.org",
            actor_display_name="Alice Support",
            event_type=TrustEventType.MEMBER_JOINED,
            occurred_at=event_time,
            external_event_id="$dup-1",
        )
    )
    second = service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@copycat:matrix.org",
            actor_display_name="Alice Support",
            event_type=TrustEventType.IDENTITY_CHANGED,
            occurred_at=event_time + timedelta(minutes=5),
            external_event_id="$dup-2",
        )
    )

    assert first is not None and second is not None
    assert first.id == second.id
    assert len(publisher.published_findings) == 1


def test_trusted_staff_name_does_not_trigger_collision(tmp_path) -> None:
    service, publisher = _service(tmp_path)

    finding = service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@alice:matrix.org",
            actor_display_name="Alice Support",
            event_type=TrustEventType.IDENTITY_CHANGED,
            occurred_at=datetime.now(UTC),
            external_event_id="$member-2",
        )
    )

    assert finding is None
    assert publisher.published_findings == []
    assert service.list_findings().items == []


def test_silent_observer_creates_shadow_finding_after_threshold(tmp_path) -> None:
    service, publisher = _service(tmp_path)
    now = datetime.now(UTC)

    for index in range(3):
        message_id = f"$message-{index}"
        service.ingest_event(
            TrustEvent(
                channel_id="matrix",
                space_id="!support:matrix.org",
                actor_id=f"@asker{index}:matrix.org",
                actor_display_name=f"Asker {index}",
                event_type=TrustEventType.MESSAGE_SENT,
                occurred_at=now + timedelta(minutes=index),
                external_event_id=message_id,
                target_message_id=message_id,
            )
        )
        service.ingest_event(
            TrustEvent(
                channel_id="matrix",
                space_id="!support:matrix.org",
                actor_id="@lurker:matrix.org",
                actor_display_name="Quiet Reader",
                event_type=TrustEventType.MESSAGE_READ,
                occurred_at=now + timedelta(minutes=index, seconds=10),
                external_event_id=f"$receipt-{index}",
                target_message_id=message_id,
            )
        )

    findings = service.list_findings(detector_key="silent_early_observer")
    assert len(findings.items) == 1
    assert findings.items[0].detector_key == "silent_early_observer"
    assert findings.items[0].alert_surface == TrustAlertSurface.ADMIN_UI
    assert publisher.published_findings[-1].detector_key == "silent_early_observer"


def test_silent_observer_is_suppressed_by_replies(tmp_path) -> None:
    service, _ = _service(tmp_path)
    now = datetime.now(UTC)

    for index in range(3):
        message_id = f"$message-{index}"
        service.ingest_event(
            TrustEvent(
                channel_id="matrix",
                space_id="!support:matrix.org",
                actor_id=f"@asker{index}:matrix.org",
                actor_display_name=f"Asker {index}",
                event_type=TrustEventType.MESSAGE_SENT,
                occurred_at=now + timedelta(minutes=index),
                external_event_id=message_id,
                target_message_id=message_id,
            )
        )
        service.ingest_event(
            TrustEvent(
                channel_id="matrix",
                space_id="!support:matrix.org",
                actor_id="@helper:matrix.org",
                actor_display_name="Helpful Human",
                event_type=TrustEventType.MESSAGE_READ,
                occurred_at=now + timedelta(minutes=index, seconds=10),
                external_event_id=f"$receipt-{index}",
                target_message_id=message_id,
            )
        )
        service.ingest_event(
            TrustEvent(
                channel_id="matrix",
                space_id="!support:matrix.org",
                actor_id="@helper:matrix.org",
                actor_display_name="Helpful Human",
                event_type=TrustEventType.MESSAGE_REPLIED,
                occurred_at=now + timedelta(minutes=index, seconds=20),
                external_event_id=f"$reply-{index}",
                target_message_id=message_id,
            )
        )

    assert service.list_findings(detector_key="silent_early_observer").items == []


def test_feedback_actions_update_finding_status_and_suppression(tmp_path) -> None:
    service, _ = _service(tmp_path)
    finding = service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@scammer:matrix.org",
            actor_display_name="Core Team",
            event_type=TrustEventType.MEMBER_JOINED,
            occurred_at=datetime.now(UTC),
            external_event_id="$member-3",
        )
    )
    assert finding is not None

    suppressed = service.apply_feedback(
        finding.id, action="false_positive", actor_id="admin"
    )
    assert suppressed.status == TrustFindingStatus.FALSE_POSITIVE

    audit_rows = service.list_access_audit(limit=10)
    assert any(
        entry.action == "finding_feedback:false_positive" for entry in audit_rows
    )


def test_retention_purges_expired_evidence_and_findings(tmp_path) -> None:
    settings = _settings(
        TRUST_MONITOR_EVIDENCE_TTL_DAYS=1,
        TRUST_MONITOR_FINDING_TTL_DAYS=1,
        TRUST_MONITOR_AGGREGATE_TTL_DAYS=1,
    )
    service, _ = _service(tmp_path, settings=settings)
    old = datetime.now(UTC) - timedelta(days=10)

    service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@scammer:matrix.org",
            actor_display_name="Core Team",
            event_type=TrustEventType.MEMBER_JOINED,
            occurred_at=old,
            external_event_id="$member-old",
        )
    )
    service.apply_retention(now=datetime.now(UTC))

    assert service.list_findings().items == []
    assert service.list_evidence(limit=10) == []


def test_evidence_store_never_persists_message_body(tmp_path) -> None:
    service, _ = _service(tmp_path)
    service.ingest_event(
        TrustEvent(
            channel_id="matrix",
            space_id="!support:matrix.org",
            actor_id="@asker:matrix.org",
            actor_display_name="Asker",
            event_type=TrustEventType.MESSAGE_SENT,
            occurred_at=datetime.now(UTC),
            external_event_id="$message-raw",
            target_message_id="$message-raw",
            metadata={"body": "secret support question", "body_length": 22},
        )
    )

    evidence = service.list_evidence(limit=10)
    assert len(evidence) == 1
    assert "body" not in evidence[0].metadata
    assert evidence[0].metadata["body_length"] == 22
