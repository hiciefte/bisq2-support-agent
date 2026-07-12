"""Offline Matrix staff-answer mining and missing-FAQ correlation tests."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from app.scripts import extract_matrix_eval_samples as extractor

FIXTURES = Path(__file__).parent.parent / "fixtures"
MATRIX_FIXTURE = FIXTURES / "matrix_staff_alignment_export.json"
MISSING_FAQ_FIXTURE = FIXTURES / "missing_faq_questions.json"
STAFF_ID = "@staff-synthetic:example.invalid"


class StubProtocolDetector:
    """Pure detector stub; extraction tests never call a model or network."""

    def detect_protocol_from_text(self, text: str) -> tuple[str | None, float]:
        if "bisq 1" in text.lower():
            return "multisig_v1", 0.95
        return None, 0.0


def _messages() -> list[dict[str, Any]]:
    data = json.loads(MATRIX_FIXTURE.read_text(encoding="utf-8"))
    return data["messages"]


def _extract() -> tuple[
    list[extractor.CandidatePair],
    list[extractor.CandidatePair],
    dict[str, int],
    list[dict[str, Any]],
]:
    candidates, behavior_candidates, rejects, rejected_examples = (
        extractor.extract_candidates(
            _messages(),
            staff_ids={STAFF_ID},
            staff_localparts=set(),
            detector=StubProtocolDetector(),
        )
    )
    return candidates, behavior_candidates, dict(rejects), rejected_examples


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        dict_keys = set(value)
        for nested in value.values():
            dict_keys.update(_all_keys(nested))
        return dict_keys
    if isinstance(value, list):
        list_keys: set[str] = set()
        for nested in value:
            list_keys.update(_all_keys(nested))
        return list_keys
    return set()


def test_behavior_artifact_retains_replies_filtered_from_legacy_benchmark() -> None:
    candidates, behavior_candidates, rejects, _rejected_examples = _extract()

    assert len(behavior_candidates) == 5
    assert len(candidates) == 3
    assert rejects["answer_clarifying"] == 1
    assert rejects["answer_too_short"] == 1
    assert all(not candidate.is_diagnostic_reply for candidate in candidates)
    assert all(not candidate.is_link_only_reply for candidate in candidates)

    artifact = extractor._to_behavior_review(
        candidates=behavior_candidates,
        source_sha256="a" * 64,
        missing_questions=[],
        missing_faq_source_sha256=None,
        missing_match_threshold=0.55,
        sender_hash_salt="fixture-salt",
    )
    diagnostic = next(
        row
        for row in artifact["individual_results"]
        if row["reply_traits"]["diagnostic"]
    )
    link_only = next(
        row
        for row in artifact["individual_results"]
        if row["reply_traits"]["link_only"]
    )
    remedy = next(
        row
        for row in artifact["individual_results"]
        if "spv_resync" in row["remedy_tags"]
    )

    assert diagnostic["review_status"] == "pending"
    assert link_only["wiki_links"] == ["https://bisq.wiki/Dispute_resolution#Mediation"]
    assert remedy["wiki_links"] == ["https://bisq.wiki/Resyncing_SPV_file#From_the_GUI"]
    assert remedy["remedy_tags"] == [
        "delete_outdated_tor_files",
        "spv_resync",
    ]
    assert remedy["metadata"]["protocol"] == "multisig_v1"
    assert remedy["metadata"]["behavior_labels"] == {
        "reviewed": False,
        "scam_warning_warranted": False,
        "staff_linked_wiki": True,
        "troubleshooting": True,
        "diagnostic_expected": False,
        "remedy_terms": ["delete outdated tor files", "SPV resync"],
    }
    assert diagnostic["metadata"]["behavior_labels"]["diagnostic_expected"] is True


def test_wiki_links_and_remedy_tags_use_deterministic_allowlists() -> None:
    text = (
        "Use https://bisq.wiki/Z_page, then https://bisq.wiki/A_page. "
        "Ignore https://bisq.wiki.example/unsafe, "
        "https://bisq.wiki@evil.example/phish, "
        "https://bisq.wiki:443.evil.example/phish, and "
        "https://bisq.wiki%2eevil.example/phish. Delete outdated Tor files, "
        "run an SPV resync, copy the data directory as-is, revert to normal SEPA, "
        "and use Ctrl-O to open mediation."
    )

    assert extractor._extract_wiki_links(text) == (
        "https://bisq.wiki/A_page",
        "https://bisq.wiki/Z_page",
    )
    assert extractor._extract_remedy_tags(text) == (
        "delete_outdated_tor_files",
        "spv_resync",
        "copy_data_directory_as_is",
        "revert_to_normal_sepa",
        "open_mediation_ctrl_o",
    )


def test_known_matrix_identifiers_are_redacted_from_message_text() -> None:
    messages = _messages()
    question = messages[0]
    question["room_id"] = "!private-room:example.invalid"
    question["content"]["body"] += (
        " My identifiers are @user-one:example.invalid, "
        "$question-diagnostic:example.invalid, and "
        "!private-room:example.invalid. Unknown identifiers are "
        "@outsider:elsewhere.invalid and $ABCDEFGHIJKLMNOPQRSTUV."
    )

    _candidates, behavior_candidates, _rejects, _examples = (
        extractor.extract_candidates(
            messages,
            staff_ids={STAFF_ID},
            staff_localparts=set(),
            detector=StubProtocolDetector(),
        )
    )
    diagnostic = next(
        candidate for candidate in behavior_candidates if candidate.is_diagnostic_reply
    )

    assert diagnostic.question.count("[matrix-identifier]") == 5
    assert "example.invalid" not in diagnostic.question


def test_review_text_redacts_pii_and_preserves_validated_wiki_links() -> None:
    raw = (
        "Email trader@example.invalid or call 555-123-4567 from 192.0.2.10. "
        "Wallet bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh. "
        "Avoid http://abcdefghijklmnop.onion/path?token=secret-value. "
        "Keep https://bisq.wiki/Resyncing_SPV_file#From_the_GUI."
    )

    sanitized = extractor._sanitize_review_text(raw, set())

    assert "trader@example.invalid" not in sanitized
    assert "555-123-4567" not in sanitized
    assert "192.0.2.10" not in sanitized
    assert "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh" not in sanitized
    assert ".onion" not in sanitized
    assert "secret-value" not in sanitized
    assert "https://bisq.wiki/Resyncing_SPV_file#From_the_GUI" in sanitized


@pytest.mark.parametrize(
    "unsafe_link",
    [
        "https://bisq.wiki/Support/trader@example.invalid",
        "https://bisq.wiki/Support?token=secret-value&user=trader@example.invalid",
        "https://bisq.wiki/IP/192.0.2.10",
        "https://bisq.wiki/Wallet/bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
    ],
)
def test_review_text_drops_valid_wiki_url_when_it_contains_pii(
    unsafe_link: str,
) -> None:
    sanitized = extractor._sanitize_review_text(f"See {unsafe_link}.", set())

    assert sanitized == "See [REDACTED_WIKI_URL]."


def test_exact_staff_id_does_not_trust_same_localpart_on_other_homeserver() -> None:
    messages = _messages()
    for message in messages:
        if message.get("sender") == STAFF_ID:
            message["sender"] = "@staff-synthetic:attacker.invalid"

    candidates, behavior_candidates, _rejects, _examples = extractor.extract_candidates(
        messages,
        staff_ids={STAFF_ID},
        staff_localparts=set(),
        detector=StubProtocolDetector(),
    )

    assert candidates == []
    assert behavior_candidates == []


def test_missing_faq_correlation_is_later_only_deterministic_and_sanitized() -> None:
    _candidates, behavior_candidates, _rejects, _rejected_examples = _extract()
    missing_questions = extractor._load_missing_faq_questions(
        MISSING_FAQ_FIXTURE,
        sender_hash_salt="fixture-salt",
    )

    first = extractor._to_behavior_review(
        candidates=behavior_candidates,
        source_sha256="a" * 64,
        missing_questions=missing_questions,
        missing_faq_source_sha256="b" * 64,
        missing_match_threshold=0.55,
        sender_hash_salt="fixture-salt",
    )
    second = extractor._to_behavior_review(
        candidates=behavior_candidates,
        source_sha256="a" * 64,
        missing_questions=missing_questions,
        missing_faq_source_sha256="b" * 64,
        missing_match_threshold=0.55,
        sender_hash_salt="fixture-salt",
    )
    remedy = next(
        row for row in first["individual_results"] if "spv_resync" in row["remedy_tags"]
    )
    annotation = remedy["missing_faq_match"]

    assert first["individual_results"] == second["individual_results"]
    assert annotation is not None
    assert set(annotation) == {"reference_hash", "score", "reason"}
    assert annotation["reason"] in {
        "exact_normalized_question",
        "strong_token_containment",
        "combined_lexical_similarity",
    }
    assert annotation["score"] >= 0.55
    assert annotation["reference_hash"] == extractor._hash_reference(
        "sanitized-missing-001",
        namespace="missing-faq-reference",
        salt="fixture-salt",
    )

    candidate = next(
        item for item in behavior_candidates if "spv_resync" in item.remedy_tags
    )
    same_time = extractor.MissingFAQQuestion(
        reference_hash="c" * 64,
        question=candidate.question,
        created_at_ms=candidate.answer_ts,
    )
    assert (
        extractor._find_missing_faq_match(candidate, [same_time], threshold=0.55)
        is None
    )

    unrelated_pairs = [
        (
            "Why is my payment stuck after restart?",
            "Why is my SPV sync stuck after restart?",
        ),
        (
            "My payment failed after restart; what should I do?",
            "My wallet sync failed after an update; what should I do?",
        ),
        (
            "Why did my bank payment fail?",
            "Why did the application startup fail?",
        ),
    ]
    for left, right in unrelated_pairs:
        score, _reason = extractor._question_match_score(left, right)
        assert score < extractor.DEFAULT_MISSING_MATCH_THRESHOLD

    serialized = json.dumps(first)
    assert "sanitized-missing-001" not in serialized
    assert "sanitized-future-002" not in serialized
    assert (
        "My Bisq 1 wallet is stuck during SPV sync; how can I repair it?"
        not in serialized
    )


def test_all_outputs_omit_raw_matrix_identifiers_and_room_metadata() -> None:
    candidates, behavior_candidates, rejects, rejected_examples = _extract()
    selected, selected_counts = extractor.select_samples(
        candidates,
        max_samples=10,
        bisq1_ratio=1.0,
        include_unknown=True,
    )
    outputs: dict[str, Any] = {
        "samples": extractor._to_samples(selected, sender_hash_salt="fixture-salt"),
        "review": extractor._to_review(
            source_sha256="a" * 64,
            total_messages=len(_messages()),
            extracted_candidates=len(candidates),
            selected=selected,
            selected_counts=selected_counts,
            reject_counts=extractor.Counter(rejects),
            extra_rejections=rejected_examples,
            sender_hash_salt="fixture-salt",
        ),
        "behavior": extractor._to_behavior_review(
            candidates=behavior_candidates,
            source_sha256="a" * 64,
            missing_questions=[],
            missing_faq_source_sha256=None,
            missing_match_threshold=0.55,
            sender_hash_salt="fixture-salt",
        ),
    }
    serialized = json.dumps(outputs)

    raw_values = {
        str(message.get(field, ""))
        for message in _messages()
        for field in ("event_id", "sender")
    }
    assert all(raw_value not in serialized for raw_value in raw_values if raw_value)
    assert "!synthetic-room:example.invalid" not in serialized
    assert _all_keys(outputs).isdisjoint(
        {"sender", "event_id", "room_id", "room_name", "question_ts", "answer_ts"}
    )
    assert all(
        len(row["staff_identity_hash"]) == 64
        for row in outputs["behavior"]["individual_results"]
    )


def test_missing_faq_input_rejects_identifier_bearing_rows(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.json"
    path.write_text(
        json.dumps(
            [
                {
                    "reference": "safe-reference",
                    "question": "Why is this test question missing from the FAQ?",
                    "created_at_ms": 1,
                    "event_id": "$raw-event",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="forbidden keys: event_id"):
        extractor._load_missing_faq_questions(path, sender_hash_salt="fixture-salt")

    raw_reference_path = tmp_path / "unsafe-reference.json"
    raw_reference_path.write_text(
        json.dumps(
            [
                {
                    "reference": "$raw-matrix-event:example.invalid",
                    "question": "Why is this support question missing from the FAQ?",
                    "created_at_ms": 1,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must not contain Matrix identifiers"):
        extractor._load_missing_faq_questions(
            raw_reference_path, sender_hash_salt="fixture-salt"
        )


def test_cli_writes_three_offline_review_artifacts(tmp_path: Path, monkeypatch) -> None:
    samples_path = tmp_path / "samples.json"
    review_path = tmp_path / "review.json"
    behavior_path = tmp_path / "behavior.json"
    monkeypatch.setattr(extractor, "ProtocolDetector", StubProtocolDetector)
    monkeypatch.setattr(
        extractor,
        "_build_staff_sets",
        lambda _args: ({STAFF_ID}, set()),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "extract_matrix_eval_samples",
            "--input",
            str(MATRIX_FIXTURE),
            "--output",
            str(samples_path),
            "--review-output",
            str(review_path),
            "--behavior-output",
            str(behavior_path),
            "--missing-faq-input",
            str(MISSING_FAQ_FIXTURE),
            "--include-unknown",
            "--sender-hash-salt",
            "fixture-salt",
        ],
    )

    assert extractor.main() == 0
    assert samples_path.exists()
    assert review_path.exists()
    behavior = json.loads(behavior_path.read_text(encoding="utf-8"))
    assert behavior["schema_version"] == extractor.BEHAVIOR_SCHEMA_VERSION
    assert behavior["statistics"]["behavior_candidates"] == 5
    assert behavior["statistics"]["missing_faq_matches"] == 1
