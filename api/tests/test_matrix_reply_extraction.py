"""Tests for Matrix reply metadata extraction (m.relates_to).

TDD Approach: Tests written first, then implementation.
Phase 1.1: Extract Matrix reply and threading information from events.
"""

from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def matrix_service():
    """Create MatrixShadowModeService with mocked dependencies."""
    with patch("app.integrations.matrix_shadow_mode.NIO_AVAILABLE", True), patch(
        "app.integrations.matrix_shadow_mode.AsyncClient"
    ), patch("app.integrations.matrix_shadow_mode.PollingStateManager"), patch(
        "app.integrations.matrix_shadow_mode.SessionManager"
    ), patch(
        "app.integrations.matrix_shadow_mode.ErrorHandler"
    ), patch(
        "app.integrations.matrix_shadow_mode.ConnectionManager"
    ):

        from app.integrations.matrix_shadow_mode import MatrixShadowModeService

        service = MatrixShadowModeService(
            homeserver="https://matrix.org",
            user_id="@bot:matrix.org",
            room_id="!test:matrix.org",
            password="test_password",
        )
        yield service


class TestMatrixReplyExtraction:
    """Test extraction of Matrix reply metadata from events."""

    def test_extract_simple_reply(self, matrix_service):
        """Should extract reply_to event ID from simple reply."""
        # Arrange
        event = Mock()
        event.source = {
            "content": {
                "m.relates_to": {"m.in_reply_to": {"event_id": "$original_event_id"}}
            }
        }

        # Act
        reply_to = matrix_service._extract_reply_to(event)

        # Assert
        assert reply_to == "$original_event_id"

    def test_extract_no_reply(self, matrix_service):
        """Should return None when message is not a reply."""
        # Arrange
        event = Mock()
        event.source = {"content": {"msgtype": "m.text"}}

        # Act
        reply_to = matrix_service._extract_reply_to(event)

        # Assert
        assert reply_to is None

    def test_extract_thread_id(self, matrix_service):
        """Should extract thread ID from threaded message."""
        # Arrange
        event = Mock()
        event.source = {
            "content": {
                "m.relates_to": {"rel_type": "m.thread", "event_id": "$thread_root_id"}
            }
        }

        # Act
        thread_id = matrix_service._extract_thread_id(event)

        # Assert
        assert thread_id == "$thread_root_id"

    def test_extract_thread_id_no_thread(self, matrix_service):
        """Should return None when message is not in a thread."""
        # Arrange
        event = Mock()
        event.source = {"content": {"msgtype": "m.text"}}

        # Act
        thread_id = matrix_service._extract_thread_id(event)

        # Assert
        assert thread_id is None

    def test_malformed_reply_metadata(self, matrix_service):
        """Should handle malformed reply metadata gracefully."""
        # Arrange
        event = Mock()
        event.source = {"content": {"m.relates_to": {"some_other_field": "value"}}}

        # Act
        reply_to = matrix_service._extract_reply_to(event)

        # Assert
        assert reply_to is None

    def test_missing_source_field(self, matrix_service):
        """Should handle missing source field gracefully."""
        # Arrange
        event = Mock(spec=[])  # No attributes

        # Act
        reply_to = matrix_service._extract_reply_to(event)

        # Assert
        assert reply_to is None
