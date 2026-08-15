from __future__ import annotations

import copy
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from app.channels.escalation_localization import render_escalation_notice
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.scripts.release_ai_quality_gate import (
    DEFAULT_API_BASE_URL,
    ReviewDraft,
    build_release_gate_summary,
    generate_fresh_rows,
    load_release_sample_set,
    load_review_draft,
)
from app.scripts.release_ai_quality_report import (
    AGGREGATE_FAILURE_CODES,
    PER_SAMPLE_FAILURE_CODES,
    model_sha256,
    validate_release_ai_quality_report,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES_PATH = REPO_ROOT / "api/data/evaluation/release_ai_quality_samples_v1.json"
BEHAVIOR_FIXTURE_PATH = REPO_ROOT / "api/tests/fixtures/staff_alignment_behavior.json"


def _loaded_samples() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return load_release_sample_set(SAMPLES_PATH)


def _passing_rows() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest, samples = _loaded_samples()
    behavior_fixture = json.loads(BEHAVIOR_FIXTURE_PATH.read_text(encoding="utf-8"))
    reviewed_wiki_url = next(
        row["source_urls"][0]
        for row in behavior_fixture
        if row.get("case_id") == "wiki-spv-resync"
    )
    answer_by_case: dict[str, str] = {
        "scam-private-message": SAFETY_REFLEX_WARNING,
        "direct-trade-limit": samples[1]["ground_truth"],
        "wiki-spv-resync": "Follow the SPV resync procedure.",
        "diagnostic-sync-version": "Which Bisq version are you using?",
        "explicit-human-escalation": "Use mediation and wait for human review.",
        "live-market-price": "The current fixture price is EUR 50,000.",
        "live-offerbook": "There are no EUR offers currently available.",
    }
    response_by_case: dict[str, dict[str, Any]] = {
        "scam-private-message": {},
        "direct-trade-limit": {},
        "wiki-spv-resync": {},
        "diagnostic-sync-version": {},
        "explicit-human-escalation": {
            "requires_human": True,
            "routing_action": "needs_human",
        },
        "live-market-price": {"mcp_tools": ["get_market_prices"]},
        "live-offerbook": {"mcp_tools": ["get_offerbook"]},
    }

    rows: list[dict[str, Any]] = []
    for sample in samples:
        case_id = sample["case_id"]
        response = {
            "request_error": None,
            "requires_human": False,
            "routing_action": "auto_send",
            "mcp_tools": [],
            "evaluation_source": "delivered",
            **response_by_case[case_id],
        }
        if response["requires_human"]:
            response["evaluation_source"] = "review_draft"
        rows.append(
            {
                **sample,
                "answer": answer_by_case[case_id],
                "review_delivery_valid": (True if response["requires_human"] else None),
                "source_urls": (
                    [reviewed_wiki_url] if case_id == "wiki-spv-resync" else []
                ),
                "release_response": response,
            }
        )
    return manifest, rows


def _build_summary(
    manifest: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return build_release_gate_summary(
        rows,
        sample_manifest=manifest,
        sample_sha256="a" * 64,
        model_id="openai:release-model",
        temperature=0.0,
        prompt_sha256="b" * 64,
        commit="c" * 40,
    )


def test_versioned_release_sample_set_is_reviewed_sanitized_and_answer_free() -> None:
    manifest, samples = _loaded_samples()

    assert manifest["sample_set_version"] == "1.0.0"
    assert {sample["metadata"]["case_kind"] for sample in samples}.issuperset(
        {"live_data", "escalation"}
    )
    assert all("answer" not in sample for sample in samples)


def test_release_sample_loader_rejects_precomputed_answer(tmp_path: Path) -> None:
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    raw["samples"][0]["answer"] = "precomputed"
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported or generated fields"):
        load_release_sample_set(path)


@pytest.mark.parametrize("schema_version", (True, 1.0, "1"))
def test_release_sample_loader_requires_integer_schema_version(
    tmp_path: Path, schema_version: object
) -> None:
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    raw["schema_version"] = schema_version
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported release sample-set schema"):
        load_release_sample_set(path)


def test_release_sample_loader_requires_real_live_data_contract(tmp_path: Path) -> None:
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    live_case = next(
        sample
        for sample in raw["samples"]
        if sample["metadata"]["case_kind"] == "live_data"
    )
    live_case["metadata"]["release_gate"]["required_mcp_tools"] = []
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="must require an MCP tool"):
        load_release_sample_set(path)


def test_release_sample_loader_requires_live_answer_evidence(tmp_path: Path) -> None:
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    live_case = next(
        sample
        for sample in raw["samples"]
        if sample["metadata"]["case_kind"] == "live_data"
    )
    live_case["metadata"]["release_gate"]["required_answer_terms"] = []
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="must require answer evidence"):
        load_release_sample_set(path)


