"""Real source publication and provenance boundaries for staff-context notes."""

import json
import threading
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from app.channels.plugins.support_markdown import BISQ2_FAQ_ONION_BASE_URL
from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver
from app.channels.staff_assist.public_context import (
    PublicContextRequest,
    PublicContextService,
    PublicEvidence,
    StaffEvidence,
)
from app.services.bisq_network_status_service import SCOPES
from app.services.faq.slug_manager import SlugManager
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def document(kind="wiki", **metadata):
    return NS(
        page_content="Document body.",
        metadata={"type": kind, "title": "Support", **metadata},
    )


def compiled(**overrides):
    return document(
        "llm_wiki",
        **{
            "id": "reviewed-playbook",
            "status": "reviewed",
            "source_refs": ["wiki:Support"],
            **overrides,
        },
    )


def compiled_resolver(*pages, **kwargs):
    return StaffEvidenceResolver(
        llm_wiki_loader=NS(load_documents=lambda _: list(pages)),
        llm_wiki_dir="unused-test-directory",
        **kwargs,
    )


def publication(row):
    value = {
        "id": row.id,
        "question": row.question,
        "answer": row.answer,
        "slug": SlugManager().generate_slug(row.question, row.id),
    }
    return NS(get_faq_by_id=lambda _: value, get_faq_by_slug=lambda _: value)


def answer(
    source_ids, text="The reviewed guidance describes the documented support workflow."
):
    return NS(
        invoke=Mock(
            return_value=NS(
                content=json.dumps(
                    {
                        "action": "note",
                        "text": text,
                        "source_ids": source_ids,
                        "reason": "Supported staff context.",
                    }
                )
            )
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("through_compiled_reference", [False, True])
async def test_faq_authority_and_publication_reads_do_not_block_event_loop(
    through_compiled_reference,
):
    loop_thread = threading.get_ident()
    reads = []
    row = NS(
        id="42", verified=True, question="Where is support?", answer="Use Support."
    )
    public_row = {
        "id": row.id,
        "question": row.question,
        "answer": row.answer,
        "slug": SlugManager().generate_slug(row.question, row.id),
    }

    def read(name, value):
        def lookup(_):
            assert threading.get_ident() != loop_thread
            reads.append(name)
            return value

        return lookup

    page = compiled(source_refs=["faq:42"])
    resolver = compiled_resolver(
        page,
        faq_service=NS(get_faq_by_id=read("authority", row)),
        public_faq_service=NS(
            get_faq_by_id=read("public_id", public_row),
            get_faq_by_slug=read("public_slug", public_row),
        ),
    )
    result = await resolver.resolve(
        question="Support?",
        documents=[page if through_compiled_reference else document("faq", id="42")],
    )
    assert reads == ["authority", "public_id", "public_slug"]
    assert any(source.kind == "faq" for source in result.evidence)


@pytest.mark.asyncio
async def test_verified_faq_uses_authoritative_public_body_slug_and_canonical_origin():
    row = NS(
        id="42",
        verified=True,
        question="Where is support?",
        answer="Use Support.",
        protocol="all",
    )
    service = NS(get_faq_by_id=Mock(return_value=row))
    retrieved = document(
        "faq", id="42", verified=False, url="https://attacker.example/fake"
    )
    retrieved.page_content = "STALE_INVENTED_BODY"
    result = await StaffEvidenceResolver(
        faq_service=service, public_faq_service=publication(row)
    ).resolve(question="Support?", documents=[retrieved])
    evidence = result.evidence[0]
    assert evidence.kind == "faq"
    assert evidence.content == "Question: Where is support?\nAnswer: Use Support."
    expected = SlugManager().generate_slug(row.question, row.id)
    assert evidence.url == f"{BISQ2_FAQ_ONION_BASE_URL}/faq/{expected}"
    assert evidence.provenance["verified"] is True
    assert "attacker" not in evidence.model_dump_json()
    assert "STALE" not in evidence.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row", [None, NS(id="42", verified=False), NS(id="42", verified=None)]
)
async def test_faq_removed_or_unverified_in_authoritative_store_is_not_evidence(row):
    result = await StaffEvidenceResolver(
        faq_service=NS(get_faq_by_id=lambda _: row)
    ).resolve(
        question="Support?",
        documents=[document("faq", id="42", verified=True)],
    )
    assert not result.evidence


@pytest.mark.asyncio
async def test_mixed_public_and_compiled_evidence_keeps_internal_page_unlinked():
    result = await compiled_resolver(compiled(public=False)).resolve(
        question="Support?",
        documents=[document(), compiled(public=False)],
    )
    assert {e.kind for e in result.evidence} == {"wiki", "llm_wiki"}
    internal = next(e for e in result.evidence if e.kind == "llm_wiki")
    assert internal.url is None
    assert internal.provenance["reference_scope"] == "page_level_not_claim_level"
    request = PublicContextRequest(
        question="Support?", evidence=result.evidence, audience="staff_only"
    )
    llm = answer([internal.id])
    preview = PublicContextService(llm).preview(request)
    assert "Internal LLM wiki: Support (reviewed)" in preview.rendered_note
    assert "https://" not in preview.rendered_note
    assert "wiki:Support" not in preview.rendered_note
    assert "page-level references" in llm.invoke.call_args.kwargs["system_content"]
    with pytest.raises(ValidationError, match="staff-only"):
        PublicContextRequest(question="Support?", evidence=result.evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"private": True},
        {"audience": "private"},
        {"status": "proposed"},
        {"source_refs": []},
        {"source_refs": ["javascript:alert(1)"]},
        {"source_refs": ["https://user:password@example.org/evidence"]},
        {"source_refs": ["https://example.org/%0aevidence"]},
        {"source_refs": ["code:bisq@main:path:1-2"]},
    ],
)
async def test_private_unreviewed_or_invalid_compiled_provenance_never_reaches_prompt(
    metadata,
):
    result = await compiled_resolver(compiled(**metadata)).resolve(
        question="Support?", documents=[compiled(**metadata)]
    )
    assert not result.evidence


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref",
    [
        "https://developer.bitcoin.org/reference/transactions.html",
        "https://bitcoin.org/en/bitcoin-paper",
        "https://support.microsoft.com/windows",
        "https://www.gnupg.org/documentation/",
        "https://www.usps.com/",
        "https://support.torproject.org/",
    ],
)
async def test_reviewed_external_primary_provenance_is_internal_evidence_not_public_link(
    ref,
):
    page = compiled(source_refs=[ref])
    result = await compiled_resolver(page).resolve(
        question="Support?", documents=[page]
    )
    evidence = result.evidence[0]
    assert evidence.source_refs == [ref]
    assert evidence.url is None
    preview = PublicContextService(answer([evidence.id])).preview(
        PublicContextRequest(
            question="Support?",
            evidence=[evidence],
            audience="staff_only",
        )
    )
    assert ref not in preview.rendered_note
    assert "Internal LLM wiki" in preview.rendered_note


