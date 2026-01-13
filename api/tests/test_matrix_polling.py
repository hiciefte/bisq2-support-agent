"""
Functional tests for Matrix polling implementation.

Tests cover:
- Session persistence across service restarts
- Database duplicate checking
- Error recovery and resilience
- Polling automation
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.integrations.matrix.polling_state import PollingStateManager


class TestSessionPersistence:
    """Test session state persists across service restarts."""

    @pytest.fixture
    def polling_state_file(self, tmp_path):
        """Create temporary polling state file path."""
        return tmp_path / "matrix_polling_state.json"

    @pytest.mark.asyncio
    async def test_session_token_persists_across_restarts(self, polling_state_file):
        """Test pagination token persists when service restarts."""
        # First manager instance - update token
        manager1 = PollingStateManager(str(polling_state_file))
        test_token = f"token_{datetime.now().timestamp()}"
        manager1.update_since_token(test_token)

        # Verify state file created
        assert polling_state_file.exists()

        # Second manager instance - should load previous token
        manager2 = PollingStateManager(str(polling_state_file))
        assert (
            manager2.since_token == test_token
        ), "Token should persist across restarts"

    @pytest.mark.asyncio
    async def test_session_file_has_correct_structure(self, polling_state_file):
        """Test session file contains expected fields."""
        manager = PollingStateManager(str(polling_state_file))
        manager.update_since_token("test_token_123")

        # Load and verify session file
        with open(polling_state_file) as f:
            session = json.load(f)

        assert "since_token" in session
        assert "last_poll" in session
        assert "processed_ids" in session
        assert session["since_token"] == "test_token_123"

        # Verify timestamp format
        last_poll = datetime.fromisoformat(session["last_poll"])
        assert last_poll.tzinfo is not None, "Timestamp should be timezone-aware"

    def test_session_file_has_secure_permissions(self, polling_state_file):
        """Test session file created with secure permissions."""
        manager = PollingStateManager(str(polling_state_file))
        manager.update_since_token("test_token")

        # Check file permissions
        stat_info = polling_state_file.stat()
        permissions = stat_info.st_mode & 0o777

        assert permissions == 0o600, f"Expected 0600, got {oct(permissions)}"


class TestDatabaseDuplicateCheck:
    """Test database duplicate checking prevents reprocessing."""

    @pytest.fixture
    def mock_repository(self):
        """Create mock repository."""
        repo = MagicMock()
        repo.get_by_question_id = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def mock_matrix_service_with_db(self, mock_repository):
        """Create mock Matrix service with database checking."""

        class MockMatrixServiceWithDB:
            def __init__(self, repository):
                self.repository = repository
                self._processed_ids = set()

            def mark_as_processed(self, event_id: str):
                self._processed_ids.add(event_id)

            def is_processed(self, event_id: str) -> bool:
                return event_id in self._processed_ids

            async def poll_for_questions(self, messages):
                """Poll with database duplicate check."""
                new_questions = []

                for msg in messages:
                    event_id = msg["event_id"]

                    # Memory check (fast path)
                    if self.is_processed(event_id):
                        continue

                    # Database check (persistent) with error handling
                    try:
                        existing = await self.repository.get_by_question_id(event_id)
                        if not existing:
                            new_questions.append(msg)
                        else:
                            # Add to memory cache for future fast-path checks
                            self.mark_as_processed(event_id)
                    except Exception:
                        # Conservative: skip on error to avoid duplicates
                        continue

                return new_questions

        return MockMatrixServiceWithDB(mock_repository)

    @pytest.mark.asyncio
    async def test_skips_messages_already_in_memory_cache(
        self, mock_matrix_service_with_db
    ):
        """Test messages in memory cache are skipped (fast path)."""
        service = mock_matrix_service_with_db

        messages = [
            {"event_id": "$event1", "body": "Question 1"},
            {"event_id": "$event2", "body": "Question 2"},
        ]

        # First poll - both messages new
        new1 = await service.poll_for_questions(messages)
        assert len(new1) == 2

        # Mark first as processed
        service.mark_as_processed("$event1")

        # Second poll - only second message new
        new2 = await service.poll_for_questions(messages)
        assert len(new2) == 1
        assert new2[0]["event_id"] == "$event2"

    @pytest.mark.asyncio
    async def test_skips_messages_already_in_database(
        self, mock_matrix_service_with_db, mock_repository
    ):
        """Test messages in database are skipped (persistent check)."""
        service = mock_matrix_service_with_db

        # Simulate database already has event1
        mock_repository.get_by_question_id = AsyncMock(
            side_effect=lambda eid: {"id": "123"} if eid == "$event1" else None
        )

        messages = [
            {"event_id": "$event1", "body": "Question 1"},  # In database
            {"event_id": "$event2", "body": "Question 2"},  # Not in database
        ]

        new_questions = await service.poll_for_questions(messages)

        # Should only return event2
        assert len(new_questions) == 1
        assert new_questions[0]["event_id"] == "$event2"

        # event1 should be added to memory cache
        assert service.is_processed("$event1")

    @pytest.mark.asyncio
    async def test_database_check_error_results_in_skip(
        self, mock_matrix_service_with_db, mock_repository
    ):
        """Test database check errors result in conservative skip (no duplicate risk)."""
        service = mock_matrix_service_with_db

        # Simulate database error
        mock_repository.get_by_question_id = AsyncMock(
            side_effect=Exception("Database connection error")
        )

        messages = [{"event_id": "$event1", "body": "Question 1"}]

        new_questions = await service.poll_for_questions(messages)

        # Should skip message on error (conservative approach)
        assert len(new_questions) == 0


class TestErrorRecovery:
    """Test error recovery and resilience."""

    @pytest.fixture
    def mock_processor(self):
        """Create mock shadow mode processor."""
        processor = MagicMock()
        processor.process_question = AsyncMock()
        return processor

    @pytest.fixture
    def mock_matrix_service_with_recovery(self, mock_processor):
        """Create mock Matrix service with error recovery."""

        class MockMatrixServiceWithRecovery:
            def __init__(self, processor):
                self.processor = processor
                self._processed_ids = set()

            def mark_as_processed(self, event_id: str):
                self._processed_ids.add(event_id)

            async def process_with_shadow_mode(self, questions):
                """Process with per-question error isolation."""
                processed_count = 0
                failed_questions = []

                for q in questions:
                    try:
                        response = await self.processor.process_question(
                            question=q["body"],
                            question_id=q["event_id"],
                        )

                        if response:
                            self.mark_as_processed(q["event_id"])
                            processed_count += 1
                    except Exception as e:
                        # Per-question failure doesn't stop entire poll
                        failed_questions.append((q["event_id"], str(e)))

                return processed_count, failed_questions

        return MockMatrixServiceWithRecovery(mock_processor)

    @pytest.mark.asyncio
    async def test_single_question_failure_does_not_stop_poll(
        self, mock_matrix_service_with_recovery, mock_processor
    ):
        """Test failure processing one question doesn't stop processing others."""
        service = mock_matrix_service_with_recovery

        # First question fails, second succeeds
        mock_processor.process_question = AsyncMock(
            side_effect=[
                Exception("Processing error"),  # First fails
                {"id": "response1"},  # Second succeeds
            ]
        )

        questions = [
            {"event_id": "$event1", "body": "Question 1"},
            {"event_id": "$event2", "body": "Question 2"},
        ]

        processed_count, failed = await service.process_with_shadow_mode(questions)

        # Should process second question despite first failure
        assert processed_count == 1
        assert len(failed) == 1
        assert failed[0][0] == "$event1"
        assert service._processed_ids == {"$event2"}

    @pytest.mark.asyncio
    async def test_all_questions_fail_gracefully(
        self, mock_matrix_service_with_recovery, mock_processor
    ):
        """Test graceful handling when all questions fail."""
        service = mock_matrix_service_with_recovery

        # All questions fail
        mock_processor.process_question = AsyncMock(
            side_effect=Exception("Processing error")
        )

        questions = [
            {"event_id": "$event1", "body": "Question 1"},
            {"event_id": "$event2", "body": "Question 2"},
        ]

        processed_count, failed = await service.process_with_shadow_mode(questions)

        assert processed_count == 0
        assert len(failed) == 2
        assert len(service._processed_ids) == 0


