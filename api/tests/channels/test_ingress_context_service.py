from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelType,
    ChatMessage,
    ClassificationDecision,
    IncomingMessage,
    LocaleContext,
    UserContext,
)
from app.services.translation.language_detector import LanguageDetectionDetails


class StubLanguageDetector:
    def __init__(self, responses):
        self._responses = responses

    async def detect_with_metadata(self, text: str):
        return self._responses[text]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingress_context_prefers_history_language_for_ambiguous_follow_up():
    from app.channels.ingress import ChannelIngressContextService

    detector = StubLanguageDetector(
        {
            "Bisq Easy": LanguageDetectionDetails(
                language_code="en",
                confidence=0.95,
                backend="english_heuristic",
            ),
            "Wie kann ich aktuell BTC mit Euro kaufen?": LanguageDetectionDetails(
                language_code="de",
                confidence=0.99,
                backend="langdetect",
            ),
        }
    )
    service = ChannelIngressContextService(language_detector=detector)
    message = IncomingMessage(
        message_id="m1",
        channel=ChannelType.WEB,
        question="Bisq Easy",
        user=UserContext(user_id="user-1"),
        chat_history=[
            ChatMessage(
                role="user", content="Wie kann ich aktuell BTC mit Euro kaufen?"
            ),
            ChatMessage(
                role="assistant",
                content="Verwenden Sie Bisq 1 Handel oder Bisq Easy (Bisq 2)?",
            ),
        ],
    )

    prepared = await service.prepare_incoming(message)

    assert prepared.locale_context is not None
    assert prepared.locale_context.language_code == "de"
    assert prepared.locale_context.source == "chat_history_hint"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingress_context_ignores_trailing_duplicate_current_user_turn_in_history():
    from app.channels.ingress import ChannelIngressContextService

    detector = StubLanguageDetector(
        {
            "Bisq Easy": LanguageDetectionDetails(
                language_code="tl",
                confidence=0.99,
                backend="langdetect",
            ),
            "Wie kann ich aktuell BTC mit Euro kaufen?": LanguageDetectionDetails(
                language_code="de",
                confidence=0.99,
                backend="langdetect",
            ),
        }
    )
    service = ChannelIngressContextService(language_detector=detector)
    message = IncomingMessage(
        message_id="m1",
        channel=ChannelType.WEB,
        question="Bisq Easy",
        user=UserContext(user_id="user-1"),
        chat_history=[
            ChatMessage(
                role="user", content="Wie kann ich aktuell BTC mit Euro kaufen?"
            ),
            ChatMessage(
                role="assistant",
                content="Verwenden Sie Bisq 1 Handel oder Bisq Easy (Bisq 2)?",
            ),
            ChatMessage(role="user", content="Bisq Easy"),
        ],
    )

    prepared = await service.prepare_incoming(message)

    assert prepared.locale_context is not None
    assert prepared.locale_context.language_code == "de"
    assert prepared.locale_context.source == "chat_history_hint"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingress_context_uses_thread_language_hint_for_ambiguous_short_message():
    from app.channels.ingress import ChannelIngressContextService

    detector = StubLanguageDetector(
        {
            "Bisq Easy": LanguageDetectionDetails(
                language_code="en",
                confidence=0.95,
                backend="english_heuristic",
            ),
        }
    )
    service = ChannelIngressContextService(language_detector=detector)
    message = IncomingMessage(
        message_id="m1",
        channel=ChannelType.MATRIX,
        question="Bisq Easy",
        user=UserContext(user_id="@user:matrix.org"),
    )

    prepared = await service.prepare_incoming(message, thread_language_hint="de")

    assert prepared.locale_context is not None
    assert prepared.locale_context.language_code == "de"
    assert prepared.locale_context.source == "thread_state_hint"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingress_context_marks_web_messages_as_explicit_invocation():
    from app.channels.ingress import ChannelIngressContextService

    detector = StubLanguageDetector(
        {
            "Hello": LanguageDetectionDetails(
                language_code="en",
                confidence=0.99,
                backend="english_heuristic",
            ),
        }
    )
    service = ChannelIngressContextService(language_detector=detector)
    message = IncomingMessage(
        message_id="m1",
        channel=ChannelType.WEB,
        question="Hello",
        user=UserContext(user_id="user-1"),
    )

    prepared = await service.prepare_incoming(message)

    assert prepared.classification is not None
    assert prepared.classification.should_process is True
    assert prepared.classification.is_explicit_invocation is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ingress_context_flags_high_risk_topics():
    from app.channels.ingress import ChannelIngressContextService

    detector = StubLanguageDetector(
        {
            "I sent the payment, did not receive BTC, and I think this is a scam": LanguageDetectionDetails(
                language_code="en",
                confidence=0.99,
                backend="english_heuristic",
            ),
        }
    )
    service = ChannelIngressContextService(language_detector=detector)
    message = IncomingMessage(
        message_id="m1",
        channel=ChannelType.MATRIX,
        question="I sent the payment, did not receive BTC, and I think this is a scam",
        user=UserContext(user_id="@user:matrix.org"),
    )

    prepared = await service.prepare_incoming(message)

    assert prepared.classification is not None
    assert prepared.classification.topic_risk == "high"
    assert prepared.classification.should_process is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_applies_ingress_service_and_skips_non_processable_messages():
    from app.channels.coordination import InMemoryCoordinationStore
    from app.channels.inbound_orchestrator import InboundMessageOrchestrator

    incoming = IncomingMessage(
        message_id="$evt1",
        channel=ChannelType.MATRIX,
        question="thanks",
        user=UserContext(user_id="@user:server"),
        channel_metadata={"room_id": "!room:server"},
    )
    prepared = incoming.model_copy(
        update={
            "classification": ClassificationDecision(
                should_process=False,
                is_question_candidate=False,
                is_explicit_invocation=False,
                is_substantive_message=False,
                topic_risk="low",
                reasons=["acknowledgment"],
            ),
            "locale_context": LocaleContext(
                language_code="en",
                confidence=0.99,
                source="detected_message",
            ),
        }
    )

    ingress_service = MagicMock()
    ingress_service.prepare_incoming = AsyncMock(return_value=prepared)

    runtime = MagicMock()

    def resolve_optional(name):
        if name == "feedback_followup_coordinator":
            return None
        if name == "ingress_context_service":
            return ingress_service
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock()

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=InMemoryCoordinationStore(),
    )

    processed = await orchestrator.process_incoming(incoming)

    assert processed is False
    ingress_service.prepare_incoming.assert_awaited_once()
    channel.handle_incoming.assert_not_called()
    dispatcher.dispatch.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_orchestrator_passes_thread_language_hint_and_persists_last_language():
    from app.channels.coordination import InMemoryCoordinationStore
    from app.channels.inbound_orchestrator import InboundMessageOrchestrator

    incoming = IncomingMessage(
        message_id="$evt1",
        channel=ChannelType.MATRIX,
        question="Bisq Easy",
        user=UserContext(user_id="@user:server"),
        channel_metadata={"room_id": "!room:server"},
    )
    prepared = incoming.model_copy(
        update={
            "classification": ClassificationDecision(
                should_process=True,
                is_question_candidate=True,
                is_explicit_invocation=False,
                is_substantive_message=True,
                topic_risk="low",
                reasons=[],
            ),
            "locale_context": LocaleContext(
                language_code="de",
                confidence=0.95,
                source="thread_state_hint",
            ),
        }
    )

    ingress_service = MagicMock()
    ingress_service.prepare_incoming = AsyncMock(return_value=prepared)

    runtime = MagicMock()

    def resolve_optional(name):
        if name == "feedback_followup_coordinator":
            return None
        if name == "ingress_context_service":
            return ingress_service
        return None

    runtime.resolve_optional = MagicMock(side_effect=resolve_optional)

    response = SimpleNamespace(
        requires_human=False,
        metadata=SimpleNamespace(routing_action="auto_send"),
    )
    channel = MagicMock()
    channel.channel_id = "matrix"
    channel.runtime = runtime
    channel.handle_incoming = AsyncMock(return_value=response)

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=True)

    store = InMemoryCoordinationStore()
    await store.set_thread_state(
        "thread:matrix:!room:server",
        {"last_language_code": "de"},
        ttl_seconds=60.0,
    )

    orchestrator = InboundMessageOrchestrator(
        channel=channel,
        channel_id="matrix",
        dispatcher=dispatcher,
        autoresponse_policy_service=None,
        coordination_store=store,
        thread_state_ttl_seconds=60.0,
    )

    processed = await orchestrator.process_incoming(incoming)

    assert processed is True
    ingress_service.prepare_incoming.assert_awaited_once_with(
        incoming,
        thread_language_hint="de",
    )
    channel.handle_incoming.assert_awaited_once_with(prepared)
    state = await store.get_thread_state("thread:matrix:!room:server")
    assert state is not None
    assert state.get("last_language_code") == "de"
