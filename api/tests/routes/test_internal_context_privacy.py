"""Internal review answers never appear on customer polling or rating APIs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.core.config import get_settings
from app.models.escalation import EscalationInvalidStateError
from app.routes.admin.escalations import generate_faq, get_escalation_service
from app.routes.escalation_polling import router
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "metadata",
    [{"response_kind": "public_context"}, {"delivery_audience": "staff_room"}],
)
@pytest.mark.parametrize("path", ["/response", "/events", "/rate"])
def test_internal_case_not_publicly_available(metadata, path):
    app = FastAPI()
    app.include_router(router)
    case = SimpleNamespace(channel_metadata=metadata, staff_answer="Internal review")
    service = SimpleNamespace(
        repository=SimpleNamespace(get_by_message_id=AsyncMock(return_value=case))
    )
    app.dependency_overrides[get_escalation_service] = lambda: service
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace()
    client = TestClient(app)
    url = "/escalations/12345678-1234-1234-1234-123456789abc" + path
    response = (
        client.post(url, json={"rating": 1}) if path == "/rate" else client.get(url)
    )
    assert response.status_code == 404
    assert "Internal review" not in response.text
    service.repository.get_by_message_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_internal_faq_refusal_is_conflict():
    from app.models.escalation import GenerateFAQRequest

    service = SimpleNamespace(
        generate_faq_from_escalation=AsyncMock(
            side_effect=EscalationInvalidStateError(
                "Internal context review cannot create FAQs"
            )
        )
    )
    with pytest.raises(HTTPException) as exc:
        await generate_faq(
            1,
            GenerateFAQRequest(
                question="Question", answer="Answer", category="General"
            ),
            service,
        )
    assert exc.value.status_code == 409
