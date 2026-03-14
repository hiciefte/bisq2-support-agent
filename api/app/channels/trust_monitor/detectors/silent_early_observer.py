from __future__ import annotations

from datetime import UTC, timedelta

from app.channels.staff import StaffResolver
from app.channels.trust_monitor.detectors.base import DetectorResult
from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.evidence_store import TrustMonitorStore
from app.channels.trust_monitor.models import (
    TrustAlertSurface,
    TrustEventType,
    TrustPolicy,
)


class SilentEarlyObserverDetector:
    detector_key = "silent_early_observer"

    def __init__(
        self,
        *,
        store: TrustMonitorStore,
        staff_resolver: StaffResolver,
    ) -> None:
        self.store = store
        self.staff_resolver = staff_resolver

    def evaluate(
        self,
        event: TrustEvent,
        *,
        actor_key: str,
        policy: TrustPolicy,
    ) -> DetectorResult | None:
        if event.event_type not in {
            TrustEventType.MESSAGE_READ,
            TrustEventType.MESSAGE_REPLIED,
        }:
            return None
        if self.staff_resolver.is_staff(event.actor_id):
            return None
        since = event.occurred_at.astimezone(UTC) - timedelta(
            days=policy.silent_observer_window_days
        )
        observations, early_hits, reply_count = self.store.count_early_reads(
            channel_id=event.channel_id,
            space_id=event.space_id,
            actor_key=actor_key,
            since=since,
            early_read_window_seconds=policy.early_read_window_seconds,
        )
        self.store.upsert_aggregate(
            detector_key=self.detector_key,
            channel_id=event.channel_id,
            space_id=event.space_id,
            actor_key=actor_key,
            actor_id=event.actor_id,
            observed_at=event.occurred_at,
            window_start_at=since,
            metrics={
                "observations": observations,
                "early_hits": early_hits,
                "reply_count": reply_count,
            },
        )
        if observations < policy.minimum_observations:
            return None
        if early_hits < policy.minimum_early_read_hits:
            return None
        ratio = float("inf") if reply_count == 0 else early_hits / max(reply_count, 1)
        if reply_count > 0 and ratio < policy.read_to_reply_ratio_threshold:
            return None
        score = min(0.99, 0.55 + (early_hits / max(observations, 1)) * 0.35)
        return DetectorResult(
            detector_key=self.detector_key,
            suspect_actor_id=event.actor_id,
            suspect_actor_key=actor_key,
            suspect_display_name=event.actor_display_name,
            score=score,
            evidence_summary={
                "observations": observations,
                "early_hits": early_hits,
                "reply_count": reply_count,
                "window_days": policy.silent_observer_window_days,
                "ratio": ratio,
            },
            alert_surface=TrustAlertSurface.ADMIN_UI,
            occurred_at=event.occurred_at.astimezone(UTC),
        )
