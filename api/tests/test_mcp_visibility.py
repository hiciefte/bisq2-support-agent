import logging

from app.core.config import Settings


def test_mcp_disabled_startup_warning_is_prominent(caplog):
    settings = Settings(ENABLE_BISQ_MCP_INTEGRATION=False)

    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        settings.log_mcp_live_data_startup_state()

    assert "MCP live-data integration is DISABLED" in caplog.text
    assert "static RAG content" in caplog.text
    assert "ENABLE_BISQ_MCP_INTEGRATION=true" in caplog.text


def test_mcp_enabled_startup_log_does_not_expose_endpoints(caplog):
    mcp_endpoint = "mcp-endpoint-sentinel-private"
    bisq_endpoint = "bisq-endpoint-sentinel-private"
    settings = Settings(
        ENABLE_BISQ_MCP_INTEGRATION=True,
        MCP_HTTP_URL=mcp_endpoint,
        BISQ_API_URL=bisq_endpoint,
    )

    with caplog.at_level(logging.INFO, logger="app.core.config"):
        settings.log_mcp_live_data_startup_state()

    assert "MCP live-data integration is enabled" in caplog.text
    assert mcp_endpoint not in caplog.text
    assert bisq_endpoint not in caplog.text