@pytest.mark.parametrize(
    ("threshold", "value"),
    (
        ("max_answer_length_ratio", 0),
        ("max_answer_length_ratio", -0.1),
        ("min_greeting_avoidance_rate", -0.01),
        ("min_scam_warning_precision", 1.01),
        ("min_scam_warning_recall", -0.01),
        ("min_wiki_link_recall", 1.01),
        ("min_diagnostic_question_rate", -0.01),
        ("min_remedy_term_overlap", 1.01),
    ),
)
def test_release_sample_loader_rejects_out_of_range_aggregate_thresholds(
    tmp_path: Path, threshold: str, value: float
) -> None:
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    raw["aggregate_thresholds"][threshold] = value
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match=r"positive|safe range"):
        load_release_sample_set(path)


@pytest.mark.parametrize(
    ("location", "field"),
    (
        ("top", "generated_answers"),
        ("labels", "generated_answer"),
        ("floor", "raw_response"),
    ),
)
def test_release_sample_loader_rejects_hidden_or_unknown_fields(
    tmp_path: Path, location: str, field: str
) -> None:
    raw = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    if location == "top":
        raw[field] = ["precomputed"]
    elif location == "labels":
        raw["samples"][0]["metadata"]["behavior_labels"][field] = "precomputed"
    else:
        raw["samples"][0]["metadata"]["release_gate"][field] = "precomputed"
    path = tmp_path / "samples.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError):
        load_release_sample_set(path)


def test_fresh_release_summary_passes_aggregate_and_per_case_floors() -> None:
    manifest, rows = _passing_rows()

    summary = _build_summary(manifest, rows)

    validate_release_ai_quality_report(
        summary,
        expected_commit="c" * 40,
        expected_model_sha256=model_sha256("openai:release-model"),
    )
    assert summary["gate"]["passed"] is True
    assert all(case["gate"]["passed"] for case in summary["per_sample"])
    assert summary["generation"] == {
        "model_sha256": model_sha256("openai:release-model"),
        "temperature": 0.0,
        "prompt_sha256": "b" * 64,
    }

    serialized = json.dumps(summary)
    for row in rows:
        assert row["question"] not in serialized
        assert row["ground_truth"] not in serialized
        assert row["answer"] not in serialized
    assert "openai:release-model" not in serialized


def test_per_case_mcp_floor_cannot_be_hidden_by_aggregate_scores() -> None:
    manifest, rows = _passing_rows()
    candidate = copy.deepcopy(rows)
    live_case = next(row for row in candidate if row["case_id"] == "live-market-price")
    live_case["release_response"]["mcp_tools"] = []

    summary = _build_summary(manifest, candidate)

    assert summary["metrics"]["greeting_avoidance_rate"] == 1.0
    assert summary["gate"]["passed"] is False
    live_case = next(
        row for row in summary["per_sample"] if row["case_id"] == "live-market-price"
    )
    assert live_case["gate"]["failures"] == ["required_mcp_tool_missing"]
    assert "per_sample_gate_failed" in summary["gate"]["failures"]


def test_live_tool_call_must_be_reflected_in_the_answer() -> None:
    manifest, rows = _passing_rows()
    candidate = copy.deepcopy(rows)
    live_case = next(row for row in candidate if row["case_id"] == "live-market-price")
    live_case["answer"] = "The live tool was called successfully."

    summary = _build_summary(manifest, candidate)

    live_case = next(
        row for row in summary["per_sample"] if row["case_id"] == "live-market-price"
    )
    assert live_case["response_contract"]["mcp_tools"] == ["get_market_prices"]
    assert live_case["gate"]["passed"] is False
    assert live_case["gate"]["failures"] == ["required_answer_term_missing"]
    assert "per_sample_gate_failed" in summary["gate"]["failures"]


def test_required_answer_terms_do_not_match_inside_larger_tokens() -> None:
    manifest, rows = _passing_rows()
    candidate = copy.deepcopy(rows)
    offerbook_case = next(
        row for row in candidate if row["case_id"] == "live-offerbook"
    )
    offerbook_case["answer"] = "There are notable EUR offers currently available."

    summary = _build_summary(manifest, candidate)

    result = next(
        row for row in summary["per_sample"] if row["case_id"] == "live-offerbook"
    )
    assert result["gate"]["failures"] == ["required_answer_term_missing"]
    assert "per_sample_gate_failed" in summary["gate"]["failures"]


