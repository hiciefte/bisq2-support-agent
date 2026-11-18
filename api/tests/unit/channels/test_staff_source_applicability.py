"""Offline source/coverage contracts, not claims about future model wording."""

import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.evidence_applicability import (
    annotate_source,
    source_applicability,
    staff_requester_product,
)
from app.channels.staff_assist.public_context import PublicEvidence, StaffEvidence
from app.channels.staff_assist.staff_context import (
    StaffContextRequest,
    StaffContextService,
    StaffConversationCoverage,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I am not using Bisq 1. Which steps apply?", None),
        ("Bisq 1 is not what I am using.", None),
        ("Bisq 1 isn't the product I use.", None),
        ("I don't use Bisq 2.", None),
        ("If I used Bisq 1, would that work?", None),
        ("Could Bisq 1 solve this?", None),
        ("Someone suggested Bisq 1.", None),
        ("Someone told me, Bisq 1 might be involved. Which app am I using?", None),
        ("Should I switch to Bisq 1?", None),
        ("I am thinking about switching to Bisq 2.", None),
        ("In Bisq 1, where can I open mediation?", "bisq1"),
        ('They wrote "I am using Bisq 1".', None),
        ("What differs between Bisq 1 and Bisq Easy?", None),
        ("Bisq 1 rather than Bisq 2?", None),
        ("I use Bisq 1. It does not start.", "bisq1"),
        ("My Bisq 2 does not connect.", "bisq2"),
        ("Bisq 1 is not starting.", "bisq1"),
        ("I don't use Bisq 1; I use Bisq Easy.", "bisq2"),
    ],
)
def test_requester_scope_does_not_promote_negated_or_other_product_mentions(
    text, expected
):
    assert staff_requester_product(text) == expected


def source(**updates):
    values = {
        "id": "reference",
        "title": "Troubleshooting",
        "content": "Bisq 1: reconnect after verifying this is a local connection issue.",
        "url": "https://bisq.wiki/Troubleshooting",
        "provenance": {"protocol": "multisig_v1"},
    }
    values.update(updates)
    return PublicEvidence(**values)


def model(**updates):
    values = {
        "action": "reply",
        "reply": "Reconnect after verifying the documented condition.",
        "staff_note": "The supplied source documents this conditional step.",
        "source_ids": ["reference"],
        "reason": "Supported next step",
    }
    values.update(updates)
    return Mock(invoke=Mock(return_value=NS(content=json.dumps(values))))


def test_explicit_metadata_conflict_preserves_original_body_and_label():
    original = source(provenance={"protocol": "bisq_easy"})
    before = original.model_dump()
    annotated = annotate_source(original)
    assert original.model_dump() == before
    assert annotated.content == original.content
    assert annotated.provenance["protocol"] == "bisq_easy"
    assert annotated.provenance["staff_applicability"]["blocked_reasons"] == [
        "source_product_metadata_conflict"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "The DAO state does not agree with peers.",
        "Trade protocol and market price need checking.",
        "VerifyPeersAccountAgeWitness appears in the supplied error.",
    ],
)
def test_feature_keywords_do_not_replace_product_detection_or_rewrite_labels(text):
    result = source_applicability(
        source(content=text, provenance={"protocol": "bisq_easy"})
    )
    assert result["explicitly_named_products"] == []
    assert result["declared_protocol"] == "bisq_easy"
    assert result["product_scope"] == "declared_not_verified"
    assert result["requester_explicit_product"] is None


def test_comparison_page_is_not_mistaken_for_an_explicit_conflict():
    result = source_applicability(
        source(content="Compare Bisq 1 with Bisq Easy before choosing a workflow.")
    )
    assert result["eligible_for_reply"]
    assert result["explicitly_named_products"] == ["bisq1", "bisq2"]


def test_primary_source_scope_survives_incidental_other_product_body():
    evidence = source(
        title="Bisq 1 wallet recovery",
        content="Bisq 2 uses a different procedure.",
        provenance={"protocol": "all"},
    )
    result = source_applicability(evidence, product="bisq2")
    assert result["explicit_text_scope"] == "bisq1"
    assert result["blocked_reasons"] == ["explicit_product_mismatch"]
    comparison = evidence.model_copy(update={"title": "Bisq 1 versus Bisq 2 recovery"})
    assert source_applicability(comparison, product="bisq2")["eligible_for_reply"]


def test_incidental_or_excluded_product_mention_does_not_define_source_scope():
    result = source_applicability(
        source(
            content="This procedure does not apply to Bisq 1.",
            provenance={"protocol": "bisq_easy"},
        )
    )
    assert result["eligible_for_reply"]
    assert result["explicit_text_scope"] is None


