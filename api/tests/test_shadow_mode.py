"""Tests for Shadow Mode data model and repository."""

from datetime import datetime, timezone

from app.models.shadow_response import ShadowResponse, ShadowStatus


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
