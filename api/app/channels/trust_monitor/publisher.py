from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.channels.trust_monitor.models import TrustAlertSurface, TrustFinding

logger = logging.getLogger(__name__)


class TrustAlertPublisher:
    def publish(self, finding: TrustFinding) -> bool:
        """Publish a finding and report whether every requested surface was scheduled."""
        raise NotImplementedError


class InMemoryTrustAlertPublisher(TrustAlertPublisher):
    def __init__(self) -> None:
        self.published_findings: list[TrustFinding] = []

    def publish(self, finding: TrustFinding) -> bool:
        self.published_findings.append(finding)
        return True


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
        self._owner_loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Bind the event loop that owns async staff-room delivery."""
        owner_loop = loop or asyncio.get_running_loop()
        if owner_loop.is_closed():
            raise RuntimeError("Cannot bind a closed event loop")
        self._owner_loop = owner_loop

    def publish(self, finding: TrustFinding) -> bool:
        surface = finding.alert_surface
        requested = False
        scheduled = True
        if surface in {TrustAlertSurface.ADMIN_UI, TrustAlertSurface.BOTH}:
            requested = True
            # TrustMonitorService durably stores the finding before publishing;
            # that stored row is the ADMIN_UI delivery surface. An optional
            # admin_publisher is only an additional side effect.
            if self.admin_publisher is not None:
                try:
                    scheduled = self.admin_publisher.publish(finding) and scheduled
                except Exception:
                    scheduled = False
                    logger.warning(
                        "Trust admin publisher failed detector=%s actor=%s",
                        finding.detector_key,
                        finding.suspect_actor_id,
                        exc_info=True,
                    )
        if surface in {TrustAlertSurface.STAFF_ROOM, TrustAlertSurface.BOTH}:
            requested = True
            scheduled = self._schedule_matrix_notification(finding) and scheduled
        return requested and scheduled

    def _schedule_matrix_notification(self, finding: TrustFinding) -> bool:
        notifier = self.matrix_notifier
        if notifier is None:
            logger.warning(
                "Trust finding requires staff-room delivery but no notifier is configured detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
            )
            return False

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        owner_loop = self._owner_loop
        if owner_loop is None or owner_loop.is_closed() or not owner_loop.is_running():
            logger.warning(
                "No bound running event loop for trust-monitor staff-room publish"
            )
            return False

        notification = notifier(finding)
        try:
            future: Any
            if current_loop is owner_loop:
                future = owner_loop.create_task(notification)
            else:
                future = asyncio.run_coroutine_threadsafe(notification, owner_loop)
            future.add_done_callback(
                lambda completed: self._log_delivery_result(completed, finding)
            )
        except Exception:
            notification.close()
            logger.warning(
                "Trust matrix notifier scheduling failed detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
                exc_info=True,
            )
            return False
        return True

    @staticmethod
    def _log_delivery_result(completed: Any, finding: TrustFinding) -> None:
        if completed.cancelled():
            logger.warning(
                "Trust matrix notifier was cancelled detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
            )
            return
        try:
            completed.result()
        except Exception:
            logger.warning(
                "Trust matrix notifier failed detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
                exc_info=True,
            )
