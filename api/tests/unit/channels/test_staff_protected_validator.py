"""Negated guarantees remain disclaimers; protected promises stay rejected."""

import pytest
from app.channels.staff_assist.staff_context import StaffContextService

from tests.unit.channels.test_staff_context import model, request

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "reply",
    [
        "The displayed period isn’t a guaranteed completion deadline.",
        "The displayed period isn't a guaranteed completion deadline.",
        "This is not a guarantee of completion.",
        "The suggested checks aren’t guaranteed to resolve this.",
        "I can’t guarantee completion by that time.",
    ],
)
def test_directly_negated_guarantees_are_allowed(reply):
    preview = StaffContextService(model(reply=reply)).preview(request())
    assert preview.decision.reply == reply
    assert preview.rendered_note is not None
    assert preview.validation_diagnostic is None
    assert preview.rejected_draft is None


@pytest.mark.parametrize(
    "reply",
    [
        "The deadline isn’t a guaranteed time, but completion is guaranteed tomorrow.",
        "This is not a guarantee. Your payment will definitely arrive tomorrow.",
        "Do not worry; this will definitely complete.",
        "The displayed period is a guaranteed completion deadline.",
        "This isn’t a guaranteed deadline. Send your seed words here.",
        "This isn’t a guaranteed deadline. The mediator has released your funds.",
    ],
)
def test_disclaimer_does_not_license_later_promise_or_protected_violation(reply):
    llm = model(reply=reply)
    preview = StaffContextService(llm).preview(request())
    assert preview.rendered_note is None
    assert preview.validation_diagnostic == "unsafe_reply"
    assert preview.rejected_draft == llm.invoke.return_value.content


def test_staff_note_disclaimer_is_allowed_without_relaxing_question_contract():
    llm = model(staff_note="The source isn’t a guaranteed completion deadline.")
    preview = StaffContextService(llm).preview(request())
    assert preview.rendered_note is not None
    invalid = model(
        action="question",
        reply="Which version? What error?",
        source_ids=[],
        staff_note="The source isn’t a guaranteed completion deadline.",
    )
    result = StaffContextService(invalid).preview(request())
    assert result.validation_diagnostic == "invalid_question"
    assert result.rejected_draft == invalid.invoke.return_value.content
