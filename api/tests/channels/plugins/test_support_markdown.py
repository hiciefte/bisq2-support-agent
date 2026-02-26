from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.models import (
    ChannelType,
    DocumentReference,
    OutgoingMessage,
    ResponseMetadata,
    UserContext,
)
from app.channels.plugins.bisq2.channel import Bisq2Channel
from app.channels.plugins.matrix.channel import MatrixChannel
from app.channels.plugins.support_markdown import (
    BISQ2_FAQ_ONION_BASE_URL,
    build_matrix_message_content,
    compose_support_answer_markdown,
    render_markdown_for_matrix,
    render_plain_text_from_markdown,
)
from app.channels.runtime import ChannelRuntime


def _make_faq_sources() -> list[DocumentReference]:
    return [
        DocumentReference(
            document_id="what-is-bisq-easy-1a2b3c4d",
            title="What is Bisq Easy?",
            url="https://bisq.network/faqs/what-is-bisq-easy-1a2b3c4d",
            relevance_score=0.91,
            category="faq",
            protocol="bisq_easy",
            section="overview",
        ),
        DocumentReference(
            document_id="faq-wallet-backup-9f8e7d6c",
            title="How to back up wallet",
            url="/faq/how-to-back-up-wallet-9f8e7d6c",
            relevance_score=0.89,
            category="faq",
            protocol="bisq_easy",
            section="wallet",
        ),
    ]


def _make_mixed_sources() -> list[DocumentReference]:
    return [
        DocumentReference(
            document_id="what-is-bisq-easy-1a2b3c4d",
            title="What is Bisq Easy?",
            url="https://bisq.network/faqs/what-is-bisq-easy-1a2b3c4d",
            relevance_score=0.91,
            category="faq",
            protocol="bisq_easy",
            section="overview",
        ),
        DocumentReference(
            document_id="bisq-wiki-offer-lifecycle",
            title="Offer lifecycle",
            url="https://bisq.wiki/Offer_lifecycle",
            relevance_score=0.83,
            category="wiki",
            protocol="bisq_easy",
            section="lifecycle",
        ),
    ]


def _make_outgoing(channel_type: ChannelType) -> OutgoingMessage:
    return OutgoingMessage(
        message_id="out-001",
        in_reply_to="in-001",
        channel=channel_type,
        answer="Use Settings > Resources to find your data directory backup steps.",
        sources=_make_faq_sources(),
        user=UserContext(user_id="user-1"),
        metadata=ResponseMetadata(
            processing_time_ms=12.0,
            rag_strategy="retrieval",
            model_name="test-model",
            confidence_score=0.72,
        ),
        original_question="How do I back up my wallet?",
    )


def test_compose_support_answer_markdown_appends_structured_footer_and_typed_sources():
    rendered = compose_support_answer_markdown(
        "Use Settings > Resources to find your data directory backup steps.",
        _make_faq_sources(),
        confidence_score=0.72,
    )

    assert "\n\n---\n\n**Answer quality**" in rendered
    assert "- Confidence: **Likely accurate (72%)**" in rendered
    assert "- Source mix: **2 FAQs**" in rendered
    assert "\n\n**Sources**\n" in rendered
    assert (
        f"- ![FAQ](bisq-icon://faq) [FAQ] [What is Bisq Easy?]({BISQ2_FAQ_ONION_BASE_URL}/faq/"
        "what-is-bisq-easy-1a2b3c4d)" in rendered
    )
    assert (
        f"- ![FAQ](bisq-icon://faq) [FAQ] [How to back up wallet]({BISQ2_FAQ_ONION_BASE_URL}/faq/"
        "how-to-back-up-wallet-9f8e7d6c)" in rendered
    )


def test_compose_support_answer_markdown_groups_faq_and_wiki_sources_in_mix():
    rendered = compose_support_answer_markdown(
        "Bisq uses a decentralized network and open-source tooling.",
        _make_mixed_sources(),
        confidence_score=0.86,
    )

    assert "- Confidence: **Verified (86%)**" in rendered
    assert "- Source mix: **1 FAQ, 1 Wiki page**" in rendered
    assert "- ![FAQ](bisq-icon://faq) [FAQ] [What is Bisq Easy?]" in rendered
    assert (
        "- ![Wiki](bisq-icon://wiki) [Wiki] [Offer lifecycle](https://bisq.wiki/Offer_lifecycle)"
        in rendered
    )


