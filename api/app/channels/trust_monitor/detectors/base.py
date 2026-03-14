from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.channels.trust_monitor.models import TrustAlertSurface


@dataclass(slots=True)
class DetectorResult:
    detector_key: str
    suspect_actor_id: str
    suspect_actor_key: str
    suspect_display_name: str
    score: float
    evidence_summary: dict[str, Any]
    notify: bool = True
    alert_surface: TrustAlertSurface = TrustAlertSurface.ADMIN_UI
    occurred_at: datetime = datetime.now(UTC)
