"""Bounded public monitor observations, never a whole-network health verdict.

Metric semantics were checked against bisq-network/bisq-monitor at
c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf: tasks/TorStartupTime.java,
tasks/SeedNodeRoundTripTime.java, tasks/PriceNodeData.java and reporter/Metrics.java.
The upstream ``bisq_v2`` prefix is a metric namespace, not a Bisq 2 product claim.
"""

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

MONITOR_URL = "https://monitor.bisq.network/api/datasources/proxy/1/render"
SOURCE_URL = (
    "https://github.com/bisq-network/bisq-monitor/tree/"
    "c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf"
)
MAX_BODY_BYTES = 262144
MAX_SERIES = 64
MAX_POINTS = 900
WINDOW_SECONDS = 900
# Upstream example task cadence is 300s; allow two intervals for evidence use.
# This is not a promise that the deployed monitor follows that cadence.
FRESH_SECONDS = 600
CACHE_SECONDS = 30
REQUEST_SECONDS = 8


@dataclass(frozen=True)
class _Scope:
    targets: tuple[str, ...]
    dashboard: str
    coverage: str
    patterns: tuple[tuple[str, str], ...]


SCOPES = {
    "tor": _Scope(
        ("bisq_v2.torNetwork.torStartupTime",),
        "https://monitor.bisq.network/d/vFNmfoF4z",
        "Startup of the monitor's own Tor process, not all Tor connections. "
        "The task records duration on success; missing data is not a failure report.",
        ((r"bisq_v2\.torNetwork\.torStartupTime", "startup"),),
    ),
    "price_nodes": _Scope(
        (
            "bisq_v2.priceNodes.*.price.USD",
            "bisq_v2.priceNodes.*.error",
            "bisq_v2.priceNodes.*..error",
        ),
        "https://monitor.bisq.network/d/S5m2YbK4z",
        "USD price observations and reported request errors from the monitor's "
        "configured price nodes. Missing error records do not prove no failures; "
        "successful data does not validate price accuracy or every currency.",
        (
            (r"bisq_v2\.priceNodes\.[^.]+\.price\.USD", "price"),
            (r"bisq_v2\.priceNodes\.[^.]+\.{1,2}error", "error"),
        ),
    ),
    "seed_nodes": _Scope(
        ("bisq_v2.seedNodes.*.rtt.serial",),
        "https://monitor.bisq.network/d/xJETG0FVz",
        "Serial ping/pong tests from the monitor to its configured legacy Bisq "
        "seed nodes. A failed probe can involve the monitor or its network path.",
        ((r"bisq_v2\.seedNodes\.[^.]+\.rtt\.serial", "ping"),),
    ),
}


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def has_fresh_network_observations(value: str) -> bool:
    """Require a structured, fresh local-tool result before current-status prose."""
    try:
        report = json.loads(value)
        if not isinstance(report, dict) or report.get("area") not in SCOPES:
            return False
        if report.get("status") not in {"observations_available", "failure_observed"}:
            return False
        if report.get("freshness", {}).get("status") != "fresh":
            return False
        observed = report.get("observations", {}).get("oldest_fresh_observed_at")
        timestamp = datetime.fromisoformat(observed).timestamp()
        return -30 <= time.time() - timestamp <= FRESH_SECONDS
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


