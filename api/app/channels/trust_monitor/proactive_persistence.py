"""Pure persister for proactive trust-monitor findings.

Extracted so the policy-override behavior can be unit-tested without
spinning up the full FastAPI lifespan.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from app.channels.trust_monitor.models import TrustAlertSurface

_logger = logging.getLogger(__name__)


def persist_proactive_finding(
    *,
    trust_monitor_service: Any,
    sync_rooms: Iterable[str],
    result: Any,
    logger: logging.Logger | None = None,
) -> bool:
    """Persist/publish a proactive result and report whether scanning may suppress it.

    The proactive scanner hardcodes ``alert_surface=BOTH`` on its detector
    results. That bypasses the operator-configurable policy, so we resolve
    the effective surface from the policy service here before storing. A
    required staff-room delivery must complete before returning ``True``.
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
            notify=False,
        )
    except Exception:
        log.warning(
            "Failed to persist proactive finding for %s (%s)",
            getattr(result, "suspect_actor_id", "?"),
            getattr(result, "detector_key", "?"),
            exc_info=True,
        )
        return False

    staff_delivery_required = finding.alert_surface in {
        TrustAlertSurface.STAFF_ROOM,
        TrustAlertSurface.BOTH,
    }
    if finding.alert_surface is TrustAlertSurface.NONE:
        return True

    publisher = getattr(trust_monitor_service, "publisher", None)
    if publisher is None:
        return not staff_delivery_required
    try:
        delivered = publisher.publish(finding)
    except Exception:
        log.warning(
            "Failed to publish proactive finding for %s (%s)",
            getattr(result, "suspect_actor_id", "?"),
            getattr(result, "detector_key", "?"),
            exc_info=True,
        )
        return not staff_delivery_required
    if not delivered:
        return not staff_delivery_required

    try:
        trust_monitor_service.store.mark_finding_notified(
            finding.id,
            notified_at=result.occurred_at,
        )
    except Exception:
        log.warning(
            "Failed to mark proactive finding %s notified",
            finding.id,
            exc_info=True,
        )
        return False
    return True