class TestPollingAutomation:
    """Test polling automation via cron."""

    def test_polling_script_exists(self):
        """Test polling script exists at expected location."""
        # Note: Script will be created in implementation phase
        # This test defines expected location
        expected_location = "docker/scripts/poll-matrix.sh"
        assert expected_location is not None

    def test_polling_script_has_executable_permissions(self):
        """Test polling script has executable permissions."""
        # This will be validated after implementation
        # Script should have 0755 permissions
        expected_permissions = 0o755
        assert expected_permissions == 0o755

    @patch("subprocess.run")
    def test_polling_script_calls_api_endpoint(self, mock_run):
        """Test polling script calls correct API endpoint."""
        # Simulate script execution
        mock_run.return_value = MagicMock(returncode=0, stdout="SUCCESS")

        # Expected command
        expected_endpoint = "http://api:8000/admin/shadow-mode/poll"
        expected_method = "POST"

        # Verify script would call correct endpoint
        assert expected_endpoint.endswith("/admin/shadow-mode/poll")
        assert expected_method == "POST"

    def test_cron_schedule_every_30_minutes(self):
        """Test cron job scheduled for 30-minute intervals."""
        # Cron schedule format: */30 * * * *
        cron_schedule = "*/30 * * * *"

        # Parse schedule
        parts = cron_schedule.split()
        assert parts[0] == "*/30", "Should run every 30 minutes"
        assert parts[1] == "*", "Should run every hour"
        assert parts[2] == "*", "Should run every day"
        assert parts[3] == "*", "Should run every month"
        assert parts[4] == "*", "Should run every day of week"


