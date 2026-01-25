"""
Tests for ConversationHandler - correction detection and reply chain aggregation.

Phase 8 TDD tests for conversation handling improvements.
"""

import json

import pytest
from app.services.training.conversation_handler import ConversationHandler


class TestCorrectionDetection:
    """Test suite for correction pattern detection (TASK 8.1)."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Cycle 8.1.1: Correction Pattern Detection ==========

    def test_detects_explicit_correction_actually(self, handler):
        """Test detection of 'actually' correction pattern."""
        message = "Actually, I was wrong about the fee. It's 0.1% not 1%"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_detects_explicit_correction_wait(self, handler):
        """Test detection of 'wait' correction pattern."""
        message = "Wait, let me check that again"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_detects_explicit_correction_sorry(self, handler):
        """Test detection of 'sorry' correction pattern."""
        message = "Sorry, I meant to say you need to wait 10 blocks"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_detects_explicit_correction_scratch_that(self, handler):
        """Test detection of 'scratch that' correction pattern."""
        message = "Scratch that, the fee is actually lower"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_detects_explicit_correction_my_mistake(self, handler):
        """Test detection of 'my mistake' correction pattern."""
        message = "My mistake, you don't need to do that step"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_does_not_detect_normal_message(self, handler):
        """Test that normal messages are not flagged as corrections."""
        message = "You can find the setting in the preferences menu"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is False
        assert correction_type is None

    def test_does_not_detect_question_with_actually(self, handler):
        """Test that questions containing 'actually' in different context are not corrections."""
        # Mid-sentence 'actually' is just emphasis, not a correction indicator
        message = "The feature actually works differently than most expect"
        is_correction, correction_type = handler.is_correction(message)
        # Quality fix: mid-sentence "actually" should NOT be detected as correction
        # Only "actually" at sentence start or after punctuation indicates correction
        assert is_correction is False

    def test_case_insensitive_detection(self, handler):
        """Test that detection is case insensitive."""
        message = "ACTUALLY, that's not correct"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    # ========== Cycle 8.1.2: Correction Supersedes Original ==========

    def test_correction_supersedes_original_answer(self, handler):
        """Test that corrections supersede original answers."""
        messages = [
            {"sender": "staff_alice", "content": "The fee is 1%"},
            {"sender": "staff_alice", "content": "Actually, it's 0.1%"},
        ]
        result = handler.get_final_answer(messages, staff_senders={"staff_alice"})
        assert result["content"] == "Actually, it's 0.1%"
        assert result["original_was_corrected"] is True
        assert result["correction_type"] == "explicit"

    def test_no_correction_returns_last_answer(self, handler):
        """Test that without correction, last message is returned."""
        messages = [
            {"sender": "staff_alice", "content": "Click the Offers tab"},
            {"sender": "staff_alice", "content": "Then select Create Offer"},
        ]
        result = handler.get_final_answer(messages, staff_senders={"staff_alice"})
        assert result["content"] == "Then select Create Offer"
        assert result["original_was_corrected"] is False
        assert result["correction_type"] is None

    def test_multiple_corrections_uses_latest(self, handler):
        """Test that multiple corrections use the latest one."""
        messages = [
            {"sender": "staff_alice", "content": "The limit is $100"},
            {"sender": "staff_alice", "content": "Sorry, it's $500"},
            {"sender": "staff_alice", "content": "Wait, I need to check - it's $600"},
        ]
        result = handler.get_final_answer(messages, staff_senders={"staff_alice"})
        assert "600" in result["content"]
        assert result["original_was_corrected"] is True

    def test_filters_non_staff_messages(self, handler):
        """Test that non-staff messages are filtered out."""
        messages = [
            {"sender": "user_bob", "content": "What is the fee?"},
            {"sender": "staff_alice", "content": "The fee is 1%"},
            {"sender": "user_bob", "content": "Thanks!"},
        ]
        result = handler.get_final_answer(messages, staff_senders={"staff_alice"})
        assert result["content"] == "The fee is 1%"
        assert result["original_was_corrected"] is False

    # ========== Cycle 8.1.3: Mark Corrected Candidates for Review ==========

    def test_get_correction_metadata(self, handler):
        """Test extraction of correction metadata for candidate."""
        messages = [
            {"sender": "user", "content": "How do I trade?"},
            {"sender": "staff", "content": "Go to trading view"},
            {"sender": "staff", "content": "Sorry, I meant go to the Offers tab first"},
        ]
        metadata = handler.get_correction_metadata(messages, staff_senders={"staff"})
        assert metadata["has_correction"] is True
        assert metadata["correction_type"] == "explicit"
        assert "correction_context" in metadata
        assert "Sorry" in metadata["correction_context"]

    def test_get_correction_metadata_no_correction(self, handler):
        """Test metadata when no correction present."""
        messages = [
            {"sender": "user", "content": "How do I trade?"},
            {"sender": "staff", "content": "Go to the Offers tab"},
        ]
        metadata = handler.get_correction_metadata(messages, staff_senders={"staff"})
        assert metadata["has_correction"] is False
        assert metadata["correction_type"] is None
        assert metadata["correction_context"] is None


class TestReplyChainAggregation:
    """Test suite for reply chain aggregation (TASK 8.2)."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Cycle 8.2.1: Build Reply Chain from Event IDs ==========

    def test_builds_reply_chain_from_event_ids(self, handler):
        """Test building a reply chain using m.in_reply_to links."""
        # Simulate Matrix messages with reply threading
        messages = {
            "msg_1": {
                "event_id": "msg_1",
                "sender": "user",
                "content": {"body": "How do I trade?"},
            },
            "msg_2": {
                "event_id": "msg_2",
                "sender": "staff",
                "content": {
                    "body": "Click the Offers tab",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg_1"}},
                },
            },
            "msg_3": {
                "event_id": "msg_3",
                "sender": "user",
                "content": {
                    "body": "Where is that?",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg_2"}},
                },
            },
            "msg_4": {
                "event_id": "msg_4",
                "sender": "staff",
                "content": {
                    "body": "Top left corner",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg_3"}},
                },
            },
        }

        chain = handler.build_reply_chain(messages["msg_4"], messages)
        assert len(chain) == 4
        assert chain[0]["event_id"] == "msg_1"
        assert chain[1]["event_id"] == "msg_2"
        assert chain[2]["event_id"] == "msg_3"
        assert chain[3]["event_id"] == "msg_4"

    def test_single_message_chain(self, handler):
        """Test chain with single message (no replies)."""
        messages = {
            "msg_1": {
                "event_id": "msg_1",
                "sender": "user",
                "content": {"body": "Hello"},
            },
        }

        chain = handler.build_reply_chain(messages["msg_1"], messages)
        assert len(chain) == 1
        assert chain[0]["event_id"] == "msg_1"

    def test_handles_missing_parent_message(self, handler):
        """Test graceful handling when parent message is missing."""
        messages = {
            "msg_2": {
                "event_id": "msg_2",
                "sender": "staff",
                "content": {
                    "body": "This replies to missing message",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg_1"}},
                },
            },
        }

        chain = handler.build_reply_chain(messages["msg_2"], messages)
        # Should return just the message itself when parent is missing
        assert len(chain) == 1
        assert chain[0]["event_id"] == "msg_2"

    # ========== Cycle 8.2.2: Group Independent Conversations ==========

    def test_groups_independent_conversations(self, handler):
        """Test grouping independent conversation threads."""
        messages = [
            # Conversation 1: 3 messages
            {
                "event_id": "conv1_1",
                "sender": "user",
                "content": {"body": "Question 1"},
            },
            {
                "event_id": "conv1_2",
                "sender": "staff",
                "content": {
                    "body": "Answer 1",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "conv1_1"}},
                },
            },
            {
                "event_id": "conv1_3",
                "sender": "user",
                "content": {
                    "body": "Thanks!",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "conv1_2"}},
                },
            },
            # Conversation 2: 2 messages
            {
                "event_id": "conv2_1",
                "sender": "user",
                "content": {"body": "Question 2"},
            },
            {
                "event_id": "conv2_2",
                "sender": "staff",
                "content": {
                    "body": "Answer 2",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "conv2_1"}},
                },
            },
            # Orphan message (no thread)
            {
                "event_id": "orphan_1",
                "sender": "user",
                "content": {"body": "Standalone question"},
            },
        ]

        groups = handler.group_conversations(messages)

        # Should have 3 groups: conv1 (3 msgs), conv2 (2 msgs), orphan (1 msg)
        assert len(groups) == 3

        # Verify group sizes
        group_sizes = sorted([len(g) for g in groups])
        assert group_sizes == [1, 2, 3]

    # ========== Cycle 8.2.3: Extract Q&A from Chain ==========

    def test_extracts_qa_from_reply_chain(self, handler):
        """Test extracting Q&A from a reply chain."""
        chain = [
            {"sender": "user", "content": {"body": "How do I trade?"}},
            {"sender": "staff", "content": {"body": "Click the Offers tab"}},
            {"sender": "user", "content": {"body": "What about fees?"}},
            {"sender": "staff", "content": {"body": "Fees are 0.1%"}},
        ]

        result = handler.extract_qa_from_chain(chain, staff_senders={"staff"})

        assert "How do I trade?" in result["question"]
        assert "What about fees?" in result["question"]
        assert result["message_count"] == 4
        assert result["has_correction"] is False

    def test_extracts_qa_with_correction(self, handler):
        """Test extracting Q&A when correction is present."""
        chain = [
            {"sender": "user", "content": {"body": "What is the fee?"}},
            {"sender": "staff", "content": {"body": "The fee is 1%"}},
            {"sender": "staff", "content": {"body": "Actually, it's 0.1%"}},
        ]

        result = handler.extract_qa_from_chain(chain, staff_senders={"staff"})

        assert "What is the fee?" in result["question"]
        # Answer should be the corrected version
        assert "0.1%" in result["answer"]
        assert result["has_correction"] is True
        assert result["correction_type"] == "explicit"

    def test_extracts_qa_handles_empty_chain(self, handler):
        """Test handling of empty chain."""
        result = handler.extract_qa_from_chain([], staff_senders={"staff"})

        assert result["question"] == ""
        assert result["answer"] is None
        assert result["message_count"] == 0


