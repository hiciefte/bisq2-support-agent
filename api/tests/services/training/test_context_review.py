"""Contextual review vetoes must survive scores, routing, and persistence."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.services.knowledge.candidate_repository import KnowledgeCandidateRepository
from app.services.knowledge.comparison_engine import AnswerComparisonEngine
from app.services.knowledge.knowledge_pipeline_service import KnowledgePipelineService


def judgment(
    disposition="accept", dimension=None, evidence="Supported by supplied context"
):
    checks = {
        name: {"status": "supported", "evidence": evidence}
        for name in (
            "protocol",
            "trade_stage",
            "action_preconditions",
            "procedural_support",
        )
    }
    if dimension:
        checks[dimension]["status"] = "unsupported"
    return {
        "factual_alignment": 1.0,
        "contradiction_score": 0.0,
        "completeness": 1.0,
        "hallucination_risk": 0.0,
        "reasoning": "Same topic and high semantic agreement",
        "disposition": disposition,
        "context_checks": checks,
    }


def engine_for(payload):
    engine = AnswerComparisonEngine(
        ai_client=Mock(),
        embeddings_model=SimpleNamespace(embed_query=lambda _: [1.0, 0.0]),
        calibration_samples_required=0,
    )
    engine._call_llm_with_retry = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
            ]
        )
    )
    return engine


def pipeline_for(engine):
    service = object.__new__(KnowledgePipelineService)
    service.comparison_engine = engine
    service.repository = SimpleNamespace(is_calibration_mode=lambda: False)
    service.learning_engine = SimpleNamespace(
        get_routing_recommendation=Mock(return_value="AUTO_APPROVE")
    )
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dimension,disposition,evidence",
    [
        (
            "procedural_support",
            "edit",
            "The generated deadline uses completion instead of the established trade date.",
        ),
        (
            "procedural_support",
            "edit",
            "The staff says SPV resync; the generated steps only restart the app.",
        ),
        (
            "action_preconditions",
            "reject",
            "Neither answer establishes that removing trade state is appropriate.",
        ),
        (
            "protocol",
            "needs_evidence",
            "The migration procedure depends on a version not established in the question.",
        ),
        (
            "trade_stage",
            "reject",
            "The buyer has already paid; pre-payment cancellation advice does not apply.",
        ),
    ],
)
async def test_context_failures_override_perfect_scores_and_survive_storage(
    tmp_path, dimension, disposition, evidence
):
    engine = engine_for(judgment(disposition, dimension, evidence))
    service = pipeline_for(engine)
    comparison = await service._compare_answers(
        "synthetic", "Question", "Staff", "Generated"
    )
    assert comparison.final_score == pytest.approx(1.0)
    assert comparison.requires_full_review is True
    routing, _ = service._determine_routing(
        comparison.final_score,
        comparison.embedding_similarity,
        requires_full_review=comparison.requires_full_review,
    )
    assert routing == "FULL_REVIEW"
    service.learning_engine.get_routing_recommendation.assert_not_called()
    repository = KnowledgeCandidateRepository(str(tmp_path / "review.db"))
    candidate = repository.create(
        source="matrix",
        source_event_id="synthetic",
        source_timestamp="2026-09-17T00:00:00Z",
        question_text="Question",
        staff_answer="Staff",
        routing=routing,
        llm_reasoning=comparison.llm_reasoning,
        final_score=comparison.final_score,
    )
    reloaded = KnowledgeCandidateRepository(repository.db_path).get_by_id(candidate.id)
    assert reloaded.routing == "FULL_REVIEW"
    assert disposition in reloaded.llm_reasoning
    assert evidence in reloaded.llm_reasoning


@pytest.mark.asyncio
@pytest.mark.parametrize("not_applicable", [False, True])
async def test_supported_or_irrelevant_context_preserves_eligible_routing(
    not_applicable,
):
    payload = judgment()
    if not_applicable:
        payload["context_checks"]["trade_stage"] = {
            "status": "not_applicable",
            "evidence": "The answer explains local storage without trade advice.",
        }
    engine = engine_for(payload)
    result = await engine.compare(
        "synthetic", "Question", "Supported answer", "Faithful paraphrase"
    )
    assert result.requires_full_review is False
    assert result.routing == "AUTO_APPROVE"
    service = pipeline_for(engine)
    comparison = await service._compare_answers(
        "synthetic", "Question", "Staff", "Generated"
    )
    assert (
        service._determine_routing(
            comparison.final_score,
            comparison.embedding_similarity,
            requires_full_review=comparison.requires_full_review,
        )[0]
        == "AUTO_APPROVE"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pop("context_checks"),
        lambda p: p.pop("disposition"),
        lambda p: p.update(disposition=[]),
        lambda p: p.update(context_checks=[]),
        lambda p: p["context_checks"].pop("protocol"),
        lambda p: p["context_checks"]["protocol"].update(status=[]),
        lambda p: p["context_checks"]["protocol"].update(evidence=" "),
        lambda p: p["context_checks"]["protocol"].update(status="unclear"),
        lambda p: p["context_checks"]["protocol"].update(status="unsupported"),
        lambda p: p.update(disposition="edit"),
    ],
)
async def test_missing_invalid_or_nonaccept_review_cannot_approve(mutation):
    payload = judgment()
    mutation(payload)
    result = await engine_for(payload).compare(
        "synthetic", "Question", "Staff", "Generated"
    )
    assert result.requires_full_review is True
    assert result.routing == "FULL_REVIEW"


@pytest.mark.asyncio
async def test_missing_engine_veto_defaults_to_full_review():
    legacy = SimpleNamespace(
        embedding_similarity=1.0,
        factual_alignment=1.0,
        contradiction_score=0.0,
        completeness=1.0,
        hallucination_risk=0.0,
        final_score=1.0,
        llm_reasoning="Legacy scores without context review",
    )
    service = pipeline_for(SimpleNamespace(compare=AsyncMock(return_value=legacy)))
    result = await service._compare_answers(
        "synthetic", "Question", "Staff", "Generated"
    )
    assert result.requires_full_review is True


@pytest.mark.asyncio
async def test_replay_writes_private_indexed_evidence(tmp_path, monkeypatch, capsys):
    from app.scripts.replay_comparison_review import replay

    monkeypatch.setattr(
        AnswerComparisonEngine, "_llm_judge", AsyncMock(return_value=judgment())
    )
    source = tmp_path / "input.json"
    output = tmp_path / "result.json"
    source.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "private-id-marker",
                        "staff_sender": "private-staff-marker",
                        "question_text": "Question",
                        "staff_answer": "Staff",
                        "generated_answer": "Generated",
                    }
                ]
            }
        )
    )
    await replay(source, output, "openai:gpt-4o-mini")
    report = json.loads(output.read_text())
    assert report["samples"][0]["sample_index"] == 1
    assert report["samples"][0]["requires_full_review"] is False
    assert output.stat().st_mode & 0o777 == 0o600
    assert "private-id-marker" not in output.read_text()
    assert "private-staff-marker" not in output.read_text()
    assert capsys.readouterr().out == "reviewed_samples=1; private_report_written=yes\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "factual_alignment",
        "contradiction_score",
        "completeness",
        "hallucination_risk",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        None,
        "0.9",
        [],
        {},
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.01,
        1.01,
        10**400,
    ],
)
async def test_invalid_scores_fail_before_arithmetic_even_when_context_accepts(
    field, value
):
    payload = judgment()
    payload[field] = value
    engine = engine_for(payload)
    result = await engine.compare("synthetic", "Question", "Staff", "Generated")
    assert result.evaluation_status == "failed"
    assert result.requires_full_review is True
    assert result.routing == "FULL_REVIEW"
    assert result.final_score == 0.0
    assert field in result.llm_reasoning
    assert engine._review_guard(payload)[0] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "factual_alignment",
        "contradiction_score",
        "completeness",
        "hallucination_risk",
    ],
)
async def test_missing_score_cannot_use_an_implicit_default(field):
    payload = judgment()
    del payload[field]
    result = await engine_for(payload).compare(
        "synthetic", "Question", "Staff", "Generated"
    )
    assert result.evaluation_status == "failed"
    assert result.routing == "FULL_REVIEW"
    assert result.final_score == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("number_type", [int, float])
async def test_valid_integer_and_float_scores_retain_approval(number_type):
    payload = judgment()
    for field in (
        "factual_alignment",
        "contradiction_score",
        "completeness",
        "hallucination_risk",
    ):
        payload[field] = number_type(payload[field])
    result = await engine_for(payload).compare(
        "synthetic", "Question", "Staff", "Generated"
    )
    assert result.evaluation_status == "success"
    assert result.requires_full_review is False
    assert result.routing == "AUTO_APPROVE"
    assert result.final_score == pytest.approx(1.0)
