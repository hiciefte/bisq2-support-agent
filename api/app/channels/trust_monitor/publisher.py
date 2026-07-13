from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from concurrent.futures import CancelledError, TimeoutError
from typing import Any

from app.channels.trust_monitor.models import TrustAlertSurface, TrustFinding

logger = logging.getLogger(__name__)


class TrustAlertPublisher:
    def publish(self, finding: TrustFinding) -> bool:
        """Publish a finding and report whether every requested surface succeeded."""
        raise NotImplementedError


class InMemoryTrustAlertPublisher(TrustAlertPublisher):
    def __init__(self) -> None:
        self.published_findings: list[TrustFinding] = []

    def publish(self, finding: TrustFinding) -> bool:
        self.published_findings.append(finding)
        return True


class CompositeTrustAlertPublisher(TrustAlertPublisher):
    # Matrix missing-room recovery can perform four sequential 30-second
    # operations (send, sync, join, retry). Keep one bounded outer deadline
    # above that complete recovery path rather than cancelling a valid retry.
    DEFAULT_DELIVERY_TIMEOUT_SECONDS = 135.0

    def __init__(
        self,
        *,
        admin_publisher: TrustAlertPublisher | None = None,
        matrix_notifier: (
            Callable[[TrustFinding], Coroutine[Any, Any, bool]] | None
        ) = None,
        delivery_timeout_seconds: float = DEFAULT_DELIVERY_TIMEOUT_SECONDS,
    ) -> None:
        self.admin_publisher = admin_publisher
        self.matrix_notifier = matrix_notifier
        self.delivery_timeout_seconds = max(float(delivery_timeout_seconds), 0.001)
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
        successful = True
        if surface in {TrustAlertSurface.ADMIN_UI, TrustAlertSurface.BOTH}:
            requested = True
            # TrustMonitorService durably stores the finding before publishing;
            # that stored row is the ADMIN_UI delivery surface. An optional
            # admin_publisher is only an additional side effect.
            if self.admin_publisher is not None:
                try:
                    successful = self.admin_publisher.publish(finding) and successful
                except Exception:
                    successful = False
                    logger.warning(
                        "Trust admin publisher failed detector=%s actor=%s",
                        finding.detector_key,
                        finding.suspect_actor_id,
                        exc_info=True,
                    )
        if surface in {TrustAlertSurface.STAFF_ROOM, TrustAlertSurface.BOTH}:
            requested = True
            successful = self._deliver_matrix_notification(finding) and successful
        return requested and successful

    def _deliver_matrix_notification(self, finding: TrustFinding) -> bool:
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

        # publish() is intentionally synchronous because the trust-monitor store is
        # synchronous. Waiting on work owned by this same loop would deadlock, so
        # production event-loop callers must offload ingestion to a worker thread.
        if current_loop is owner_loop:
            logger.warning(
                "Refusing blocking trust-monitor staff-room publish on owner event loop"
            )
            return False

        notification: Coroutine[Any, Any, bool] | None = None
        try:
            notification = notifier(finding)
            future = asyncio.run_coroutine_threadsafe(notification, owner_loop)
        except Exception:
            if notification is not None:
                notification.close()
            logger.warning(
                "Trust matrix notifier scheduling failed detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
                exc_info=True,
            )
            return False

        try:
            return bool(future.result(timeout=self.delivery_timeout_seconds))
        except TimeoutError:
            future.cancel()
            logger.warning(
                "Trust matrix notifier timed out detector=%s actor=%s timeout_seconds=%s",
                finding.detector_key,
                finding.suspect_actor_id,
                self.delivery_timeout_seconds,
            )
        except CancelledError:
            logger.warning(
                "Trust matrix notifier was cancelled detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
            )
        except Exception:
            logger.warning(
                "Trust matrix notifier failed detector=%s actor=%s",
                finding.detector_key,
                finding.suspect_actor_id,
                exc_info=True,
            )
        return False
