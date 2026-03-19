from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.channels.trust_monitor.models import TrustAlertSurface, TrustFinding

logger = logging.getLogger(__name__)


class TrustAlertPublisher:
    def publish(self, finding: TrustFinding) -> None:
        raise NotImplementedError


class InMemoryTrustAlertPublisher(TrustAlertPublisher):
    def __init__(self) -> None:
        self.published_findings: list[TrustFinding] = []

    def publish(self, finding: TrustFinding) -> None:
        self.published_findings.append(finding)


class CompositeTrustAlertPublisher(TrustAlertPublisher):
    def __init__(
        self,
        *,
        admin_publisher: TrustAlertPublisher | None = None,
        matrix_notifier: (
            Callable[[TrustFinding], Coroutine[Any, Any, None]] | None
        ) = None,
    ) -> None:
        self.admin_publisher = admin_publisher
        self.matrix_notifier = matrix_notifier

    def publish(self, finding: TrustFinding) -> None:
        surface = finding.alert_surface
        if surface in {TrustAlertSurface.ADMIN_UI, TrustAlertSurface.BOTH}:
            if self.admin_publisher is not None:
                try:
                    self.admin_publisher.publish(finding)
                except Exception:
                    logger.warning(
                        "Trust admin publisher failed detector=%s actor=%s",
                        finding.detector_key,
                        finding.suspect_actor_id,
                        exc_info=True,
                    )
        if surface in {TrustAlertSurface.STAFF_ROOM, TrustAlertSurface.BOTH}:
            if self.matrix_notifier is None:
                logger.warning(
                    "Trust finding requires staff-room delivery but no notifier is configured detector=%s actor=%s",
                    finding.detector_key,
                    finding.suspect_actor_id,
                )
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(
                    "No running event loop for trust-monitor staff-room publish"
                )
                return
            try:
                loop.create_task(self.matrix_notifier(finding))
            except Exception:
                logger.warning(
                    "Trust matrix notifier scheduling failed detector=%s actor=%s",
                    finding.detector_key,
                    finding.suspect_actor_id,
                    exc_info=True,
                )