@pytest.mark.asyncio
async def test_compiled_faq_ref_resolves_original_body_without_relabeling_compiled_claim():
    row = NS(
        id="42",
        verified=True,
        question="FAQ question",
        answer="Original published body.",
    )
    result = await compiled_resolver(
        compiled(source_refs=["faq:42", "wiki:Support"]),
        faq_service=NS(get_faq_by_id=lambda _: row),
        public_faq_service=publication(row),
    ).resolve(
        question="Support?",
        documents=[compiled(source_refs=["faq:42", "wiki:Support"])],
    )
    internal = next(e for e in result.evidence if e.kind == "llm_wiki")
    public = next(e for e in result.evidence if e.kind == "faq")
    assert internal.content == "Document body."
    assert internal.url is None
    assert "Original published body." in public.content
    assert "Document body." not in public.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["missing_service", "missing_slug", "stale_body", "wrong_id", "missing_route"],
)
async def test_public_faq_requires_actual_current_published_route(failure):
    row = NS(
        id="42", verified=True, question="Published question", answer="Current answer"
    )
    published = publication(row)
    value = published.get_faq_by_id("42")
    if failure == "missing_service":
        published = None
    elif failure == "missing_slug":
        value["slug"] = ""
    elif failure == "stale_body":
        value["answer"] = "Old answer"
    elif failure == "wrong_id":
        value["id"] = "43"
    else:
        published.get_faq_by_slug = lambda _: None
    result = await StaffEvidenceResolver(
        faq_service=NS(get_faq_by_id=lambda _: row),
        public_faq_service=published,
    ).resolve(question="Support?", documents=[document("faq", id="42")])
    assert not result.evidence


@pytest.mark.asyncio
async def test_withdrawn_compiled_page_does_not_survive_in_stale_index():
    result = await compiled_resolver().resolve(
        question="Support?",
        documents=[compiled()],
    )
    assert not result.evidence
    result = await compiled_resolver(compiled(status="deprecated")).resolve(
        question="Support?",
        documents=[compiled()],
    )
    assert not result.evidence


