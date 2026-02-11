import pytest


@pytest.mark.unit
def test_generate_faq_request_accepts_arbitrary_category():
    from app.models.escalation import GenerateFAQRequest

    req = GenerateFAQRequest(
        question="Q?",
        answer="A.",
        category="Trading",
        protocol="all",
    )
    assert req.category == "Trading"


@pytest.mark.unit
def test_generate_faq_request_empty_category_defaults_general():
    from app.models.escalation import GenerateFAQRequest

    req = GenerateFAQRequest(
        question="Q?",
        answer="A.",
        category="   ",
    )
    assert req.category == "General"