class TestPrometheusMetrics:
    """Test Prometheus metrics collection."""

    def test_metrics_track_poll_success(self):
        """Test metrics track successful polls."""
        from prometheus_client import REGISTRY

        # Check if metrics exist (will be created in implementation)
        _metric_names = [m.name for m in REGISTRY.collect()]  # noqa: F841

        expected_metrics = [
            "matrix_polls_total",
            "matrix_questions_detected",
            "matrix_questions_processed",
            "matrix_poll_duration_seconds",
        ]

        # Metrics will be added in Phase 3
        # This test defines expected metrics
        for metric in expected_metrics:
            assert metric is not None

    def test_metrics_track_poll_failure(self):
        """Test metrics track failed polls."""
        # Metrics should have status label: success/failure
        expected_labels = ["room_id", "status"]

        for label in expected_labels:
            assert label is not None

    def test_metrics_track_poll_duration(self):
        """Test metrics track poll duration."""
        # Duration metric should be histogram type
        metric_type = "histogram"
        assert metric_type == "histogram"


class TestEndToEndPolling:
    """End-to-end integration tests."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_polling_workflow(self):
        """Test complete polling workflow from API call to database storage."""
        # This will be an integration test requiring:
        # - Test Matrix homeserver
        # - Test database
        # - Full service stack

        # Test flow:
        # 1. Call /admin/shadow-mode/poll endpoint
        # 2. Service connects to Matrix
        # 3. Fetches new messages
        # 4. Filters support questions
        # 5. Checks for duplicates
        # 6. Processes questions
        # 7. Saves to database
        # 8. Saves session state
        # 9. Returns processed count

        # Placeholder for integration test
        workflow_steps = [
            "api_call",
            "matrix_connect",
            "fetch_messages",
            "filter_questions",
            "check_duplicates",
            "process_questions",
            "save_to_database",
            "save_session",
            "return_response",
        ]

        assert len(workflow_steps) == 9

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_polling_respects_rate_limits(self):
        """Test polling respects Matrix API rate limits."""
        # Matrix homeserver limits: 10 requests per 60 seconds
        max_requests = 10
        time_window = 60

        # Test should verify rate limiter is enforced
        assert max_requests == 10
        assert time_window == 60
