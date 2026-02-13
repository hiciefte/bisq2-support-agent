"""Tests for Bisq sync deduplication logic.

These tests verify that the sync service correctly tracks processed message IDs
to prevent duplicate FAQ candidates from being created on subsequent polls.

The key bug being tested:
- Input filtering uses Bisq `messageId` from API
- But processed tracking was using `answer_msg_id` from LLM extraction output
- This mismatch caused the same messages to be processed repeatedly
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
from app.channels.plugins.bisq2.services.sync_service import Bisq2SyncService


class TestBisq2SyncDeduplication:
    """Test that Bisq sync correctly prevents duplicate processing."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.BISQ_API_URL = "http://localhost:8090"
        settings.BISQ_STAFF_USERS = ["staff1", "staff2"]
        settings.OPENAI_MODEL = "gpt-4o-mini"
        settings.LLM_TEMPERATURE = 0.1
        settings.MAX_TOKENS = 4096
        return settings

    @pytest.fixture
    def state_manager(self, tmp_path):
        """Create a real state manager with temp file."""
        state_file = str(tmp_path / "bisq_sync_state.json")
        return BisqSyncStateManager(state_file=state_file)

    @pytest.fixture
    def mock_bisq_api(self):
        """Create mock Bisq API."""
        api = AsyncMock()
        return api

    @pytest.fixture
    def mock_pipeline_service(self):
        """Create mock pipeline service."""
        service = MagicMock()
        service.extract_faqs_batch = AsyncMock()
        return service

    @pytest.fixture
    def sync_service(
        self, mock_settings, mock_pipeline_service, mock_bisq_api, state_manager
    ):
        """Create Bisq2SyncService for testing."""
        return Bisq2SyncService(
            settings=mock_settings,
            pipeline_service=mock_pipeline_service,
            bisq_api=mock_bisq_api,
            state_manager=state_manager,
        )

    @pytest.mark.asyncio
    async def test_marks_all_input_messages_as_processed(
        self, sync_service, mock_bisq_api, mock_pipeline_service, state_manager
    ):
        """After sync, ALL input message IDs should be marked as processed.

        This is the core bug fix test. Previously, only the extracted FAQ
        answer_msg_ids were marked, not the input Bisq message IDs.
        """
        # Arrange: 5 input messages from Bisq API
        input_messages = [
            {"messageId": "msg-001", "author": "user1", "message": "Question 1?"},
            {"messageId": "msg-002", "author": "staff1", "message": "Answer 1"},
            {"messageId": "msg-003", "author": "user2", "message": "Question 2?"},
            {"messageId": "msg-004", "author": "staff2", "message": "Answer 2"},
            {"messageId": "msg-005", "author": "user3", "message": "Thanks!"},
        ]
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"messages": input_messages}
        )

        # LLM extracts 1 FAQ pair (answer_msg_id is msg-002)
        mock_result = MagicMock()
        mock_result.candidate_id = 1
        mock_result.source_event_id = "msg-002"  # Only the answer message ID
        mock_result.routing = "FULL_REVIEW"
        mock_pipeline_service.extract_faqs_batch.return_value = [mock_result]

        # Act: Run sync
        await sync_service.sync_conversations()

        # Assert: ALL 5 input message IDs should be marked as processed
        # Not just the 1 answer_msg_id that was extracted
        for msg in input_messages:
            msg_id = msg["messageId"]
            assert state_manager.is_processed(msg_id), (
                f"Message {msg_id} should be marked as processed but wasn't. "
                f"This causes duplicate processing on next poll."
            )

    @pytest.mark.asyncio
    async def test_second_poll_filters_all_previously_seen_messages(
        self, sync_service, mock_bisq_api, mock_pipeline_service, state_manager
    ):
        """On second poll with same messages, none should be sent to LLM.

        This verifies that marking input messages as processed actually
        prevents them from being re-processed on subsequent polls.
        """
        # Arrange: Same 5 messages returned on both polls
        input_messages = [
            {"messageId": "msg-001", "author": "user1", "message": "Question 1?"},
            {"messageId": "msg-002", "author": "staff1", "message": "Answer 1"},
            {"messageId": "msg-003", "author": "user2", "message": "Question 2?"},
            {"messageId": "msg-004", "author": "staff2", "message": "Answer 2"},
            {"messageId": "msg-005", "author": "user3", "message": "Thanks!"},
        ]
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"messages": input_messages}
        )

        # First poll extracts 1 FAQ
        mock_result = MagicMock()
        mock_result.candidate_id = 1
        mock_result.source_event_id = "msg-002"
        mock_result.routing = "FULL_REVIEW"
        mock_pipeline_service.extract_faqs_batch.return_value = [mock_result]

        # Act: First poll
        await sync_service.sync_conversations()

        # Reset mock to track second call
        mock_pipeline_service.extract_faqs_batch.reset_mock()

        # Act: Second poll with same messages
        result = await sync_service.sync_conversations()

        # Assert: extract_faqs_batch should NOT be called (no new messages)
        # Or called with empty list
        if mock_pipeline_service.extract_faqs_batch.called:
            call_args = mock_pipeline_service.extract_faqs_batch.call_args
            messages_sent = call_args[1].get(
                "messages", call_args[0][0] if call_args[0] else []
            )
            assert len(messages_sent) == 0, (
                f"Second poll sent {len(messages_sent)} messages to LLM, "
                f"but all should have been filtered out"
            )

        # Result should be 0 (no new candidates)
        assert result == 0

    @pytest.mark.asyncio
    async def test_new_messages_still_processed_on_second_poll(
        self, sync_service, mock_bisq_api, mock_pipeline_service, state_manager
    ):
        """New messages on second poll should still be processed.

        Verifies that the fix doesn't break the ability to process new messages.
        """
        # First poll: 2 messages
        first_messages = [
            {"messageId": "msg-001", "author": "user1", "message": "Question 1?"},
            {"messageId": "msg-002", "author": "staff1", "message": "Answer 1"},
        ]
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"messages": first_messages}
        )

        mock_result1 = MagicMock()
        mock_result1.candidate_id = 1
        mock_result1.source_event_id = "msg-002"
        mock_result1.routing = "FULL_REVIEW"
        mock_pipeline_service.extract_faqs_batch.return_value = [mock_result1]

        # First poll
        await sync_service.sync_conversations()

        # Second poll: Same 2 messages + 2 NEW messages
        second_messages = [
            {"messageId": "msg-001", "author": "user1", "message": "Question 1?"},
            {"messageId": "msg-002", "author": "staff1", "message": "Answer 1"},
            {
                "messageId": "msg-003",
                "author": "user2",
                "message": "Question 2?",
            },  # NEW
            {"messageId": "msg-004", "author": "staff2", "message": "Answer 2"},  # NEW
        ]
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"messages": second_messages}
        )

        mock_result2 = MagicMock()
        mock_result2.candidate_id = 2
        mock_result2.source_event_id = "msg-004"
        mock_result2.routing = "FULL_REVIEW"
        mock_pipeline_service.extract_faqs_batch.return_value = [mock_result2]

        # Reset mock to track second call
        mock_pipeline_service.extract_faqs_batch.reset_mock()

        # Second poll
        await sync_service.sync_conversations()

        # Assert: Only the 2 NEW messages should be sent to LLM
        assert mock_pipeline_service.extract_faqs_batch.called
        call_args = mock_pipeline_service.extract_faqs_batch.call_args
        messages_sent = call_args[1].get(
            "messages", call_args[0][0] if call_args[0] else []
        )

        assert (
            len(messages_sent) == 2
        ), f"Expected 2 new messages to be sent, got {len(messages_sent)}"

        sent_ids = {m["messageId"] for m in messages_sent}
        assert sent_ids == {
            "msg-003",
            "msg-004",
        }, f"Expected new messages msg-003 and msg-004, got {sent_ids}"

    @pytest.mark.asyncio
    async def test_messages_marked_even_when_no_faqs_extracted(
        self, sync_service, mock_bisq_api, mock_pipeline_service, state_manager
    ):
        """Messages should be marked as processed even if LLM extracts no FAQs.

        If messages are only chatter with no valid Q&A pairs, they should
        still be marked to prevent re-sending them to the LLM repeatedly.
        """
        # Arrange: 3 messages that are just chatter (no Q&A)
        input_messages = [
            {"messageId": "msg-001", "author": "user1", "message": "Hello!"},
            {"messageId": "msg-002", "author": "user2", "message": "Hi there!"},
            {"messageId": "msg-003", "author": "user3", "message": "Good morning!"},
        ]
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"messages": input_messages}
        )

        # LLM extracts 0 FAQ pairs
        mock_pipeline_service.extract_faqs_batch.return_value = []

        # Act: Run sync
        await sync_service.sync_conversations()

        # Assert: All 3 messages should still be marked as processed
        for msg in input_messages:
            msg_id = msg["messageId"]
            assert state_manager.is_processed(msg_id), (
                f"Message {msg_id} should be marked as processed even though "
                f"no FAQs were extracted from it"
            )

    @pytest.mark.asyncio
    async def test_duplicate_candidates_prevented(
        self, sync_service, mock_bisq_api, mock_pipeline_service, state_manager
    ):
        """The same Q&A should not create duplicate candidates on repeated polls.

        This is the end-to-end test for the duplicate bug. Simulates what was
        happening in production: same messages being sent to LLM repeatedly,
        creating duplicate candidates.
        """
        # Same messages on every poll
        input_messages = [
            {
                "messageId": "msg-001",
                "author": "user1",
                "message": "Is Faster Payments available?",
            },
            {
                "messageId": "msg-002",
                "author": "staff1",
                "message": "Yes, FP is available",
            },
        ]
        mock_bisq_api.export_chat_messages = AsyncMock(
            return_value={"messages": input_messages}
        )

        # Track how many times extract_faqs_batch is called
        call_count = 0

        async def counting_extract(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            mock_result.candidate_id = call_count
            mock_result.source_event_id = "msg-002"
            mock_result.routing = "FULL_REVIEW"
            return [mock_result]

        mock_pipeline_service.extract_faqs_batch = AsyncMock(
            side_effect=counting_extract
        )

        # Act: Run sync 3 times (simulating 3 poll intervals)
        for _ in range(3):
            await sync_service.sync_conversations()

        # Assert: LLM extraction should only be called ONCE (first poll)
        # The subsequent polls should filter out already-processed messages
        assert call_count == 1, (
            f"extract_faqs_batch was called {call_count} times, "
            f"but should only be called once. "
            f"Duplicate candidates would be created on each call."
        )


class TestBisqSyncStateManager:
    """Test BisqSyncStateManager persistence and functionality."""

    @pytest.fixture
    def state_file(self, tmp_path):
        """Create temp state file path."""
        return str(tmp_path / "bisq_sync_state.json")

    def test_new_manager_has_no_processed_ids(self, state_file):
        """New state manager should have empty processed set."""
        manager = BisqSyncStateManager(state_file=state_file)
        assert len(manager.processed_message_ids) == 0

    def test_mark_processed_adds_to_set(self, state_file):
        """mark_processed should add ID to the set."""
        manager = BisqSyncStateManager(state_file=state_file)

        manager.mark_processed("msg-001")
        manager.mark_processed("msg-002")

        assert manager.is_processed("msg-001")
        assert manager.is_processed("msg-002")
        assert not manager.is_processed("msg-003")

    def test_state_persists_across_instances(self, state_file):
        """Processed IDs should persist when reloading from file."""
        # First instance
        manager1 = BisqSyncStateManager(state_file=state_file)
        manager1.mark_processed("msg-001")
        manager1.mark_processed("msg-002")
        manager1.update_last_sync(datetime.now(timezone.utc))
        manager1.save_state()

        # Second instance loads from same file
        manager2 = BisqSyncStateManager(state_file=state_file)

        assert manager2.is_processed("msg-001")
        assert manager2.is_processed("msg-002")
        assert not manager2.is_processed("msg-003")

    def test_mark_batch_processed(self, state_file):
        """Test marking multiple IDs as processed efficiently."""
        manager = BisqSyncStateManager(state_file=state_file)

        ids_to_mark = ["msg-001", "msg-002", "msg-003", "msg-004", "msg-005"]

        # The fix should provide a way to mark multiple IDs at once
        # Currently this tests the basic functionality
        for msg_id in ids_to_mark:
            manager.mark_processed(msg_id)

        for msg_id in ids_to_mark:
            assert manager.is_processed(msg_id)
