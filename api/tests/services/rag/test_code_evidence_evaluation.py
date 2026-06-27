import pytest
from app.services.rag.code_evidence_evaluation import (
    CodeEvidenceEvalCase,
    CodeEvidenceRetrievalEvaluator,
)
from app.services.rag.interfaces import RetrievedDocument


class StaticRetriever:
    def __init__(self, results_by_query: dict[str, list[RetrievedDocument]]) -> None:
        self.results_by_query = results_by_query

    def retrieve(
        self,
        query: str,
        *,
        protocol: str | None = None,
        k: int = 3,
        min_score: float = 0.0,
    ) -> list[RetrievedDocument]:
        return self.results_by_query[query][:k]


def _doc(document_id: str) -> RetrievedDocument:
    return RetrievedDocument(
        id=document_id,
        content=f"Claim: {document_id}",
        metadata={"id": document_id, "type": "code_fact", "audience": "staff_only"},
        score=1.0,
    )


def test_retrieval_evaluator_reports_recall_at_k_and_mrr() -> None:
    retriever = StaticRetriever(
        {
            "sell offer limit": [_doc("expected-b"), _doc("distractor")],
            "startup peer bootstrap": [_doc("distractor"), _doc("expected-c")],
        }
    )
    cases = [
        CodeEvidenceEvalCase(
            question="sell offer limit",
            expected_ids=["expected-a", "expected-b"],
            protocol="bisq_easy",
        ),
        CodeEvidenceEvalCase(
            question="startup peer bootstrap",
            expected_ids=["expected-c"],
            protocol="all",
        ),
    ]

    result = CodeEvidenceRetrievalEvaluator(retriever).evaluate(cases, k=2)

    assert result.total_cases == 2
    assert result.recall_at_k == 0.75
    assert result.mrr == 0.75
    assert result.failures == [
        {
            "question": "sell offer limit",
            "expected_ids": ["expected-a", "expected-b"],
            "retrieved_ids": ["expected-b", "distractor"],
            "missing_ids": ["expected-a"],
        }
    ]


def test_retrieval_evaluator_treats_empty_expected_ids_as_invalid_case() -> None:
    retriever = StaticRetriever({"anything": [_doc("some-doc")]})

    result = CodeEvidenceRetrievalEvaluator(retriever).evaluate(
        [CodeEvidenceEvalCase(question="anything", expected_ids=[])],
        k=2,
    )

    assert result.total_cases == 1
    assert result.recall_at_k == 0.0
    assert result.mrr == 0.0
    assert result.failures[0]["reason"] == "missing_expected_ids"


def test_eval_case_parser_rejects_invalid_expected_ids_shape() -> None:
    with pytest.raises(ValueError, match="expected_ids"):
        CodeEvidenceEvalCase.from_dict(
            {"question": "sell offer limit", "expected_ids": "expected-a"}
        )


def test_eval_case_parser_rejects_blank_expected_ids() -> None:
    with pytest.raises(ValueError, match="expected_ids"):
        CodeEvidenceEvalCase.from_dict(
            {"question": "sell offer limit", "expected_ids": ["expected-a", "  "]}
        )


def test_eval_case_parser_rejects_blank_protocol() -> None:
    with pytest.raises(ValueError, match="protocol"):
        CodeEvidenceEvalCase.from_dict(
            {
                "question": "sell offer limit",
                "expected_ids": ["expected-a"],
                "protocol": "  ",
            }
        )