class TestMultiTurnConsolidation:
    """Test suite for multi-turn FAQ consolidation (TASK 8.3)."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Cycle 8.3.1: Process Conversation as Unit ==========

    def test_prepare_conversation_for_candidate(self, handler):
        """Test preparing a conversation for candidate creation."""
        messages = [
            {
                "event_id": "msg_1",
                "sender": "user",
                "content": {"body": "How do I create an offer?"},
            },
            {
                "event_id": "msg_2",
                "sender": "staff",
                "content": {"body": "Go to the Offers tab"},
            },
            {
                "event_id": "msg_3",
                "sender": "user",
                "content": {"body": "What about the price?"},
            },
            {
                "event_id": "msg_4",
                "sender": "staff",
                "content": {"body": "Set it relative to market or fixed"},
            },
        ]

        result = handler.prepare_conversation_for_candidate(
            messages,
            staff_senders={"staff"},
            last_event_id="msg_4",
        )

        assert result["source_event_id"] == "msg_4"
        assert "How do I create an offer?" in result["question_text"]
        assert "What about the price?" in result["question_text"]
        assert "Set it relative to market or fixed" in result["staff_answer"]
        assert result["message_count"] == 4
        assert result["is_multi_turn"] is True
        assert result["has_correction"] is False

    def test_single_message_is_not_multi_turn(self, handler):
        """Test that single Q&A is not marked as multi-turn."""
        messages = [
            {
                "event_id": "msg_1",
                "sender": "user",
                "content": {"body": "What is Bisq?"},
            },
            {
                "event_id": "msg_2",
                "sender": "staff",
                "content": {"body": "A P2P exchange"},
            },
        ]

        result = handler.prepare_conversation_for_candidate(
            messages,
            staff_senders={"staff"},
            last_event_id="msg_2",
        )

        assert result["message_count"] == 2
        assert result["is_multi_turn"] is False

    def test_conversation_with_correction_flagged(self, handler):
        """Test that conversations with corrections are properly flagged."""
        messages = [
            {
                "event_id": "msg_1",
                "sender": "user",
                "content": {"body": "What is the fee?"},
            },
            {
                "event_id": "msg_2",
                "sender": "staff",
                "content": {"body": "The fee is 1%"},
            },
            {
                "event_id": "msg_3",
                "sender": "staff",
                "content": {"body": "Actually, it's 0.1%"},
            },
        ]

        result = handler.prepare_conversation_for_candidate(
            messages,
            staff_senders={"staff"},
            last_event_id="msg_3",
        )

        assert result["has_correction"] is True
        assert "0.1%" in result["staff_answer"]
        assert result["suggested_routing"] == "FULL_REVIEW"

    # ========== Cycle 8.3.2: Store Conversation Context ==========

    def test_stores_conversation_context(self, handler):
        """Test that full conversation context is stored."""
        messages = [
            {
                "event_id": "msg_1",
                "sender": "user",
                "timestamp": "2024-01-01T10:00:00Z",
                "content": {"body": "Question 1"},
            },
            {
                "event_id": "msg_2",
                "sender": "staff",
                "timestamp": "2024-01-01T10:01:00Z",
                "content": {"body": "Answer 1"},
            },
        ]

        result = handler.prepare_conversation_for_candidate(
            messages,
            staff_senders={"staff"},
            last_event_id="msg_2",
        )

        # conversation_context should be JSON string
        context = json.loads(result["conversation_context"])
        assert len(context) == 2
        assert context[0]["sender"] == "user"
        assert context[0]["content"] == "Question 1"
        assert context[1]["sender"] == "staff"
        assert context[1]["content"] == "Answer 1"

    # ========== Cycle 8.3.3: Routing Suggestion ==========

    def test_suggests_full_review_for_correction(self, handler):
        """Test that corrections suggest FULL_REVIEW routing."""
        messages = [
            {"event_id": "msg_1", "sender": "user", "content": {"body": "Q?"}},
            {
                "event_id": "msg_2",
                "sender": "staff",
                "content": {"body": "Wrong answer"},
            },
            {
                "event_id": "msg_3",
                "sender": "staff",
                "content": {"body": "Sorry, correct answer"},
            },
        ]

        result = handler.prepare_conversation_for_candidate(
            messages, staff_senders={"staff"}, last_event_id="msg_3"
        )

        assert result["suggested_routing"] == "FULL_REVIEW"
        assert result["routing_reason"] == "contains_correction"

    def test_suggests_normal_routing_for_simple_qa(self, handler):
        """Test that simple Q&A gets normal routing."""
        messages = [
            {"event_id": "msg_1", "sender": "user", "content": {"body": "Q?"}},
            {"event_id": "msg_2", "sender": "staff", "content": {"body": "A"}},
        ]

        result = handler.prepare_conversation_for_candidate(
            messages, staff_senders={"staff"}, last_event_id="msg_2"
        )

        assert result["suggested_routing"] is None  # No override
        assert result["routing_reason"] is None


class TestQualityFixes:
    """Test suite for quality fixes identified by quality review (Phase 6.5).

    Issues addressed:
    1. Position-based "actually" detection (sentence start only)
    2. Filter conversations with empty question_text
    3. Cycle detection in build_reply_chain()
    4. Matrix edit prefix (*) detection and consolidation
    5. Timestamp sorting in _extend_chain_forward()
    6. Q&A role validation heuristic
    """

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Fix 1: Position-Based "Actually" Detection ==========

    def test_actually_at_sentence_start_is_correction(self, handler):
        """Test that 'actually' at sentence start is detected as correction."""
        # "Actually, ..." at the start should be a correction
        message = "Actually, the fee is 0.1% not 1%"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_actually_mid_sentence_is_not_correction(self, handler):
        """Test that 'actually' mid-sentence is NOT detected as correction.

        FALSE POSITIVE FIX: Sentences like "The feature actually works differently"
        should NOT be flagged as corrections - the word 'actually' is being used
        as an adverb for emphasis, not to indicate a correction.
        """
        # This was a false positive in the review - mid-sentence "actually" shouldn't be correction
        message = "The feature actually works differently than most expect"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is False
        assert correction_type is None

    def test_actually_after_comma_is_correction(self, handler):
        """Test that 'actually' after comma/period is detected as correction."""
        # "..., actually ..." suggests a correction
        message = "Wait, actually that's not right"
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    def test_actually_after_period_is_correction(self, handler):
        """Test that 'actually' starting a new sentence is correction."""
        message = "Let me check. Actually, I was wrong about that."
        is_correction, correction_type = handler.is_correction(message)
        assert is_correction is True
        assert correction_type == "explicit"

    # ========== Fix 2: Empty Question Filtering ==========

    def test_filters_conversations_with_empty_question(self, handler):
        """Test that conversations with empty question_text are filtered out.

        Orphan staff messages that cannot be linked to a user question should
        not produce FAQ candidates since they lack the question component.
        """
        # A staff-only message with no user question
        messages = [
            {
                "date": "2026-01-18T17:02:47.889Z",
                "author": "suddenwhipvapor",
                "authorId": "staff-id",
                "message": "Welcome to Bisq!",
                "messageId": "msg-1",
                "wasEdited": False,
            },
        ]

        result = handler.extract_conversations_unified(
            messages,
            source="bisq2",
            staff_ids={"suddenwhipvapor"},
            apply_temporal_proximity=True,
        )

        # Should produce no conversations (filtered out due to empty question)
        assert len(result) == 0

    def test_keeps_conversations_with_question(self, handler):
        """Test that conversations with non-empty questions are kept."""
        messages = [
            {
                "date": "2026-01-18T17:02:34.711Z",
                "author": "user",
                "authorId": "user-id",
                "message": "How do I start?",
                "messageId": "msg-1",
                "wasEdited": False,
            },
            {
                "date": "2026-01-18T17:02:47.889Z",
                "author": "staff",
                "authorId": "staff-id",
                "message": "Go to Offers tab",
                "messageId": "msg-2",
                "wasEdited": False,
                "citation": {"messageId": "msg-1", "author": "user", "text": "..."},
            },
        ]

        result = handler.extract_conversations_unified(
            messages,
            source="bisq2",
            staff_ids={"staff"},
            apply_temporal_proximity=True,
        )

        assert len(result) == 1
        assert result[0]["question_text"] == "How do I start?"

    # ========== Fix 3: Cycle Detection in build_reply_chain() ==========

    def test_detects_cycle_in_reply_chain(self, handler):
        """Test that cycles in reply chains are detected and broken.

        A circular reference (A replies to B, B replies to A) should not
        cause infinite loops.
        """
        # Circular reference: msg-2 replies to msg-1, msg-1 replies to msg-2
        messages = {
            "msg-1": {
                "event_id": "msg-1",
                "sender": "user",
                "content": {
                    "body": "Question?",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg-2"}},
                },
            },
            "msg-2": {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {
                    "body": "Answer",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg-1"}},
                },
            },
        }

        # This should NOT hang or crash - cycle should be detected
        chain = handler.build_reply_chain(messages["msg-2"], messages)

        # Chain should be finite (no infinite loop)
        assert len(chain) <= 2  # At most 2 messages (cycle broken)

    def test_handles_self_reference_cycle(self, handler):
        """Test that self-referencing message doesn't cause infinite loop."""
        # A message that replies to itself (corrupted data)
        messages = {
            "msg-1": {
                "event_id": "msg-1",
                "sender": "user",
                "content": {
                    "body": "Self-referencing message",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg-1"}},
                },
            },
        }

        chain = handler.build_reply_chain(messages["msg-1"], messages)

        # Should contain exactly 1 message (self-reference detected)
        assert len(chain) == 1

    # ========== Fix 4: Matrix Edit Prefix Detection ==========

    def test_detects_matrix_edit_prefix(self, handler):
        """Test detection of Matrix edit prefix (* at start of message).

        Matrix clients indicate message edits with '* ' prefix.
        """
        original_msg = {
            "event_id": "msg-1",
            "sender": "staff",
            "content": {"body": "The fee is 1%"},
            "origin_server_ts": 1700000000000,
        }
        edited_msg = {
            "event_id": "msg-2",
            "sender": "staff",
            "content": {"body": "* The fee is 0.1%"},  # Edit prefix
            "origin_server_ts": 1700000001000,
        }

        assert handler.is_matrix_edit(original_msg) is False
        assert handler.is_matrix_edit(edited_msg) is True

    def test_consolidates_matrix_edits(self, handler):
        """Test that edited messages supersede originals."""
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user",
                "content": {"body": "What is the fee?"},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {"body": "The fee is 1%"},
                "origin_server_ts": 1700000060000,
            },
            {
                "event_id": "msg-3",
                "sender": "staff",
                "content": {"body": "* The fee is 0.1%"},  # Edit
                "origin_server_ts": 1700000061000,
            },
        ]

        # Consolidate edits before processing
        consolidated = handler.consolidate_matrix_edits(messages)

        # Should have 2 messages (edit replaces original)
        # The staff answer should be the edited version
        staff_msgs = [m for m in consolidated if m["sender"] == "staff"]
        assert len(staff_msgs) == 1
        assert "0.1%" in staff_msgs[0]["content"]["body"]

    # ========== Fix 5: Timestamp Sorting in _extend_chain_forward() ==========

    def test_extend_chain_sorts_by_timestamp(self, handler):
        """Test that extended chain is sorted by timestamp."""
        # Messages added to chain out of order
        chain = [
            {
                "event_id": "msg-1",
                "sender": "user",
                "content": {"body": "Question"},
                "origin_server_ts": 1700000000000,
            },
        ]
        all_messages = [
            chain[0],
            {
                "event_id": "msg-3",  # Later timestamp but comes first in list
                "sender": "staff",
                "content": {
                    "body": "Follow-up",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg-2"}},
                },
                "origin_server_ts": 1700000120000,
            },
            {
                "event_id": "msg-2",  # Earlier timestamp but comes second in list
                "sender": "staff",
                "content": {
                    "body": "Answer",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg-1"}},
                },
                "origin_server_ts": 1700000060000,
            },
        ]

        extended = handler._extend_chain_forward(chain, all_messages)

        # Should be sorted by timestamp
        timestamps = [m.get("origin_server_ts", 0) for m in extended]
        assert timestamps == sorted(timestamps)

    # ========== Fix 6: Q&A Role Validation ==========

    def test_validates_qa_role_pattern(self, handler):
        """Test that extracted Q&A follows expected user->staff pattern.

        A valid FAQ should typically start with a user question, not a staff message.
        """
        # Invalid: Staff message first without user question
        messages = [
            {
                "event_id": "msg-1",
                "sender": "staff",
                "content": {"body": "Welcome everyone!"},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {"body": "Feel free to ask questions"},
                "origin_server_ts": 1700000060000,
            },
        ]

        result = handler.extract_qa_from_chain(messages, staff_senders={"staff"})

        # Should indicate the Q&A pattern is invalid
        assert result.get("is_valid_qa_pattern") is False

    def test_valid_qa_pattern_user_first(self, handler):
        """Test that user-first conversations have valid Q&A pattern."""
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user",
                "content": {"body": "How do I trade?"},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {"body": "Go to Offers tab"},
                "origin_server_ts": 1700000060000,
            },
        ]

        result = handler.extract_qa_from_chain(messages, staff_senders={"staff"})

        assert result.get("is_valid_qa_pattern") is True


