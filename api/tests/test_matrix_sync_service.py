"""Tests for Matrix sync service - TDD approach.

These tests drive the implementation of MatrixSyncService which polls
Matrix rooms for staff replies and processes them through the unified
training pipeline.
"""

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings for Matrix sync."""
    settings = MagicMock()
    settings.MATRIX_HOMESERVER_URL = "https://matrix.bisq.network"
    settings.MATRIX_SYNC_USER = "@bisq-bot:matrix.bisq.network"
    settings.MATRIX_SYNC_PASSWORD = "test-password"
    settings.MATRIX_SYNC_USER_RESOLVED = "@bisq-bot:matrix.bisq.network"
    settings.MATRIX_SYNC_PASSWORD_RESOLVED = "test-password"
    # Use single room for simpler test assertions
    settings.MATRIX_SYNC_ROOMS = ["!room1:matrix.bisq.network"]
    settings.MATRIX_SYNC_SESSION_PATH = "/tmp/test_matrix_session.json"
    settings.DATA_DIR = "/tmp/test_data"
    settings.TRUSTED_STAFF_IDS = [
        "@suddenwhipvapor:matrix.bisq.network",
        "@pazza83:matrix.bisq.network",
    ]
    return settings


@pytest.fixture
def mock_pipeline_service():
    """Create mock UnifiedPipelineService for LLM-based extraction."""
    service = AsyncMock()
    # Mock extract_faqs_batch for LLM-based extraction
    service.extract_faqs_batch = AsyncMock(
        return_value=[
            MagicMock(
                candidate_id=1,
                source="matrix",
                source_event_id="matrix_$answer_event_id",
                routing="FULL_REVIEW",
                final_score=0.85,
                is_calibration_sample=False,
            )
        ]
    )
    return service


@pytest.fixture
def mock_polling_state():
    """Create mock PollingStateManager."""
    state = MagicMock()
    state.since_token = None  # Kept for backward compatibility
    state.room_tokens = {}  # Per-room pagination tokens
    state.processed_ids = set()
    state.is_processed = MagicMock(return_value=False)
    state.mark_processed = MagicMock()
    state.update_since_token = MagicMock()  # Kept for backward compatibility
    state.get_room_token = MagicMock(return_value=None)  # Per-room token getter
    state.update_room_token = MagicMock()  # Per-room token setter
    state.save_batch_processed = MagicMock()
    return state


@pytest.fixture
def mock_error_handler():
    """Create mock ErrorHandler for retry logic."""
    handler = MagicMock()
    # Make call_with_retry an AsyncMock that calls the underlying function
    handler.call_with_retry = AsyncMock()
    return handler


class MockMatrixEvent:
    """Mock matrix-nio event object for testing."""

    def __init__(self, event_dict: Dict[str, Any]):
        self.source = event_dict
        self.event_id = event_dict.get("event_id", "")
        self.sender = event_dict.get("sender", "")
        self.server_timestamp = event_dict.get("origin_server_ts", 0)
        content = event_dict.get("content", {})
        self.body = content.get("body", "")
        self.msgtype = content.get("msgtype", "m.text")


class MockRoomMessagesResponse:
    """Mock RoomMessagesResponse for testing."""

    def __init__(self, chunk: List[Dict[str, Any]], end: str):
        # Wrap dicts in MockMatrixEvent objects
        self.chunk = [MockMatrixEvent(event) for event in chunk]
        self.end = end


@pytest.fixture(autouse=True)
def patch_room_messages_response():
    """Auto-patch RoomMessagesResponse for isinstance checks in all tests."""
    with patch(
        "app.services.training.ingest.matrix_sync_service.RoomMessagesResponse",
        MockRoomMessagesResponse,
    ):
        yield


@pytest.fixture
def sample_room_messages() -> Dict[str, Any]:
    """Sample Matrix room_messages response with staff reply."""
    return {
        "chunk": [
            # User question
            {
                "event_id": "$question_event_id",
                "type": "m.room.message",
                "sender": "@user123:matrix.org",
                "origin_server_ts": 1700000000000,
                "content": {
                    "msgtype": "m.text",
                    "body": "How do I set up Bisq 2? I'm new to Bitcoin trading.",
                },
            },
            # Staff reply to question
            {
                "event_id": "$answer_event_id",
                "type": "m.room.message",
                "sender": "@suddenwhipvapor:matrix.bisq.network",
                "origin_server_ts": 1700000060000,
                "content": {
                    "msgtype": "m.text",
                    "body": "> How do I set up Bisq 2?\n\nDownload from bisq.network, verify signatures, and follow the setup wizard.",
                    "m.relates_to": {
                        "m.in_reply_to": {
                            "event_id": "$question_event_id",
                        }
                    },
                },
            },
        ],
        "start": "s12345",
        "end": "s12346",
    }


@pytest.fixture
def sample_staff_to_staff_messages() -> Dict[str, Any]:
    """Sample Matrix messages - staff replying to staff (should be ignored)."""
    return {
        "chunk": [
            # Staff message
            {
                "event_id": "$staff1_event_id",
                "type": "m.room.message",
                "sender": "@pazza83:matrix.bisq.network",
                "origin_server_ts": 1700000000000,
                "content": {
                    "msgtype": "m.text",
                    "body": "Should we update the FAQ for Bisq Easy?",
                },
            },
            # Another staff replying to first staff
            {
                "event_id": "$staff2_event_id",
                "type": "m.room.message",
                "sender": "@suddenwhipvapor:matrix.bisq.network",
                "origin_server_ts": 1700000060000,
                "content": {
                    "msgtype": "m.text",
                    "body": "> Should we update the FAQ?\n\nYes, let's do that.",
                    "m.relates_to": {
                        "m.in_reply_to": {
                            "event_id": "$staff1_event_id",
                        }
                    },
                },
            },
        ],
        "start": "s12345",
        "end": "s12346",
    }


# =============================================================================
# Test: Service Initialization
# =============================================================================


class TestMatrixSyncServiceInit:
    """Tests for MatrixSyncService initialization."""

    def test_service_requires_matrix_configuration(self):
        """Service should skip gracefully when Matrix is not configured."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = ""  # Not configured
        settings.MATRIX_SYNC_ROOMS = []

        service = MatrixSyncService(
            settings=settings,
            pipeline_service=MagicMock(),
            polling_state=MagicMock(),
        )
        assert service.is_configured() is False

    def test_service_initializes_with_all_components(self, mock_settings):
        """Service should initialize with settings, pipeline, and polling state."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        pipeline = MagicMock()
        polling_state = MagicMock()

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=pipeline,
            polling_state=polling_state,
        )

        assert service.settings == mock_settings
        assert service.pipeline_service == pipeline
        assert service.polling_state == polling_state
        assert service.is_configured() is True

    def test_uses_trusted_staff_ids_from_settings(self, mock_settings):
        """Service should use TRUSTED_STAFF_IDS from settings."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=MagicMock(),
            polling_state=MagicMock(),
        )

        # Should use settings-based staff IDs
        assert "@suddenwhipvapor:matrix.bisq.network" in service.trusted_staff_ids
        assert "@pazza83:matrix.bisq.network" in service.trusted_staff_ids

    def test_reads_matrix_sync_rooms(self):
        """Service should read MATRIX_SYNC_ROOMS."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = "https://matrix.bisq.network"
        settings.MATRIX_SYNC_ROOMS = ["!sync:matrix.bisq.network"]
        settings.TRUSTED_STAFF_IDS = []

        service = MatrixSyncService(
            settings=settings,
            pipeline_service=MagicMock(),
            polling_state=MagicMock(),
        )

        assert service.is_configured() is True
        assert service._get_sync_rooms(settings) == ["!sync:matrix.bisq.network"]


# =============================================================================
# Test: Room Polling
# =============================================================================


class TestRoomPolling:
    """Tests for Matrix room polling functionality."""

    @pytest.mark.asyncio
    async def test_sync_fetches_messages_using_per_room_token(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
    ):
        """Sync should use per-room token for incremental polling."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        # Configure per-room token (the new approach)
        mock_polling_state.get_room_token = MagicMock(return_value="s12345_previous")

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        # Mock the Matrix client and error handler with proper response type
        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(chunk=[], end="s12346")
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with (
            patch.object(service, "_get_client", return_value=mock_client),
            patch(
                "app.services.training.ingest.matrix_sync_service.RoomMessagesResponse",
                MockRoomMessagesResponse,
            ),
        ):
            await service.sync_rooms()

        # Verify call_with_retry was called (which wraps room_messages)
        assert mock_error_handler.call_with_retry.called
        # Verify get_room_token was called to fetch the per-room token
        mock_polling_state.get_room_token.assert_called()

    @pytest.mark.asyncio
    async def test_sync_updates_room_token_after_poll(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
    ):
        """Sync should update per-room token after successful poll."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        # Mock the Matrix client and error handler with proper response type
        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(chunk=[], end="s12346_new")
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with (
            patch.object(service, "_get_client", return_value=mock_client),
            patch(
                "app.services.training.ingest.matrix_sync_service.RoomMessagesResponse",
                MockRoomMessagesResponse,
            ),
        ):
            await service.sync_rooms()

        # Verify per-room token was updated (uses update_room_token, not update_since_token)
        mock_polling_state.update_room_token.assert_called()

    @pytest.mark.asyncio
    async def test_sync_handles_empty_room_response(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
    ):
        """Sync should handle empty room responses gracefully."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        # Mock the Matrix client with empty response
        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(chunk=[], end="s12346")
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with (
            patch.object(service, "_get_client", return_value=mock_client),
            patch(
                "app.services.training.ingest.matrix_sync_service.RoomMessagesResponse",
                MockRoomMessagesResponse,
            ),
        ):
            count = await service.sync_rooms()

        # Should return 0 processed
        assert count == 0


