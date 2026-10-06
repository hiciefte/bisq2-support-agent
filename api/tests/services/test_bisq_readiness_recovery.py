"""Readiness recovers public Bisq probes without the dependent scheduler."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app.metrics.task_metrics import clear_bisq2_api_probes, record_bisq2_api_probe
from app.routes import health as health_routes
from app.routes.health import _bisq_api_ready, readiness_check
from app.services.bisq_mcp_service import Bisq2MCPService
from app.services.bisq_startup_self_test_service import BisqStartupSelfTestService

pytestmark = pytest.mark.unit


@pytest.fixture
async def service(monkeypatch):
    monkeypatch.setattr(
        "app.metrics.task_metrics._persist_bisq2_api_metrics", lambda: None
    )
    clear_bisq2_api_probes("export", "market_prices", "offerbook")
    settings = SimpleNamespace(
        BISQ_API_URL="http://bisq-test.invalid:8090",
        BISQ_API_TIMEOUT=1,
        BISQ_API_AUTH_ENABLED=False,
        ENABLE_BISQ_MCP_INTEGRATION=True,
        BISQ2_CHANNEL_ENABLED=False,
    )
    instance = Bisq2MCPService(settings)
    instance._client = httpx.AsyncClient(
        base_url=instance.active_base_url,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"openapi": "3.0.1"})
        ),
    )
    instance._make_request = AsyncMock(return_value={"quotes": {}, "offers": []})
    yield instance
    await instance.close()
    clear_bisq2_api_probes("export", "market_prices", "offerbook")


def _request(service):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                bisq_mcp_service=service,
                settings=service.settings,
                rag_service=SimpleNamespace(
                    rag_chain=object(),
                    document_retriever=object(),
                    retriever=object(),
                    check_readiness=AsyncMock(return_value=True),
                ),
            )
        )
    )


@pytest.mark.asyncio
async def test_ready_recovers_failed_startup_without_scheduler(service):
    service._make_request.side_effect = httpx.ConnectError("not ready")
    bisq_api = AsyncMock()
    startup = BisqStartupSelfTestService(service.settings, bisq_api, service)
    result = await startup.run()
    assert result["status"] == "degraded"
    assert (await readiness_check(_request(service))).status_code == 503
    service._make_request.side_effect = None
    service._readiness_retry_after = 0  # Advance past the failed recovery cooldown.
    assert (await readiness_check(_request(service))).status_code == 200
    assert service._make_request.await_count == 6
    bisq_api.export_chat_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_stays_unready_and_recovery_retries_are_rate_limited(service):
    service._make_request.side_effect = httpx.ReadTimeout("not ready")
    assert await _bisq_api_ready(_request(service)) is False
    assert service._make_request.await_count == 2
    service._make_request.side_effect = None
    assert await _bisq_api_ready(_request(service)) is False
    assert service._make_request.await_count == 2
    service._readiness_retry_after = 0
    assert await _bisq_api_ready(_request(service)) is True
    assert service._make_request.await_count == 4


@pytest.mark.asyncio
async def test_healthy_probes_are_not_reissued(service):
    for probe in ("market_prices", "offerbook"):
        record_bisq2_api_probe(probe, is_healthy=True)
    assert await _bisq_api_ready(_request(service)) is True
    service._make_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_only_reissues_failed_live_probe_and_keeps_export_failure(
    service,
):
    record_bisq2_api_probe("market_prices", is_healthy=True)
    record_bisq2_api_probe("offerbook", is_healthy=False)
    record_bisq2_api_probe("export", is_healthy=False)
    assert await _bisq_api_ready(_request(service)) is False
    service._make_request.assert_awaited_once_with(
        "/api/v1/offerbook/markets/EUR/offers"
    )
    result = await service.health_check()
    assert result["readiness"]["checks"]["export"]["healthy"] is False
    assert result["readiness"]["checks"]["offerbook"]["healthy"] is True


@pytest.mark.asyncio
async def test_recovery_does_not_accept_a_cached_success_after_live_failure(service):
    await service.get_market_prices("EUR")
    await service.get_offerbook("EUR", "SELL")
    record_bisq2_api_probe("market_prices", is_healthy=False)
    record_bisq2_api_probe("offerbook", is_healthy=False)
    service._make_request.side_effect = httpx.ConnectError("offline")
    assert await _bisq_api_ready(_request(service)) is False
    assert service._make_request.await_count == 4


@pytest.mark.asyncio
async def test_ordinary_health_does_not_start_live_probe_recovery(service):
    result = await service.health_check()
    assert result["api_available"] is True
    assert result["readiness"]["status"] == "unknown"
    service._make_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_live_data_never_starts_recovery(service):
    service.enabled = False
    result = await service.health_check(refresh_failed_live_probes=True)
    assert result["readiness"]["status"] == "disabled"
    service._make_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_openapi_failure_still_blocks_readiness_after_live_recovery(service):
    await service._client.aclose()
    service._client = httpx.AsyncClient(
        base_url=service.active_base_url,
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    )
    assert await _bisq_api_ready(_request(service)) is False
    assert service._make_request.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_readiness_calls_share_one_recovery(service):
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked_request(*args):
        entered.set()
        await release.wait()
        return {"quotes": {}, "offers": []}

    service._make_request.side_effect = blocked_request
    checks = [
        asyncio.create_task(_bisq_api_ready(_request(service))) for _ in range(20)
    ]
    await entered.wait()
    assert service._make_request.await_count == 1
    release.set()
    assert all(await asyncio.gather(*checks))
    assert service._make_request.await_count == 2


@pytest.mark.asyncio
async def test_route_timeout_does_not_cancel_or_duplicate_inflight_probe(
    service, monkeypatch
):
    monkeypatch.setattr(health_routes, "READINESS_DEPENDENCY_TIMEOUT_SECONDS", 0.01)
    release = asyncio.Event()

    async def blocked_request(*args):
        await release.wait()
        return {"quotes": {}, "offers": []}

    service._make_request.side_effect = blocked_request
    assert await _bisq_api_ready(_request(service)) is False
    task = service._readiness_recovery_task
    assert task is not None and not task.done()
    assert await _bisq_api_ready(_request(service)) is False
    assert service._readiness_recovery_task is task
    assert service._make_request.await_count == 1
    release.set()
    await task
    assert await _bisq_api_ready(_request(service)) is True
    assert service._make_request.await_count == 2


@pytest.mark.asyncio
async def test_unexpected_probe_error_remains_failed_without_secret_detail(
    service, caplog
):
    detail = "sensitive probe detail"
    service.get_market_prices = AsyncMock(side_effect=RuntimeError(detail))
    assert await _bisq_api_ready(_request(service)) is False
    assert detail not in caplog.text
    result = await service.health_check()
    assert result["readiness"]["checks"]["market_prices"]["healthy"] is False
    assert result["readiness"]["checks"]["offerbook"]["healthy"] is True


@pytest.mark.asyncio
async def test_close_cancels_owned_recovery_and_cannot_start_another(service):
    entered = asyncio.Event()

    async def blocked_request(*args):
        entered.set()
        await asyncio.Event().wait()

    service._make_request.side_effect = blocked_request
    check = asyncio.create_task(_bisq_api_ready(_request(service)))
    await entered.wait()
    task = service._readiness_recovery_task
    await service.close()
    assert task.cancelled()
    with pytest.raises(asyncio.CancelledError):
        await check
    await service._refresh_failed_live_probes()
    assert service._make_request.await_count == 1
