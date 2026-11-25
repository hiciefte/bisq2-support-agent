"""Requester product scope survives the real Staff retrieval and audit path."""

import pytest

from tests.channels.test_context_runtime_integration import (
    context,
    no_public_delivery,
    run,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as shared_runtime_case,
)

pytestmark = pytest.mark.unit
runtime_case = shared_runtime_case


@pytest.mark.parametrize(
    "question,product,version",
    [
        ("In Bisq 1, where can I open mediation?", "bisq1", "Bisq 1"),
        ("In Bisq Easy, where can I open mediation?", "bisq2", "Bisq 2"),
        ("Where can I open mediation?", None, None),
        ("Does mediation differ between Bisq 1 and Bisq 2?", None, None),
        ("I am not using Bisq 1. Which steps apply?", None, None),
        ("Someone mentioned Bisq 1. Which application do I need?", None, None),
    ],
)
async def test_requester_scope_controls_retrieval_and_is_preserved(
    runtime_case, question, product, version
):
    bundle = runtime_case
    bundle.incoming = bundle.incoming.model_copy(update={"question": question})
    bundle.client.room_context.side_effect = lambda *a, **kw: context(body=question)
    case = await run(bundle)
    kwargs = bundle.retrieve.call_args.kwargs
    assert kwargs == {
        "detected_version": version,
        "detect_from_query": False,
        "require_reranker_success": True,
    }
    assert case.channel_metadata["retrieval_requester_product"] == product
    assert "excluded_evidence_snapshot" in case.channel_metadata
    assert "source_applicability" in case.channel_metadata
    assert "conversation_coverage" in case.channel_metadata
    assert case.channel_metadata["public_citation_readiness"] == "public_links_provided"
    no_public_delivery(bundle)