class BisqNetworkStatusService:
    """Only server-owned queries; neither URLs nor metric expressions are inputs."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any, str | None, float]] = {}
        self._lock = asyncio.Lock()

    async def get_status(self, area: str) -> dict[str, Any]:
        if not isinstance(area, str) or area not in SCOPES:
            return {"status": "unknown", "reason": "unsupported_area"}
        scope = SCOPES[area]
        try:
            async with asyncio.timeout(REQUEST_SECONDS):
                async with self._lock:
                    cached = self._cache.get(area)
                    if cached is None or time.monotonic() - cached[0] >= CACHE_SECONDS:
                        try:
                            data = await self._fetch(scope)
                            reason = None
                        except (httpx.HTTPError, ValueError, TimeoutError):
                            data, reason = None, "upstream_unavailable_or_invalid"
                        cached = (time.monotonic(), data, reason, time.time())
                        self._cache[area] = cached
                    _, data, reason, fetched_at = cached
                    return self._summarize(area, scope, data, reason, fetched_at)
        except TimeoutError:
            return self._summarize(area, scope, None, "upstream_timeout", time.time())

    async def _fetch(self, scope: _Scope) -> list[dict[str, Any]]:
        params = [
            ("format", "json"),
            ("from", "-15min"),
            ("until", "now"),
            ("maxDataPoints", str(MAX_POINTS)),
        ] + [("target", target) for target in scope.targets]
        # No credentials, environment proxies, redirects, or provider calls.
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream(
                "GET", MONITOR_URL, params=tuple(params)
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise ValueError("oversized monitor response")
        data = json.loads(body)
        if not isinstance(data, list) or len(data) > MAX_SERIES:
            raise ValueError("invalid monitor series")
        return data

    @staticmethod
    def _summarize(
        area: str, scope: _Scope, data: Any, reason: str | None, fetched_at: float
    ) -> dict[str, Any]:
        now = time.time()
        result: dict[str, Any] = {
            "area": area,
            "status": "unknown",
            "reason": reason,
            "checked_at": _iso(now),
            "fetched_at": _iso(fetched_at),
            "window_seconds": WINDOW_SECONDS,
            "freshness": {
                "status": "unknown",
                "maximum_age_seconds": FRESH_SECONDS,
                "policy": "Evidence freshness limit, not a service SLA.",
            },
            "observations": {},
            "coverage": scope.coverage,
            "limitations": (
                "One public monitor and its configured probes; coverage can be partial. "
                "This does not establish a global outage, a user's local condition, "
                "or Bisq 2 application health. bisq_v2 is a metric namespace, not "
                "a product version. Graphite buckets can aggregate observations; "
                "positive samples do not prove absence of failures. "
                "No public incident source is connected."
            ),
            "dashboard_url": scope.dashboard,
            "metric_source_url": SOURCE_URL,
            "incident_reference": None,
        }
        if reason:
            return result
        try:
            counts = {"fresh_positive": 0, "fresh_failure": 0, "stale": 0, "missing": 0}
            latest_times: list[float] = []
            seen: set[str] = set()
            for series in data:
                if not isinstance(series, dict):
                    raise ValueError("invalid series")
                target, points = series.get("target"), series.get("datapoints")
                if not isinstance(target, str) or target in seen:
                    raise ValueError("invalid target")
                seen.add(target)
                kind = next(
                    (
                        kind
                        for pattern, kind in scope.patterns
                        if re.fullmatch(pattern, target)
                    ),
                    None,
                )
                if (
                    kind is None
                    or not isinstance(points, list)
                    or len(points) > MAX_POINTS
                ):
                    raise ValueError("unexpected target or points")
                samples = []
                for point in points:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("invalid datapoint")
                    value, timestamp = point
                    if type(timestamp) not in (int, float) or not math.isfinite(
                        timestamp
                    ):
                        raise ValueError("invalid timestamp")
                    if timestamp > now + 30 or timestamp < now - WINDOW_SECONDS - 60:
                        raise ValueError("out of window timestamp")
                    if value is None:
                        continue
                    if type(value) not in (int, float) or not math.isfinite(value):
                        raise ValueError("invalid value")
                    # Only the seed ping and price error tasks define -1 failures.
                    valid = value == -1 if kind == "error" else value >= 0
                    if kind == "ping" and value == -1:
                        valid = True
                    if kind == "price" and value == 0:
                        valid = False
                    if not valid:
                        raise ValueError("unsupported metric value")
                    samples.append((timestamp, value))
                if not samples:
                    # Sparse error streams are expected: absence is not success.
                    if kind != "error":
                        counts["missing"] += 1
                    continue
                timestamp, value = max(samples)
                if now - timestamp > FRESH_SECONDS:
                    if kind != "error":
                        counts["stale"] += 1
                    continue
                latest_times.append(timestamp)
                counts["fresh_failure" if value == -1 else "fresh_positive"] += 1
            result["observations"] = {
                **counts,
                "unit": "latest fresh observation per returned metric series",
                "latest_observed_at": _iso(max(latest_times)) if latest_times else None,
                "oldest_fresh_observed_at": (
                    _iso(min(latest_times)) if latest_times else None
                ),
            }
            fresh = counts["fresh_positive"] + counts["fresh_failure"]
            partial = counts["stale"] + counts["missing"] > 0
            result["freshness"]["status"] = (
                "partial"
                if fresh and partial
                else "fresh" if fresh else "stale_or_missing"
            )
            result["reason"] = (
                "partial_or_missing_observations"
                if partial or not fresh
                else "observed_probes_only"
            )
            if fresh and not partial:
                result["status"] = (
                    "failure_observed"
                    if counts["fresh_failure"]
                    else "observations_available"
                )
        except (TypeError, ValueError, OverflowError):
            result["reason"] = "upstream_unavailable_or_invalid"
            result["observations"] = {}
        return result
