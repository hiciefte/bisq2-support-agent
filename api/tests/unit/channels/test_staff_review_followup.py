"""Offline integration regressions for verified review findings on 7b68."""

import json
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.evidence_applicability import (
    source_applicability,
    staff_requester_product,
    staff_requester_version,
)
from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver
from app.channels.staff_assist.grounding import GroundingBriefService
from app.channels.staff_assist.public_context import PublicEvidence
from app.channels.staff_assist.staff_context import (
    StaffContextRequest,
    StaffContextService,
)

pytestmark = pytest.mark.unit


def preview(reply, question="My client does not start.", staff_note="Needs a detail."):
    llm = NS(
        invoke=Mock(
            return_value=NS(
                content=json.dumps(
                    dict(
                        action="question",
                        reply=reply,
                        staff_note=staff_note,
                        source_ids=[],
                        reason="Clarify",
                    )
                )
            )
        )
    )
    return StaffContextService(llm).preview(StaffContextRequest(question=question))


@pytest.mark.parametrize(
    "reply",
    [
        "Could you provide your wallet password?",
        "What is your account password?",
        "Can the wallet be reset?",
        "Could my wallet be restored?",
        "How can my wallet safely be restored?",
        "How could my wallet be safely restored?",
        "Could you send your passphrase?",
    ],
)
def test_sensitive_or_passive_operation_is_not_diagnostic(reply):
    result = preview(reply)
    assert not result.rendered_note
    assert result.rejected_draft


@pytest.mark.parametrize(
    "reply",
    [
        "Did you restore from a backup?",
        "Was your wallet restored before the error?",
        "What exact error text appears?",
        "Is a wallet password configured?",
    ],
)
def test_nonsensitive_history_and_state_remain_diagnostic(reply):
    assert preview(reply).rendered_note


def test_failed_asset_receipt_retains_risk_without_unrelated_clause_coupling():
    assert preview(
        "What does the screen show?", "I sent it, but the BTC never arrived."
    ).money_at_risk
    assert not preview(
        "What does the screen show?", "I read about BTC, but my icon changed."
    ).money_at_risk


@pytest.mark.parametrize(
    "report", ["My BTC hasn’t been received yet.", "My BTC hasn't arrived."]
)
def test_passive_missing_asset_receipt_gets_staff_risk_label(report):
    """Missing receipts get the display label; an asset name alone does not."""
    assert preview("What does the screen show?", report).money_at_risk
    assert not preview(
        "What does the screen show?", "My BTC amount is shown."
    ).money_at_risk


def test_verification_instruction_is_not_completed_staff_action_claim():
    assert preview(
        "What error appears?", staff_note="Check whether Staff contacted the mediator."
    ).rendered_note
    assert not preview(
        "What error appears?", staff_note="Staff contacted the mediator."
    ).rendered_note


def test_exempt_verification_does_not_hide_later_completed_action():
    """An exempt verification phrase does not excuse a separate action claim."""
    result = preview(
        "What error appears?",
        staff_note="Check whether the mediator acted, because we already refunded you.",
    )
    assert result.validation_diagnostic == "unsafe_reply"
    assert result.rejected_draft
    assert not result.rendered_note


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My friend uses Bisq 2. My wallet is stuck.", None),
        ("A helper uses Bisq 2.", None),
        ("I don't see an error, but I'm using Bisq 2.", "bisq2"),
        ("I don't use Bisq 2.", None),
        ("Someone told me, Bisq 2 might be involved.", None),
        ("I use Bisq 1.", "bisq1"),
    ],
)
def test_requester_scope_requires_own_affirmative_clause(text, expected):
    assert staff_requester_product(text) == expected


def test_title_and_leading_body_scope_conflict_even_without_protocol():
    source = PublicEvidence(
        id="e1",
        title="Bisq 1 wallet recovery",
        content="Bisq 2: use the following recovery procedure.",
        url="https://bisq.wiki/Recovery",
    )
    assert (
        "source_explicit_scope_conflict"
        in source_applicability(source, product="bisq1")["blocked_reasons"]
    )
    incidental = source.model_copy(
        update={"content": "Bisq 2 has a different procedure."}
    )
    assert source_applicability(incidental, product="bisq1")["eligible_for_reply"]


