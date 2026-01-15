"""Pytest fixtures for MCP server testing."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_bisq_service():
    """Mock Bisq2MCPService for isolated testing.

    Returns an AsyncMock that simulates the Bisq2MCPService's
    formatted output methods used by MCP tools.
    """
    service = AsyncMock()
    service.get_market_prices_formatted = AsyncMock(
        return_value="BTC/EUR: 95,000.00\nBTC/USD: 100,000.00"
    )
    service.get_offerbook_formatted = AsyncMock(
        return_value="5 BUY offers, 3 SELL offers\n\nTop offers:\n- BUY 0.5 BTC @ 95,000 EUR"
    )
    service.get_reputation_formatted = AsyncMock(
        return_value="Reputation Score: 85,000\nProfile Age: 180 days\nSuccessful Trades: 42"
    )
    service.get_markets_formatted = AsyncMock(
        return_value="Available Markets: EUR, USD, CHF, GBP, JPY"
    )
    return service


@pytest.fixture
def mock_bisq_service_with_errors():
    """Mock Bisq2MCPService that returns errors for testing error handling."""
    service = AsyncMock()
    service.get_market_prices_formatted = AsyncMock(
        side_effect=Exception("API connection failed")
    )
    service.get_offerbook_formatted = AsyncMock(
        side_effect=Exception("API connection failed")
    )
    service.get_reputation_formatted = AsyncMock(
        side_effect=Exception("Invalid profile ID")
    )
    service.get_markets_formatted = AsyncMock(
        side_effect=Exception("API connection failed")
    )
    return service


@pytest.fixture
def mock_settings():
    """Mock Settings for testing without real configuration."""
    settings = MagicMock()
    settings.OPENAI_API_KEY = "test-key-not-real"
    settings.OPENAI_MODEL = "openai:gpt-4o-mini"
    settings.MAX_TOKENS = 1000
    settings.LLM_TEMPERATURE = 0.1
    settings.ENABLE_BISQ_MCP_INTEGRATION = True
    settings.BISQ_API_TIMEOUT = 5
    settings.BISQ_CACHE_TTL_PRICES = 120
    settings.BISQ_CACHE_TTL_OFFERS = 30
    return settings
