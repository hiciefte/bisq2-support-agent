from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any

from app.channels.staff import StaffResolver
from app.channels.trust_monitor.detectors.silent_early_observer import (
    SilentEarlyObserverDetector,
)
from app.channels.trust_monitor.detectors.staff_name_collision import (
    StaffNameCollisionDetector,
    normalize_display_name,
)
from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.evidence_store import TrustMonitorStore
from app.channels.trust_monitor.models import (
    TrustAccessAuditEntry,
    TrustFeedbackAction,
    TrustFinding,
    TrustFindingCounts,
    TrustFindingList,
    TrustFindingStatus,
    utc_now,
)
from app.channels.trust_monitor.publisher import TrustAlertPublisher
from app.services.trust_monitor_policy_service import TrustMonitorPolicyService


class TrustMonitorService:
    def __init__(
        self,
        *,
        db_path: str,
        settings: Any,
        policy_service: TrustMonitorPolicyService,
        publisher: TrustAlertPublisher,
        staff_resolver: StaffResolver,
    ) -> None:
        self.settings = settings
        self.store = TrustMonitorStore(db_path)
        self.policy_service = policy_service
        self.publisher = publisher
        self.staff_resolver = staff_resolver
        self._name_collision = StaffNameCollisionDetector(staff_resolver)
        self._silent_observer = SilentEarlyObserverDetector(
            store=self.store,
            staff_resolver=staff_resolver,
        )
        self._actor_secret = str(
            getattr(settings, "TRUST_MONITOR_ACTOR_KEY_SECRET", "") or "trust-monitor"
        ).encode("utf-8")

    def actor_key(self, channel_id: str, actor_id: str) -> str:
        digest = hmac.new(
            self._actor_secret,
            f"{channel_id}:{actor_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return digest

    def ingest_event(self, event: TrustEvent) -> TrustFinding | None:
        policy = self.policy_service.get_policy()
        if not policy.enabled:
            return None
        if (
            event.channel_id == "matrix"
            and event.space_id not in policy.matrix_public_room_ids
        ):
            if event.space_id != policy.matrix_staff_room_id:
                return None
        actor_key = self.actor_key(event.channel_id, event.actor_id)
        target_actor_key = (
            self.actor_key(event.channel_id, event.target_actor_id)
            if event.target_actor_id
            else None
        )
        trusted_staff = self.staff_resolver.is_staff(event.actor_id)
        self.store.upsert_actor_profile(
            channel_id=event.channel_id,
            actor_key=actor_key,
            actor_id=event.actor_id,
            display_name=event.actor_display_name,
            normalized_display_name=normalize_display_name(event.actor_display_name),
            trusted_staff=trusted_staff,
            occurred_at=event.occurred_at,
            metadata=event.metadata,
        )
        stored_event = self.store.insert_event(
            event=event,
            actor_key=actor_key,
            target_actor_key=target_actor_key,
            trusted_staff=trusted_staff,
        )
        if stored_event is None:
            return None

        candidate = None
        if policy.name_collision_enabled:
            candidate = self._name_collision.evaluate(event, actor_key=actor_key)
        if candidate is None and policy.silent_observer_enabled:
            candidate = self._silent_observer.evaluate(
                event,
                actor_key=actor_key,
                policy=policy,
            )
        if candidate is None:
            return None
        candidate.alert_surface = policy.alert_surface
        existing = self.store.find_existing_finding(
            detector_key=candidate.detector_key,
            channel_id=event.channel_id,
            space_id=event.space_id,
            suspect_actor_key=candidate.suspect_actor_key,
        )
        if existing is not None:
            now = candidate.occurred_at
            if existing.benign_until is not None and existing.benign_until > now:
                return existing
            if (
                existing.suppressed_until is not None
                and existing.suppressed_until > now
            ):
                return existing
            notify = not (
                existing.last_notified_at is not None
                and (now - existing.last_notified_at) < timedelta(hours=12)
            )
        else:
            notify = True
        finding = self.store.upsert_finding(
            detector_key=candidate.detector_key,
            channel_id=event.channel_id,
            space_id=event.space_id,
            suspect_actor_key=candidate.suspect_actor_key,
            suspect_actor_id=candidate.suspect_actor_id,
            suspect_display_name=candidate.suspect_display_name.strip(),
            score=candidate.score,
            alert_surface=candidate.alert_surface,
            evidence_summary=candidate.evidence_summary,
            created_at=candidate.occurred_at,
            notify=notify,
        )
        if notify:
            self.publisher.publish(finding)
        return finding

    def list_findings(
        self,
        *,
        status: str | None = None,
        detector_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TrustFindingList:
        return self.store.list_findings(
            status=status,
            detector_key=detector_key,
            limit=limit,
            offset=offset,
        )

    def count_findings(self) -> TrustFindingCounts:
        return self.store.count_findings()

    def apply_feedback(
        self, finding_id: int, *, action: str, actor_id: str
    ) -> TrustFinding:
        now = utc_now()
        finding = self.store.get_finding(finding_id)
        if finding is None:
            raise KeyError(f"Unknown trust finding {finding_id}")
        feedback_action = TrustFeedbackAction(action)
        suppressed_until = None
        benign_until = None
        status = finding.status
        if feedback_action is TrustFeedbackAction.RESOLVE:
            status = TrustFindingStatus.RESOLVED
        elif feedback_action is TrustFeedbackAction.FALSE_POSITIVE:
            status = TrustFindingStatus.FALSE_POSITIVE
            suppressed_until = now + timedelta(days=7)
        elif feedback_action is TrustFeedbackAction.SUPPRESS:
            status = TrustFindingStatus.SUPPRESSED
            suppressed_until = now + timedelta(days=7)
        elif feedback_action is TrustFeedbackAction.MARK_BENIGN:
            status = TrustFindingStatus.BENIGN
            benign_until = now + timedelta(days=30)
        self.store.add_feedback(
            finding_id=finding_id,
            actor_id=actor_id,
            action=feedback_action,
            created_at=now,
        )
        updated = self.store.update_finding_status(
            finding_id=finding_id,
            status=status,
            updated_at=now,
            suppressed_until=suppressed_until,
            benign_until=benign_until,
        )
        self.store.add_access_audit(
            actor_id=actor_id,
            action=f"finding_feedback:{feedback_action.value}",
            target_type="finding",
            target_id=str(finding_id),
            created_at=now,
        )
        return updated

    def list_access_audit(self, *, limit: int = 50) -> list[TrustAccessAuditEntry]:
        return self.store.list_access_audit(limit=limit)

    def list_evidence(self, *, limit: int = 50):
        return self.store.list_evidence(limit=limit)

    def apply_retention(self, *, now: datetime | None = None) -> None:
        self.store.purge_expired(
            policy=self.policy_service.get_policy(), now=now or utc_now()
        )
