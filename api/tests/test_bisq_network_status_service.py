"""Public monitor contracts: bounded IO and truthful, identifier-free evidence."""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from app.services import bisq_network_status_service as module

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def series(target="bisq_v2.torNetwork.torStartupTime", value=2345, age=20):
    return {"target": target, "datapoints": [[value, int(time.time() - age)]]}


@pytest.fixture
def service():
    return module.BisqNetworkStatusService()


def upstream(monkeypatch, payload=None, *, status=200, raw=None, handler=None):
    requests, options = [], []

    def respond(request):
        requests.append(request)
        if handler:
            return handler(request)
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=payload)

    original = httpx.AsyncClient

    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    return requests, options


async def test_tor_positive_is_only_monitor_observation(service, monkeypatch):
    requests, options = upstream(monkeypatch, [series()])
    result = await service.get_status("tor")
    assert result["status"] == "observations_available"
    assert result["observations"]["fresh_positive"] == 1
    assert result["observations"]["latest_observed_at"]
    assert result["freshness"]["status"] == "fresh"
    assert result["incident_reference"] is None
    assert "not all Tor" in result["coverage"]
    assert "not a product version" in result["limitations"]
    assert "global outage" in result["limitations"]
    assert "service SLA" in result["freshness"]["policy"]
    assert str(requests[0].url).startswith(module.MONITOR_URL + "?")
    assert requests[0].method == "GET"
    assert dict(requests[0].url.params) == {
        "format": "json",
        "from": "-15min",
        "until": "now",
        "maxDataPoints": "900",
        "target": "bisq_v2.torNetwork.torStartupTime",
    }
    assert options == [{"timeout": 5, "follow_redirects": False, "trust_env": False}]
    assert "authorization" not in requests[0].headers


async def test_seed_failure_does_not_expose_identifier(service, monkeypatch):
    upstream(monkeypatch, [series("bisq_v2.seedNodes.private_node.rtt.serial", -1)])
    result = await service.get_status("seed_nodes")
    assert result["status"] == "failure_observed"
    assert result["observations"]["fresh_failure"] == 1
    assert "private_node" not in json.dumps(result)
    assert "network path" in result["coverage"]


async def test_seed_positive_and_failure_are_counted_without_global_verdict(
    service, monkeypatch
):
    upstream(
        monkeypatch,
        [
            series("bisq_v2.seedNodes.a.rtt.serial", 100),
            series("bisq_v2.seedNodes.b.rtt.serial", -1),
        ],
    )
    result = await service.get_status("seed_nodes")
    assert result["status"] == "failure_observed"
    assert result["observations"]["fresh_positive"] == 1
    assert result["observations"]["fresh_failure"] == 1


@pytest.mark.parametrize("error_path", [".error", "..error"])
async def test_price_failure_is_reported_even_with_recent_price(
    service, monkeypatch, error_path
):
    upstream(
        monkeypatch,
        [
            series("bisq_v2.priceNodes.private_node.price.USD", 65000),
            series("bisq_v2.priceNodes.private_node" + error_path, -1),
        ],
    )
    result = await service.get_status("price_nodes")
    assert result["status"] == "failure_observed"
    assert "private_node" not in json.dumps(result)
    assert "price accuracy" in result["coverage"]


async def test_absent_price_errors_do_not_claim_failure_free(service, monkeypatch):
    upstream(
        monkeypatch,
        [
            series("bisq_v2.priceNodes.a.price.USD", 65000),
            series("bisq_v2.priceNodes.a.error", None),
        ],
    )
    result = await service.get_status("price_nodes")
    assert result["status"] == "observations_available"
    assert "do not prove no failures" in result["coverage"]


@pytest.mark.parametrize("payload", [[], [series(value=None)], [series(age=700)]])
async def test_missing_or_stale_is_unknown(service, monkeypatch, payload):
    upstream(monkeypatch, payload)
    result = await service.get_status("tor")
    assert result["status"] == "unknown"
    assert result["freshness"]["status"] == "stale_or_missing"


