"""Tests for Matrix settings with strict sync/alert variable names."""

import pytest
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

    def test_matrix_homeserver_without_active_lanes_is_valid(self):
        settings = Settings(
            MATRIX_HOMESERVER_URL="https://matrix.org",
        )

        assert settings.MATRIX_HOMESERVER_URL == "https://matrix.org"

    def test_matrix_sync_enabled_requires_sync_config_fields(self):
        with pytest.raises(ValueError, match="MATRIX_SYNC_ENABLED is True"):
            Settings(
                MATRIX_SYNC_ENABLED=True,
                MATRIX_HOMESERVER_URL="",
                MATRIX_SYNC_USER="",
                MATRIX_SYNC_PASSWORD="",
                MATRIX_SYNC_ROOMS=[],
            )

    def test_matrix_sync_enabled_accepts_complete_sync_config(self):
        settings = Settings(
            MATRIX_SYNC_ENABLED=True,
            MATRIX_HOMESERVER_URL="https://matrix.org",
            MATRIX_SYNC_USER="@bot:matrix.org",
            MATRIX_SYNC_PASSWORD="secret",
            MATRIX_SYNC_ROOMS=["!room:matrix.org"],
        )

        assert settings.MATRIX_SYNC_ENABLED is True

    def test_matrix_sync_enabled_accepts_lane_specific_credentials(self):
        settings = Settings(
            MATRIX_SYNC_ENABLED=True,
            MATRIX_HOMESERVER_URL="https://matrix.org",
            MATRIX_SYNC_USER="@sync-bot:matrix.org",
            MATRIX_SYNC_PASSWORD="sync-secret",
            MATRIX_SYNC_ROOMS=["!room:matrix.org"],
        )

        assert settings.MATRIX_SYNC_ENABLED is True
        assert settings.MATRIX_SYNC_USER_RESOLVED == "@sync-bot:matrix.org"
        assert settings.MATRIX_SYNC_PASSWORD_RESOLVED == "sync-secret"

    def test_matrix_alert_resolved_credentials_prefer_alert_specific(self):
        settings = Settings(
            MATRIX_HOMESERVER_URL="https://matrix.org",
            MATRIX_ALERT_USER="@alert:matrix.org",
            MATRIX_ALERT_PASSWORD="alert-secret",
            MATRIX_ALERT_ROOM="!ops:matrix.org",
        )

        assert settings.MATRIX_ALERT_USER_RESOLVED == "@alert:matrix.org"
        assert settings.MATRIX_ALERT_PASSWORD_RESOLVED == "alert-secret"
