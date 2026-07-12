"""Tests for opt-in Stage-2 divergence guidance."""

import json
import os
from pathlib import Path

import pytest
from app.core.config import Settings
from app.db.database import get_database
from app.db.run_migrations import run_migrations
from app.services.feedback.prompt_optimizer import PromptOptimizer
from app.services.feedback_service import FeedbackService

_EXISTING_GUIDANCE = "Keep existing categorized thumbs-down guidance."


def _settings(tmp_path: Path, *, enabled: bool | None = None) -> Settings:
    values = {
        "DEBUG": True,
        "DATA_DIR": str(tmp_path),
        "OPENAI_API_KEY": "test-api-key",
        "ADMIN_API_KEY": "test-admin-key-with-sufficient-length-24chars",
        "ENVIRONMENT": "testing",
        "COOKIE_SECURE": False,
    }
    if enabled is not None:
        values["ENABLE_STAGE2_DIVERGENCE_GUIDANCE"] = enabled

    settings = Settings(**values)
    db_path = os.path.join(settings.DATA_DIR, "feedback.db")
    database = get_database()
    database.reset()
    database.initialize(db_path)
    run_migrations(db_path)
    database.reset()
    database.initialize(db_path)
    return settings


def _write_report(settings: Settings, payload: object) -> None:
    path = Path(settings.STAGE2_DIVERGENCE_REPORT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _service_with_existing_guidance(settings: Settings) -> FeedbackService:
    service = FeedbackService(settings=settings)
    service.prompt_optimizer.prompt_guidance = [_EXISTING_GUIDANCE]
    return service


def test_stage2_divergence_guidance_is_disabled_by_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_report(
        settings,
        {
            "schema_version": 1,
            "divergence_counts": {"scam_warning_missing": 3},
        },
    )
    service = _service_with_existing_guidance(settings)

    assert settings.ENABLE_STAGE2_DIVERGENCE_GUIDANCE is False
    assert service.get_prompt_guidance() == [_EXISTING_GUIDANCE]


def test_enabled_report_merges_only_allowlisted_human_guidance(tmp_path: Path) -> None:
    settings = _settings(tmp_path, enabled=True)
    raw_question = "raw question must not reach the prompt"
    raw_answer = "raw model answer must not reach the prompt"
    _write_report(
        settings,
        {
            "schema_version": 1,
            "metrics": {"scam_warning_recall": 0.5},
            "divergence_counts": {
                "answer_too_long": 2,
                "scam_warning_missing": 1,
                "wiki_link_missing": 0,
                "unknown_signal": raw_answer,
            },
            "per_sample": [{"question": raw_question, "answer": raw_answer}],
        },
    )
    service = _service_with_existing_guidance(settings)

    guidance = service.get_prompt_guidance()

    assert guidance == [
        _EXISTING_GUIDANCE,
        PromptOptimizer.DIVERGENCE_GUIDANCE["answer_too_long"],
        PromptOptimizer.DIVERGENCE_GUIDANCE["scam_warning_missing"],
    ]
    assert raw_question not in " ".join(guidance)
    assert raw_answer not in " ".join(guidance)


def test_each_known_divergence_has_deterministic_guidance() -> None:
    optimizer = PromptOptimizer()
    counts = {signal: 1 for signal in PromptOptimizer.ALLOWED_DIVERGENCE_SIGNALS}
    counts["unknown_signal"] = 99

    guidance = optimizer.get_prompt_guidance(counts)

    assert guidance == list(PromptOptimizer.DIVERGENCE_GUIDANCE.values())
    diagnostic_guidance = PromptOptimizer.DIVERGENCE_GUIDANCE[
        "diagnostic_question_missing"
    ]
    assert "instead of speculative steps" in diagnostic_guidance
    assert "before giving steps" not in diagnostic_guidance


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"schema_version": 2, "divergence_counts": {"answer_too_long": 1}},
        {"schema_version": True, "divergence_counts": {"answer_too_long": 1}},
        {"schema_version": 1, "divergence_counts": []},
        {
            "schema_version": 1,
            "divergence_counts": {"answer_too_long": "1"},
        },
        {
            "schema_version": 1,
            "divergence_counts": {"answer_too_long": True},
        },
        {
            "schema_version": 1,
            "divergence_counts": {"answer_too_long": -1},
        },
    ],
)
def test_malformed_report_is_ignored_without_replacing_existing_guidance(
    tmp_path: Path, payload: object, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(tmp_path, enabled=True)
    _write_report(settings, payload)
    service = _service_with_existing_guidance(settings)

    assert service.get_prompt_guidance() == [_EXISTING_GUIDANCE]
    assert "Ignoring" in caplog.text


def test_missing_report_is_ignored_without_replacing_existing_guidance(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(tmp_path, enabled=True)
    service = _service_with_existing_guidance(settings)

    assert service.get_prompt_guidance() == [_EXISTING_GUIDANCE]
    assert "Ignoring unavailable or malformed Stage-2 divergence report" in caplog.text


def test_invalid_json_is_ignored_without_replacing_existing_guidance(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(tmp_path, enabled=True)
    report_path = Path(settings.STAGE2_DIVERGENCE_REPORT_PATH)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{not-json", encoding="utf-8")
    service = _service_with_existing_guidance(settings)

    assert service.get_prompt_guidance() == [_EXISTING_GUIDANCE]
    assert "Ignoring unavailable or malformed Stage-2 divergence report" in caplog.text
