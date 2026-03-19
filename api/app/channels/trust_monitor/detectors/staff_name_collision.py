from __future__ import annotations

import re
import unicodedata
from datetime import UTC

from app.channels.staff import StaffResolver
from app.channels.trust_monitor.detectors.base import DetectorResult
from app.channels.trust_monitor.events import TrustEvent
from app.channels.trust_monitor.models import TrustAlertSurface, TrustEventType


def normalize_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().lower()
    collapsed = re.sub(r"\s+", " ", normalized)
    return "".join(character for character in collapsed if character.isalnum())


class StaffNameCollisionDetector:
    detector_key = "staff_name_collision"

    def __init__(self, staff_resolver: StaffResolver) -> None:
        self.staff_resolver = staff_resolver
        self._trusted_aliases = {
            normalize_display_name(name)
            for name in staff_resolver.get_display_names()
            if normalize_display_name(name)
        }

    def evaluate(self, event: TrustEvent, *, actor_key: str) -> DetectorResult | None:
        if event.event_type not in {
            TrustEventType.MEMBER_JOINED,
            TrustEventType.IDENTITY_CHANGED,
        }:
            return None
        if self.staff_resolver.is_staff(event.actor_id):
            return None
        normalized = normalize_display_name(event.actor_display_name)
        if not normalized or normalized not in self._trusted_aliases:
            return None
        return DetectorResult(
            detector_key=self.detector_key,
            suspect_actor_id=event.actor_id,
            suspect_actor_key=actor_key,
            suspect_display_name=event.actor_display_name,
            score=0.99,
            evidence_summary={
                "matched_alias": event.actor_display_name,
                "trusted_aliases": sorted(self.staff_resolver.get_display_names()),
                "event_type": event.event_type.value,
            },
            alert_surface=TrustAlertSurface.ADMIN_UI,
            occurred_at=event.occurred_at.astimezone(UTC),
        )