def test_review_gate_rejects_an_invalid_public_replacement() -> None:
    manifest, rows = _passing_rows()
    candidate = copy.deepcopy(rows)
    escalation_case = next(
        row for row in candidate if row["case_id"] == "explicit-human-escalation"
    )
    escalation_case["review_delivery_valid"] = False

    summary = _build_summary(manifest, candidate)

    result = next(
        row
        for row in summary["per_sample"]
        if row["case_id"] == "explicit-human-escalation"
    )
    assert "review_answer_not_replaced" in result["gate"]["failures"]
    assert "per_sample_gate_failed" in summary["gate"]["failures"]


def test_failed_summary_archives_only_allowlisted_failure_codes() -> None:
    manifest, rows = _passing_rows()
    candidate = copy.deepcopy(rows)
    private_text = (
        "exception credential-value https://service.invalid/private generated answer"
    )
    candidate[0]["answer"] = private_text
    candidate[0]["release_response"]["request_error"] = "request_failed"

    summary = _build_summary(manifest, candidate)
    serialized = json.dumps(summary)

    assert summary["gate"]["passed"] is False
    assert set(summary["gate"]["failures"]).issubset(AGGREGATE_FAILURE_CODES)
    assert all(
        set(row["gate"]["failures"]).issubset(PER_SAMPLE_FAILURE_CODES)
        for row in summary["per_sample"]
    )
    assert private_text not in serialized
    assert "service.invalid" not in serialized


