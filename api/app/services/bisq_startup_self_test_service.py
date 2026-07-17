"""Startup self-test for authenticated Bisq dependencies."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.channels.plugins.bisq2.client.api import Bisq2API
from app.channels.plugins.bisq2.test_scope import resolve_bisq2_test_scope
from app.core.config import Settings
from app.metrics.task_metrics import (
    clear_bisq2_api_probes,
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
        channel_enabled = self.settings.BISQ2_CHANNEL_ENABLED
        test_scope = resolve_bisq2_test_scope(self.settings)
        export_required = bool(channel_enabled or test_scope.ready)
        scoped_export_enabled = test_scope.ready
        mcp_enabled = self.bisq_mcp_service.enabled
        disabled_probes = []
        if not export_required:
            disabled_probes.append("export")
        if not mcp_enabled:
            disabled_probes.extend(("market_prices", "offerbook"))
        if disabled_probes:
            clear_bisq2_api_probes(*disabled_probes)

        if not export_required and not mcp_enabled:
            return get_bisq2_api_readiness_snapshot(enabled=False)

        if channel_enabled and not test_scope.ready:
            logger.warning(
                "Bisq export startup self-test blocked by production-test scope "
                "(reason=%s channel_count=%s sender_profile_count=%s)",
                test_scope.reason,
                test_scope.channel_count,
                test_scope.sender_profile_count,
            )
            record_bisq2_api_probe("export", is_healthy=False)

        if scoped_export_enabled:
            try:
                export_result = await self.bisq_api.export_chat_messages()
                record_bisq2_api_probe("export", is_healthy=bool(export_result))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Bisq export startup self-test failed (%s)",
                    type(exc).__name__,
                )
                record_bisq2_api_probe("export", is_healthy=False)

        if mcp_enabled:
            try:
                prices_result = await self.bisq_mcp_service.get_market_prices("EUR")
                record_bisq2_api_probe(
                    "market_prices",
                    is_healthy=bool(prices_result.get("success")),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Bisq market-price startup self-test failed (%s)",
                    type(exc).__name__,
                )
                record_bisq2_api_probe("market_prices", is_healthy=False)

            try:
                offerbook_result = await self.bisq_mcp_service.get_offerbook(
                    "EUR", "SELL"
                )
                record_bisq2_api_probe(
                    "offerbook",
                    is_healthy=bool(offerbook_result.get("success")),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Bisq offerbook startup self-test failed (%s)",
                    type(exc).__name__,
                )
                record_bisq2_api_probe("offerbook", is_healthy=False)

        return get_bisq2_api_readiness_snapshot(enabled=True)