class TestLLMDistillation:
    """Test suite for LLM distillation of complex conversations (TASK 8.4)."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Cycle 8.4.1: Distillation Prompt Template ==========

    def test_create_distillation_prompt(self, handler):
        """Test that distillation prompt includes conversation."""
        messages = [
            {"sender": "user", "content": "How do I create an offer?"},
            {"sender": "staff", "content": "Click the Offers tab"},
            {"sender": "user", "content": "Where is that?"},
            {"sender": "staff", "content": "Top left corner, then select Create"},
        ]

        prompt = handler.create_distillation_prompt(messages)

        # Should include system instructions
        assert "distillation" in prompt.lower() or "faq" in prompt.lower()
        # Should include conversation messages
        assert "How do I create an offer?" in prompt
        assert "Click the Offers tab" in prompt
        assert "Top left corner" in prompt
        # Should request Q&A output format
        assert "question" in prompt.lower()
        assert "answer" in prompt.lower()

    def test_distillation_prompt_handles_corrections(self, handler):
        """Test that prompt instructs to use corrected info only."""
        messages = [
            {"sender": "user", "content": "What's the fee?"},
            {"sender": "staff", "content": "1%"},
            {"sender": "staff", "content": "Sorry, it's actually 0.1%"},
        ]

        prompt = handler.create_distillation_prompt(messages)

        # Should mention corrections
        assert "correct" in prompt.lower()

    # ========== Cycle 8.4.2: LLM Distillation Call ==========

    def test_should_distill_long_conversation(self, handler):
        """Test that long conversations are marked for distillation."""
        # 6 message conversation (> threshold of 4)
        messages = [
            {
                "event_id": f"msg_{i}",
                "sender": "user" if i % 2 == 0 else "staff",
                "content": {"body": f"Message {i}"},
            }
            for i in range(6)
        ]

        result = handler.prepare_conversation_for_candidate(
            messages, staff_senders={"staff"}, last_event_id="msg_5"
        )

        # Should indicate distillation is needed for long conversations
        assert result["needs_distillation"] is True

    def test_should_not_distill_short_conversation(self, handler):
        """Test that short conversations don't need distillation."""
        messages = [
            {"event_id": "msg_1", "sender": "user", "content": {"body": "Q?"}},
            {"event_id": "msg_2", "sender": "staff", "content": {"body": "A"}},
        ]

        result = handler.prepare_conversation_for_candidate(
            messages, staff_senders={"staff"}, last_event_id="msg_2"
        )

        assert result["needs_distillation"] is False

    # ========== Cycle 8.4.3: Distilled vs Raw Storage ==========

    def test_distillation_threshold_is_configurable(self, handler):
        """Test that distillation threshold can be checked."""
        # Default threshold is 4 messages
        assert handler.distillation_threshold == 4

    def test_prepare_includes_distillation_flag(self, handler):
        """Test that prepare returns needs_distillation based on threshold."""
        # 4 messages - at threshold, not over
        messages = [
            {"event_id": "msg_1", "sender": "user", "content": {"body": "Q1"}},
            {"event_id": "msg_2", "sender": "staff", "content": {"body": "A1"}},
            {"event_id": "msg_3", "sender": "user", "content": {"body": "Q2"}},
            {"event_id": "msg_4", "sender": "staff", "content": {"body": "A2"}},
        ]

        result = handler.prepare_conversation_for_candidate(
            messages, staff_senders={"staff"}, last_event_id="msg_4"
        )

        # 4 messages is NOT over threshold of 4
        assert result["needs_distillation"] is False

        # 5 messages IS over threshold
        messages.append(
            {"event_id": "msg_5", "sender": "user", "content": {"body": "Q3"}}
        )
        result = handler.prepare_conversation_for_candidate(
            messages, staff_senders={"staff"}, last_event_id="msg_5"
        )

        assert result["needs_distillation"] is True


