"""Offline, synthetic source-discussion attribution and fragment admission."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from app.channels.staff_assist.public_context import STAFF_CONTEXT_PROMPT

from tests.channels.test_context_runtime_integration import (
    context,
    run,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as existing_runtime_case,
)
from tests.channels.test_context_trial import enable_trial

pytestmark = pytest.mark.unit
OWNER = "@user:example.org"
OTHER = "@other:example.org"


@pytest.fixture
async def runtime_case(tmp_path):
    async for bundle in existing_runtime_case.__wrapped__(tmp_path):
        yield bundle


def event(event_id, text, *, sender=OTHER, timestamp=None, relation=None, **extra):
    return NS(
        event_id=event_id,
        body=text,
        sender=sender,
        server_timestamp=timestamp
        or int(datetime.now(timezone.utc).timestamp() * 1000),
        source={
            "content": {
                "body": text,
                "msgtype": "m.text",
                "m.relates_to": relation or {},
            }
        },
        **extra,
    )


def source(bundle, question, *, before=None, after=None):
    bundle.incoming = bundle.incoming.model_copy(update={"question": question})
    response = context(body=question, after=after)
    response.event.sender = OWNER
    response.events_before = before or []
    bundle.client.room_context.side_effect = None
    bundle.client.room_context.return_value = response
    return response


@pytest.mark.asyncio
async def test_surrounding_discussion_is_attributed_without_case_ownership(
    runtime_case,
):
    bundle = runtime_case
    before = [
        event("$prior-own", "My connection timeout is ten seconds.", sender=OWNER),
        event("$helper", "Which connection setting did you change?"),
    ]
    after = [event("$later", "A different participant has a profile problem.")]
    question = "The client now reports PeerHandshakeMismatch."
    source(bundle, question, before=before, after=after)
    case = await run(bundle)
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert prompt["question"] == question
    assert prompt["recent_messages"] == [
        {
            "role": "participant",
            "content": before[1].body,
            "speaker": "participant-1",
        },
        {"role": "user", "content": before[0].body, "speaker": "requester"},
        {"role": "participant", "content": after[0].body, "speaker": "participant-1"},
    ]
    assert case.user_id == OWNER
    assert len(case.channel_metadata["incident_messages"]) == 1
    assert OWNER not in json.dumps(prompt)
    assert OTHER not in json.dumps(prompt)
    assert "possibly unrelated surrounding discussion" in STAFF_CONTEXT_PROMPT
    assert "Do not answer a helper's question" in STAFF_CONTEXT_PROMPT
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", ["empty", "unrelated", "ambiguous", "brand_only"])
async def test_unresolved_answer_fragment_defers_before_retrieval(
    runtime_case, history
):
    bundle = runtime_case
    enable_trial(bundle)
    before = []
    if history == "unrelated":
        before = [event("$unrelated", "What is the current offer price?")]
    elif history == "ambiguous":
        before = [
            event("$a", "Does PeerHandshakeMismatch appear?"),
            event(
                "$b",
                "Did PeerHandshakeMismatch start after the update?",
                sender="@third:example.org",
            ),
        ]
    question = "Yes, PeerHandshakeMismatch remains after the change."
    if history == "brand_only":
        before = [event("$brand", "Does PayPal support this payment?")]
        question = "Yes, PayPal is what I selected."
    source(bundle, question, before=before)
    case = await run(bundle)
    assert (
        case.channel_metadata["context_reason"]
        == "source_followup_antecedent_unavailable"
    )
    assert "context_trial_reserved_at" not in case.channel_metadata
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_unique_diagnostic_antecedent_is_context_not_another_owner(runtime_case):
    bundle = runtime_case
    source(
        bundle,
        "Yes, PeerHandshakeMismatch remains after the change.",
        before=[
            event("$helper", "Does PeerHandshakeMismatch appear after the change?")
        ],
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    assert case.user_id == OWNER
    assert len(case.channel_metadata["incident_messages"]) == 1
    assert case.channel_metadata["source_context_snapshot"][0]["role"] == "participant"
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_self_contained_negative_report_does_not_require_antecedent(runtime_case):
    bundle = runtime_case
    source(
        bundle, "No offers are visible in Bisq 2 after the update; how can I fix this?"
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_discussion_filters_private_stale_invalid_and_bot_neighbors(runtime_case):
    bundle = runtime_case
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    included = event("$safe", "Contact person@example.org about the profile.")
    edited = event("$edited", "Obsolete neighboring text.")
    replacement = event(
        "$replacement",
        "Replacement text.",
        relation={"rel_type": "m.replace", "event_id": "$edited"},
    )
    redacted = event("$redacted", "Redacted neighboring text.")
    redaction = event("$redaction", "", redacts="$redacted")
    nontext = event("$file", "private filename.png")
    nontext.source["content"]["msgtype"] = "m.image"
    source(
        bundle,
        "Where can I find the application settings?",
        before=[
            included,
            edited,
            replacement,
            redacted,
            redaction,
            nontext,
            event("$old", "Old unrelated text.", timestamp=now_ms - 901000),
            event("$bot", "Previous bot draft.", sender=bundle.client.user_id),
            event("$unknown", "Unknown author.", sender=""),
            event(
                "$thread",
                "Another native thread.",
                relation={"rel_type": "m.thread", "event_id": "$elsewhere"},
            ),
        ],
    )
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert len(messages) == 1
    assert "person@example.org" not in messages[0].content
    assert "Contact" in messages[0].content
    assert messages[0].role == "participant"


@pytest.mark.asyncio
async def test_discussion_does_not_cross_trial_start(runtime_case):
    bundle = runtime_case
    trial = enable_trial(bundle)
    source(
        bundle,
        "Where are connection settings?",
        before=[
            event(
                "$old",
                "Before the trial.",
                timestamp=int(trial.start_at.timestamp() * 1000) - 1,
            ),
            event("$current", "During the trial."),
        ],
    )
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert [message.content for message in messages] == ["During the trial."]


@pytest.mark.asyncio
async def test_native_thread_context_excludes_other_room_discussion(runtime_case):
    bundle = runtime_case
    response = source(
        bundle,
        "Where are connection settings?",
        before=[
            event("$outside", "Unrelated plain room message."),
            event(
                "$sibling",
                "A related human diagnostic question?",
                relation={"rel_type": "m.thread", "event_id": "$root"},
            ),
            event("$root", "The connection fails on startup."),
        ],
    )
    response.event.source = {
        "content": {"m.relates_to": {"rel_type": "m.thread", "event_id": "$root"}}
    }
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert [message.content for message in messages] == [
        "The connection fails on startup.",
        "A related human diagnostic question?",
    ]


@pytest.mark.asyncio
async def test_native_thread_retains_immediate_reply_target_or_defers(runtime_case):
    bundle = runtime_case
    root = event("$root", ("Captured owner details. " * 160).strip(), sender=OWNER)
    question = event(
        "$question",
        ("Which setting did you change? " * 20).strip(),
        relation={"rel_type": "m.thread", "event_id": "$root"},
    )
    response = source(bundle, "Yes, I used it.", before=[question, root])
    response.event.source = {
        "content": {
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": "$root",
                "m.in_reply_to": {"event_id": "$question"},
            }
        }
    }
    bundle.incoming.channel_metadata["incident_context"] = [
        {"event_id": "$root", "text": root.body}
    ]
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert messages == []
    assert reason == "source_discussion_capacity_reached"

    # With enough capacity, preserve both the owner context and the question
    # actually answered, without assigning the helper's words to the owner.
    root.body = "Captured owner diagnostic details."
    bundle.incoming.channel_metadata["incident_context"][0]["text"] = root.body
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert [(message.role, message.content) for message in messages] == [
        ("user", root.body),
        ("participant", question.body),
    ]


@pytest.mark.asyncio
async def test_self_contained_thread_update_can_follow_acknowledgement(runtime_case):
    bundle = runtime_case
    root = event("$root", "The connection fails on startup.", sender=OWNER)
    acknowledgement = event(
        "$ack", "Thanks", relation={"rel_type": "m.thread", "event_id": "$root"}
    )
    response = source(
        bundle,
        "The client now reports PeerHandshakeMismatch after restarting.",
        before=[acknowledgement, root],
    )
    response.event.source = {
        "content": {
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": "$root",
                "m.in_reply_to": {"event_id": "$ack"},
            }
        }
    }
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert [(message.role, message.content) for message in messages] == [
        ("user", root.body)
    ]


@pytest.mark.asyncio
async def test_captured_owner_context_is_retained_when_neighborhood_is_full(
    runtime_case,
):
    bundle = runtime_case
    owner_history = event(
        "$owned", "The diagnostic is PeerHandshakeMismatch.", sender=OWNER
    )
    source(
        bundle,
        "Where are connection settings?",
        before=[
            event(f"$room-{index}", f"Other message {index}.") for index in range(20)
        ]
        + [owner_history],
    )
    bundle.incoming.channel_metadata["incident_context"] = [
        {"event_id": "$owned", "text": owner_history.body}
    ]
    messages, reason = await bundle.engine._read_source(bundle.incoming)
    assert reason is None
    assert len(messages) == 10
    assert messages[0].content == owner_history.body
    assert messages[0].role == "user"


@pytest.mark.asyncio
async def test_needed_antecedent_too_large_defers_instead_of_truncating(runtime_case):
    bundle = runtime_case
    source(
        bundle,
        "Yes, PeerHandshakeMismatch remains after the change.",
        before=[event("$needed", "PeerHandshakeMismatch diagnostic detail. " * 120)],
    )
    case = await run(bundle)
    assert (
        case.channel_metadata["context_reason"] == "source_discussion_capacity_reached"
    )
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_neighbor_changed_after_generation_withholds_stale_note(runtime_case):
    bundle = runtime_case
    neighbor = event("$helper", "Which connection setting did you change?")
    response = source(bundle, "The connection fails on startup.", before=[neighbor])
    preview = bundle.llm.invoke.return_value

    def generate(*args, **kwargs):
        response.events_before = []  # The neighboring message was redacted.
        return preview

    bundle.llm.invoke.side_effect = generate
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "source_context_changed"
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_neighbor_changed_after_root_withholds_threaded_note(runtime_case):
    bundle = runtime_case
    neighbor = event("$helper", "Which connection setting did you change?")
    response = source(bundle, "The connection fails on startup.", before=[neighbor])
    results = iter(bundle.sender.side_effect)

    async def send(*args, **kwargs):
        response.events_before = []
        return next(results)

    bundle.sender.side_effect = send
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "source_context_changed"
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    assert "staff_note_event_id" not in case.channel_metadata
    bundle.llm.invoke.assert_called_once()
    bundle.sender.assert_awaited_once()
