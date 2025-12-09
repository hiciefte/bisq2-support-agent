"""Tests for Shadow Mode data model and repository."""

import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.services.shadow_mode.repository import ShadowModeRepository


class TestShadowStatus:
    """Tests for ShadowStatus enum."""

    def test_status_values(self):
        """Test all status enum values exist."""
        assert ShadowStatus.PENDING_VERSION_REVIEW == "pending_version_review"
        assert ShadowStatus.PENDING_RESPONSE_REVIEW == "pending_response_review"
        assert ShadowStatus.RAG_FAILED == "rag_failed"
        assert ShadowStatus.APPROVED == "approved"
        assert ShadowStatus.EDITED == "edited"
        assert ShadowStatus.REJECTED == "rejected"
        assert ShadowStatus.SKIPPED == "skipped"

    def test_status_is_string_enum(self):
        """Test status values are strings."""
        for status in ShadowStatus:
            assert isinstance(status.value, str)


class TestShadowResponse:
    """Tests for ShadowResponse dataclass."""

    def test_create_minimal_response(self):
        """Test creating response with minimal required fields."""
        response = ShadowResponse(
            id="test-123",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[
                {"content": "Test question", "timestamp": "2024-01-01T10:00:00Z"}
            ],
        )

        assert response.id == "test-123"
        assert response.channel_id == "room-abc"
        assert response.user_id == "user-xyz"
        assert len(response.messages) == 1
        assert response.status == ShadowStatus.PENDING_VERSION_REVIEW
        assert response.version_confidence == 0.0
        assert response.retry_count == 0

    def test_create_full_response(self):
        """Test creating response with all fields."""
        now = datetime.now(timezone.utc)
        response = ShadowResponse(
            id="test-456",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[
                {
                    "content": "My trade is stuck",
                    "timestamp": "2024-01-01T10:00:00Z",
                    "sender_type": "user",
                },
                {
                    "content": "Can you provide details?",
                    "timestamp": "2024-01-01T10:01:00Z",
                    "sender_type": "support",
                },
            ],
            synthesized_question="My trade is stuck and I need help",
            detected_version="bisq2",
            version_confidence=0.85,
            detection_signals={"explicit_mention": 0.9, "feature_patterns": 0.8},
            confirmed_version="bisq2",
            version_change_reason=None,
            preprocessed={"embedding": [0.1, 0.2]},
            generated_response="Here's how to resolve...",
            sources=[{"title": "Trade Help", "type": "wiki"}],
            edited_response=None,
            status=ShadowStatus.PENDING_RESPONSE_REVIEW,
            rag_error=None,
            retry_count=0,
            created_at=now,
            updated_at=now,
        )

        assert response.detected_version == "bisq2"
        assert response.version_confidence == 0.85
        assert len(response.messages) == 2
        assert response.status == ShadowStatus.PENDING_RESPONSE_REVIEW

    def test_messages_structure(self):
        """Test message structure with all fields."""
        response = ShadowResponse(
            id="test-789",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[
                {
                    "content": "Help with trade",
                    "timestamp": "2024-01-01T10:00:00Z",
                    "sender_type": "user",
                    "message_id": "msg-001",
                },
            ],
        )

        msg = response.messages[0]
        assert msg["content"] == "Help with trade"
        assert msg["sender_type"] == "user"
        assert msg["message_id"] == "msg-001"

    def test_default_timestamps(self):
        """Test that timestamps default to current UTC time."""
        response = ShadowResponse(
            id="test-time",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
        )

        assert response.created_at is not None
        assert response.updated_at is not None
        assert response.created_at.tzinfo == timezone.utc

    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        response = ShadowResponse(
            id="test-dict",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            detected_version="bisq2",
            version_confidence=0.75,
        )

        data = response.to_dict()

        assert data["id"] == "test-dict"
        assert data["detected_version"] == "bisq2"
        assert data["version_confidence"] == 0.75
        assert data["status"] == "pending_version_review"
        assert isinstance(data["messages"], list)
        assert isinstance(data["created_at"], str)

    def test_from_dict_deserialization(self):
        """Test deserialization from dictionary."""
        data = {
            "id": "test-from-dict",
            "channel_id": "room-abc",
            "user_id": "user-xyz",
            "messages": [{"content": "Test question"}],
            "detected_version": "bisq1",
            "version_confidence": 0.65,
            "status": "pending_response_review",
            "created_at": "2024-01-01T10:00:00+00:00",
            "updated_at": "2024-01-01T10:00:00+00:00",
        }

        response = ShadowResponse.from_dict(data)

        assert response.id == "test-from-dict"
        assert response.detected_version == "bisq1"
        assert response.status == ShadowStatus.PENDING_RESPONSE_REVIEW