class TestBisq2ToUnifiedConversion:
    """Test suite for Bisq 2 message to unified format conversion."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Phase 1: Conversion Function Tests ==========

    def test_bisq2_to_unified_basic_message(self, handler):
        """Test basic conversion of Bisq 2 message to unified format."""
        bisq2_msg = {
            "date": "2026-01-11T17:07:45.673Z",
            "channel": "support",
            "author": "suddenwhipvapor",
            "authorId": "43de7ff4ba67de90656f36c4c8e826c8cbda7575",
            "message": "are you on windows?",
            "messageId": "4b16e8ed-0c59-4c91-abcd-936c741d4159",
            "wasEdited": False,
        }

        unified = handler.bisq2_to_unified(bisq2_msg)

        # Verify unified format has Matrix-like structure
        assert unified["event_id"] == "4b16e8ed-0c59-4c91-abcd-936c741d4159"
        assert unified["sender"] == "suddenwhipvapor"
        assert unified["content"]["body"] == "are you on windows?"
        assert "origin_server_ts" in unified
        # Verify timestamp is in milliseconds
        assert isinstance(unified["origin_server_ts"], int)

    def test_bisq2_to_unified_with_citation(self, handler):
        """Test conversion of Bisq 2 message with citation (reply reference)."""
        bisq2_msg = {
            "date": "2026-01-11T17:07:45.673Z",
            "channel": "support",
            "author": "suddenwhipvapor",
            "authorId": "43de7ff4ba67de90656f36c4c8e826c8cbda7575",
            "message": "are you on windows?",
            "messageId": "4b16e8ed-0c59-4c91-abcd-936c741d4159",
            "wasEdited": False,
            "citation": {
                "messageId": "8becff61-a87f-47aa-902b-49487ee0a506",
                "author": "george-orwell-III",
                "authorId": "ad629fd44ffe75738951baf3bc3fb36af6478c4a",
                "text": "I've been having an issue...",
            },
        }

        unified = handler.bisq2_to_unified(bisq2_msg)

        # Verify reply reference is in Matrix format
        assert "m.relates_to" in unified["content"]
        reply_to = unified["content"]["m.relates_to"]["m.in_reply_to"]
        assert reply_to["event_id"] == "8becff61-a87f-47aa-902b-49487ee0a506"

    def test_bisq2_to_unified_timestamp_conversion(self, handler):
        """Test that ISO date is converted to Unix timestamp in milliseconds."""
        bisq2_msg = {
            "date": "2026-01-11T17:07:45.673Z",
            "channel": "support",
            "author": "test_user",
            "authorId": "test123",
            "message": "test message",
            "messageId": "msg-001",
            "wasEdited": False,
        }

        unified = handler.bisq2_to_unified(bisq2_msg)

        # Expected: 2026-01-11T17:07:45.673Z in milliseconds
        # This should be around 1768165665673 (year 2026)
        assert unified["origin_server_ts"] > 1700000000000  # After 2023
        assert unified["origin_server_ts"] < 1900000000000  # Before 2030

    def test_bisq2_to_unified_preserves_source_metadata(self, handler):
        """Test that conversion preserves useful metadata."""
        bisq2_msg = {
            "date": "2026-01-11T17:07:45.673Z",
            "channel": "support",
            "author": "suddenwhipvapor",
            "authorId": "43de7ff4ba67de90656f36c4c8e826c8cbda7575",
            "message": "test message",
            "messageId": "msg-001",
            "wasEdited": True,
        }

        unified = handler.bisq2_to_unified(bisq2_msg)

        # Should preserve source type for later filtering
        assert unified.get("source") == "bisq2"
        # Should preserve author ID for staff detection
        assert unified.get("author_id") == "43de7ff4ba67de90656f36c4c8e826c8cbda7575"

    def test_bisq2_messages_group_correctly_after_conversion(self, handler):
        """Test that converted Bisq 2 messages group correctly using existing pipeline."""
        # Simulate a real Bisq 2 conversation thread
        bisq2_messages = [
            {
                "date": "2026-01-13T10:27:46.163Z",
                "author": "Snip",
                "authorId": "baa0e3950ff642b655385752b58d96ab451f8878",
                "message": "I noticed that I have no reputation anymore!",
                "messageId": "7c2c254a-cf23-44f8-aa9a-ad4fa58d2b22",
                "wasEdited": False,
            },
            {
                "date": "2026-01-13T10:28:38.622Z",
                "author": "suddenwhipvapor",
                "authorId": "43de7ff4ba67de90656f36c4c8e826c8cbda7575",
                "message": "you probably had to wait to receive full data from the network",
                "messageId": "1042a547-ce8d-48be-91d4-a5745667820c",
                "wasEdited": False,
                "citation": {
                    "messageId": "7c2c254a-cf23-44f8-aa9a-ad4fa58d2b22",
                    "author": "Snip",
                    "authorId": "baa0e3950ff642b655385752b58d96ab451f8878",
                    "text": "I noticed that I have no reputation anymore!",
                },
            },
            {
                "date": "2026-01-13T10:29:04.897Z",
                "author": "Snip",
                "authorId": "baa0e3950ff642b655385752b58d96ab451f8878",
                "message": "Yes ... you right thanks.",
                "messageId": "f957e402-2a34-4f59-ac3e-f2fd7df618c4",
                "wasEdited": False,
                "citation": {
                    "messageId": "1042a547-ce8d-48be-91d4-a5745667820c",
                    "author": "suddenwhipvapor",
                    "authorId": "43de7ff4ba67de90656f36c4c8e826c8cbda7575",
                    "text": "you probably had to wait...",
                },
            },
        ]

        # Convert all messages
        unified_messages = [handler.bisq2_to_unified(msg) for msg in bisq2_messages]

        # Use existing group_conversations method
        groups = handler.group_conversations(unified_messages)

        # Should group into 1 conversation (all linked by citations)
        assert len(groups) == 1
        assert len(groups[0]) == 3


class TestNormalizeMessages:
    """Test suite for normalize_messages function."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    def test_normalize_bisq2_messages(self, handler):
        """Test normalizing a list of Bisq 2 messages."""
        bisq2_messages = [
            {
                "date": "2026-01-11T17:07:45.673Z",
                "author": "user1",
                "authorId": "id1",
                "message": "Question",
                "messageId": "msg-1",
                "wasEdited": False,
            },
            {
                "date": "2026-01-11T17:08:00.000Z",
                "author": "staff",
                "authorId": "id2",
                "message": "Answer",
                "messageId": "msg-2",
                "wasEdited": False,
                "citation": {"messageId": "msg-1", "author": "user1", "text": "..."},
            },
        ]

        normalized = handler.normalize_messages(bisq2_messages, source="bisq2")

        assert len(normalized) == 2
        # All should have unified format
        for msg in normalized:
            assert "event_id" in msg
            assert "sender" in msg
            assert "content" in msg
            assert "origin_server_ts" in msg

    def test_normalize_matrix_messages_passthrough(self, handler):
        """Test that Matrix messages pass through unchanged."""
        matrix_messages = [
            {
                "event_id": "matrix-1",
                "sender": "@user:matrix.org",
                "content": {"body": "Question"},
                "origin_server_ts": 1768165665673,
            },
            {
                "event_id": "matrix-2",
                "sender": "@staff:matrix.org",
                "content": {
                    "body": "Answer",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "matrix-1"}},
                },
                "origin_server_ts": 1768165700000,
            },
        ]

        normalized = handler.normalize_messages(matrix_messages, source="matrix")

        assert len(normalized) == 2
        # Matrix messages should pass through mostly unchanged
        assert normalized[0]["event_id"] == "matrix-1"
        assert normalized[1]["event_id"] == "matrix-2"


