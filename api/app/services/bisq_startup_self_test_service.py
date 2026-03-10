"""Startup self-test for authenticated Bisq dependencies."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.channels.plugins.bisq2.client.api import Bisq2API
from app.core.config import Settings
from app.metrics.task_metrics import (
    get_bisq2_api_readiness_snapshot,
    record_bisq2_api_probe,
)
from app.services.bisq_mcp_service import Bisq2MCPService

logger = logging.getLogger(__name__)


class BisqStartupSelfTestService:
    """Run a startup smoke test for export and live-data Bisq dependencies."""

    def __init__(
        self,
        settings: Settings,
        bisq_api: Bisq2API,
        bisq_mcp_service: Bisq2MCPService,
    ) -> None:
        self.settings = settings
        self.bisq_api = bisq_api
        self.bisq_mcp_service = bisq_mcp_service

    async def run(self) -> Dict[str, Any]:
        """Execute startup probes and return a readiness snapshot."""
        if not self.bisq_mcp_service.enabled:
            return get_bisq2_api_readiness_snapshot(enabled=False)

        try:
            export_result = await self.bisq_api.export_chat_messages()
            record_bisq2_api_probe("export", is_healthy=bool(export_result))
        except Exception:  # noqa: BLE001
            logger.exception("Bisq export startup self-test failed")
            record_bisq2_api_probe("export", is_healthy=False)

        try:
            prices_result = await self.bisq_mcp_service.get_market_prices("EUR")
            record_bisq2_api_probe(
                "market_prices",
                is_healthy=bool(prices_result.get("success")),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Bisq market-price startup self-test failed")
            record_bisq2_api_probe("market_prices", is_healthy=False)

        try:
            offerbook_result = await self.bisq_mcp_service.get_offerbook("EUR", "SELL")
            record_bisq2_api_probe(
                "offerbook",
                is_healthy=bool(offerbook_result.get("success")),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Bisq offerbook startup self-test failed")
            record_bisq2_api_probe("offerbook", is_healthy=False)

        return get_bisq2_api_readiness_snapshot(enabled=True)