class TestShadowModeRepositoryV2:
    """Tests for ShadowModeRepositoryV2."""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database file."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def repository(self, temp_db):
        """Create repository instance with temp database."""
        return ShadowModeRepositoryV2(temp_db)

    def test_create_tables(self, repository):
        """Test database tables are created."""
        # Tables should be created during init
        import sqlite3

        conn = sqlite3.connect(repository.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_responses_v2'"
        )
        result = cursor.fetchone()
        conn.close()

        assert result is not None
        assert result[0] == "shadow_responses_v2"

    def test_add_response(self, repository):
        """Test adding a new response."""
        response = ShadowResponse(
            id="add-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test question"}],
            detected_version="bisq2",
            version_confidence=0.8,
        )

        repository.add_response(response)

        retrieved = repository.get_response("add-test-1")
        assert retrieved is not None
        assert retrieved.id == "add-test-1"
        assert retrieved.detected_version == "bisq2"

    def test_get_response_not_found(self, repository):
        """Test getting non-existent response returns None."""
        result = repository.get_response("non-existent")
        assert result is None

    def test_update_response(self, repository):
        """Test updating response fields."""
        response = ShadowResponse(
            id="update-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            status=ShadowStatus.PENDING_VERSION_REVIEW,
        )
        repository.add_response(response)

        # Update with confirmed version
        repository.update_response(
            "update-test-1",
            {
                "confirmed_version": "bisq2",
                "status": ShadowStatus.PENDING_RESPONSE_REVIEW.value,
            },
        )

        updated = repository.get_response("update-test-1")
        assert updated.confirmed_version == "bisq2"
        assert updated.status == ShadowStatus.PENDING_RESPONSE_REVIEW

    def test_get_responses_by_status(self, repository):
        """Test filtering responses by status."""
        # Add responses with different statuses
        for i, status in enumerate(
            [
                ShadowStatus.PENDING_VERSION_REVIEW,
                ShadowStatus.PENDING_VERSION_REVIEW,
                ShadowStatus.PENDING_RESPONSE_REVIEW,
            ]
        ):
            response = ShadowResponse(
                id=f"status-test-{i}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": f"Test {i}"}],
                status=status,
            )
            repository.add_response(response)

        version_review = repository.get_responses(status="pending_version_review")
        assert len(version_review) == 2

        response_review = repository.get_responses(status="pending_response_review")
        assert len(response_review) == 1

    def test_get_responses_pagination(self, repository):
        """Test pagination of responses."""
        # Add 10 responses
        for i in range(10):
            response = ShadowResponse(
                id=f"page-test-{i}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": f"Test {i}"}],
            )
            repository.add_response(response)

        # Get first page
        page1 = repository.get_responses(limit=5, offset=0)
        assert len(page1) == 5

        # Get second page
        page2 = repository.get_responses(limit=5, offset=5)
        assert len(page2) == 5

        # IDs should be different
        page1_ids = {r.id for r in page1}
        page2_ids = {r.id for r in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_delete_response(self, repository):
        """Test deleting a response."""
        response = ShadowResponse(
            id="delete-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
        )
        repository.add_response(response)

        result = repository.delete_response("delete-test-1")
        assert result is True

        # Should be gone
        retrieved = repository.get_response("delete-test-1")
        assert retrieved is None

    def test_delete_all_responses(self, repository):
        """Test deleting all responses."""
        # Add multiple responses
        for i in range(3):
            response = ShadowResponse(
                id=f"delete-all-{i}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": f"Test {i}"}],
            )
            repository.add_response(response)

        count = repository.delete_all_responses()
        assert count == 3

        # All should be gone
        all_responses = repository.get_responses()
        assert len(all_responses) == 0

    def test_get_stats(self, repository):
        """Test getting statistics."""
        # Add responses with different statuses
        statuses = [
            ShadowStatus.PENDING_VERSION_REVIEW,
            ShadowStatus.PENDING_RESPONSE_REVIEW,
            ShadowStatus.APPROVED,
            ShadowStatus.APPROVED,
            ShadowStatus.EDITED,
            ShadowStatus.REJECTED,
        ]

        for i, status in enumerate(statuses):
            response = ShadowResponse(
                id=f"stats-test-{i}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": f"Test {i}"}],
                status=status,
                version_confidence=0.5 + (i * 0.05),
            )
            repository.add_response(response)

        stats = repository.get_stats()

        assert stats["total"] == 6
        assert stats["pending_version_review"] == 1
        assert stats["pending_response_review"] == 1
        assert stats["approved"] == 2
        assert stats["edited"] == 1
        assert stats["rejected"] == 1

    def test_json_serialization_messages(self, repository):
        """Test that messages are properly serialized to JSON."""
        messages = [
            {"content": "First message", "timestamp": "2024-01-01T10:00:00Z"},
            {"content": "Second message", "timestamp": "2024-01-01T10:01:00Z"},
        ]

        response = ShadowResponse(
            id="json-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=messages,
        )
        repository.add_response(response)

        retrieved = repository.get_response("json-test-1")
        assert len(retrieved.messages) == 2
        assert retrieved.messages[0]["content"] == "First message"
        assert retrieved.messages[1]["content"] == "Second message"

    def test_json_serialization_sources(self, repository):
        """Test that sources are properly serialized to JSON."""
        sources = [
            {"title": "Wiki Article", "type": "wiki", "content": "..."},
            {"title": "FAQ Entry", "type": "faq", "content": "..."},
        ]

        response = ShadowResponse(
            id="sources-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            sources=sources,
        )
        repository.add_response(response)

        retrieved = repository.get_response("sources-test-1")
        assert len(retrieved.sources) == 2
        assert retrieved.sources[0]["title"] == "Wiki Article"

    def test_update_rag_error(self, repository):
        """Test updating RAG error status."""
        response = ShadowResponse(
            id="error-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            status=ShadowStatus.PENDING_RESPONSE_REVIEW,
        )
        repository.add_response(response)

        # Simulate RAG failure
        repository.update_response(
            "error-test-1",
            {
                "status": ShadowStatus.RAG_FAILED.value,
                "rag_error": "Failed to retrieve documents",
                "retry_count": 1,
            },
        )

        updated = repository.get_response("error-test-1")
        assert updated.status == ShadowStatus.RAG_FAILED
        assert updated.rag_error == "Failed to retrieve documents"
        assert updated.retry_count == 1

    def test_responses_ordered_by_created_at(self, repository):
        """Test that responses are returned in order by created_at desc."""
        import time

        # Add responses with slight time gaps
        for i in range(3):
            response = ShadowResponse(
                id=f"order-test-{i}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": f"Test {i}"}],
            )
            repository.add_response(response)
            time.sleep(0.01)  # Small delay to ensure different timestamps

        responses = repository.get_responses()

        # Should be in reverse chronological order (newest first)
        assert responses[0].id == "order-test-2"
        assert responses[2].id == "order-test-0"


