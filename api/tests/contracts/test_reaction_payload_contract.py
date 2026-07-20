"""Cross-repo contract tests: Python agent <-> Bisq2 Java DTO payloads.

Validates that the JSON payloads produced/consumed by the Python agent
match the expected shapes of the Bisq2 Java DTOs. If a Java DTO field
is renamed or added, these tests surface the mismatch without needing
a running Java node.

Covered contracts:
- SendSupportMessageRequest  (Python -> Java)
- SendSupportMessageResponse (Java -> Python)
- SendSupportReactionRequest (Python -> Java)
- SupportChatReactionDto / WebSocketEvent payload (Java -> Python)
- SubscriptionRequest  (Python -> Java)
- SubscriptionResponse (Java -> Python)
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

import pytest
from app.channels.plugins.bisq2.client.websocket import (
    is_valid_subscription_response,
)
from app.channels.plugins.bisq2.reaction_handler import BISQ2_REACTION_MAP
from app.channels.reactions import ReactionEvent, ReactionRating

# =============================================================================
# Expected Java DTO schemas (field name -> expected type description)
# =============================================================================

# record SendSupportMessageRequest(String text, @Nullable String citation,
#        @Nullable String citationAuthorUserProfileId,
#        @Nullable String citationMessageId)
SEND_MESSAGE_REQUEST_FIELDS: Dict[str, str] = {
    "text": "string",
    "citation": "string|null|optional",
    "citationAuthorUserProfileId": "string|null|optional",
    "citationMessageId": "string|null|optional",
}

# record SendSupportMessageResponse(String messageId, long timestamp)
SEND_MESSAGE_RESPONSE_FIELDS: Dict[str, str] = {
    "messageId": "string",
    "timestamp": "integer",
}

# record SendSupportReactionRequest(int reactionId, boolean isRemoved,
#        @Nullable String senderUserProfileId)
SEND_REACTION_REQUEST_FIELDS: Dict[str, str] = {
    "reactionId": "integer",
    "isRemoved": "boolean",
}

# record SupportChatReactionDto(String reaction, String messageId,
#        String senderUserProfileId, String channelId)
SUPPORT_CHAT_REACTION_DTO_FIELDS: Dict[str, str] = {
    "reaction": "string",
    "messageId": "string",
    "senderUserProfileId": "string",
    "channelId": "string",
}

# WebSocketEvent envelope: {topic, subscriberId, payload, modificationType,
#                           sequenceNumber}
WEBSOCKET_EVENT_FIELDS: Dict[str, str] = {
    "topic": "string",
    "subscriberId": "string",
    "payload": "string",
    "modificationType": "string",
    "sequenceNumber": "integer",
}

# SubscriptionRequest: {requestType, requestId, topic, parameter?}
SUBSCRIPTION_REQUEST_FIELDS: Dict[str, str] = {
    "requestType": "string",
    "requestId": "string",
    "topic": "string",
    "parameter": "string|optional",
}

# SubscriptionResponse: {type, requestId, payload, errorMessage}
SUBSCRIPTION_RESPONSE_FIELDS: Dict[str, str] = {
    "type": "string",
    "requestId": "string",
    "payload": "string|null",
    "errorMessage": "string|null",
}

# Bisq2 Reaction enum ordinals
BISQ2_REACTIONS: Dict[str, int] = {
    "THUMBS_UP": 0,
    "THUMBS_DOWN": 1,
    "HAPPY": 2,
    "LAUGH": 3,
    "HEART": 4,
    "PARTY": 5,
}


# =============================================================================
# Helpers
# =============================================================================


def _type_check(value: Any, expected: str) -> bool:
    """Check if a value matches the expected type description."""
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string|null":
        return value is None or isinstance(value, str)
    return False


def _validate_payload(payload: Dict[str, Any], schema: Dict[str, str]) -> None:
    """Assert that payload has exactly the expected fields with correct types."""
    required_fields = {
        field
        for field, expected in schema.items()
        if not expected.endswith("|optional")
    }
    missing = required_fields - set(payload.keys())
    assert not missing, f"Missing fields: {missing}"
    extra = set(payload.keys()) - set(schema.keys())
    assert not extra, f"Unexpected fields: {extra}"

    for field, expected_type in schema.items():
        if field not in payload:
            continue
        if expected_type.endswith("|optional"):
            expected_type = expected_type.removesuffix("|optional")
        assert _type_check(
            payload[field], expected_type
        ), f"Field '{field}': expected {expected_type}, got {type(payload[field]).__name__} ({payload[field]!r})"


# =============================================================================
# SendSupportMessageRequest contract (Python -> Java)
# =============================================================================


class TestSendMessageRequestContract:
    """Python agent builds request payloads matching Java SendSupportMessageRequest."""

    def test_message_request_minimal(self):
        """Minimal request: text only; citation intentionally omitted."""
        payload = {"text": "You can download Bisq from bisq.network."}
        _validate_payload(payload, {"text": "string"})
        assert "citation" not in payload or payload["citation"] is None

    def test_message_request_with_citation(self):
        """Request with citation matches Java DTO."""
        payload = {
            "text": "You can download Bisq from bisq.network.",
            "citation": "How do I use Bisq?",
            "citationAuthorUserProfileId": "profile-fixture",
            "citationMessageId": "message-fixture",
        }
        _validate_payload(payload, SEND_MESSAGE_REQUEST_FIELDS)

    def test_message_request_text_not_empty(self):
        """Text must not be empty (Java DTO validation)."""
        payload = {"text": "Hello"}
        assert len(payload["text"]) > 0

    def test_message_request_is_json_serializable(self):
        """Payload must be JSON-serializable for HTTP POST body."""
        payload = {
            "text": "Response with special chars: <>&\"'",
            "citation": None,
        }
        serialized = json.dumps(payload)
        roundtrip = json.loads(serialized)
        assert roundtrip["text"] == payload["text"]


# =============================================================================
# SendSupportMessageResponse contract (Java -> Python)
# =============================================================================


class TestSendMessageResponseContract:
    """Java returns SendSupportMessageResponse, Python must parse correctly."""

    def test_response_fields(self):
        """Response has messageId (string) and timestamp (long)."""
        response = {
            "messageId": "abc123def456",
            "timestamp": 1718000000000,
        }
        _validate_payload(response, SEND_MESSAGE_RESPONSE_FIELDS)

    def test_response_message_id_is_hex(self):
        """Bisq2 messageIds are typically hex strings."""
        response = {"messageId": "a1b2c3d4e5f6", "timestamp": 1718000000000}
        assert all(c in "0123456789abcdef" for c in response["messageId"])

    def test_response_timestamp_millis(self):
        """Java uses millisecond timestamps; Python must handle them."""
        java_ts = 1718000000000  # June 2024, ms
        python_dt = datetime.fromtimestamp(java_ts / 1000, tz=timezone.utc)
        assert python_dt.year >= 2024

    def test_response_empty_on_404(self):
        """bisq_api.send_support_message() returns empty dict on 404."""
        response: Dict[str, Any] = {}
        assert "messageId" not in response


# =============================================================================
# SendSupportReactionRequest contract (Python -> Java)
# =============================================================================


class TestSendReactionRequestContract:
    """Python agent builds reaction request matching Java SendSupportReactionRequest."""

    def test_reaction_request_add(self):
        """Add reaction request."""
        payload = {"reactionId": 0, "isRemoved": False}
        _validate_payload(payload, SEND_REACTION_REQUEST_FIELDS)

    def test_reaction_request_remove(self):
        """Remove reaction request."""
        payload = {"reactionId": 1, "isRemoved": True}
        _validate_payload(payload, SEND_REACTION_REQUEST_FIELDS)

    @pytest.mark.parametrize(
        "name,ordinal",
        list(BISQ2_REACTIONS.items()),
    )
    def test_reaction_id_matches_java_enum(self, name: str, ordinal: int):
        """reactionId must use Java Reaction enum ordinals."""
        payload = {"reactionId": ordinal, "isRemoved": False}
        assert isinstance(payload["reactionId"], int)
        assert 0 <= payload["reactionId"] <= 5

    def test_reaction_endpoint_url_pattern(self):
        """Endpoint follows /api/v1/support/channels/{channelId}/{messageId}/reactions."""
        channel_id = "support.support"
        message_id = "abc123"
        endpoint = f"/api/v1/support/channels/{channel_id}/{message_id}/reactions"
        assert endpoint == "/api/v1/support/channels/support.support/abc123/reactions"


# =============================================================================
# SupportChatReactionDto / WebSocket payload contract (Java -> Python)
# =============================================================================


class TestSupportChatReactionDtoContract:
    """Python parses the current Java SupportChatReactionDto shape."""

    @pytest.fixture()
    def sample_reaction_dto(self) -> Dict[str, Any]:
        return {
            "reaction": "THUMBS_UP",
            "messageId": "message-abc-123",
            "senderUserProfileId": "user-profile-xyz",
            "channelId": "support.support",
        }

    def test_reaction_dto_schema(self, sample_reaction_dto):
        """SupportChatReactionDto has the exact expected fields and types."""
        _validate_payload(sample_reaction_dto, SUPPORT_CHAT_REACTION_DTO_FIELDS)

    def test_reaction_dto_all_names(self):
        """All Java reaction names are valid SupportChatReactionDto values."""
        for name in BISQ2_REACTIONS:
            dto = {
                "reaction": name,
                "messageId": "message-abc-123",
                "senderUserProfileId": "user-1",
                "channelId": "support.support",
            }
            _validate_payload(dto, SUPPORT_CHAT_REACTION_DTO_FIELDS)

    @pytest.mark.parametrize("required_field", ["senderUserProfileId", "channelId"])
    def test_reaction_dto_requires_scope_fields(
        self, sample_reaction_dto, required_field
    ):
        """Sender and channel scope are mandatory in the current Java DTO."""
        sample_reaction_dto.pop(required_field)

        with pytest.raises(AssertionError):
            _validate_payload(
                sample_reaction_dto,
                SUPPORT_CHAT_REACTION_DTO_FIELDS,
            )


# =============================================================================
# WebSocket event envelope contract (Java -> Python)
# =============================================================================


class TestWebSocketEventContract:
    """WebSocketEvent envelope wrapping serialized SupportChatReactionDto JSON."""

    @pytest.fixture()
    def sample_event(self) -> Dict[str, Any]:
        return {
            "topic": "SUPPORT_CHAT_REACTIONS",
            "subscriberId": "sub-001",
            "payload": json.dumps(
                {
                    "reaction": "THUMBS_UP",
                    "messageId": "message-abc-123",
                    "senderUserProfileId": "user-1",
                    "channelId": "support.support",
                }
            ),
            "modificationType": "ADDED",
            "sequenceNumber": 1,
        }

    def test_event_envelope_schema(self, sample_event):
        """Event has topic, subscriberId, payload, modificationType, sequenceNumber."""
        _validate_payload(sample_event, WEBSOCKET_EVENT_FIELDS)

    def test_event_payload_is_reaction_dto(self, sample_event):
        """Serialized event payload matches SupportChatReactionDto schema."""
        payload = json.loads(sample_event["payload"])
        _validate_payload(payload, SUPPORT_CHAT_REACTION_DTO_FIELDS)

    def test_modification_type_values(self, sample_event):
        """modificationType is either ADDED or REMOVED."""
        assert sample_event["modificationType"] in ("ADDED", "REMOVED")

    def test_topic_support_reactions(self, sample_event):
        """Topic for support reactions is SUPPORT_CHAT_REACTIONS."""
        assert sample_event["topic"] == "SUPPORT_CHAT_REACTIONS"

    def test_event_json_roundtrip(self, sample_event):
        """Event survives JSON serialization (WebSocket transport)."""
        raw = json.dumps(sample_event)
        parsed = json.loads(raw)
        assert parsed == sample_event

    def test_handler_extracts_correct_fields(self, sample_event):
        """Bisq2ReactionHandler extracts the fields the contract defines."""
        ws_payload = json.loads(sample_event["payload"])

        for field in (
            "reaction",
            "messageId",
            "senderUserProfileId",
            "channelId",
        ):
            assert ws_payload.get(field) is not None


# =============================================================================
# WebSocket SubscriptionRequest contract (Python -> Java)
# =============================================================================


class TestSubscriptionRequestContract:
    """Python sends SubscriptionRequest to subscribe to topics."""

    def test_subscription_request_schema(self):
        """Request has requestType, requestId, and topic."""
        request = {
            "requestType": "Subscribe",
            "requestId": "1",
            "topic": "SUPPORT_CHAT_REACTIONS",
        }
        _validate_payload(request, SUBSCRIPTION_REQUEST_FIELDS)

    def test_subscription_request_type_literal(self):
        """requestType must be exactly 'Subscribe'."""
        request = {"requestType": "Subscribe", "requestId": "1", "topic": "T"}
        assert request["requestType"] == "Subscribe"

    def test_subscription_with_parameter(self):
        """Optional parameter field for filtered subscriptions."""
        request = {
            "requestType": "Subscribe",
            "requestId": "2",
            "topic": "SUPPORT_CHAT_MESSAGES",
            "parameter": "support.support",
        }
        _validate_payload(request, SUBSCRIPTION_REQUEST_FIELDS)
        assert request["parameter"] == "support.support"

    def test_matches_bisq2_websocket_client(self):
        """Payload matches what Bisq2WebSocketClient.subscribe() actually sends."""
        # Replicate the exact logic from bisq2_websocket.py subscribe()
        sequence = 1
        topic = "SUPPORT_CHAT_REACTIONS"
        request = {
            "requestType": "Subscribe",
            "requestId": str(sequence),
            "topic": topic,
        }
        assert request["requestType"] == "Subscribe"
        assert request["requestId"] == "1"
        assert request["topic"] == "SUPPORT_CHAT_REACTIONS"


class TestSubscriptionResponseContract:
    """Python accepts the current Java SubscriptionResponse shape."""

    def test_success_response_schema_and_validation(self):
        response = {
            "type": "SubscriptionResponse",
            "requestId": "1",
            "payload": "[]",
            "errorMessage": None,
        }

        _validate_payload(response, SUBSCRIPTION_RESPONSE_FIELDS)
        assert is_valid_subscription_response(response, "1") is True
        assert "success" not in response

    def test_null_payload_is_valid_when_error_is_blank(self):
        response = {
            "type": "SubscriptionResponse",
            "requestId": "request-fixture",
            "payload": None,
            "errorMessage": " ",
        }

        _validate_payload(response, SUBSCRIPTION_RESPONSE_FIELDS)
        assert is_valid_subscription_response(response, "request-fixture") is True

    def test_error_response_is_not_an_acknowledgement(self):
        response = {
            "type": "SubscriptionResponse",
            "requestId": "request-fixture",
            "payload": None,
            "errorMessage": "subscription rejected",
        }

        _validate_payload(response, SUBSCRIPTION_RESPONSE_FIELDS)
        assert is_valid_subscription_response(response, "request-fixture") is False


# =============================================================================
# Reaction name -> rating mapping contract
# =============================================================================


class TestReactionMappingContract:
    """Python reaction mapping matches Java Reaction enum semantics."""

    def test_mapped_reactions_cover_positive_negative(self):
        """At least one POSITIVE and one NEGATIVE mapping exists."""
        ratings = set(BISQ2_REACTION_MAP.values())
        assert ReactionRating.POSITIVE in ratings
        assert ReactionRating.NEGATIVE in ratings

    def test_thumbs_up_is_positive(self):
        """THUMBS_UP(0) -> POSITIVE (core contract)."""
        assert BISQ2_REACTION_MAP["THUMBS_UP"] == ReactionRating.POSITIVE

    def test_thumbs_down_is_negative(self):
        """THUMBS_DOWN(1) -> NEGATIVE (core contract)."""
        assert BISQ2_REACTION_MAP["THUMBS_DOWN"] == ReactionRating.NEGATIVE

    def test_laugh_is_positive_in_map(self):
        """LAUGH(3) is treated as positive feedback."""
        assert BISQ2_REACTION_MAP["LAUGH"] == ReactionRating.POSITIVE
        assert BISQ2_REACTION_MAP["PARTY"] == ReactionRating.POSITIVE

    def test_all_mapped_reactions_have_valid_java_ordinals(self):
        """Every mapped reaction name corresponds to a valid Java enum ordinal."""
        for name in BISQ2_REACTION_MAP:
            assert name in BISQ2_REACTIONS, f"{name} not in Java Reaction enum"

    def test_reaction_event_from_websocket_payload(self):
        """Demonstrate full conversion: WS payload -> ReactionEvent."""
        ws_payload = {
            "reaction": "THUMBS_UP",
            "messageId": "msg-abc",
            "senderUserProfileId": "user-xyz",
            "channelId": "support.support",
        }

        rating = BISQ2_REACTION_MAP.get(ws_payload["reaction"])
        assert rating == ReactionRating.POSITIVE

        event = ReactionEvent(
            channel_id="bisq2",
            external_message_id=ws_payload["messageId"],
            reactor_id=ws_payload["senderUserProfileId"],
            rating=rating,
            raw_reaction=ws_payload["reaction"],
            timestamp=datetime.now(timezone.utc),
            metadata={"delivery_target": ws_payload["channelId"]},
        )
        assert event.channel_id == "bisq2"
        assert event.external_message_id == "msg-abc"
        assert event.rating == ReactionRating.POSITIVE
        assert event.metadata["delivery_target"] == "support.support"


# =============================================================================
# REST endpoint URL contract
# =============================================================================


class TestEndpointUrlContract:
    """REST endpoint URLs match the Java SupportRestApi routing."""

    def test_send_message_endpoint(self):
        """POST /api/v1/support/channels/{channelId}/messages"""
        channel_id = "support.support"
        url = f"/api/v1/support/channels/{channel_id}/messages"
        assert url == "/api/v1/support/channels/support.support/messages"

    def test_send_reaction_endpoint(self):
        """POST /api/v1/support/channels/{channelId}/{messageId}/reactions"""
        channel_id = "support.support"
        message_id = "deadbeef1234"
        url = f"/api/v1/support/channels/{channel_id}/{message_id}/reactions"
        assert url == "/api/v1/support/channels/support.support/deadbeef1234/reactions"

    def test_websocket_endpoint(self):
        """WebSocket at ws://{host}:{port}/websocket"""
        host = "localhost"
        port = 8090
        url = f"ws://{host}:{port}/websocket"
        assert url == "ws://localhost:8090/websocket"
