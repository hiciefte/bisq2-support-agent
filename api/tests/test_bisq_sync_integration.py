"""Tests for Bisq sync integration in UnifiedPipelineService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.training.unified_pipeline_service import UnifiedPipelineService
from app.services.training.unified_repository import UnifiedFAQCandidateRepository


class TestBisqSyncIntegration:
    """Test Bisq sync method in UnifiedPipelineService."""

    @pytest.fixture
    def mock_repository(self, tmp_path):
        """Create a mock repository."""
        db_path = str(tmp_path / "test.db")
        return UnifiedFAQCandidateRepository(db_path)

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_STAFF_USERS = ["staff1", "staff2"]
        return settings

    @pytest.fixture
    def pipeline_service(self, mock_repository, mock_settings):
        """Create pipeline service for testing."""
        return UnifiedPipelineService(
            settings=mock_settings,
            rag_service=MagicMock(),
            faq_service=MagicMock(),
            repository=mock_repository,
        )

    def test_pipeline_has_sync_bisq_method(self, pipeline_service):
        """UnifiedPipelineService should have sync_bisq_conversations method."""
        assert hasattr(pipeline_service, "sync_bisq_conversations")
        assert callable(pipeline_service.sync_bisq_conversations)

    @pytest.mark.asyncio
    async def test_sync_bisq_delegates_to_service(
        self, pipeline_service, mock_settings
    ):
        """sync_bisq_conversations should delegate to Bisq2SyncService."""
        with patch(
            "app.services.training.unified_pipeline_service.Bisq2SyncService"
        ) as mock_sync_class, patch(
            "app.services.training.unified_pipeline_service.Bisq2API"
        ), patch(
            "app.services.training.unified_pipeline_service.BisqSyncStateManager"
        ):
            mock_sync_instance = AsyncMock()
            mock_sync_instance.sync_conversations = AsyncMock(return_value=5)
            mock_sync_class.return_value = mock_sync_instance

            result = await pipeline_service.sync_bisq_conversations()

            # Verify service was instantiated
            mock_sync_class.assert_called_once()

            # Verify sync_conversations was called
            mock_sync_instance.sync_conversations.assert_called_once()

            assert result == 5

    @pytest.mark.asyncio
    async def test_sync_bisq_returns_processed_count(self, pipeline_service):
        """sync_bisq_conversations should return integer count."""
        with patch(
            "app.services.training.unified_pipeline_service.Bisq2SyncService"
        ) as mock_sync_class, patch(
            "app.services.training.unified_pipeline_service.Bisq2API"
        ), patch(
            "app.services.training.unified_pipeline_service.BisqSyncStateManager"
        ):
            mock_sync_instance = AsyncMock()
            mock_sync_instance.sync_conversations = AsyncMock(return_value=10)
            mock_sync_class.return_value = mock_sync_instance

            result = await pipeline_service.sync_bisq_conversations()

            assert isinstance(result, int)
            assert result == 10

    @pytest.mark.asyncio
    async def test_sync_bisq_handles_unconfigured(self, pipeline_service):
        """sync_bisq_conversations should return 0 if not configured."""
        with patch(
            "app.services.training.unified_pipeline_service.Bisq2SyncService"
        ) as mock_sync_class, patch(
            "app.services.training.unified_pipeline_service.Bisq2API"
        ), patch(
            "app.services.training.unified_pipeline_service.BisqSyncStateManager"
        ):
            mock_sync_instance = AsyncMock()
            # Unconfigured service returns 0
            mock_sync_instance.sync_conversations = AsyncMock(return_value=0)
            mock_sync_class.return_value = mock_sync_instance

            result = await pipeline_service.sync_bisq_conversations()

            assert result == 0

    @pytest.mark.asyncio
    async def test_sync_bisq_passes_settings(self, pipeline_service, mock_settings):
        """sync_bisq_conversations should pass settings to sync service."""
        with patch(
            "app.services.training.unified_pipeline_service.Bisq2SyncService"
        ) as mock_sync_class, patch(
            "app.services.training.unified_pipeline_service.Bisq2API"
        ), patch(
            "app.services.training.unified_pipeline_service.BisqSyncStateManager"
        ):
            mock_sync_instance = AsyncMock()
            mock_sync_instance.sync_conversations = AsyncMock(return_value=0)
            mock_sync_class.return_value = mock_sync_instance

            await pipeline_service.sync_bisq_conversations()

            # Verify settings were passed
            call_kwargs = mock_sync_class.call_args[1]
            assert call_kwargs.get("settings") == mock_settings


class TestMatrixSyncIntegration:
    """Test Matrix sync method in UnifiedPipelineService."""

    @pytest.fixture
    def mock_repository(self, tmp_path):
        """Create a mock repository."""
        db_path = str(tmp_path / "test.db")
        return UnifiedFAQCandidateRepository(db_path)

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.MATRIX_ROOM_IDS = ["!room:matrix.org"]
        settings.MATRIX_STAFF_IDS = ["@staff:matrix.org"]
        return settings

    @pytest.fixture
    def pipeline_service(self, mock_repository, mock_settings):
        """Create pipeline service for testing."""
        return UnifiedPipelineService(
            settings=mock_settings,
            rag_service=MagicMock(),
            faq_service=MagicMock(),
            repository=mock_repository,
        )

    def test_pipeline_has_sync_matrix_method(self, pipeline_service):
        """UnifiedPipelineService should have sync_matrix_conversations method."""
        assert hasattr(pipeline_service, "sync_matrix_conversations")
        assert callable(pipeline_service.sync_matrix_conversations)

    @pytest.mark.asyncio
    async def test_sync_matrix_delegates_to_service(
        self, pipeline_service, mock_settings
    ):
        """sync_matrix_conversations should delegate to MatrixSyncService."""
        with patch(
            "app.services.training.unified_pipeline_service.MatrixSyncService"
        ) as mock_sync_class, patch(
            "app.services.training.unified_pipeline_service.PollingStateManager"
        ):
            mock_sync_instance = AsyncMock()
            mock_sync_instance.sync_rooms = AsyncMock(return_value=3)
            mock_sync_class.return_value = mock_sync_instance

            result = await pipeline_service.sync_matrix_conversations()

            mock_sync_class.assert_called_once()
            mock_sync_instance.sync_rooms.assert_called_once()

            assert result == 3

    @pytest.mark.asyncio
    async def test_sync_matrix_returns_processed_count(self, pipeline_service):
        """sync_matrix_conversations should return integer count."""
        with patch(
            "app.services.training.unified_pipeline_service.MatrixSyncService"
        ) as mock_sync_class, patch(
            "app.services.training.unified_pipeline_service.PollingStateManager"
        ):
            mock_sync_instance = AsyncMock()
            mock_sync_instance.sync_rooms = AsyncMock(return_value=7)
            mock_sync_class.return_value = mock_sync_instance

            result = await pipeline_service.sync_matrix_conversations()

            assert isinstance(result, int)
            assert result == 7
