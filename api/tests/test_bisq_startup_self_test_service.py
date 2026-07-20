from unittest.mock import AsyncMock, MagicMock

import pytest
from app.metrics.task_metrics import (
    BISQ2_API_EXPORT_LAST_CHECK_TIMESTAMP,
    BISQ2_API_EXPORT_READINESS_STATUS,
    BISQ2_API_EXPORT_RESPONSE_TIME,
    BISQ2_API_HEALTH_STATUS,
    BISQ2_API_LAST_CHECK_TIMESTAMP,
    BISQ2_API_MARKET_PRICES_LAST_CHECK_TIMESTAMP,
    BISQ2_API_MARKET_PRICES_READINESS_STATUS,
    BISQ2_API_MARKET_PRICES_RESPONSE_TIME,
    BISQ2_API_OFFERBOOK_LAST_CHECK_TIMESTAMP,
    BISQ2_API_OFFERBOOK_READINESS_STATUS,
    BISQ2_API_OFFERBOOK_RESPONSE_TIME,
    BISQ2_API_RESPONSE_TIME,
)
from app.services.bisq_startup_self_test_service import BisqStartupSelfTestService


def _enable_scoped_channel(settings) -> None:
    settings.BISQ2_CHANNEL_ENABLED = True
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-allowed"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-allowed"]
    settings.BISQ2_STAFF_PROFILE_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""


@pytest.fixture(autouse=True)
def reset_bisq_probe_metrics():
    BISQ2_API_HEALTH_STATUS.set(0)
    BISQ2_API_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_RESPONSE_TIME.set(0)
    BISQ2_API_EXPORT_READINESS_STATUS.set(0)
    BISQ2_API_EXPORT_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_EXPORT_RESPONSE_TIME.set(0)
    BISQ2_API_MARKET_PRICES_READINESS_STATUS.set(0)
    BISQ2_API_MARKET_PRICES_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_MARKET_PRICES_RESPONSE_TIME.set(0)
    BISQ2_API_OFFERBOOK_READINESS_STATUS.set(0)
    BISQ2_API_OFFERBOOK_LAST_CHECK_TIMESTAMP.set(0)
    BISQ2_API_OFFERBOOK_RESPONSE_TIME.set(0)


@pytest.mark.asyncio
async def test_run_returns_disabled_snapshot_when_mcp_is_disabled():
    settings = MagicMock()
    settings.BISQ2_CHANNEL_ENABLED = False
    bisq_api = AsyncMock()
    mcp_service = MagicMock()
    mcp_service.enabled = False

    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )
    BISQ2_API_EXPORT_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_EXPORT_RESPONSE_TIME.set(1)
    BISQ2_API_MARKET_PRICES_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_MARKET_PRICES_RESPONSE_TIME.set(1)
    BISQ2_API_OFFERBOOK_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_OFFERBOOK_RESPONSE_TIME.set(1)
    BISQ2_API_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_RESPONSE_TIME.set(1)

    result = await service.run()

    assert result["status"] == "disabled"
    assert all(check["status"] == "not_checked" for check in result["checks"].values())
    assert BISQ2_API_LAST_CHECK_TIMESTAMP._value.get() == 0
    assert BISQ2_API_RESPONSE_TIME._value.get() == 0
    bisq_api.export_chat_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_executes_export_market_prices_and_offerbook_checks():
    settings = MagicMock()
    _enable_scoped_channel(settings)
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
    _enable_scoped_channel(settings)
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


@pytest.mark.asyncio
async def test_run_skips_export_when_only_live_data_is_enabled():
    settings = MagicMock()
    settings.BISQ2_CHANNEL_ENABLED = False
    bisq_api = AsyncMock()
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
    BISQ2_API_EXPORT_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_EXPORT_RESPONSE_TIME.set(1)

    result = await service.run()

    bisq_api.export_chat_messages.assert_not_awaited()
    mcp_service.get_market_prices.assert_awaited_once_with("EUR")
    mcp_service.get_offerbook.assert_awaited_once_with("EUR", "SELL")
    assert result["status"] == "healthy"
    assert result["checks"]["export"]["status"] == "not_checked"
    assert BISQ2_API_EXPORT_RESPONSE_TIME._value.get() == 0


@pytest.mark.asyncio
async def test_run_checks_export_when_only_support_channel_is_enabled():
    settings = MagicMock()
    _enable_scoped_channel(settings)
    bisq_api = AsyncMock()
    bisq_api.export_chat_messages.return_value = {"messages": []}
    mcp_service = AsyncMock()
    mcp_service.enabled = False

    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )
    BISQ2_API_MARKET_PRICES_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_MARKET_PRICES_RESPONSE_TIME.set(1)
    BISQ2_API_OFFERBOOK_LAST_CHECK_TIMESTAMP.set(100)
    BISQ2_API_OFFERBOOK_RESPONSE_TIME.set(1)

    result = await service.run()

    bisq_api.export_chat_messages.assert_awaited_once_with()
    mcp_service.get_market_prices.assert_not_awaited()
    mcp_service.get_offerbook.assert_not_awaited()
    assert result["status"] == "healthy"
    assert result["checks"]["export"]["healthy"] is True
    assert result["checks"]["market_prices"]["status"] == "not_checked"
    assert result["checks"]["offerbook"]["status"] == "not_checked"


@pytest.mark.asyncio
async def test_run_checks_export_for_scoped_training_with_live_channel_disabled():
    settings = MagicMock()
    settings.BISQ2_CHANNEL_ENABLED = False
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-training"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-training"]
    settings.BISQ2_STAFF_PROFILE_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
    bisq_api = AsyncMock()
    bisq_api.export_chat_messages.return_value = {"messages": []}
    mcp_service = MagicMock()
    mcp_service.enabled = False
    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )

    result = await service.run()

    bisq_api.export_chat_messages.assert_awaited_once_with()
    assert result["status"] == "healthy"
    assert result["checks"]["export"]["healthy"] is True


@pytest.mark.asyncio
async def test_scoped_training_export_failure_is_degraded_without_detail(caplog):
    settings = MagicMock()
    settings.BISQ2_CHANNEL_ENABLED = False
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-training"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-training"]
    settings.BISQ2_STAFF_PROFILE_IDS = []
    settings.BISQ2_CHATOPS_ENABLED = False
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
    sensitive_detail = "private-endpoint sentinel-secret profile-training"
    bisq_api = AsyncMock()
    bisq_api.export_chat_messages.side_effect = RuntimeError(sensitive_detail)
    mcp_service = MagicMock()
    mcp_service.enabled = False
    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )

    result = await service.run()

    assert result["status"] == "degraded"
    assert result["checks"]["export"]["healthy"] is False
    assert sensitive_detail not in caplog.text


@pytest.mark.asyncio
async def test_run_blocks_export_io_when_enabled_scope_is_incomplete():
    settings = MagicMock()
    settings.BISQ2_CHANNEL_ENABLED = True
    settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-allowed"]
    settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = []
    settings.BISQ2_CHATOPS_CHANNEL_IDS = []
    settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
    bisq_api = AsyncMock()
    mcp_service = MagicMock()
    mcp_service.enabled = False
    service = BisqStartupSelfTestService(
        settings=settings,
        bisq_api=bisq_api,
        bisq_mcp_service=mcp_service,
    )

    result = await service.run()

    bisq_api.export_chat_messages.assert_not_awaited()
    assert result["status"] == "degraded"
    assert result["checks"]["export"]["healthy"] is False