class TestVersionConfirmationAPI:
    """Tests for Phase 3: Version Confirmation API endpoints."""

    @pytest.fixture
    def repository(self, tmp_path):
        """Create a repository for testing."""
        db_path = str(tmp_path / "test.db")
        return ShadowModeRepositoryV2(db_path)

    def test_confirm_version_updates_status(self, repository):
        """Test that confirming version moves response to pending_response_review."""
        response = ShadowResponse(
            id="confirm-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "My trade is stuck"}],
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            detected_version="bisq2",
            version_confidence=0.65,
        )
        repository.add_response(response)

        # Confirm version (same as detected)
        repository.confirm_version(
            "confirm-test-1",
            confirmed_version="bisq2",
            change_reason=None,
        )

        updated = repository.get_response("confirm-test-1")
        assert updated.status == ShadowStatus.PENDING_RESPONSE_REVIEW
        assert updated.confirmed_version == "bisq2"
        assert updated.version_change_reason is None

    def test_confirm_version_with_change(self, repository):
        """Test confirming with different version stores reason."""
        response = ShadowResponse(
            id="confirm-test-2",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "My trade is stuck"}],
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            detected_version="bisq2",
            version_confidence=0.55,
        )
        repository.add_response(response)

        # Confirm different version with reason
        repository.confirm_version(
            "confirm-test-2",
            confirmed_version="bisq1",
            change_reason="User mentioned desktop app later",
        )

        updated = repository.get_response("confirm-test-2")
        assert updated.status == ShadowStatus.PENDING_RESPONSE_REVIEW
        assert updated.confirmed_version == "bisq1"
        assert updated.version_change_reason == "User mentioned desktop app later"

    def test_confirm_version_invalid_status(self, repository):
        """Test confirming version from wrong status raises error."""
        response = ShadowResponse(
            id="confirm-test-3",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            status=ShadowStatus.APPROVED,  # Wrong status
        )
        repository.add_response(response)

        with pytest.raises(ValueError, match="Cannot confirm version"):
            repository.confirm_version(
                "confirm-test-3",
                confirmed_version="bisq2",
            )

    def test_skip_version_review(self, repository):
        """Test skipping version review."""
        response = ShadowResponse(
            id="skip-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            status=ShadowStatus.PENDING_VERSION_REVIEW,
        )
        repository.add_response(response)

        repository.skip_response("skip-test-1")

        updated = repository.get_response("skip-test-1")
        assert updated.status == ShadowStatus.SKIPPED

    def test_retry_rag_success(self, repository):
        """Test retrying RAG from failed state."""
        response = ShadowResponse(
            id="retry-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            status=ShadowStatus.RAG_FAILED,
            rag_error="Connection timeout",
            retry_count=1,
        )
        repository.add_response(response)

        # Simulate retry success
        repository.update_rag_result(
            "retry-test-1",
            generated_response="Here's the answer...",
            sources=[{"title": "Wiki"}],
            rag_error=None,
        )

        updated = repository.get_response("retry-test-1")
        assert updated.status == ShadowStatus.PENDING_RESPONSE_REVIEW
        assert updated.generated_response == "Here's the answer..."
        assert updated.rag_error is None
        assert updated.retry_count == 2

    def test_retry_rag_failure(self, repository):
        """Test retry that fails again."""
        response = ShadowResponse(
            id="retry-test-2",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            status=ShadowStatus.RAG_FAILED,
            rag_error="First error",
            retry_count=1,
        )
        repository.add_response(response)

        # Simulate another failure
        repository.update_rag_result(
            "retry-test-2",
            generated_response=None,
            sources=[],
            rag_error="Connection timeout again",
        )

        updated = repository.get_response("retry-test-2")
        assert updated.status == ShadowStatus.RAG_FAILED
        assert updated.rag_error == "Connection timeout again"
        assert updated.retry_count == 2

    def test_get_version_change_events(self, repository):
        """Test retrieving version change events for training."""
        # Create and confirm with change
        response1 = ShadowResponse(
            id="change-test-1",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test"}],
            detected_version="bisq2",
            version_confidence=0.6,
        )
        repository.add_response(response1)
        repository.confirm_version(
            "change-test-1",
            confirmed_version="bisq1",
            change_reason="Desktop app mentioned",
        )

        # Create and confirm without change
        response2 = ShadowResponse(
            id="change-test-2",
            channel_id="room-abc",
            user_id="user-xyz",
            messages=[{"content": "Test 2"}],
            detected_version="bisq2",
            version_confidence=0.9,
        )
        repository.add_response(response2)
        repository.confirm_version(
            "change-test-2",
            confirmed_version="bisq2",
        )

        # Get only changes (for training data)
        changes = repository.get_version_changes()
        assert len(changes) == 1
        assert changes[0]["id"] == "change-test-1"
        assert changes[0]["detected_version"] == "bisq2"
        assert changes[0]["confirmed_version"] == "bisq1"

    def test_filter_by_status(self, repository):
        """Test filtering responses by status."""
        # Create responses with different statuses
        for status in [
            ShadowStatus.PENDING_VERSION_REVIEW,
            ShadowStatus.PENDING_RESPONSE_REVIEW,
            ShadowStatus.RAG_FAILED,
        ]:
            response = ShadowResponse(
                id=f"filter-{status.value}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": "Test"}],
                status=status,
            )
            repository.add_response(response)

        # Filter by version review
        version_review = repository.get_responses(
            status=ShadowStatus.PENDING_VERSION_REVIEW.value
        )
        assert len(version_review) == 1
        assert version_review[0].status == ShadowStatus.PENDING_VERSION_REVIEW

        # Filter by response review
        response_review = repository.get_responses(
            status=ShadowStatus.PENDING_RESPONSE_REVIEW.value
        )
        assert len(response_review) == 1

    def test_get_stats_v2(self, repository):
        """Test getting statistics with new status types."""
        # Add various statuses
        statuses = [
            ShadowStatus.PENDING_VERSION_REVIEW,
            ShadowStatus.PENDING_VERSION_REVIEW,
            ShadowStatus.PENDING_RESPONSE_REVIEW,
            ShadowStatus.RAG_FAILED,
            ShadowStatus.APPROVED,
        ]

        for i, status in enumerate(statuses):
            response = ShadowResponse(
                id=f"stats-test-{i}",
                channel_id="room-abc",
                user_id="user-xyz",
                messages=[{"content": "Test"}],
                status=status,
                version_confidence=0.7 if i < 3 else 0.9,
            )
            repository.add_response(response)

        stats = repository.get_stats()
        assert stats["total"] == 5
        assert stats["pending_version_review"] == 2
        assert stats["pending_response_review"] == 1
        assert stats["rag_failed"] == 1
        assert stats["approved"] == 1