async def test_partial_coverage_remains_unknown_but_retains_observations(
    service, monkeypatch
):
    upstream(
        monkeypatch,
        [
            series("bisq_v2.seedNodes.a.rtt.serial", -1),
            series("bisq_v2.seedNodes.b.rtt.serial", None),
        ],
    )
    result = await service.get_status("seed_nodes")
    assert result["status"] == "unknown"
    assert result["observations"]["fresh_failure"] == 1
    assert result["freshness"]["status"] == "partial"


@pytest.mark.parametrize(
    "area", ["all", "bisq2", "https://example.test", "tor&target=*", None, []]
)
async def test_invalid_scope_cannot_trigger_request(service, monkeypatch, area):
    fetch = AsyncMock()
    monkeypatch.setattr(service, "_fetch", fetch)
    assert await service.get_status(area) == {
        "status": "unknown",
        "reason": "unsupported_area",
    }
    fetch.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [None],
        [series(value=-1)],
        [series(value=True)],
        [series(value=float("nan"))],
        [series(age=-120)],
        [series(age=1200)],
        [series(target="private_node.injected")],
        [series(), series()],
        [{"target": "bisq_v2.torNetwork.torStartupTime", "datapoints": [[3]]}],
        [{"target": "bisq_v2.torNetwork.torStartupTime", "datapoints": [[3, "now"]]}],
        [
            {
                "target": "bisq_v2.torNetwork.torStartupTime",
                "datapoints": [[3, time.time()]] * 901,
            }
        ],
        [series()] * 65,
    ],
)
async def test_invalid_response_fails_closed_without_payload(
    service, monkeypatch, payload
):
    # json.dumps deliberately permits NaN to test hostile upstream JSON.
    upstream(monkeypatch, raw=json.dumps(payload).encode())
    result = await service.get_status("tor")
    assert result["status"] == "unknown"
    assert result["reason"] == "upstream_unavailable_or_invalid"
    assert result["observations"] == {}
    assert "private_node" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,raw",
    [(503, b"private upstream detail"), (302, b""), (200, b"{"), (200, b"x" * 262145)],
)
async def test_http_and_body_failures_are_unknown(service, monkeypatch, status, raw):
    requests, _ = upstream(monkeypatch, status=status, raw=raw)
    result = await service.get_status("tor")
    assert result["status"] == "unknown"
    assert len(requests) == 1
    assert "private upstream" not in json.dumps(result)


async def test_transport_timeout_does_not_retry(service, monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout("private endpoint detail", request=request)

    requests, _ = upstream(monkeypatch, handler=fail)
    result = await service.get_status("tor")
    assert result["status"] == "unknown"
    assert len(requests) == 1


async def test_total_deadline_includes_slow_stream(service, monkeypatch):
    async def slow(_):
        await asyncio.sleep(0.1)

    monkeypatch.setattr(service, "_fetch", slow)
    monkeypatch.setattr(module, "REQUEST_SECONDS", 0.01)
    assert (await service.get_status("tor"))["reason"] == "upstream_timeout"


async def test_cache_avoids_repeat_and_expires(service, monkeypatch):
    requests, _ = upstream(monkeypatch, [series()])
    first = await service.get_status("tor")
    assert (await service.get_status("tor"))["fetched_at"] == first["fetched_at"]
    assert len(requests) == 1
    prior = service._cache["tor"]
    service._cache["tor"] = (prior[0] - 31, *prior[1:])
    await service.get_status("tor")
    assert len(requests) == 2


async def test_cached_samples_do_not_get_new_observation_timestamps(
    service, monkeypatch
):
    requests, _ = upstream(monkeypatch, [series()])
    first = await service.get_status("tor")
    second = await service.get_status("tor")
    assert first["observations"] == second["observations"]
    assert len(requests) == 1