def test_explicit_conflict_cannot_reenter_generation_or_reply_by_id():
    evidence = source(provenance={"protocol": "bisq_easy"})
    llm = model()
    request = StaffContextRequest(question="Which step applies?", evidence=[evidence])
    preview = StaffContextService(llm).preview(request)
    payload = json.loads(llm.invoke.call_args.args[0])
    assert payload["evidence"] == []
    assert "Bisq 1: reconnect" not in llm.invoke.call_args.args[0]
    assert request.evidence[0].content == evidence.content
    assert preview.validation_diagnostic == "inapplicable_source"
    assert preview.rejected_draft == llm.invoke.return_value.content
    assert not preview.rendered_note
    assert not preview.source_applicability["reference"]["eligible_for_reply"]


def test_conflicting_sources_still_allow_a_useful_missing_fact_question():
    llm = model(action="question", reply="Which product are you using?", source_ids=[])
    preview = StaffContextService(llm).preview(
        StaffContextRequest(
            question="The connection is unavailable.",
            evidence=[source(provenance={"protocol": "bisq_easy"})],
        )
    )
    assert preview.rendered_note
    assert preview.decision.action == "question"


def test_explicit_requester_product_mismatch_is_excluded_without_topic_guessing():
    llm = model()
    preview = StaffContextService(llm).preview(
        StaffContextRequest(question="I'm using Bisq 2.", evidence=[source()])
    )
    assert preview.validation_diagnostic == "inapplicable_source"
    assert preview.source_applicability["reference"]["blocked_reasons"] == [
        "explicit_product_mismatch"
    ]


def test_negated_requester_product_does_not_quarantine_other_product_evidence():
    llm = model()
    evidence = source(
        content="Bisq 2: check the connection.", provenance={"protocol": "bisq_easy"}
    )
    preview = StaffContextService(llm).preview(
        StaffContextRequest(
            question="I am not using Bisq 1. Which steps apply?", evidence=[evidence]
        )
    )
    assert preview.rendered_note
    assert (
        preview.source_applicability["reference"]["requester_explicit_product"] is None
    )


def test_unknown_source_scope_does_not_become_verified_through_retrieval():
    info = source_applicability(
        source(content="Check the account state.", provenance={})
    )
    assert info["product_scope"] == "unknown"
    assert info["user_state_preconditions"] == "not_established_by_retrieval"
    assert info["public_citation"] == "vetted_url_not_live_checked"


def test_missing_parent_attachment_and_peer_facts_survive_model_payload():
    llm = model(
        action="question", reply="Which transfer has not arrived?", source_ids=[]
    )
    coverage = StaffConversationCoverage(
        status="bounded_observed",
        missing_parent_event_ids=["parent-unobserved"],
        omitted_event_ids=["older-turn"],
        attachment_event_ids=["image-event"],
        unselected_event_count=2,
    )
    preview = StaffContextService(llm).preview(
        StaffContextRequest(
            question="The transfer hasn't arrived; see the image.",
            conversation_coverage=coverage,
            recent_messages=[
                {
                    "role": "user",
                    "speaker": "requester",
                    "content": "Transfer missing.",
                },
                {
                    "role": "participant",
                    "speaker": "participant-1",
                    "content": "My wallet is offline too.",
                },
            ],
            evidence=[source()],
        )
    )
    payload = json.loads(llm.invoke.call_args.args[0])
    assert preview.rendered_note
    assert payload["conversation_coverage"] == coverage.model_dump()
    assert payload["recent_messages"][1]["role"] == "participant"
    assert payload["question"] == "The transfer hasn't arrived; see the image."
    assert "My wallet is offline too." not in payload["question"]


@pytest.mark.parametrize("include_public", [False, True])
def test_internal_sources_have_honest_citation_readiness(include_public):
    internal = StaffEvidence(
        id="saved",
        title="Saved excerpt",
        content="Check the account state.",
        kind="saved_excerpt",
    )
    evidence = [internal] + ([source()] if include_public else [])
    preview = StaffContextService(
        model(source_ids=[entry.id for entry in evidence])
    ).preview(StaffContextRequest(question="Which step applies?", evidence=evidence))
    assert preview.public_citation_readiness == (
        "partial_public_links" if include_public else "internal_evidence_only"
    )
    assert "no public citation" in preview.rendered_note
    assert "saved_excerpt" not in preview.rendered_note


def test_public_link_readiness_does_not_claim_live_verification():
    preview = StaffContextService(model()).preview(
        StaffContextRequest(question="Which step applies?", evidence=[source()])
    )
    assert preview.public_citation_readiness == "public_links_provided"
    assert (
        preview.source_applicability["reference"]["public_citation"]
        == "vetted_url_not_live_checked"
    )
