"""Tests for Shadow Mode Repository - Unknown Version Enhancement.

CRITICAL: This test file verifies the Unknown version enhancement database operations:
- 5 new columns: training_protocol, requires_clarification, clarifying_question, source, clarification_answer
- 3 new indexes: idx_shadow_responses_clarification, idx_shadow_responses_version_training, idx_shadow_responses_source
- 29-column INSERT operations (was 24 columns)
- Version confirmation with new parameters
"""

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from app.models.shadow_response import ShadowResponse, ShadowStatus
from app.services.shadow_mode.repository import ShadowModeRepository


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_shadow.db"
        yield str(db_path)


@pytest.fixture
def repository(temp_db):
    """Create repository instance with temporary database."""
    return ShadowModeRepository(temp_db)


@pytest.fixture
def sample_response():
    """Create sample ShadowResponse for testing."""
    return ShadowResponse(
        id="test-id-1",
        channel_id="channel-1",
        user_id="user-1",
        messages=[{"role": "user", "content": "How do I trade?"}],
        synthesized_question="How do I trade?",
        detected_version="Unknown",
        version_confidence=0.30,
        detection_signals={"ambiguous": True},
        status=ShadowStatus.PENDING_VERSION_REVIEW,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestDatabaseSchema:
    """Test suite for database schema with Unknown version enhancement."""

    def test_create_tables_adds_new_columns(self, repository, temp_db):
        """Verify _create_tables() adds 5 new columns for Unknown version enhancement."""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        # Get table schema
        cursor.execute("PRAGMA table_info(shadow_responses)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}  # {name: type}
        conn.close()

        # Verify 5 new columns exist
        assert "training_protocol" in columns, "training_protocol column missing"
        assert (
            "requires_clarification" in columns
        ), "requires_clarification column missing"
        assert "clarifying_question" in columns, "clarifying_question column missing"
        assert "source" in columns, "source column missing"
        assert "clarification_answer" in columns, "clarification_answer column missing"

        # Verify column types
        assert columns["training_protocol"] == "TEXT"
        assert (
            columns["requires_clarification"] == "BOOLEAN"
        )  # SQLite stores as INTEGER
        assert columns["clarifying_question"] == "TEXT"
        assert columns["source"] == "TEXT"
        assert columns["clarification_answer"] == "TEXT"

    def test_create_tables_sets_default_values(self, repository, temp_db):
        """Verify default values: requires_clarification=FALSE, source='shadow_mode'."""
        # Add response WITHOUT specifying new fields
        response = ShadowResponse(
            id="test-defaults",
            channel_id="channel-1",
            user_id="user-1",
            messages=[],
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.add_response(response)

        # Query database directly to check defaults
        conn = sqlite3.connect(temp_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT requires_clarification, source FROM shadow_responses WHERE id = ?",
            ("test-defaults",),
        )
        row = cursor.fetchone()
        conn.close()

        assert row["requires_clarification"] == 0, "Default should be FALSE (0)"
        assert row["source"] == "shadow_mode", "Default source should be 'shadow_mode'"

    def test_create_tables_adds_clarification_index(self, repository, temp_db):
        """Verify idx_shadow_responses_clarification index exists."""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_shadow_responses_clarification'
        """)
        index = cursor.fetchone()
        conn.close()

        assert index is not None, "idx_shadow_responses_clarification index missing"

    def test_create_tables_adds_version_training_index(self, repository, temp_db):
        """Verify idx_shadow_responses_version_training index exists."""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_shadow_responses_version_training'
        """)
        index = cursor.fetchone()
        conn.close()

        assert index is not None, "idx_shadow_responses_version_training index missing"

    def test_create_tables_adds_source_index(self, repository, temp_db):
        """Verify idx_shadow_responses_source index exists."""
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_shadow_responses_source'
        """)
        index = cursor.fetchone()
        conn.close()

        assert index is not None, "idx_shadow_responses_source index missing"


class TestAddResponse:
    """Test suite for add_response() with new fields."""

    def test_add_response_with_training_protocol(self, repository, sample_response):
        """Add response with training_protocol='bisq_easy' - verify 29-column INSERT."""
        # Set new fields
        sample_response.training_protocol = "bisq_easy"
        sample_response.requires_clarification = True
        sample_response.clarifying_question = "Which Bisq version?"

        # Add response
        repository.add_response(sample_response)

        # Retrieve and verify
        retrieved = repository.get_response(sample_response.id)
        assert retrieved is not None
        assert retrieved.training_protocol == "bisq_easy"
        assert retrieved.requires_clarification  # SQLite stores as 1 (truthy)
        assert retrieved.clarifying_question == "Which Bisq version?"

    def test_add_response_with_all_new_fields(self, repository, sample_response):
        """Add response with all 5 new fields populated."""
        # Set ALL new fields
        sample_response.training_protocol = "multisig_v1"
        sample_response.requires_clarification = True
        sample_response.clarifying_question = "Are you using Bisq 1 trading?"
        sample_response.source = "rag_bot_clarification"
        sample_response.clarification_answer = "I'm using Bisq 1"

        # Add response
        repository.add_response(sample_response)

        # Retrieve and verify ALL fields
        retrieved = repository.get_response(sample_response.id)
        assert retrieved.training_protocol == "multisig_v1"
        assert retrieved.requires_clarification  # SQLite stores as 1 (truthy)
        assert retrieved.clarifying_question == "Are you using Bisq 1 trading?"
        assert retrieved.source == "rag_bot_clarification"
        assert retrieved.clarification_answer == "I'm using Bisq 1"

    def test_add_response_with_null_new_fields(self, repository, sample_response):
        """Add response with new fields = None - verify INSERT succeeds."""
        # Explicitly set new fields to None
        sample_response.training_protocol = None
        sample_response.requires_clarification = False
        sample_response.clarifying_question = None
        sample_response.source = "shadow_mode"  # Default
        sample_response.clarification_answer = None

        # Add response
        repository.add_response(sample_response)

        # Retrieve and verify NULL handling
        retrieved = repository.get_response(sample_response.id)
        assert retrieved.training_protocol is None
        assert not retrieved.requires_clarification  # SQLite stores as 0 (falsy)
        assert retrieved.clarifying_question is None
        assert retrieved.source == "shadow_mode"
        assert retrieved.clarification_answer is None


class TestConfirmVersion:
    """Test suite for confirm_version() with new parameters."""

    def test_confirm_version_unknown_with_training_protocol(
        self, repository, sample_response
    ):
        """Confirm version as 'Unknown' with training_protocol='bisq_easy'."""
        # Add initial response
        repository.add_response(sample_response)

        # Confirm as Unknown with training_protocol
        success = repository.confirm_version(
            response_id=sample_response.id,
            confirmed_version="Unknown",
            change_reason="Ambiguous question",
            training_protocol="bisq_easy",
            requires_clarification=True,
            clarifying_question="Which Bisq version are you using?",
        )

        assert success is True

        # Verify all new fields stored
        retrieved = repository.get_response(sample_response.id)
        assert retrieved.confirmed_version == "Unknown"
        assert retrieved.training_protocol == "bisq_easy"
        assert retrieved.requires_clarification  # SQLite stores as 1 (truthy)
        assert retrieved.clarifying_question == "Which Bisq version are you using?"
        assert retrieved.status == ShadowStatus.PENDING_RESPONSE_REVIEW

    def test_confirm_version_stores_clarifying_question(
        self, repository, sample_response
    ):
        """Confirm with custom clarifying_question - verify stored correctly."""
        repository.add_response(sample_response)

        custom_question = "Are you asking about Bisq 1's DAO or Bisq 2's reputation?"
        success = repository.confirm_version(
            response_id=sample_response.id,
            confirmed_version="Unknown",
            training_protocol="multisig_v1",
            clarifying_question=custom_question,
        )

        assert success is True

        retrieved = repository.get_response(sample_response.id)
        assert retrieved.clarifying_question == custom_question

    def test_confirm_version_bisq1_without_training_protocol(
        self, repository, sample_response
    ):
        """Confirm as 'Bisq 1' WITHOUT training_protocol - should succeed."""
        repository.add_response(sample_response)

        success = repository.confirm_version(
            response_id=sample_response.id,
            confirmed_version="Bisq 1",
            change_reason="DAO keywords detected",
            # NO training_protocol, requires_clarification, or clarifying_question
        )

        assert success is True

        retrieved = repository.get_response(sample_response.id)
        assert retrieved.confirmed_version == "Bisq 1"
        assert retrieved.training_protocol is None  # Should remain NULL
        assert not retrieved.requires_clarification  # SQLite stores as 0 (falsy)
        assert retrieved.clarifying_question is None


class TestGetVersionChanges:
    """Test suite for get_version_changes() with new fields."""

    def test_get_version_changes_includes_new_fields(self, repository):
        """Verify get_version_changes() returns all 5 new fields."""
        # Add response with version change
        response = ShadowResponse(
            id="test-change-1",
            channel_id="channel-1",
            user_id="user-1",
            messages=[{"role": "user", "content": "How do I trade?"}],
            synthesized_question="How do I trade?",
            detected_version="Bisq 2",
            version_confidence=0.50,
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.add_response(response)

        # Confirm as Unknown with all new fields
        repository.confirm_version(
            response_id="test-change-1",
            confirmed_version="Unknown",
            change_reason="Needs clarification",
            training_protocol="multisig_v1",
            requires_clarification=True,
            clarifying_question="Which version?",
        )

        # Get version changes
        changes = repository.get_version_changes()

        # Verify returned data includes new fields
        assert len(changes) == 1
        change = changes[0]
        assert change["confirmed_version"] == "Unknown"
        assert change["training_protocol"] == "multisig_v1"
        assert change["requires_clarification"]  # SQLite stores as 1 (truthy)
        assert change["clarifying_question"] == "Which version?"
        # Note: source and clarification_answer should also be included
        assert "source" in change
        assert "clarification_answer" in change

    def test_get_version_changes_filters_by_source(self, repository):
        """Add responses with different sources - verify filtering possible."""
        # Add shadow_mode response
        response1 = ShadowResponse(
            id="shadow-1",
            channel_id="channel-1",
            user_id="user-1",
            messages=[],
            detected_version="Bisq 2",
            source="shadow_mode",
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.add_response(response1)
        repository.confirm_version("shadow-1", "Bisq 1")

        # Add rag_bot_clarification response
        response2 = ShadowResponse(
            id="rag-bot-1",
            channel_id="channel-1",
            user_id="user-1",
            messages=[],
            detected_version="Unknown",
            source="rag_bot_clarification",
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.add_response(response2)
        repository.confirm_version("rag-bot-1", "Bisq 2")

        # Get all changes
        changes = repository.get_version_changes()

        # Verify both sources returned
        sources = [c["source"] for c in changes]
        assert "shadow_mode" in sources
        assert "rag_bot_clarification" in sources


class TestRowToResponse:
    """Test suite for _row_to_response() mapping with new fields."""

    def test_row_to_response_maps_all_new_fields(self, repository, sample_response):
        """Verify _row_to_response() maps all 5 new fields correctly."""
        # Set all new fields
        sample_response.training_protocol = "bisq_easy"
        sample_response.requires_clarification = True
        sample_response.clarifying_question = "Which version?"
        sample_response.source = "rag_bot_clarification"
        sample_response.clarification_answer = "Bisq 2"

        # Add and retrieve (exercises _row_to_response)
        repository.add_response(sample_response)
        retrieved = repository.get_response(sample_response.id)

        # Verify ShadowResponse object has correct values
        assert isinstance(retrieved, ShadowResponse)
        assert retrieved.training_protocol == "bisq_easy"
        assert retrieved.requires_clarification  # SQLite stores as 1 (truthy)
        assert retrieved.clarifying_question == "Which version?"
        assert retrieved.source == "rag_bot_clarification"
        assert retrieved.clarification_answer == "Bisq 2"

    def test_row_to_response_handles_null_new_fields(self, repository, sample_response):
        """Verify _row_to_response() uses correct defaults for NULL fields."""
        # Add response without new fields
        repository.add_response(sample_response)

        # Retrieve (exercises _row_to_response with NULLs)
        retrieved = repository.get_response(sample_response.id)

        # Verify defaults
        assert retrieved.training_protocol is None
        assert not retrieved.requires_clarification  # SQLite stores as 0 (falsy)
        assert retrieved.clarifying_question is None
        assert retrieved.source == "shadow_mode"  # Default
        assert retrieved.clarification_answer is None


class TestSourceWeighting:
    """Test suite for source field behavior (1.5x vs 1.0x weight)."""

    def test_source_defaults_to_shadow_mode(self, repository, sample_response):
        """Verify source defaults to 'shadow_mode' when not specified."""
        # Add response without explicit source
        repository.add_response(sample_response)

        retrieved = repository.get_response(sample_response.id)
        assert retrieved.source == "shadow_mode"

    def test_source_rag_bot_clarification_stored(self, repository, sample_response):
        """Verify source='rag_bot_clarification' stored correctly."""
        sample_response.source = "rag_bot_clarification"
        repository.add_response(sample_response)

        retrieved = repository.get_response(sample_response.id)
        assert retrieved.source == "rag_bot_clarification"


class TestIntegrationScenarios:
    """Integration test scenarios combining multiple operations."""

    def test_admin_marks_unknown_full_workflow(self, repository):
        """Full workflow: Admin marks Unknown → sets training_protocol → RAG generates."""
        # 1. Initial response capture
        response = ShadowResponse(
            id="workflow-1",
            channel_id="channel-1",
            user_id="user-1",
            messages=[{"role": "user", "content": "What are the fees?"}],
            synthesized_question="What are the fees?",
            detected_version="Unknown",
            version_confidence=0.25,
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.add_response(response)

        # 2. Admin confirms as Unknown with training_protocol
        repository.confirm_version(
            response_id="workflow-1",
            confirmed_version="Unknown",
            change_reason="Generic question",
            training_protocol="bisq_easy",
            requires_clarification=True,
            clarifying_question="Are you asking about Bisq 2 or Bisq 1 fees?",
        )

        # 3. Verify status progression
        retrieved = repository.get_response("workflow-1")
        assert retrieved.confirmed_version == "Unknown"
        assert retrieved.training_protocol == "bisq_easy"
        assert retrieved.status == ShadowStatus.PENDING_RESPONSE_REVIEW

    def test_rag_bot_clarification_full_workflow(self, repository):
        """Full workflow: RAG bot asks → User answers → Saved as high-value training."""
        # 1. RAG bot creates clarification request
        response = ShadowResponse(
            id="clarification-1",
            channel_id="channel-1",
            user_id="user-1",
            messages=[
                {"role": "user", "content": "How do I restore my wallet?"},
                {"role": "assistant", "content": "Which Bisq version's wallet?"},
                {"role": "user", "content": "I'm using Bisq 2"},
            ],
            synthesized_question="How do I restore my wallet?",
            detected_version="Bisq 2",  # After user answers
            version_confidence=0.95,  # High confidence from direct answer
            source="rag_bot_clarification",  # CRITICAL: Source weight = 1.5x
            clarification_answer="I'm using Bisq 2",
            status=ShadowStatus.PENDING_VERSION_REVIEW,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.add_response(response)

        # 2. Verify saved with correct source
        retrieved = repository.get_response("clarification-1")
        assert retrieved.source == "rag_bot_clarification"
        assert retrieved.clarification_answer == "I'm using Bisq 2"
        assert retrieved.detected_version == "Bisq 2"
        assert retrieved.version_confidence == 0.95
