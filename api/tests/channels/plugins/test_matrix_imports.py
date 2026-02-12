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
