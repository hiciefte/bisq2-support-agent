"""Pure persister for proactive trust-monitor findings.

Extracted so the policy-override behavior can be unit-tested without
spinning up the full FastAPI lifespan.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

_logger = logging.getLogger(__name__)


def persist_proactive_finding(
    *,
    trust_monitor_service: Any,
    sync_rooms: Iterable[str],
    result: Any,
    logger: logging.Logger | None = None,
) -> None:
    """Persist a proactive detector result, honoring the policy alert surface.

    The proactive scanner hardcodes ``alert_surface=BOTH`` on its detector
    results. That bypasses the operator-configurable policy, so we resolve
    the effective surface from the policy service here before storing.
    """
    log = logger or _logger
    try:
        space_id = next(iter(sync_rooms), "proactive_scan")
        policy = trust_monitor_service.policy_service.get_policy()
        finding = trust_monitor_service.store.upsert_finding(
            detector_key=result.detector_key,
            channel_id="matrix",
            space_id=space_id,
            suspect_actor_key=result.suspect_actor_key,
            suspect_actor_id=result.suspect_actor_id,
            suspect_display_name=result.suspect_display_name,
            score=result.score,
            alert_surface=policy.alert_surface,
            evidence_summary=result.evidence_summary,
            created_at=result.occurred_at,
            notify=True,
        )
        if trust_monitor_service.publisher:
            trust_monitor_service.publisher.publish(finding)
    except Exception:
        log.warning(
            "Failed to persist proactive finding for %s (%s)",
            getattr(result, "suspect_actor_id", "?"),
            getattr(result, "detector_key", "?"),
            exc_info=True,
        )
