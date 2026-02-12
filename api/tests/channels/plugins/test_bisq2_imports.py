"""Verify Bisq2 domain module is importable from consolidated paths."""


class TestBisq2DomainImports:
    """All Bisq2 code should be importable from channels/plugins/bisq2/."""

    def test_bisq2_api_importable(self):
        from app.channels.plugins.bisq2.client.api import Bisq2API

        assert Bisq2API is not None

    def test_bisq2_websocket_importable(self):
        from app.channels.plugins.bisq2.client.websocket import Bisq2WebSocketClient

        assert Bisq2WebSocketClient is not None

    def test_bisq2_sync_state_importable(self):
        from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager

        assert BisqSyncStateManager is not None

    def test_bisq2_sync_service_importable(self):
        from app.channels.plugins.bisq2.services.sync_service import Bisq2SyncService

        assert Bisq2SyncService is not None

    def test_bisq2_config_importable(self):
        from app.channels.plugins.bisq2.config import Bisq2ChannelConfig

        assert Bisq2ChannelConfig is not None
