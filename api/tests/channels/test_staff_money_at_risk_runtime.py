"""The rendered Staff label is also persisted for the existing Admin badge."""

import json

import pytest

from tests.channels.test_context_runtime_integration import (
    no_public_delivery,
    run,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as shared_runtime_case,
)

runtime_case = shared_runtime_case
pytestmark = pytest.mark.unit


async def test_generated_monetary_procedure_persists_staff_only_label(runtime_case):
    bundle = runtime_case
    bundle.llm.invoke.return_value.content = json.dumps(
        {
            "action": "reply",
            "reply": "Consolidate the documented UTXOs using Funds > Send funds after checking the prerequisites.",
            "staff_note": "The supplied guide documents the procedure; current wallet state is unknown.",
            "source_ids": ["e1"],
            "reason": "documented_step",
        }
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    assert case.channel_metadata["money_at_risk"] is True
    assert "money at risk" in case.ai_draft_answer
    assert bundle.llm.invoke.call_count == 1
    no_public_delivery(bundle)