# =============================================================================
# Test: LLM-Based FAQ Extraction
# =============================================================================


class TestLLMBasedExtraction:
    """Tests for LLM-based FAQ extraction from Matrix messages.

    The new architecture uses UnifiedFAQExtractor via pipeline_service.extract_faqs_batch()
    for single-pass LLM extraction instead of pattern-based reply matching.
    """

    @pytest.mark.asyncio
    async def test_calls_extract_faqs_batch_with_messages(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should call extract_faqs_batch with all new messages."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            _count = await service.sync_rooms()  # noqa: F841

        # Should have called extract_faqs_batch
        mock_pipeline_service.extract_faqs_batch.assert_called_once()
        call_kwargs = mock_pipeline_service.extract_faqs_batch.call_args.kwargs
        assert call_kwargs["source"] == "matrix"
        assert isinstance(call_kwargs["messages"], list)
        assert len(call_kwargs["messages"]) == 2  # Both messages sent to LLM

    @pytest.mark.asyncio
    async def test_passes_staff_identifiers_to_extractor(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should pass trusted staff identifiers to the LLM extractor."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            await service.sync_rooms()

        # Verify staff_identifiers were passed
        call_kwargs = mock_pipeline_service.extract_faqs_batch.call_args.kwargs
        assert "staff_identifiers" in call_kwargs
        staff_ids = call_kwargs["staff_identifiers"]
        assert "@suddenwhipvapor:matrix.bisq.network" in staff_ids

    @pytest.mark.asyncio
    async def test_returns_count_from_extraction_results(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should return count based on successful candidate extractions."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            count = await service.sync_rooms()

        # mock_pipeline_service returns 1 result with candidate_id
        assert count == 1

    @pytest.mark.asyncio
    async def test_handles_empty_extraction_results(
        self,
        mock_settings,
        mock_polling_state,
        mock_error_handler,
        sample_staff_to_staff_messages,
    ):
        """Should handle when LLM returns no FAQ pairs."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        # Pipeline returns empty results when no Q&A found
        mock_pipeline = AsyncMock()
        mock_pipeline.extract_faqs_batch = AsyncMock(return_value=[])

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_staff_to_staff_messages["chunk"],
            end=sample_staff_to_staff_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            count = await service.sync_rooms()

        assert count == 0


# =============================================================================
# Test: Message Format Conversion (removed old Q&A Extraction tests)
# =============================================================================


class TestMessageFormatConversion:
    """Tests for converting Matrix events to dict format for LLM extraction."""

    def test_event_to_dict_extracts_required_fields(self, mock_settings):
        """Should convert matrix-nio events to dict format."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=MagicMock(),
            polling_state=MagicMock(),
        )

        # Create mock event
        mock_event = MagicMock()
        mock_event.source = {
            "event_id": "$test_event",
            "sender": "@user:matrix.org",
            "origin_server_ts": 1700000000000,
            "content": {"body": "Test message", "msgtype": "m.text"},
        }

        # Act
        result = service._event_to_dict(mock_event)

        # Assert - should return the source dict
        assert result["event_id"] == "$test_event"
        assert result["sender"] == "@user:matrix.org"
        assert result["content"]["body"] == "Test message"

    def test_event_to_dict_handles_missing_source(self, mock_settings):
        """Should build dict from event attributes if source not available."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=MagicMock(),
            polling_state=MagicMock(),
        )

        # Event without source attribute
        mock_event = MagicMock(spec=["event_id", "sender", "server_timestamp", "body"])
        mock_event.event_id = "$fallback_event"
        mock_event.sender = "@user:matrix.org"
        mock_event.server_timestamp = 1700000000000
        mock_event.body = "Fallback message"
        del mock_event.source  # Remove source attribute

        # Act
        result = service._event_to_dict(mock_event)

        # Assert - should build from attributes
        assert result["event_id"] == "$fallback_event"
        assert result["sender"] == "@user:matrix.org"
        assert result["content"]["body"] == "Fallback message"


# =============================================================================
# Test: Pipeline Integration (LLM-based)
# =============================================================================


class TestPipelineIntegration:
    """Tests for integration with UnifiedPipelineService using LLM extraction."""

    @pytest.mark.asyncio
    async def test_tracks_processed_event_ids_from_results(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should mark processed event IDs based on extraction results."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            await service.sync_rooms()

        # Verify event was marked as processed
        mock_polling_state.mark_processed.assert_called()

    @pytest.mark.asyncio
    async def test_skips_already_processed_events(
        self,
        mock_settings,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should skip events that have already been processed."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        # Mark ALL events as already processed
        mock_polling_state.is_processed = MagicMock(return_value=True)

        # Pipeline should not be called when all messages filtered
        mock_pipeline = AsyncMock()
        mock_pipeline.extract_faqs_batch = AsyncMock(return_value=[])

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            count = await service.sync_rooms()

        # All messages filtered out before extraction
        assert count == 0
        mock_pipeline.extract_faqs_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_count_of_processed_pairs(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should return count of successfully processed Q&A pairs."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            count = await service.sync_rooms()

        # mock returns 1 result with candidate_id
        assert count == 1


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in MatrixSyncService."""

    @pytest.mark.asyncio
    async def test_handles_connection_failure_gracefully(
        self,
        mock_settings,
        mock_pipeline_service,
        mock_polling_state,
        mock_error_handler,
    ):
        """Should handle room-level connection failures and continue."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        # Mock error handler that fails - room-level exception is caught
        mock_error_handler.call_with_retry = AsyncMock(
            side_effect=Exception("Connection failed")
        )
        service._error_handler = mock_error_handler

        mock_client = AsyncMock()

        with patch.object(service, "_get_client", return_value=mock_client):
            # Should not crash - room-level exceptions are caught and logged
            count = await service.sync_rooms()

        # Returns 0 because processing failed, but doesn't crash
        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_extraction_errors_gracefully(
        self,
        mock_settings,
        mock_polling_state,
        mock_error_handler,
        sample_room_messages,
    ):
        """Should handle extraction errors without crashing.

        Room-level exceptions are caught and logged, allowing sync to continue
        with other rooms. The service returns 0 for failed rooms.
        """
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        # Make extraction fail
        mock_pipeline = AsyncMock()
        mock_pipeline.extract_faqs_batch = AsyncMock(
            side_effect=Exception("LLM extraction failed")
        )

        service = MatrixSyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline,
            polling_state=mock_polling_state,
        )

        mock_client = AsyncMock()
        mock_response = MockRoomMessagesResponse(
            chunk=sample_room_messages["chunk"],
            end=sample_room_messages["end"],
        )
        mock_error_handler.call_with_retry = AsyncMock(return_value=mock_response)
        service._error_handler = mock_error_handler

        with patch.object(service, "_get_client", return_value=mock_client):
            # Room-level errors are caught and logged, returns 0 for that room
            count = await service.sync_rooms()
            assert count == 0


# =============================================================================
# Test: Not Configured Scenarios
# =============================================================================


class TestNotConfigured:
    """Tests for when Matrix is not configured."""

    @pytest.mark.asyncio
    async def test_sync_returns_zero_when_not_configured(
        self, mock_pipeline_service, mock_polling_state
    ):
        """sync_rooms should return 0 when Matrix is not configured."""
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        settings = MagicMock()
        settings.MATRIX_HOMESERVER_URL = ""
        settings.MATRIX_SYNC_ROOMS = []

        service = MatrixSyncService(
            settings=settings,
            pipeline_service=mock_pipeline_service,
            polling_state=mock_polling_state,
        )

        count = await service.sync_rooms()
        assert count == 0
        mock_pipeline_service.process_matrix_answer.assert_not_called()


class TestCredentialResolution:
    """Tests for sync credential resolution without shared fallback."""

    def test_sync_credential_helpers_prefer_lane_specific_values(self):
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        settings = MagicMock()
        settings.MATRIX_SYNC_USER_RESOLVED = "@sync:matrix.org"
        settings.MATRIX_SYNC_PASSWORD_RESOLVED = "sync-secret"
        settings.MATRIX_SYNC_USER = "@ignored:matrix.org"
        settings.MATRIX_SYNC_PASSWORD = "ignored-secret"

        assert MatrixSyncService._get_sync_user(settings) == "@sync:matrix.org"
        assert MatrixSyncService._get_sync_password(settings) == "sync-secret"

    def test_sync_credential_helpers_use_only_sync_values(self):
        from app.services.training.ingest.matrix_sync_service import MatrixSyncService

        settings = MagicMock()
        settings.MATRIX_SYNC_USER_RESOLVED = ""
        settings.MATRIX_SYNC_PASSWORD_RESOLVED = ""
        settings.MATRIX_SYNC_USER = "@sync:matrix.org"
        settings.MATRIX_SYNC_PASSWORD = "sync-secret"

        assert MatrixSyncService._get_sync_user(settings) == "@sync:matrix.org"
        assert MatrixSyncService._get_sync_password(settings) == "sync-secret"
