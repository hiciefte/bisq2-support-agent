from unittest.mock import AsyncMock, MagicMock

import pytest
from app.metrics.task_metrics import (
    BISQ2_API_EXPORT_LAST_CHECK_TIMESTAMP,
    BISQ2_API_EXPORT_READINESS_STATUS,
    BISQ2_API_MARKET_PRICES_LAST_CHECK_TIMESTAMP,
    BISQ2_API_MARKET_PRICES_READINESS_STATUS,
    BISQ2_API_OFFERBOOK_LAST_CHECK_TIMESTAMP,
    BISQ2_API_OFFERBOOK_READINESS_STATUS,
)
from app.services.bisq_startup_self_test_service import BisqStartupSelfTestService


@pytest.fixture(autouse=True)
def reset_bisq_probe_metrics():
    BISQ2_API_EXPORT_READINESS_STATUS.set(0)
    BISQ2_API_EXPORT_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_MARKET_PRICES_READINESS_STATUS.set(0)
    BISQ2_API_MARKET_PRICES_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_OFFERBOOK_READINESS_STATUS.set(0)
    BISQ2_API_OFFERBOOK_LAST_CHECK_TIMESTAMP.set(0)


@pytest.mark.asyncio
async def test_run_returns_disabled_snapshot_when_mcp_is_disabled():
    settings = MagicMock()
    bisq_api = AsyncMock()
    mcp_service = MagicMock()
    mcp_service.enabled = False

    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )

    result = await service.run()

    assert result["status"] == "disabled"
    bisq_api.export_chat_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_executes_export_market_prices_and_offerbook_checks():
    settings = MagicMock()
    bisq_api = AsyncMock()
    bisq_api.export_chat_messages.return_value = {"messages": []}
    mcp_service = AsyncMock()
    mcp_service.enabled = True
    mcp_service.get_market_prices.return_value = {
        "success": True,
        "prices": [{"currency": "EUR", "rate": 60000}],
    }
    mcp_service.get_offerbook.return_value = {
        "success": True,
        "offers": [{"currency": "EUR"}],
    }

    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )

    result = await service.run()

    bisq_api.export_chat_messages.assert_awaited_once_with()
    mcp_service.get_market_prices.assert_awaited_once_with("EUR")
    mcp_service.get_offerbook.assert_awaited_once_with("EUR", "SELL")
    assert result["status"] == "healthy"


@pytest.mark.asyncio
async def test_run_marks_overall_status_degraded_when_any_probe_fails():
    settings = MagicMock()
    bisq_api = AsyncMock()
    bisq_api.export_chat_messages.return_value = {}
    mcp_service = AsyncMock()
    mcp_service.enabled = True
    mcp_service.get_market_prices.return_value = {
        "success": True,
        "prices": [{"currency": "EUR", "rate": 60000}],
    }
    mcp_service.get_offerbook.return_value = {
        "success": False,
        "offers": [],
        "error": "upstream unavailable",
    }

    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )

    result = await service.run()

    assert result["status"] == "degraded"
    assert result["checks"]["export"]["healthy"] is False
    assert result["checks"]["offerbook"]["healthy"] is False
