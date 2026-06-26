from app.channels.staff_assist.grounding import GroundingBriefService
from app.services.rag.interfaces import RetrievedDocument


class FakeRetriever:
    def __init__(self, docs: list[RetrievedDocument]):
        self.docs = docs
        self.calls = []

    def retrieve(self, query: str, *, protocol=None, k: int = 3):
        self.calls.append({"query": query, "protocol": protocol, "k": k})
        return self.docs[:k]


def _code_doc(**metadata) -> RetrievedDocument:
    md = {
        "type": "code_fact",
        "audience": "staff_only",
        "repo": "bisq2",
        "commit": "abc123",
        "path": "bisq-easy/src/main/java/Foo.java",
        "line_start": 10,
        "line_end": 12,
        "protocol": "bisq_easy",
        "risk_level": "medium",
        "freshness_class": "main_branch",
        "claim": "Sell offer creation depends on reputation score.",
        "support_use": "Use only as staff investigation evidence.",
        "source_refs": ["code:bisq2@abc123:bisq-easy/src/main/java/Foo.java:10-12"],
    }
    md.update(metadata)
    return RetrievedDocument(
        id=str(md.get("id", "code-fact")),
        content="Claim: Sell offer creation depends on reputation score.",
        metadata=md,
        score=0.91,
    )


def test_grounding_brief_includes_staff_only_evidence() -> None:
    retriever = FakeRetriever([_code_doc()])
    service = GroundingBriefService(code_retriever=retriever)

    brief = service.build(
        question="Why can I not create a Bisq Easy sell offer?",
        knowledge_sources=[],
        draft_answer="Ask the user for the exact error text.",
    )

    assert brief is not None
    assert brief["summary"] == "Staff-only grounding for this support request."
    assert brief["likely_protocol"] == "bisq_easy"
    assert brief["evidence"][0]["kind"] == "code_fact"
    assert brief["evidence"][0]["audience"] == "staff_only"
    assert (
        brief["evidence"][0]["claim"]
        == "Sell offer creation depends on reputation score."
    )
    assert brief["safe_customer_guidance"]
    assert brief["do_not_say"]
    assert "Ask the user for the exact error text." in brief["staff_enriched_answer"]
    assert "Staff-only codebase context" in brief["staff_enriched_answer"]
    assert (
        "Sell offer creation depends on reputation score."
        in brief["staff_enriched_answer"]
    )


def test_grounding_brief_omits_non_staff_evidence() -> None:
    retriever = FakeRetriever([_code_doc(audience="public_reviewed")])
    service = GroundingBriefService(code_retriever=retriever)

    brief = service.build(question="sell offer reputation", knowledge_sources=[])

    assert brief is None


def test_grounding_brief_passes_protocol_from_sources() -> None:
    retriever = FakeRetriever([_code_doc(protocol="multisig_v1")])
    service = GroundingBriefService(code_retriever=retriever)

    service.build(
        question="Why is my deposit stuck?",
        knowledge_sources=[{"protocol": "multisig_v1"}],
    )

    assert retriever.calls == [
        {"query": "Why is my deposit stuck?", "protocol": "multisig_v1", "k": 3}
    ]
