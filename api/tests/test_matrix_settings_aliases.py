"""Tests for Matrix settings with strict sync/alert variable names."""

from app.core.config import Settings


class TestMatrixSettings:
    """Verify Matrix sync/alert configuration helpers."""

    def test_matrix_sync_rooms_parsed_from_csv(self):
        settings = Settings(
            MATRIX_SYNC_ROOMS="!room1:matrix.org,!room2:matrix.org",
        )

        assert settings.MATRIX_SYNC_ROOMS == [
            "!room1:matrix.org",
            "!room2:matrix.org",
        ]

    def test_matrix_sync_session_path_uses_data_dir(self):
        settings = Settings(
            DATA_DIR="/tmp/bisq-matrix-test",
            MATRIX_SYNC_SESSION_FILE="matrix_sync_session.json",
        )

        expected_path = "/tmp/bisq-matrix-test/matrix_sync_session.json"
        assert settings.MATRIX_SYNC_SESSION_PATH == expected_path

    def test_matrix_alert_session_path_uses_data_dir(self):
        settings = Settings(
            DATA_DIR="/tmp/bisq-matrix-test",
            MATRIX_ALERT_SESSION_FILE="matrix_alert_session.json",
        )

        expected_path = "/tmp/bisq-matrix-test/matrix_alert_session.json"
        assert settings.MATRIX_ALERT_SESSION_FILE_PATH == expected_path

    def test_matrix_homeserver_with_password_is_valid(self):
        settings = Settings(
            MATRIX_HOMESERVER_URL="https://matrix.org",
            MATRIX_PASSWORD="secret",
        )

        assert settings.MATRIX_HOMESERVER_URL == "https://matrix.org"
