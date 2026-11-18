"""Staff-only labels identify monetary review context without changing behavior."""

import json

import pytest
from app.channels.staff_assist.staff_context import StaffContextService
from app.channels.staff_assist.staff_prompt import STAFF_CONTEXT_PROMPT

from tests.unit.channels.test_staff_context import model, request

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "question",
    [
        "Is that my deposit coming back?",
        "I cannot tell whether the amount was a refund or a payment.",
        "The payout has not arrived.",
        "Why are there several unspent transaction outputs?",
    ],
)
def test_focal_monetary_context_labels_header_and_admin_preview(question):
    llm = model(
        action="question",
        reply="Which transaction are you referring to?",
        source_ids=[],
    )
    preview = StaffContextService(llm).preview(
        request(question=question, high_risk_action=False)
    )
    assert preview.decision.action == "question"
    assert preview.money_at_risk is True
    assert preview.rendered_note.startswith("AI reply · money at risk")
    payload = json.loads(llm.invoke.call_args.args[0])
    assert payload["high_risk_action"] is False
    assert llm.invoke.call_args.kwargs["system_content"] == STAFF_CONTEXT_PROMPT


@pytest.mark.parametrize(
    "reply",
    [
        "Use the documented procedure to consolidate the available BTC in the same wallet.",
        "Send the available bitcoin to the receiving address shown by your wallet.",
        "Open mediation from the affected trade screen once its prerequisites hold.",
        "Check the prerequisites before restoring the wallet from its backup.",
    ],
)
def test_generated_monetary_procedure_is_labeled_when_input_flag_is_false(reply):
    preview = StaffContextService(model(reply=reply)).preview(
        request(high_risk_action=False)
    )
    assert preview.money_at_risk is True
    assert preview.decision.reply == reply
    assert preview.rendered_note.startswith("AI reply · money at risk")
    assert preview.rejected_draft is None


@pytest.mark.parametrize(
    "reply",
    [
        "Open Settings > Network and inspect the connection status.",
        "Send a screenshot of the About page to the existing support thread.",
        "Consolidate the diagnostic logs into one file for review.",
        "The displayed BTC price refreshes periodically.",
    ],
)
def test_nonmonetary_diagnostics_do_not_gain_a_money_label(reply):
    preview = StaffContextService(model(reply=reply)).preview(request())
    assert preview.rendered_note is not None
    assert preview.money_at_risk is False
    assert "money at risk" not in preview.rendered_note


@pytest.mark.parametrize(
    "role,speaker,expected",
    [
        ("participant", "participant-1", False),
        ("user", "requester", True),
    ],
)
def test_unrelated_participant_money_text_does_not_label_focal_request(
    role, speaker, expected
):
    preview = StaffContextService(model()).preview(
        request(
            recent_messages=[
                {
                    "role": role,
                    "speaker": speaker,
                    "content": "My deposit and refund are missing.",
                }
            ]
        )
    )
    assert preview.money_at_risk is expected


def test_trusted_input_flag_still_forces_label_without_changing_reply():
    preview = StaffContextService(model()).preview(request(high_risk_action=True))
    unflagged = StaffContextService(model()).preview(request(high_risk_action=False))
    assert preview.money_at_risk is True
    assert preview.decision.action == "reply"
    assert preview.decision.reply == unflagged.decision.reply
    assert unflagged.money_at_risk is False
    assert "money at risk" not in unflagged.rendered_note


@pytest.mark.parametrize(
    "reply,staff_note",
    [
        (
            "Send a screenshot of the About page to the support thread.",
            "The displayed BTC price refreshes periodically.",
        ),
        (
            "Send a screenshot, while the BTC price refreshes periodically.",
            "The connection details are unknown.",
        ),
    ],
)
def test_unrelated_clauses_and_fields_do_not_combine_into_money_risk(reply, staff_note):
    preview = StaffContextService(model(reply=reply, staff_note=staff_note)).preview(
        request()
    )
    assert preview.rendered_note is not None
    assert preview.money_at_risk is False


def test_decimal_amount_does_not_split_a_monetary_instruction():
    preview = StaffContextService(
        model(reply="Send 0.01 BTC only after verifying the documented prerequisites.")
    ).preview(request())
    assert preview.money_at_risk is True


def test_rejected_monetary_output_keeps_existing_safeguard_and_admin_label():
    llm = model(reply="The mediator has released your funds.")
    preview = StaffContextService(llm).preview(request())
    assert preview.money_at_risk is True
    assert preview.rendered_note is None
    assert preview.validation_diagnostic == "unsafe_reply"
    assert preview.rejected_draft == llm.invoke.return_value.content


def test_staff_note_monetary_uncertainty_is_visible_to_admin():
    preview = StaffContextService(
        model(
            staff_note="The documented screen is relevant; whether this is a refund remains unknown."
        )
    ).preview(request())
    assert preview.money_at_risk is True
    assert preview.decision.action == "reply"
