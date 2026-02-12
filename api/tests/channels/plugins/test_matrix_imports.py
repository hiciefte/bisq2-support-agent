"""Verify Matrix domain module is importable from consolidated paths."""


class TestMatrixClientImports:
    """Matrix client layer should be importable from plugins/matrix/client/."""

    def test_connection_manager_importable(self):
        from app.channels.plugins.matrix.client.connection_manager import (
            ConnectionManager,
        )

        assert ConnectionManager is not None

    def test_error_handler_importable(self):
        from app.channels.plugins.matrix.client.error_handler import ErrorHandler

        assert ErrorHandler is not None

    def test_session_manager_importable(self):
        from app.channels.plugins.matrix.client.session_manager import SessionManager

        assert SessionManager is not None

    def test_polling_state_importable(self):
        from app.channels.plugins.matrix.client.polling_state import (
            PollingStateManager,
        )

        assert PollingStateManager is not None

    def test_matrix_metrics_importable(self):
        from app.channels.plugins.matrix.metrics import matrix_auth_total

        assert matrix_auth_total is not None


class TestMatrixServicesImports:
    """Matrix services should be importable from plugins/matrix/services/."""

    def test_sync_service_importable(self):
        from app.channels.plugins.matrix.services.sync_service import (
            MatrixSyncService,
        )

        assert MatrixSyncService is not None

    def test_export_parser_importable(self):
        from app.channels.plugins.matrix.services.export_parser import (
            MatrixExportParser,
        )

        assert MatrixExportParser is not None

    def test_alert_service_importable(self):
        from app.channels.plugins.matrix.services.alert_service import (
            MatrixAlertService,
        )

        assert MatrixAlertService is not None

    def test_matrix_config_importable(self):
        from app.channels.plugins.matrix.config import MatrixChannelConfig

        assert MatrixChannelConfig is not None
