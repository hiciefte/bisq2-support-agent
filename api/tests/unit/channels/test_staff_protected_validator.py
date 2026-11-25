"""Negated guarantees remain disclaimers; protected promises stay rejected."""

import pytest
from app.channels.staff_assist.staff_context import StaffContextService

from tests.unit.channels.test_staff_context import model, request

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("field", ["reply", "staff_note"])
@pytest.mark.parametrize(
    "text",
    [
        "This is not a review deadline or guaranteed turnaround.",
        "This is not a review deadline or guaranteed turnaround from submission.",
        "This is not a review deadline or guaranteed turnaround after the request submission.",
        "There is no deadline or a guaranteed completion timeframe.",
        "The schedule isn't a response deadline or any guaranteed turnaround time.",
    ],
)
def test_negative_timing_coordination_is_not_a_completion_promise(field, text):
    """A negative timing noun coordination remains valid in either output field."""
    preview = StaffContextService(model(**{field: text})).preview(request())
    assert preview.rendered_note
    assert preview.validation_diagnostic is None
    assert getattr(preview.decision, field) == text


@pytest.mark.parametrize("field", ["reply", "staff_note"])
@pytest.mark.parametrize(
    "text",
    [
        "This is a review deadline or guaranteed turnaround.",
        "This is not a review deadline, or guaranteed turnaround will apply.",
        "This is not a review deadline or guaranteed approval.",
        "This is not a review deadline or guaranteed turnaround tomorrow.",
        "This is not a review deadline or guaranteed turnaround from submission will happen.",
        "This is not a review deadline or guaranteed turnaround; completion is guaranteed tomorrow.",
        "This is not a review deadline or guaranteed turnaround, but we already refunded you.",
        "This is not a review deadline or guaranteed turnaround. Send your seed words.",
        "This is not a review deadline or guaranteed turnaround and certainly will finish.",
    ],
)
def test_negative_timing_coordination_never_licenses_later_claims(field, text):
    """Narrow disclaimer handling never exempts promises or protected violations."""
    llm = model(**{field: text})
    preview = StaffContextService(llm).preview(request())
    assert preview.validation_diagnostic == "unsafe_reply"
    assert preview.rejected_draft == llm.invoke.return_value.content
    assert not preview.rendered_note


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