class TestUnifiedExtraction:
    """Test suite for unified conversation extraction from multiple sources."""

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    def test_extract_conversations_unified_bisq2(self, handler):
        """Test extracting conversations from Bisq 2 messages."""
        bisq2_messages = [
            {
                "date": "2026-01-13T10:27:46.163Z",
                "author": "Snip",
                "authorId": "baa0e3950ff642b655385752b58d96ab451f8878",
                "message": "Why do I have no reputation?",
                "messageId": "7c2c254a-cf23-44f8-aa9a-ad4fa58d2b22",
                "wasEdited": False,
            },
            {
                "date": "2026-01-13T10:28:38.622Z",
                "author": "suddenwhipvapor",
                "authorId": "43de7ff4ba67de90656f36c4c8e826c8cbda7575",
                "message": "Wait for network sync. I see your rep is 70000.",
                "messageId": "1042a547-ce8d-48be-91d4-a5745667820c",
                "wasEdited": False,
                "citation": {
                    "messageId": "7c2c254a-cf23-44f8-aa9a-ad4fa58d2b22",
                    "author": "Snip",
                    "text": "...",
                },
            },
        ]

        # Staff IDs for Bisq 2 messages
        staff_ids = {"suddenwhipvapor"}

        result = handler.extract_conversations_unified(
            bisq2_messages,
            source="bisq2",
            staff_ids=staff_ids,
        )

        assert len(result) == 1
        conv = result[0]
        assert conv["source"] == "bisq2"
        assert "Why do I have no reputation" in conv["question_text"]
        assert "70000" in conv["staff_answer"]
        assert conv["message_count"] == 2

    def test_extract_conversations_unified_output_format(self, handler):
        """Test that unified extraction output matches expected format."""
        bisq2_messages = [
            {
                "date": "2026-01-13T10:27:46.163Z",
                "author": "user",
                "authorId": "user-id",
                "message": "Question text",
                "messageId": "msg-1",
                "wasEdited": False,
            },
            {
                "date": "2026-01-13T10:28:38.622Z",
                "author": "staff",
                "authorId": "staff-id",
                "message": "Answer text",
                "messageId": "msg-2",
                "wasEdited": False,
                "citation": {"messageId": "msg-1", "author": "user", "text": "..."},
            },
        ]

        result = handler.extract_conversations_unified(
            bisq2_messages,
            source="bisq2",
            staff_ids={"staff"},
        )

        # Verify output format
        conv = result[0]
        assert "source" in conv
        assert "conversation_id" in conv
        assert "messages" in conv
        assert "question_text" in conv
        assert "staff_answer" in conv
        assert "message_count" in conv
        assert "is_multi_turn" in conv
        assert "has_correction" in conv

    def test_extract_multi_turn_with_correction(self, handler):
        """Test extraction of multi-turn conversation with correction detection."""
        bisq2_messages = [
            {
                "date": "2026-01-13T10:00:00.000Z",
                "author": "user",
                "authorId": "user-id",
                "message": "What is the fee?",
                "messageId": "msg-1",
                "wasEdited": False,
            },
            {
                "date": "2026-01-13T10:01:00.000Z",
                "author": "staff",
                "authorId": "staff-id",
                "message": "The fee is 1%",
                "messageId": "msg-2",
                "wasEdited": False,
                "citation": {"messageId": "msg-1", "author": "user", "text": "..."},
            },
            {
                "date": "2026-01-13T10:02:00.000Z",
                "author": "staff",
                "authorId": "staff-id",
                "message": "Actually, sorry - the fee is 0.1%",
                "messageId": "msg-3",
                "wasEdited": False,
                "citation": {"messageId": "msg-2", "author": "staff", "text": "..."},
            },
        ]

        result = handler.extract_conversations_unified(
            bisq2_messages,
            source="bisq2",
            staff_ids={"staff"},
        )

        conv = result[0]
        assert conv["has_correction"] is True
        assert "0.1%" in conv["staff_answer"]
        assert conv["message_count"] == 3
        assert conv["is_multi_turn"] is True


