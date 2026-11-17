"""Staff output mechanics; mocked outputs are not evidence of answer quality."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.channels.staff_assist.public_context import (
    PUBLIC_CONTEXT_PROMPT,
    PublicContextRequest,
    PublicContextService,
)
from app.channels.staff_assist.staff_context import (
    StaffContextRequest,
    StaffContextService,
    load_staff_examples,
)
from app.channels.staff_assist.staff_prompt import STAFF_CONTEXT_PROMPT
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def request(**kwargs):
    values = {
        "question": "The application cannot connect. What should I do?",
        "evidence": [
            {
                "id": "guide",
                "title": "Guide",
                "url": "https://bisq.wiki/Support",
                "content": "For this synthetic problem, open Settings > Network and reconnect.",
            }
        ],
    }
    values.update(kwargs)
    return StaffContextRequest.model_validate(values)


def model(**kwargs):
    output = {
        "action": "reply",
        "reply": "The connection is unavailable. Open Settings > Network and reconnect.",
        "staff_note": "The guide supports this action; the network cause is unknown.",
        "source_ids": ["guide"],
        "reason": "Supported next step",
    }
    output.update(kwargs)
    return Mock(
        invoke=Mock(
            return_value=SimpleNamespace(
                content=json.dumps(output), usage={"total_tokens": 150}
            )
        )
    )


def test_independent_prompt_is_short_and_output_has_separate_staff_notes():
    llm = model()
    preview = StaffContextService(llm).preview(request())
    assert preview.decision.action == "reply" and preview.requires_review
    assert "Settings \\> Network" in preview.rendered_note
    assert "Staff note:" in preview.rendered_note
    assert len(STAFF_CONTEXT_PROMPT.split()) < 500
    assert (
        "FIRST state" not in STAFF_CONTEXT_PROMPT
        and "at most 55" not in STAFF_CONTEXT_PROMPT
    )
    assert llm.invoke.call_args.kwargs["system_content"] == STAFF_CONTEXT_PROMPT
    assert "Examples\nillustrate style only" in STAFF_CONTEXT_PROMPT


@pytest.mark.parametrize(
    "reply",
    [
        "For Bisq 1, open mediation from the trade screen after the trade period expires.",
        "If the balance is sufficient, consolidate the documented UTXOs using Funds > Send funds.",
        "After checking the prerequisites, run an SPV resync from the documented menu.",
        "Check " + "this diagnostic detail " * 35 + "in Settings > Network [status].",
    ],
)
def test_steps_menu_paths_symbols_and_over_55_words_are_not_discarded(reply):
    preview = StaffContextService(model(reply=reply)).preview(request())
    assert preview.decision.reply == reply
    assert preview.rendered_note is not None and preview.rejected_draft is None


@pytest.mark.parametrize(
    "question",
    [
        "Which application are you using?",
        "Did you restore from a backup?",
        "What error appeared after restarting?",
        "Welche Version wird angezeigt?",
        "你使用哪个版本？",
    ],
)
def test_useful_question_can_be_generated_without_evidence(question):
    llm = model(action="question", reply=question, source_ids=[])
    preview = StaffContextService(llm).preview(request(evidence=[]))
    llm.invoke.assert_called_once()
    assert preview.decision.action == "question" and preview.decision.reply == question
    assert preview.rendered_note and preview.knowledge_gap is None


@pytest.mark.parametrize(
    "action,reply,source_ids",
    [
        ("question", "Which version? What error?", []),
        ("question", "The relay is broken. Which version?", []),
        ("reply", "Which version? What error?", ["guide"]),
        ("reply", "Which version?", ["guide"]),
    ],
)
def test_one_question_contract_cannot_be_bypassed_by_a_source(
    action, reply, source_ids
):
    llm = model(action=action, reply=reply, source_ids=source_ids)
    preview = StaffContextService(llm).preview(request())
    assert preview.rendered_note is None
    assert preview.rejected_draft == llm.invoke.return_value.content
    assert preview.validation_diagnostic == "invalid_question"


@pytest.mark.parametrize(
    "reply",
    [
        "Send your seed words here.",
        "Never hesitate, send your seed words here.",
        "Do not worry, provide the private keys.",
        "What is your recovery phrase?",
        "The mediator has released your funds.",
        "We have already processed your refund.",
        "This is guaranteed to fix the connection.",
    ],
)
def test_protected_invariants_reject_and_retain_exact_text(reply):
    llm = model(reply=reply)
    preview = StaffContextService(llm).preview(request())
    assert preview.rendered_note is None
    assert preview.validation_diagnostic == "unsafe_reply"
    assert preview.rejected_draft == llm.invoke.return_value.content


def test_protective_secret_warning_is_allowed_and_scam_warning_is_preserved():
    preview = StaffContextService(
        model(reply="Never share seed words or private keys.")
    ).preview(request(question="Someone sent me a private message offering support."))
    assert preview.decision.reply.startswith(SAFETY_REFLEX_WARNING)
    assert preview.rendered_note and preview.requires_review


def test_risk_words_do_not_hold_staff_drafts_and_are_labeled():
    llm = model()
    preview = StaffContextService(llm).preview(
        request(
            question="I did not receive my payment; how do I open a dispute?",
            high_risk_action=True,
        )
    )
    llm.invoke.assert_called_once()
    assert preview.money_at_risk is True and "money at risk" in preview.rendered_note


@pytest.mark.parametrize(
    "reason", ["not_request", "already_answered", "knowledge_gap: payout signing error"]
)
def test_valid_silence_and_knowledge_gap_never_produce_a_post(reason):
    preview = StaffContextService(
        model(action="silence", reply="", staff_note="", source_ids=[], reason=reason)
    ).preview(request(evidence=[]))
    assert preview.rendered_note is None and preview.rejected_draft is None
    assert preview.knowledge_gap == (
        "payout signing error" if reason.startswith("knowledge_gap:") else None
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"action":"reply"}',
        json.dumps(
            {
                "action": "reply",
                "reply": "x" * 11000,
                "staff_note": "Source supports it",
                "reason": "test",
                "source_ids": ["guide"],
            }
        ),
    ],
)
def test_invalid_and_oversized_output_is_retained_in_full(raw):
    llm = Mock(invoke=Mock(return_value=SimpleNamespace(content=raw, usage=None)))
    preview = StaffContextService(llm).preview(request())
    assert preview.rendered_note is None and preview.rejected_draft == raw


def test_input_limits_are_staff_only_and_attribution_is_retained():
    messages = [{"role": "user", "speaker": "requester", "content": "A detail"}] * 100
    value = request(question="x" * 12000, recent_messages=messages)
    llm = model()
    StaffContextService(llm).preview(value)
    sent = json.loads(llm.invoke.call_args.args[0])
    assert len(sent["recent_messages"]) == 100 and len(sent["question"]) == 12000
    with pytest.raises(ValidationError):
        PublicContextRequest(question="x" * 12000)
    with pytest.raises(ValidationError):
        PublicContextRequest(question="x", recent_messages=messages)


def test_private_examples_load_with_hash_and_invalid_private_file_falls_back(tmp_path):
    examples = [{"reply": "Which version is shown?"}] * 15
    path = tmp_path / "staff-context-examples.json"
    path.write_text(json.dumps(examples))
    llm = model()
    service = StaffContextService(llm, data_dir=tmp_path)
    preview = service.preview(request())
    assert preview.examples_source == "private_file"
    assert (
        preview.examples_sha256
        == hashlib.sha256(
            json.dumps(examples, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
    )
    assert json.loads(llm.invoke.call_args.args[0])["style_examples"] == examples
    path.write_text('[{"reply":"Ask @person:example.org"}]')
    loaded, source = load_staff_examples(tmp_path)
    assert source == "synthetic_fallback_invalid_file" and loaded != examples


def test_public_audience_remains_on_original_prompt_and_old_contract():
    llm = Mock(
        invoke=Mock(
            return_value=SimpleNamespace(
                content=json.dumps(
                    {
                        "action": "note",
                        "text": "A supported fact.",
                        "source_ids": ["guide"],
                        "reason": "Useful fact",
                    }
                ),
                usage=None,
            )
        )
    )
    public = PublicContextRequest.model_validate(
        {
            **request().model_dump(exclude={"conversation_coverage"}),
            "audience": "public",
        }
    )
    result = PublicContextService(llm).preview(public)
    assert result.rendered_note.startswith("AI context · ")
    assert llm.invoke.call_args.kwargs["system_content"] == PUBLIC_CONTEXT_PROMPT


@pytest.mark.parametrize(
    "staff_note",
    [
        "Ask the requester to send their private keys.",
        "Never worry, ask them to share seed words.",
    ],
)
def test_staff_note_cannot_carry_an_unsafe_instruction(staff_note):
    llm = model(staff_note=staff_note)
    preview = StaffContextService(llm).preview(request())
    assert (
        preview.rendered_note is None
        and preview.rejected_draft == llm.invoke.return_value.content
    )


def test_evidence_may_motivate_one_question_without_turning_it_into_a_fact():
    llm = model(
        action="question", reply="Has the trade period expired?", source_ids=["guide"]
    )
    preview = StaffContextService(llm).preview(request())
    assert preview.decision.action == "question" and preview.rendered_note