def test_compose_support_answer_markdown_escapes_source_labels_and_drops_unsafe_links():
    long_title = "L" * 240
    rendered = compose_support_answer_markdown(
        "Answer.",
        [
            DocumentReference(
                document_id="faq-malicious-title",
                title=f"Wallet ](javascript:alert(1))\u202e {long_title}",
                url="javascript:alert(1)",
                relevance_score=0.9,
                category="faq",
                protocol="bisq_easy",
                section="wallet",
            ),
            DocumentReference(
                document_id="wiki-safe",
                title="Offer lifecycle",
                url="https://bisq.wiki/Offer_lifecycle",
                relevance_score=0.8,
                category="wiki",
                protocol="bisq_easy",
                section="lifecycle",
            ),
        ],
        confidence_score=0.66,
    )

    assert "javascript:alert(1)" not in rendered
    assert "\u202e" not in rendered
    assert r"Wallet \]\(javascript:alert\(1\)\)" in rendered
    assert ("L" * 200) not in rendered
    assert "- ![FAQ](bisq-icon://faq) [FAQ] Wallet" in rendered
    assert (
        "- ![Wiki](bisq-icon://wiki) [Wiki] [Offer lifecycle](https://bisq.wiki/Offer_lifecycle)"
        in rendered
    )


def test_compose_support_answer_markdown_is_idempotent_for_existing_footer_markers():
    already_rendered = (
        "Answer text\n\n"
        "**Confidence:** Verified (91%)\n"
        "**Sources:**\n"
        "- [Some source](https://example.com)"
    )

    rendered = compose_support_answer_markdown(
        already_rendered,
        _make_faq_sources(),
        confidence_score=0.91,
    )

    assert rendered == already_rendered


def test_build_matrix_message_content_contains_html_and_plain_fallback():
    markdown = (
        "**Bold** heading\n\n"
        "- [Bisq Easy](https://bisq.wiki/Bisq_Easy)\n"
        "- `inline`\n"
    )
    content = build_matrix_message_content(markdown)

    assert content["msgtype"] == "m.text"
    assert content["format"] == "org.matrix.custom.html"
    assert "formatted_body" in content
    assert "<strong>Bold</strong>" in content["formatted_body"]
    assert "**" not in content["body"]
    assert "[Bisq Easy]" not in content["body"]
    assert "Bisq Easy" in content["body"]


def test_markdown_renderers_produce_html_and_plain_text():
    markdown = "**Value** [Link](https://example.org)"
    html = render_markdown_for_matrix(markdown)
    plain = render_plain_text_from_markdown(markdown)

    assert "<strong>Value</strong>" in html
    assert "href=" in html
    assert plain == "Value Link"


@pytest.mark.asyncio
async def test_bisq2_channel_send_message_uses_rendered_markdown_and_cleans_visible_citation():
    mock_api = MagicMock()
    mock_api.send_support_message = AsyncMock(return_value={"messageId": "bisq-msg-1"})

    runtime = MagicMock(spec=ChannelRuntime)

    def _resolve(name: str):
        if name == "bisq2_api":
            return mock_api
        return None

    runtime.resolve_optional = MagicMock(side_effect=_resolve)
    channel = Bisq2Channel(runtime)

    outgoing = _make_outgoing(ChannelType.BISQ2).model_copy(
        update={
            "original_question": (
                "Current question: Who is behind Bisq?\n"
                "Recent chat history:\n"
                "- user: What is Bisq?\n"
                "- participant: Bisq is decentralized."
            )
        }
    )
    result = await channel.send_message("support.support", outgoing)

    assert result is True
    sent_kwargs = mock_api.send_support_message.call_args.kwargs
    assert sent_kwargs["citation"] == "Current question: Who is behind Bisq?"

    sent_text = sent_kwargs["text"]
    assert "**Answer quality**" in sent_text
    assert "- Source mix: **2 FAQs**" in sent_text


@pytest.mark.asyncio
async def test_matrix_channel_send_message_uses_rendered_markdown():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.event_id = "$event123"
    mock_client.room_send = AsyncMock(return_value=mock_response)

    runtime = MagicMock(spec=ChannelRuntime)

    def _resolve(name: str):
        if name == "matrix_client":
            return mock_client
        return None

    runtime.resolve_optional = MagicMock(side_effect=_resolve)
    channel = MatrixChannel(runtime)

    outgoing = _make_outgoing(ChannelType.MATRIX)
    result = await channel.send_message("!room:matrix.org", outgoing)

    assert result is True
    sent_content = mock_client.room_send.call_args.kwargs["content"]
    sent_body = sent_content["body"]
    assert sent_content["format"] == "org.matrix.custom.html"
    assert "formatted_body" in sent_content
    assert "m.relates_to" in sent_content
    assert sent_content["m.relates_to"]["m.in_reply_to"]["event_id"] == "in-001"
    assert "**Likely accurate (72%)**" not in sent_body
    assert "Likely accurate (72%)" in sent_body
    assert "formatted_body" in sent_content
    assert (
        f"{BISQ2_FAQ_ONION_BASE_URL}/faq/how-to-back-up-wallet-9f8e7d6c"
        in sent_content["formatted_body"]
    )