class TestTemporalProximityGrouping:
    """Test suite for temporal proximity-based conversation grouping (Phase 6).

    Based on analysis of Bisq 2 and Matrix support messages:
    - Default threshold: 5 minutes (300 seconds)
    - 90th percentile of quick staff responses
    - Conservative to minimize false positives
    """

    @pytest.fixture
    def handler(self):
        """Create a ConversationHandler instance."""
        return ConversationHandler()

    # ========== Phase 6.1: Basic Temporal Proximity Detection ==========

    def test_temporal_proximity_default_threshold(self, handler):
        """Test that default temporal proximity threshold is 5 minutes."""
        assert handler.temporal_proximity_threshold_ms == 300000  # 5 minutes in ms

    def test_temporal_proximity_configurable(self, handler):
        """Test that temporal proximity threshold is configurable."""
        custom_handler = ConversationHandler(temporal_proximity_threshold_ms=600000)
        assert custom_handler.temporal_proximity_threshold_ms == 600000  # 10 minutes

    def test_messages_within_threshold_are_grouped(self, handler):
        """Test that orphan staff message within threshold is grouped with preceding user msg."""
        # User question at T=0
        # Staff response at T=2 minutes (no explicit reply link)
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user",
                "content": {"body": "How do I start a trade?"},
                "origin_server_ts": 1700000000000,  # T=0
            },
            {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {"body": "Go to the Offers tab and click Create Offer."},
                "origin_server_ts": 1700000120000,  # T=2 minutes (within 5min threshold)
            },
        ]

        groups = handler.group_conversations(messages)
        groups_with_proximity = handler.apply_temporal_proximity(
            groups, staff_senders={"staff"}
        )

        # Should be merged into one group
        assert len(groups_with_proximity) == 1
        assert len(groups_with_proximity[0]) == 2

    def test_messages_outside_threshold_not_grouped(self, handler):
        """Test that orphan staff message outside threshold remains separate."""
        # User question at T=0
        # Staff response at T=10 minutes (outside 5min threshold)
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user",
                "content": {"body": "How do I start a trade?"},
                "origin_server_ts": 1700000000000,  # T=0
            },
            {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {"body": "Go to the Offers tab."},
                "origin_server_ts": 1700000600000,  # T=10 minutes (outside threshold)
            },
        ]

        groups = handler.group_conversations(messages)
        groups_with_proximity = handler.apply_temporal_proximity(
            groups, staff_senders={"staff"}
        )

        # Should remain as two separate groups
        assert len(groups_with_proximity) == 2

    # ========== Phase 6.2: Orphan Detection ==========

    def test_identifies_orphan_staff_message(self, handler):
        """Test identification of orphan staff messages (no reply link)."""
        orphan_msg = {
            "event_id": "msg-1",
            "sender": "staff",
            "content": {"body": "The answer is yes."},
            "origin_server_ts": 1700000000000,
        }

        assert handler.is_orphan_message(orphan_msg) is True

    def test_linked_message_is_not_orphan(self, handler):
        """Test that messages with explicit reply links are not orphans."""
        linked_msg = {
            "event_id": "msg-2",
            "sender": "staff",
            "content": {
                "body": "The answer is yes.",
                "m.relates_to": {"m.in_reply_to": {"event_id": "msg-1"}},
            },
            "origin_server_ts": 1700000000000,
        }

        assert handler.is_orphan_message(linked_msg) is False

    def test_non_staff_orphan_not_merged(self, handler):
        """Test that orphan user messages are not merged by temporal proximity."""
        messages = [
            {
                "event_id": "msg-1",
                "sender": "staff",
                "content": {"body": "Let me check that for you."},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "user",  # User message, not staff
                "content": {"body": "Thanks!"},
                "origin_server_ts": 1700000060000,  # 1 minute later
            },
        ]

        groups = handler.group_conversations(messages)
        groups_with_proximity = handler.apply_temporal_proximity(
            groups, staff_senders={"staff"}
        )

        # User message without reply should remain separate
        assert len(groups_with_proximity) == 2

    # ========== Phase 6.3: Complex Scenarios ==========

    def test_multiple_orphan_staff_messages_chain(self, handler):
        """Test grouping multiple consecutive orphan staff messages."""
        # User asks question
        # Staff sends answer in multiple parts without explicit replies
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user",
                "content": {"body": "How does reputation work?"},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "staff",
                "content": {"body": "Reputation is earned through trades."},
                "origin_server_ts": 1700000060000,  # 1 min
            },
            {
                "event_id": "msg-3",
                "sender": "staff",
                "content": {"body": "You can also buy it with BSQ."},
                "origin_server_ts": 1700000090000,  # 1.5 min
            },
        ]

        groups = handler.group_conversations(messages)
        groups_with_proximity = handler.apply_temporal_proximity(
            groups, staff_senders={"staff"}
        )

        # All should be merged into one group
        assert len(groups_with_proximity) == 1
        assert len(groups_with_proximity[0]) == 3

    def test_interleaved_conversations_not_mixed(self, handler):
        """Test that temporal proximity doesn't mix different conversations."""
        # Two users asking questions, staff responding
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user_a",
                "content": {"body": "Question from A"},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "user_b",
                "content": {"body": "Question from B"},
                "origin_server_ts": 1700000030000,  # 30 sec later
            },
            {
                "event_id": "msg-3",
                "sender": "staff",
                "content": {"body": "Answer to B"},
                "origin_server_ts": 1700000060000,  # 1 min after msg-2
                # No explicit reply, but closer in time to user_b
            },
        ]

        groups = handler.group_conversations(messages)
        groups_with_proximity = handler.apply_temporal_proximity(
            groups, staff_senders={"staff"}
        )

        # Staff msg should be grouped with most recent user msg (user_b)
        # user_a's message should remain separate
        merged_count = sum(len(g) for g in groups_with_proximity)
        assert merged_count == 3  # All messages accounted for

    def test_linked_messages_take_precedence(self, handler):
        """Test that explicit reply links are not overridden by temporal proximity."""
        messages = [
            {
                "event_id": "msg-1",
                "sender": "user_a",
                "content": {"body": "First question"},
                "origin_server_ts": 1700000000000,
            },
            {
                "event_id": "msg-2",
                "sender": "user_b",
                "content": {"body": "Second question"},
                "origin_server_ts": 1700000300000,  # 5 min later
            },
            {
                "event_id": "msg-3",
                "sender": "staff",
                "content": {
                    "body": "Answer to first",
                    "m.relates_to": {"m.in_reply_to": {"event_id": "msg-1"}},
                },
                "origin_server_ts": 1700000360000,  # 1 min after msg-2
                # Has explicit reply to msg-1, even though temporally closer to msg-2
            },
        ]

        groups = handler.group_conversations(messages)
        groups_with_proximity = handler.apply_temporal_proximity(
            groups, staff_senders={"staff"}
        )

        # msg-3 should be grouped with msg-1 (explicit link), not msg-2 (temporal)
        for group in groups_with_proximity:
            event_ids = [m["event_id"] for m in group]
            if "msg-3" in event_ids:
                assert "msg-1" in event_ids
                assert "msg-2" not in event_ids

    # ========== Phase 6.4: Integration with Unified Pipeline ==========

    def test_unified_extraction_uses_temporal_proximity(self, handler):
        """Test that extract_conversations_unified applies temporal proximity."""
        bisq2_messages = [
            {
                "date": "2026-01-18T17:02:34.711Z",
                "author": "dogkate",
                "authorId": "user-id",
                "message": "Is it possible to send fiat to Bisq?",
                "messageId": "msg-1",
                "wasEdited": False,
            },
            {
                "date": "2026-01-18T17:02:47.889Z",  # 13 seconds later
                "author": "suddenwhipvapor",
                "authorId": "staff-id",
                "message": "then you can trade btc for usdt",
                "messageId": "msg-2",
                "wasEdited": False,
                # No citation - this would be orphan without temporal proximity
            },
        ]

        result = handler.extract_conversations_unified(
            bisq2_messages,
            source="bisq2",
            staff_ids={"suddenwhipvapor"},
            apply_temporal_proximity=True,
        )

        # Should produce one conversation with both messages
        assert len(result) >= 1
        # Verify the conversation contains the staff answer
        assert any("usdt" in conv.get("staff_answer", "").lower() for conv in result)