@pytest.mark.parametrize("product", [None, "bisq2"])
async def test_conflicting_duplicate_is_excluded_before_grounding_and_selection(
    product,
):
    grounding = NS(build=Mock(return_value=None))
    docs = [
        NS(
            page_content="Same shared body.",
            metadata=dict(
                type="wiki", title="Guide", url="https://bisq.wiki/Guide", protocol=p
            ),
        )
        for p in ["multisig_v1", "all", "bisq_easy"]
    ]
    result = await StaffEvidenceResolver(grounding_service=grounding).resolve(
        question="Which step applies?", documents=docs, product=product
    )
    assert not result.evidence
    assert result.excluded_evidence
    assert {source.provenance["protocol"] for source in result.excluded_evidence} == {
        "multisig_v1",
        "all",
        "bisq_easy",
    }
    assert len(result.excluded_evidence) == 3
    assert all(
        not source.provenance["staff_applicability"]["eligible_for_reply"]
        for source in result.excluded_evidence
    )
    assert grounding.build.call_args.kwargs["knowledge_sources"] == []


async def test_consistent_duplicate_remains_usable():
    doc = NS(
        page_content="Same body.",
        metadata=dict(
            type="wiki",
            title="Bisq 2 guide",
            url="https://bisq.wiki/Guide",
            protocol="bisq_easy",
        ),
    )
    result = await StaffEvidenceResolver().resolve(
        question="I use Bisq 2.", documents=[doc, doc]
    )
    assert len(result.evidence) == 1
    assert not result.excluded_evidence


@pytest.mark.parametrize(
    "question,version",
    [
        (
            "I use Bisq 2. A helper is running version 2.3.4. Why is my offer stuck?",
            None,
        ),
        ("I am using Bisq 2 version 2.3.4.", "2.3.4"),
        ("I'm currently running version 2.3.4.", "2.3.4"),
        ("I installed Bisq 2 version 2.3.4.", "2.3.4"),
        ("My current Bisq 2 version 2.3.4 is stuck.", "2.3.4"),
        ("Bisq 2 version 2.3.4 fails to start.", "2.3.4"),
        ("I upgraded to version 2.3.4.", "2.3.4"),
        ("I use Bisq 2. I updated to 2.3.4.", "2.3.4"),
        ("I use Bisq 2. I updated to version 2.3.4.", "2.3.4"),
        ("I upgraded to v2.3.4.", "2.3.4"),
        ("I updated to 02.3.4.", None),
        ("I updated to 2.3.4.1.", None),
        ("I updated to 2.3.4+build.", None),
        ("I updated to 2.3.4 or 2.4.0.", None),
        ("I plan to upgrade to version 2.3.4.", None),
        ("I want to switch to Bisq 2 version 2.3.4.", None),
        ("I don't use version 2.3.4.", None),
        ("I’m not using version 2.3.4.", None),
        ("Should I upgrade to version 2.3.4?", None),
        ("Am I running version 2.3.4?", None),
        ("I previously ran version 2.3.4.", None),
        ("I upgraded from version 2.3.4.", None),
        ("I have a question about version 2.3.4.", None),
    ],
)
async def test_attributed_version_survives_real_grounding_without_reinference(
    question, version
):
    retriever = NS(retrieve=Mock(return_value=[]))
    grounding = GroundingBriefService(code_retriever=retriever)
    assert staff_requester_version(question) == version
    await StaffEvidenceResolver(grounding_service=grounding).resolve(
        question=question, documents=[], product="bisq2"
    )
    assert retriever.retrieve.call_args.kwargs.get("user_version") == version


def test_legacy_grounding_version_inference_unchanged():
    retriever = NS(retrieve=Mock(return_value=[]))
    GroundingBriefService(code_retriever=retriever).build(
        question="Bisq 2 version 2.3.4", knowledge_sources=[]
    )
    assert retriever.retrieve.call_args.kwargs["user_version"] == "2.3.4"