@pytest.mark.asyncio
async def test_generation_queries_full_pipeline_without_hook_bypass() -> None:
    _, samples = _loaded_samples()
    sample = next(row for row in samples if row["case_id"] == "live-market-price")
    requests: list[httpx.Request] = []
    review_draft_loader = AsyncMock(return_value=None)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(
            200,
            json={
                "answer": "The live market tool returned the reviewed fixture value.",
                "sources": [],
                "requires_human": False,
                "routing_action": "auto_send",
                "mcp_tools_used": [
                    {
                        "tool": "get_market_prices",
                        "result": "sensitive tool payload must not be retained",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await generate_fresh_rows(
            client,
            api_url=DEFAULT_API_BASE_URL,
            samples=[sample],
            timeout_seconds=5,
            review_draft_loader=review_draft_loader,
        )

    payload = json.loads(requests[1].content)
    assert payload == {"question": sample["question"], "chat_history": []}
    review_draft_loader.assert_not_awaited()
    assert rows[0]["release_response"] == {
        "request_error": None,
        "requires_human": False,
        "routing_action": "auto_send",
        "mcp_tools": ["get_market_prices"],
        "evaluation_source": "delivered",
    }
    assert "sensitive tool payload" not in json.dumps(rows[0]["release_response"])


@pytest.mark.asyncio
async def test_generation_scores_redacted_review_draft_after_public_replacement() -> (
    None
):
    manifest, samples = _loaded_samples()
    sample = next(
        row for row in samples if row["case_id"] == "explicit-human-escalation"
    )
    message_id = "web_01234567-89ab-4cde-8fab-0123456789ab"
    public_notice = "A team member will review this and follow up."
    review_draft = "Use mediation and wait for human review."
    review_draft_loader = AsyncMock(
        return_value=ReviewDraft(
            answer=review_draft,
            expected_delivery=public_notice,
        )
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(
            200,
            json={
                "answer": public_notice,
                "sources": [],
                "message_id": message_id,
                "requires_human": True,
                "routing_action": "needs_human",
                "mcp_tools_used": [],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await generate_fresh_rows(
            client,
            api_url=DEFAULT_API_BASE_URL,
            samples=[sample],
            timeout_seconds=5,
            review_draft_loader=review_draft_loader,
        )

    assert json.loads(requests[1].content) == {
        "question": sample["question"],
        "chat_history": [],
    }
    review_draft_loader.assert_awaited_once_with(message_id)
    assert rows[0]["answer"] == review_draft
    assert rows[0]["review_delivery_valid"] is True
    assert rows[0]["release_response"]["evaluation_source"] == "review_draft"

    summary = _build_summary(manifest, rows)
    assert summary["per_sample"][0]["response_contract"]["evaluation_source"] == (
        "review_draft"
    )
    serialized = json.dumps(summary)
    assert review_draft not in serialized
    assert public_notice not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_delivery",
    (
        "Use mediation and wait for human review.",
        (
            "A team member will review this and follow up.\n\n"
            "Use mediation and wait for human review."
        ),
        "A team member will review this and follow up.\n\nUse mediation",
    ),
)
async def test_generation_rejects_public_draft_leakage(
    unsafe_delivery: str,
) -> None:
    manifest, samples = _loaded_samples()
    sample = next(
        row for row in samples if row["case_id"] == "explicit-human-escalation"
    )
    message_id = "web_01234567-89ab-4cde-8fab-0123456789ab"
    public_notice = "A team member will review this and follow up."
    review_draft = "Use mediation and wait for human review."
    review_draft_loader = AsyncMock(
        return_value=ReviewDraft(
            answer=review_draft,
            expected_delivery=public_notice,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(
            200,
            json={
                "answer": unsafe_delivery,
                "sources": [],
                "message_id": message_id,
                "requires_human": True,
                "routing_action": "needs_human",
                "mcp_tools_used": [],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await generate_fresh_rows(
            client,
            api_url=DEFAULT_API_BASE_URL,
            samples=[sample],
            timeout_seconds=5,
            review_draft_loader=review_draft_loader,
        )

    assert rows[0]["review_delivery_valid"] is False
    summary = _build_summary(manifest, rows)
    result = summary["per_sample"][0]
    assert "review_answer_not_replaced" in result["gate"]["failures"]
    serialized = json.dumps(summary)
    assert review_draft not in serialized
    assert unsafe_delivery not in serialized


@pytest.mark.asyncio
async def test_generation_fails_closed_when_review_draft_is_unavailable() -> None:
    manifest, samples = _loaded_samples()
    sample = next(
        row for row in samples if row["case_id"] == "explicit-human-escalation"
    )
    message_id = "web_01234567-89ab-4cde-8fab-0123456789ab"
    review_draft_loader = AsyncMock(return_value=None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(
            200,
            json={
                "answer": "A team member will review this and follow up.",
                "sources": [],
                "message_id": message_id,
                "requires_human": True,
                "routing_action": "needs_human",
                "mcp_tools_used": [],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await generate_fresh_rows(
            client,
            api_url=DEFAULT_API_BASE_URL,
            samples=[sample],
            timeout_seconds=5,
            review_draft_loader=review_draft_loader,
        )

    summary = _build_summary(manifest, rows)
    result = summary["per_sample"][0]
    assert result["response_contract"]["evaluation_source"] == "unavailable"
    assert result["gate"]["passed"] is False
    assert "review_draft_unavailable" in result["gate"]["failures"]
    assert "empty_answer" in result["gate"]["failures"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message_id", "routing_action"),
    (
        (None, "needs_human"),
        ("not-a-web-message-id", "needs_human"),
        ("web_01234567-89ab-4cde-8fab-0123456789ab", "unknown"),
    ),
)
async def test_generation_fails_closed_for_missing_identity_or_unknown_routing(
    message_id: str | None,
    routing_action: str,
) -> None:
    manifest, samples = _loaded_samples()
    sample = next(
        row for row in samples if row["case_id"] == "explicit-human-escalation"
    )
    review_draft_loader = AsyncMock(return_value=None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        payload: dict[str, Any] = {
            "answer": "A team member will review this and follow up.",
            "sources": [],
            "requires_human": False,
            "routing_action": routing_action,
            "mcp_tools_used": [],
        }
        if message_id is not None:
            payload["message_id"] = message_id
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await generate_fresh_rows(
            client,
            api_url=DEFAULT_API_BASE_URL,
            samples=[sample],
            timeout_seconds=5,
            review_draft_loader=review_draft_loader,
        )

    if message_id and message_id.startswith("web_"):
        review_draft_loader.assert_awaited_once_with(message_id)
    else:
        review_draft_loader.assert_not_awaited()
    result = _build_summary(manifest, rows)["per_sample"][0]
    assert result["response_contract"]["evaluation_source"] == "unavailable"
    assert "review_draft_unavailable" in result["gate"]["failures"]


@pytest.mark.asyncio
async def test_generation_sanitizes_review_loader_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manifest, samples = _loaded_samples()
    sample = next(
        row for row in samples if row["case_id"] == "explicit-human-escalation"
    )
    private_detail = "private database exception detail"
    review_draft_loader = AsyncMock(side_effect=RuntimeError(private_detail))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(
            200,
            json={
                "answer": "A team member will review this and follow up.",
                "sources": [],
                "message_id": "web_01234567-89ab-4cde-8fab-0123456789ab",
                "requires_human": True,
                "routing_action": "needs_human",
                "mcp_tools_used": [],
            },
        )

    with caplog.at_level(
        logging.WARNING,
        logger="app.scripts.release_ai_quality_gate",
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            rows = await generate_fresh_rows(
                client,
                api_url=DEFAULT_API_BASE_URL,
                samples=[sample],
                timeout_seconds=5,
                review_draft_loader=review_draft_loader,
            )

    summary = _build_summary(manifest, rows)
    assert "review_draft_unavailable" in summary["per_sample"][0]["gate"]["failures"]
    assert sample["case_id"] in caplog.text
    assert "RuntimeError" in caplog.text
    assert private_detail not in caplog.text
    assert private_detail not in json.dumps(rows)
    assert private_detail not in json.dumps(summary)


@pytest.mark.asyncio
async def test_review_draft_loader_reads_only_valid_web_escalations(
    tmp_path: Path,
) -> None:
    from app.models.escalation import EscalationCreate
    from app.services.escalation.escalation_repository import EscalationRepository

    db_path = tmp_path / "escalations.db"
    repository = EscalationRepository(str(db_path))
    await repository.initialize()
    message_id = "web_01234567-89ab-4cde-8fab-0123456789ab"
    await repository.create(
        EscalationCreate(
            message_id=message_id,
            channel="web",
            user_id="quality-gate",
            question="Reviewed question",
            ai_draft_answer_original="PII-filtered review draft",
            ai_draft_answer="Canonical draft",
            confidence_score=0.0,
            routing_action="needs_human",
        )
    )

    review_draft = await load_review_draft(str(db_path), message_id)
    assert review_draft == ReviewDraft(
        answer="PII-filtered review draft",
        expected_delivery=render_escalation_notice(
            channel_id="web",
            escalation_id=1,
            support_handle="support",
        ),
    )
    assert await load_review_draft(str(db_path), "not-a-web-message-id") is None

    warning_message_id = "web_aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    warning_draft = f"{SAFETY_REFLEX_WARNING}\n\nEscalated draft"
    warning_escalation = await repository.create(
        EscalationCreate(
            message_id=warning_message_id,
            channel="web",
            user_id="quality-gate",
            question="Reviewed question",
            ai_draft_answer_original=warning_draft,
            ai_draft_answer=warning_draft,
            confidence_score=0.0,
            routing_action="needs_human",
        )
    )
    warning_review_draft = await load_review_draft(
        str(db_path),
        warning_message_id,
    )
    warning_notice = render_escalation_notice(
        channel_id="web",
        escalation_id=warning_escalation.id,
        support_handle="support",
    )
    assert warning_review_draft == ReviewDraft(
        answer=warning_draft,
        expected_delivery=f"{SAFETY_REFLEX_WARNING}\n\n{warning_notice}",
    )

    other_channel_id = "web_11111111-2222-4333-8444-555555555555"
    await repository.create(
        EscalationCreate(
            message_id=other_channel_id,
            channel="matrix",
            user_id="quality-gate",
            question="Reviewed question",
            ai_draft_answer_original="Other-channel draft",
            ai_draft_answer="Other-channel draft",
            confidence_score=0.0,
            routing_action="needs_human",
        )
    )
    assert await load_review_draft(str(db_path), other_channel_id) is None


@pytest.mark.asyncio
async def test_review_draft_loader_does_not_create_a_missing_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing.db"

    with pytest.raises(sqlite3.OperationalError):
        await load_review_draft(
            str(db_path),
            "web_01234567-89ab-4cde-8fab-0123456789ab",
        )

    assert not db_path.exists()


@pytest.mark.asyncio
async def test_generation_records_safe_http_failure_without_response_detail() -> None:
    _, samples = _loaded_samples()
    review_draft_loader = AsyncMock(return_value=None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "ready"})
        return httpx.Response(503, text="internal exception detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await generate_fresh_rows(
            client,
            api_url=DEFAULT_API_BASE_URL,
            samples=[samples[0]],
            timeout_seconds=5,
            review_draft_loader=review_draft_loader,
        )

    assert rows[0]["release_response"]["request_error"] == "http_error"
    assert rows[0]["release_response"]["evaluation_source"] == "unavailable"
    review_draft_loader.assert_not_awaited()
    assert "internal exception detail" not in json.dumps(rows)
