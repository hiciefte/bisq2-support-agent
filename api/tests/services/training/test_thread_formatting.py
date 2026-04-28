"""Tests for reply-to thread context in extraction transcripts.

The LLM needs explicit "← IN REPLY TO [Msg #N]" markers to correctly
pair user questions with staff answers in multi-party conversations.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.training.unified_faq_extractor import UnifiedFAQExtractor


def _make_extractor() -> UnifiedFAQExtractor:
    settings = SimpleNamespace(
        LLM_EXTRACTION_MODEL="test",
        LLM_EXTRACTION_TEMPERATURE=0.0,
        LLM_EXTRACTION_MAX_TOKENS=4000,
    )
    return UnifiedFAQExtractor(
        aisuite_client=None,
        settings=settings,  # type: ignore[arg-type]
        staff_identifiers=["staff1", "@staff1:matrix.org"],
    )


class TestThreadContextInTranscript:
    def test_matrix_reply_to_shows_msg_number(self) -> None:
        ext = _make_extractor()
        messages = [
            {"id": "$evt1", "author": "user1", "text": "How do I open mediation?"},
            {
                "id": "$evt2",
                "author": "user2",
                "text": "Is it safe to turn off my laptop?",
            },
            {
                "id": "$evt3",
                "author": "staff1",
                "text": "Select the trade and press Ctrl+O.",
                "reply_to": "$evt1",
            },
        ]
        transcript, _ = ext._anonymize_messages(messages)
        lines = transcript.strip().splitlines()
        assert len(lines) == 3
        assert "← IN REPLY TO [Msg #1]" in lines[2]
        assert "[User_1]" in lines[2] or "User_1" in lines[2]

    def test_bisq2_citation_shows_msg_number(self) -> None:
        ext = _make_extractor()
        messages = [
            {"id": "msg1", "author": "user1", "text": "What are the fees?"},
            {
                "id": "msg2",
                "author": "staff1",
                "text": "Trading fee is 0.1%.",
                "citation": {"author": "user1", "text": "What are the fees?"},
            },
        ]
        transcript, _ = ext._anonymize_messages(messages)
        lines = transcript.strip().splitlines()
        assert "← IN REPLY TO [Msg #1]" in lines[1]

    def test_no_reply_to_leaves_line_unchanged(self) -> None:
        ext = _make_extractor()
        messages = [
            {"id": "msg1", "author": "user1", "text": "Hello, how are you?"},
        ]
        transcript, _ = ext._anonymize_messages(messages)
        assert "IN REPLY TO" not in transcript

    def test_reply_to_unknown_event_falls_back_to_raw_id(self) -> None:
        ext = _make_extractor()
        messages = [
            {
                "id": "$evt5",
                "author": "staff1",
                "text": "Sure, that works.",
                "reply_to": "$evt_unknown",
            },
        ]
        transcript, _ = ext._anonymize_messages(messages)
        assert "reply to: $evt_unknown" in transcript

    def test_reply_to_preserves_original_text(self) -> None:
        ext = _make_extractor()
        messages = [
            {"id": "$a", "author": "user1", "text": "How do I backup?"},
            {
                "id": "$b",
                "author": "staff1",
                "text": "Go to Wallet > Backup.",
                "reply_to": "$a",
            },
        ]
        transcript, _ = ext._anonymize_messages(messages)
        assert "Go to Wallet > Backup." in transcript
