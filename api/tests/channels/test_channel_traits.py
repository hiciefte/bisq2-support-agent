from types import SimpleNamespace

from app.channels.models import ChannelType, IncomingMessage, UserContext
from app.channels.response_enricher import ChannelRAGResponseEnricher
from app.channels.traits import (
    channel_is_group_room,
    channel_supports_staff_grounding,
    supported_chatops_channel_ids,
)


def test_builtin_channel_traits_expose_group_staff_capabilities():
    assert channel_is_group_room("matrix") is True
    assert channel_is_group_room("bisq2") is True
    assert channel_is_group_room("web") is False
    assert channel_supports_staff_grounding("matrix") is True
    assert channel_supports_staff_grounding("bisq2") is True
    assert channel_supports_staff_grounding("web") is False
    assert set(supported_chatops_channel_ids()) == {"matrix", "bisq2"}


def test_response_enricher_uses_staff_grounding_trait():
    grounding_service = SimpleNamespace(
        build=lambda **_kwargs: {"staff_enriched_answer": "Staff-only brief"}
    )
    runtime = SimpleNamespace(
        resolve_optional=lambda name: (
            grounding_service if name == "staff_grounding_brief_service" else None
        )
    )
    incoming = IncomingMessage(
        message_id="$evt-grounding",
        channel=ChannelType.MATRIX,
        question="How do I inspect this error?",
        user=UserContext(user_id="@user:server"),
    )
    enricher = ChannelRAGResponseEnricher(runtime)

    response = enricher(
        incoming,
        {
            "answer": "Draft answer",
            "sources": [],
            "routing_action": "auto_send",
        },
    )

    assert response["staff_enriched_answer"] == "Staff-only brief"
    assert response["requires_human"] is True
    assert response["routing_action"] == "queue_medium"