@pytest.mark.asyncio
async def test_current_compiled_body_replaces_stale_indexed_guidance():
    current = compiled()
    current.page_content = "Current reviewed guidance."
    result = await compiled_resolver(current).resolve(
        question="Support?",
        documents=[compiled()],
    )
    assert result.evidence[0].content == "Current reviewed guidance."
    assert "Document body." not in result.evidence[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,freshness", [("unknown", "unknown"), ("observations_available", "stale")]
)
async def test_monitoring_preserves_unknown_stale_and_limited_coverage(
    status, freshness
):
    report = {
        "area": "tor",
        "status": status,
        "freshness": {"status": freshness},
        "checked_at": "2026-09-24T00:00:00Z",
        "coverage": SCOPES["tor"].coverage,
        "limitations": "Does not establish Bisq 2 health or a global outage.",
    }
    monitor = NS(get_status=AsyncMock(return_value=report))
    result = await StaffEvidenceResolver(network_status_service=monitor).resolve(
        question="Is Tor down now?",
        documents=[],
    )
    monitor.get_status.assert_awaited_once_with("tor")
    evidence = result.evidence[0]
    assert evidence.kind == "monitoring"
    assert json.loads(evidence.content) == report
    assert evidence.provenance["freshness"]["status"] == freshness
    assert evidence.url == SCOPES["tor"].dashboard
    monitor.get_status.reset_mock()
    result = await StaffEvidenceResolver(network_status_service=monitor).resolve(
        question="How do Tor bridges work?",
        documents=[],
    )
    assert not result.evidence
    monitor.get_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_wrong_release_code_is_excluded_and_matching_code_retains_scope():
    fact = {
        "id": "fact",
        "audience": "staff_only",
        "claim": "A scoped implementation fact.",
        "source_refs": ["code:bisq2@abcdef123456:module/File.java:10-12"],
        "freshness_class": "release_bound",
        "applies_to_versions": ["2.1.9"],
    }
    brief = {
        "evidence": [fact],
        "uncertainties": ["Version match does not establish cause."],
    }
    grounding = NS(build=Mock(return_value=brief))
    resolver = StaffEvidenceResolver(grounding_service=grounding)
    result = await resolver.resolve(question="Bisq 2 version 2.1.8 fails", documents=[])
    assert not result.evidence
    result = await resolver.resolve(question="Bisq 2 version 2.1.9 fails", documents=[])
    evidence = result.evidence[0]
    assert evidence.kind == "code_fact"
    assert evidence.url is None
    assert json.loads(evidence.content)["source_releases"] == ["2.1.9"]
    assert "Version match does not establish cause" in evidence.content
    preview = PublicContextService(answer([evidence.id])).preview(
        PublicContextRequest(
            question="Support?",
            evidence=[evidence],
            audience="staff_only",
        )
    )
    assert "source release: 2\\.1\\.9" in preview.rendered_note


@pytest.mark.asyncio
async def test_trial_cutoff_is_checked_before_each_live_read():
    monitor = NS(get_status=AsyncMock())
    allowed = AsyncMock(return_value=False)
    result = await StaffEvidenceResolver(
        network_status_service=monitor,
        before_live_read=allowed,
    ).resolve(question="Are Tor and seed nodes down now?", documents=[])
    monitor.get_status.assert_not_awaited()
    assert "live_read_deferred" in result.diagnostics


@pytest.mark.asyncio
async def test_live_offerbook_uses_aggregate_counts_without_counterparty_data():
    service = NS(
        get_offerbook=AsyncMock(
            return_value={
                "success": True,
                "timestamp": "2026-09-24T00:00:00Z",
                "currency_filter": "EUR",
                "total_count": 8,
                "filtered_count": 8,
                "offers": [
                    {
                        "makerProfileId": "PRIVATE_PROFILE",
                        "makerNickName": "PRIVATE_NICK",
                    }
                ],
            }
        )
    )
    result = await StaffEvidenceResolver(bisq_service=service).resolve(
        question="How many EUR offers are available now?",
        documents=[],
    )
    service.get_offerbook.assert_awaited_once_with(currency="EUR")
    assert result.evidence[0].kind == "live_tool"
    assert "PRIVATE" not in result.evidence[0].content
    assert json.loads(result.evidence[0].content)["result"]["total_count"] == 8


def test_staff_evidence_cannot_invent_an_external_url():
    with pytest.raises(ValidationError):
        StaffEvidence(
            id="internal",
            title="Internal",
            kind="llm_wiki",
            content="Guidance",
            url="https://bisq.wiki/Support",
        )


def test_identical_public_links_are_rendered_once():
    evidence = [
        PublicEvidence(
            id=f"e{i}",
            title="Support",
            content=f"Chunk {i}",
            url="https://bisq.wiki/Support",
        )
        for i in (1, 2)
    ]
    request = PublicContextRequest(question="Support?", evidence=evidence)
    preview = PublicContextService(answer(["e1", "e2"])).preview(request)
    assert preview.rendered_note.count("https://bisq.wiki/Support") == 1
