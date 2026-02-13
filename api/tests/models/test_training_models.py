"""Test that QAPair is importable from shared models (not channel-specific code)."""

from datetime import datetime, timezone


class TestQAPairSharedModel:
    """QAPair should live in app.models.training, not matrix_export_parser."""

    def test_qapair_importable_from_models(self):
        from app.models.training import QAPair

        pair = QAPair(
            question_event_id="$q1:matrix.org",
            question_text="How do I trade?",
            question_sender="@user:matrix.org",
            question_timestamp=datetime.now(timezone.utc),
            answer_event_id="$a1:matrix.org",
            answer_text="Use the trade wizard.",
            answer_sender="@staff:matrix.org",
            answer_timestamp=datetime.now(timezone.utc),
        )
        assert pair.question_text == "How do I trade?"

    def test_qapair_still_importable_from_training_init(self):
        """Backwards compat: training __init__ re-exports QAPair."""
        from app.services.training import QAPair

        assert QAPair is not None

    def test_qapair_has_expected_fields(self):
        from app.models.training import QAPair

        pair = QAPair(
            question_event_id="$q1:matrix.org",
            question_text="Q",
            question_sender="@u:m.org",
            question_timestamp=datetime.now(timezone.utc),
            answer_event_id="$a1:matrix.org",
            answer_text="A",
            answer_sender="@s:m.org",
            answer_timestamp=datetime.now(timezone.utc),
        )
        assert pair.thread_depth == 1
        assert pair.has_followup is False
