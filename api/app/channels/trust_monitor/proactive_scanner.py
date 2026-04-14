"""Proactive impersonation scanner for Matrix.

Periodically searches the Matrix user directory and public room directory
for potential impersonation of Bisq staff. Creates trust findings when
suspicious accounts or rooms are discovered.

Capabilities:
1. User directory scan — finds accounts with display names matching staff
2. Public room directory scan — finds rooms with Bisq-related names
3. Educational warning — posts scam warnings when name collisions are found
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from app.channels.staff import StaffResolver
from app.channels.trust_monitor.detectors.base import DetectorResult
from app.channels.trust_monitor.detectors.staff_name_collision import (
    normalize_display_name,
)
from app.channels.trust_monitor.models import TrustAlertSurface

try:
    from nio import RoomSendResponse

    _NIO_AVAILABLE = True
except ImportError:
    _NIO_AVAILABLE = False
    RoomSendResponse = None

logger = logging.getLogger(__name__)

# Bisq-related keywords for public room scanning
_BISQ_ROOM_KEYWORDS = [
    "bisq",
    "bisq support",
    "bisq help",
    "bisq easy",
    "bisq2",
    "bisq 2",
]

# Subset used for the "suspicious room name" filter
_SUSPICIOUS_ROOM_TERMS = ["bisq support", "bisq help", "bisq easy"]

_SCAM_WARNING = (
    "\u26a0\ufe0f **Security Notice**: Official Bisq support staff will **NEVER** send "
    "you a direct message first. If someone DMs you claiming to be Bisq support, "
    "**do not share your seed phrase, passwords, or send any funds**. "
    "Report suspicious accounts to the room moderators."
)

# Minimum interval between scam warnings per room (24 hours)
_WARNING_COOLDOWN = timedelta(hours=24)


class ProactiveImpersonationScanner:
    """Periodic scanner for Matrix impersonation attempts."""

    DETECTOR_KEY_USER = "proactive_user_impersonation"
    DETECTOR_KEY_ROOM = "proactive_fake_room"

    def __init__(
        self,
        *,
        homeserver_url: str,
        access_token: str,
        staff_resolver: StaffResolver,
        trusted_staff_ids: set[str],
        monitored_room_ids: set[str],
        official_room_ids: set[str] | None = None,
        matrix_client: Any | None = None,
        scan_interval_seconds: int = 900,
        on_finding: Any | None = None,
    ) -> None:
        self.homeserver_url = homeserver_url.rstrip("/")
        self.access_token = access_token
        self.staff_resolver = staff_resolver
        self.trusted_staff_ids = {sid.lower() for sid in trusted_staff_ids}
        self.monitored_room_ids = monitored_room_ids
        self.official_room_ids = (official_room_ids or set()) | set(monitored_room_ids)
        self.matrix_client = matrix_client
        self.scan_interval_seconds = scan_interval_seconds
        self.on_finding = on_finding
        self._task: asyncio.Task[Any] | None = None
        self._running = False
        self._reported_user_ids: set[str] = set()
        self._reported_room_ids: set[str] = set()
        self._last_warning_per_room: dict[str, datetime] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scan_loop())
        logger.info(
            "Proactive impersonation scanner started (interval=%ds)",
            self.scan_interval_seconds,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Proactive impersonation scanner stopped")

    async def _scan_loop(self) -> None:
        logger.info("Proactive scanner waiting 30s before first scan...")
        await asyncio.sleep(30)
        while self._running:
            try:
                await self._run_scans()
            except Exception:
                logger.warning(
                    "Proactive scan cycle failed (interval=%ds)",
                    self.scan_interval_seconds,
                    exc_info=True,
                )
            try:
                await asyncio.sleep(self.scan_interval_seconds)
            except asyncio.CancelledError:
                break

    async def _run_scans(self) -> None:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        timeout = aiohttp.ClientTimeout(total=15)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            user_findings, room_findings = await asyncio.gather(
                self._scan_user_directory(session),
                self._scan_public_rooms(session),
            )

        for finding in user_findings + room_findings:
            if self.on_finding is not None:
                try:
                    self.on_finding(finding)
                except Exception:
                    logger.warning("on_finding callback failed", exc_info=True)

        if user_findings:
            await self._post_scam_warning()

    # ------------------------------------------------------------------
    # User directory scanning
    # ------------------------------------------------------------------

    async def _scan_user_directory(
        self, session: aiohttp.ClientSession
    ) -> list[DetectorResult]:
        """Search Matrix user directory for display names matching staff."""
        staff_names = self.staff_resolver.get_display_names()
        if not staff_names:
            return []

        findings: list[DetectorResult] = []

        per_request_timeout = aiohttp.ClientTimeout(total=10)

        for name in staff_names:
            normalized_staff = normalize_display_name(name)
            try:
                resp = await session.post(
                    f"{self.homeserver_url}/_matrix/client/v3/user_directory/search",
                    json={"search_term": name, "limit": 20},
                    timeout=per_request_timeout,
                )
                if resp.status != 200:
                    continue

                data = await resp.json()

                for user in data.get("results", []):
                    user_id = str(user.get("user_id", "")).strip()
                    display_name = str(user.get("display_name", "")).strip()

                    if not user_id or not display_name:
                        continue
                    if user_id.lower() in self.trusted_staff_ids:
                        continue
                    if user_id in self._reported_user_ids:
                        continue
                    if normalize_display_name(display_name) != normalized_staff:
                        continue

                    logger.warning(
                        "Proactive scan: potential impersonator '%s' (%s) "
                        "matches staff name '%s'",
                        display_name,
                        user_id,
                        name,
                    )
                    self._reported_user_ids.add(user_id)
                    findings.append(
                        DetectorResult(
                            detector_key=self.DETECTOR_KEY_USER,
                            suspect_actor_id=user_id,
                            suspect_actor_key=user_id,
                            suspect_display_name=display_name,
                            score=0.95,
                            evidence_summary={
                                "matched_staff_name": name,
                                "user_id": user_id,
                                "display_name": display_name,
                                "detection_method": "user_directory_search",
                            },
                            alert_surface=TrustAlertSurface.BOTH,
                            occurred_at=datetime.now(UTC),
                        )
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError):
                logger.debug(
                    "User directory search timed out or failed for '%s'",
                    name,
                    exc_info=True,
                )
            except Exception:
                logger.debug(
                    "User directory search error for '%s'", name, exc_info=True
                )

        if findings:
            logger.info(
                "Proactive user scan found %d potential impersonator(s)",
                len(findings),
            )
        return findings

    # ------------------------------------------------------------------
    # Public room directory scanning
    # ------------------------------------------------------------------

    async def _scan_public_rooms(
        self, session: aiohttp.ClientSession
    ) -> list[DetectorResult]:
        """Search Matrix public room directory for Bisq-related rooms."""
        findings: list[DetectorResult] = []

        per_request_timeout = aiohttp.ClientTimeout(total=10)

        for keyword in _BISQ_ROOM_KEYWORDS:
            try:
                resp = await session.post(
                    f"{self.homeserver_url}/_matrix/client/v3/publicRooms",
                    json={"filter": {"generic_search_term": keyword}, "limit": 50},
                    timeout=per_request_timeout,
                )
                if resp.status != 200:
                    continue

                data = await resp.json()

                for room in data.get("chunk", []):
                    room_id = str(room.get("room_id", "")).strip()
                    room_name = str(room.get("name", "")).strip()

                    if not room_id:
                        continue
                    if room_id in self.official_room_ids:
                        continue
                    if room_id in self._reported_room_ids:
                        continue

                    name_lower = room_name.lower()
                    if not any(term in name_lower for term in _SUSPICIOUS_ROOM_TERMS):
                        continue

                    logger.warning(
                        "Proactive scan: suspicious room '%s' (%s)",
                        room_name,
                        room_id,
                    )
                    self._reported_room_ids.add(room_id)
                    findings.append(
                        DetectorResult(
                            detector_key=self.DETECTOR_KEY_ROOM,
                            suspect_actor_id=room_id,
                            suspect_actor_key=room_id,
                            suspect_display_name=room_name,
                            score=0.80,
                            evidence_summary={
                                "room_id": room_id,
                                "room_name": room_name,
                                "matched_keyword": keyword,
                                "num_joined_members": room.get("num_joined_members", 0),
                                "detection_method": "public_room_directory_search",
                            },
                            alert_surface=TrustAlertSurface.BOTH,
                            occurred_at=datetime.now(UTC),
                        )
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError):
                logger.debug(
                    "Public room search timed out or failed for '%s'",
                    keyword,
                    exc_info=True,
                )
            except Exception:
                logger.debug(
                    "Public room search error for '%s'", keyword, exc_info=True
                )

        if findings:
            logger.info(
                "Proactive room scan found %d suspicious room(s)", len(findings)
            )
        return findings

    # ------------------------------------------------------------------
    # Educational warning (rate-limited per room)
    # ------------------------------------------------------------------

    async def _post_scam_warning(self) -> None:
        """Post a scam warning in monitored rooms (max once per 24h per room)."""
        if self.matrix_client is None or not _NIO_AVAILABLE:
            return

        now = datetime.now(UTC)
        for room_id in self.monitored_room_ids:
            last = self._last_warning_per_room.get(room_id)
            if last is not None and (now - last) < _WARNING_COOLDOWN:
                continue

            try:
                resp = await self.matrix_client.room_send(
                    room_id=room_id,
                    message_type="m.room.message",
                    content={"msgtype": "m.notice", "body": _SCAM_WARNING},
                )
                if isinstance(resp, RoomSendResponse):
                    self._last_warning_per_room[room_id] = now
                    logger.info("Posted scam warning to %s", room_id)
                else:
                    logger.warning(
                        "Failed to post scam warning to %s: %s", room_id, resp
                    )
            except Exception:
                logger.warning(
                    "Error posting scam warning to %s", room_id, exc_info=True
                )
