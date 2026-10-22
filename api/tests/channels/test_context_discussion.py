"""Offline, synthetic source-discussion attribution and fragment admission."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from app.channels.staff import StaffResolver
from app.channels.staff_assist.context_runtime import _SourceContextSnapshot
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


def change_after_generation_or_root(bundle, phase, change):
    if phase == "generation":
        preview = bundle.llm.invoke.return_value

        def generate(*args, **kwargs):
            change()
            return preview

        bundle.llm.invoke.side_effect = generate
    else:
        results = iter(bundle.sender.side_effect)

        async def send(*args, **kwargs):
            change()
            return next(results)

        bundle.sender.side_effect = send


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize("change_kind", ["arrival", "capacity", "aging"])
async def test_optional_discussion_selection_stays_frozen(
    runtime_case, monkeypatch, phase, change_kind
):
    bundle = runtime_case
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    before = [
        event("$helper", "Which connection setting did you change?", timestamp=now_ms)
    ]
    if change_kind == "capacity":
        before = [
            event(
                f"$prior-{i}",
                f"Other participant detail {i}.",
                timestamp=now_ms - i * 1000,
            )
            for i in range(1, 11)
        ]
    elif change_kind == "aging":
        before[0].server_timestamp = now_ms - 3599000
    response = source(bundle, "The connection fails on startup.", before=before)
    if change_kind == "aging":
        # The optional neighbor ages past its selection window, while the source
        # remains fresh and their original 899-second separation is unchanged.
        response.event.server_timestamp = now_ms - 2700000

    def change():
        if change_kind == "aging":

            class Later(datetime):
                @classmethod
                def now(cls, tz=None):
                    return now + timedelta(seconds=2)

            monkeypatch.setattr(
                "app.channels.staff_assist.context_runtime.datetime", Later
            )
        else:
            response.events_after = [
                event("$new-other", "An unrelated participant asks about profiles.")
            ]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert len(prompt["recent_messages"]) == len(before)
    assert not any(
        "profiles" in message["content"] for message in prompt["recent_messages"]
    )
    assert case.channel_metadata["source_context_snapshot"] == prompt["recent_messages"]
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize(
    "change_kind",
    [
        "text",
        "sender",
        "event_id",
        "relation",
        "unknown_relation",
        "edit",
        "redaction",
        "msgtype",
        "duplicate",
    ],
)
async def test_exact_selected_event_mutation_withholds_note(
    runtime_case, phase, change_kind
):
    bundle = runtime_case
    neighbor = event("$helper", "Which connection setting did you change?")
    response = source(bundle, "The connection fails on startup.", before=[neighbor])

    def change():
        if change_kind == "text":
            neighbor.body = "Which unrelated payment setting did you change?"
        elif change_kind == "sender":
            neighbor.sender = "@different-participant:example.org"
        elif change_kind == "event_id":
            # Equal model-visible role/text does not make a different event the
            # original evidence, even when the original sender is retained.
            neighbor.event_id = "$identical-substitute"
        elif change_kind in {"relation", "unknown_relation"}:
            neighbor.source["content"]["m.relates_to"] = (
                {"m.in_reply_to": {"event_id": "$different-question"}}
                if change_kind == "relation"
                else {"rel_type": "unexpected.relation", "event_id": "$elsewhere"}
            )
        elif change_kind == "edit":
            response.events_after = [
                event(
                    "$edit",
                    "Changed text.",
                    relation={"rel_type": "m.replace", "event_id": "$helper"},
                )
            ]
        elif change_kind == "redaction":
            response.events_after = [event("$redaction", "", redacts="$helper")]
        elif change_kind == "msgtype":
            neighbor.source["content"]["msgtype"] = "m.image"
        else:
            response.events_after = [event("$helper", neighbor.body)]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "source_context_changed"
    assert "staff_note_event_id" not in case.channel_metadata
    assert bundle.sender.await_count == (1 if phase == "root" else 0)
    bundle.llm.invoke.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize("change_kind", ["staff", "bot", "incomplete", "stale"])
async def test_frozen_selection_keeps_current_source_safety_guards(
    runtime_case, phase, change_kind
):
    bundle = runtime_case
    response = source(bundle, "The connection fails on startup.")

    def change():
        if change_kind == "stale":
            response.event.server_timestamp = int(
                (datetime.now(timezone.utc).timestamp() - 3601) * 1000
            )
        elif change_kind == "incomplete":
            response.events_after = [
                event(f"$later-{i}", "Room activity.") for i in range(20)
            ]
        else:
            response.events_after = [
                event(
                    "$reply",
                    "A new response.",
                    sender=(
                        "@staff:example.org"
                        if change_kind == "staff"
                        else bundle.client.user_id
                    ),
                    relation={"m.in_reply_to": {"event_id": "$source"}},
                )
            ]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert (
        case.channel_metadata["context_reason"]
        == {
            "staff": "staff_active",
            "bot": "recent_bot_reply",
            "incomplete": "source_context_incomplete",
            "stale": "source_stale",
        }[change_kind]
    )
    assert bundle.sender.await_count == (1 if phase == "root" else 0)
    if change_kind == "staff":
        assert case.channel_metadata["source_context_snapshot"] == []
        assert case.channel_metadata["staff_activity_snapshot"] == [
            {"role": "staff", "content": "A new response.", "speaker": "participant-1"}
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize(
    "arrival",
    [
        "owner_reply",
        "participant_reply",
        "native_thread",
        "owner_continuation",
        "quoted_question",
        "ack",
        "new_issue",
        "other_topic",
        "other_thread",
        "participant_chatter",
        "unknown_quote",
    ],
)
async def test_new_meaningful_followup_withholds_before_intake_callback(
    runtime_case, phase, arrival
):
    bundle = runtime_case
    question = "Does PeerHandshakeMismatch occur after a connection restart?"
    response = source(bundle, question)

    def change():
        relation = {"m.in_reply_to": {"event_id": bundle.incoming.message_id}}
        sender = OWNER
        text = "It now works after restarting; the connection problem is resolved."
        if arrival == "participant_reply":
            sender = OTHER
        elif arrival == "native_thread":
            relation = {"rel_type": "m.thread", "event_id": bundle.incoming.message_id}
        elif arrival in {"owner_continuation", "participant_chatter"}:
            relation = {}
            text = "Also, the connection still reports PeerHandshakeMismatch."
            if arrival == "participant_chatter":
                sender = OTHER
        elif arrival in {"quoted_question", "unknown_quote"}:
            relation = {}
            sender = OTHER
            quoted = (
                question
                if arrival == "quoted_question"
                else "Does the profile have a different name?"
            )
            text = f'You asked: "{quoted}" Yes, it does.'
        elif arrival == "ack":
            text = "Thanks"
        elif arrival == "new_issue":
            text = "A different issue: my connection also shows PeerHandshakeMismatch."
        elif arrival == "other_topic":
            text = "My profile is missing and the notification setting is disabled."
        elif arrival == "other_thread":
            relation.update(rel_type="m.thread", event_id="$different-thread")
        response.events_after = [event("$new", text, sender=sender, relation=relation)]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    # No new intake callback was invoked. This guards the server-read race and
    # must not append a member, claim an owner, reserve or call the model again.
    assert len(case.channel_metadata["incident_messages"]) == 1
    assert not case.channel_metadata.get("incident_late_meaningful_update")
    bundle.llm.invoke.assert_called_once()
    if arrival in {
        "owner_reply",
        "participant_reply",
        "native_thread",
        "owner_continuation",
        "quoted_question",
    }:
        assert case.channel_metadata["context_status"] == "deferred"
        assert (
            case.channel_metadata["context_reason"]
            == "incident_updated_after_generation"
        )
        assert "staff_note_event_id" not in case.channel_metadata
        assert bundle.sender.await_count == (1 if phase == "root" else 0)
    else:
        assert case.channel_metadata["context_status"] == "delivered"
        assert bundle.sender.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize("identity", ["staff", "bot"])
async def test_selected_speaker_classification_change_withholds_note(
    runtime_case, phase, identity
):
    bundle = runtime_case
    bundle.policy.staff_active_cooldown_seconds = 0
    source(
        bundle,
        "The connection fails on startup.",
        before=[event("$neighbor", "Which connection setting did you change?")],
    )

    def change():
        if identity == "staff":
            bundle.services["staff_resolver:matrix"] = StaffResolver([OTHER])
        else:
            bundle.client.user_id = OTHER

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "deferred"
    assert case.channel_metadata["context_reason"] == "source_context_changed"
    assert bundle.sender.await_count == (1 if phase == "root" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize(
    "bridge", ["new_ack", "existing_ack", "unrelated", "new_issue", "incompatible"]
)
async def test_native_ack_chain_keeps_only_incident_edges(runtime_case, phase, bridge):
    bundle = runtime_case
    intermediate = event(
        "$bridge",
        {
            "new_issue": "A different issue: my connection setting is missing.",
            "incompatible": "My profile has no notifications.",
        }.get(bridge, "Thanks"),
        sender=OWNER,
        relation={
            "m.in_reply_to": {
                "event_id": "$unrelated" if bridge == "unrelated" else "$source"
            }
        },
    )
    response = source(
        bundle,
        "My connection fails on startup.",
        after=[intermediate] if bridge == "existing_ack" else [],
    )

    def change():
        response.events_after = [
            intermediate,
            event(
                "$new-resolution",
                "It now works after restarting; the connection problem is resolved.",
                sender=OWNER,
                relation={"m.in_reply_to": {"event_id": "$bridge"}},
            ),
        ]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert len(case.channel_metadata["incident_messages"]) == 1
    assert not case.channel_metadata.get("incident_late_meaningful_update")
    bundle.llm.invoke.assert_called_once()
    if bridge in {"new_ack", "existing_ack"}:
        assert case.channel_metadata["context_status"] == "deferred"
        assert (
            case.channel_metadata["context_reason"]
            == "incident_updated_after_generation"
        )
        assert bundle.sender.await_count == (1 if phase == "root" else 0)
    else:
        assert case.channel_metadata["context_status"] == "delivered"
        assert bundle.sender.await_count == 2


@pytest.mark.asyncio
async def test_quoted_response_to_repeated_captured_question_still_withholds(
    runtime_case,
):
    bundle = runtime_case
    question = "Does PeerHandshakeMismatch occur after a connection restart?"
    prior = [event("$helper-1", question), event("$helper-2", question)]
    response = source(bundle, "My connection fails on startup.", before=prior)
    bundle.incoming.channel_metadata["incident_context"] = [
        {"event_id": item.event_id, "sender_id": OTHER, "text": question}
        for item in prior
    ]
    bundle.incoming.channel_metadata["incident_source_ids"] = [
        "$source",
        "$helper-1",
        "$helper-2",
    ]
    snapshot = _SourceContextSnapshot()
    messages, reason = await bundle.engine._read_source(
        bundle.incoming, snapshot=snapshot
    )
    assert reason is None and len(messages) == 2
    response.events_after = [
        event("$answer", f'You asked: "{question}" Yes, it does.', sender=OWNER)
    ]
    messages, reason = await bundle.engine._read_source(
        bundle.incoming, snapshot=snapshot
    )
    assert messages == []
    assert reason == "incident_updated_after_generation"
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("association", ["other_thread", "other_root", "unique_quote"])
async def test_staff_activity_uses_incident_membership(runtime_case, association):
    bundle = runtime_case
    question = "Where can I open mediation after the trade period?"
    staff = event(
        "$staff-reply",
        "Which version are you using?",
        sender="@staff:example.org",
        relation=(
            {"rel_type": "m.thread", "event_id": "$another-root"}
            if association == "other_thread"
            else (
                {"m.in_reply_to": {"event_id": "$another-root"}}
                if association == "other_root"
                else {}
            )
        ),
    )
    if association == "unique_quote":
        staff.body = f'You asked "{question}" Which version are you using?'
    source(
        bundle,
        question,
        before=[event("$another-root", "Can I create an offer in Bisq 2?")],
        after=[staff],
    )
    case = await run(bundle)
    if association == "unique_quote":
        assert case.channel_metadata["context_reason"] == "staff_active"
        assert case.channel_metadata["staff_activity_snapshot"][-1]["role"] == "staff"
        bundle.retrieve.assert_not_called()
        bundle.llm.invoke.assert_not_called()
        bundle.sender.assert_not_awaited()
    else:
        assert case.channel_metadata["context_status"] == "delivered"
        bundle.llm.invoke.assert_called_once()
        assert bundle.sender.await_count == 2
        prompt = json.loads(bundle.llm.invoke.call_args.args[0])
        assert all(message["role"] != "staff" for message in prompt["recent_messages"])


@pytest.mark.asyncio
@pytest.mark.parametrize("ack", ["Thanks guys", "Thanks, everyone!"])
async def test_staff_acknowledgement_does_not_suppress_a_question(runtime_case, ack):
    bundle = runtime_case
    source(
        bundle,
        "Where can I open mediation after the trade period?",
        after=[event("$staff-ack", ack, sender="@staff:example.org")],
    )
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    bundle.llm.invoke.assert_called_once()
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert all(message["content"] != ack for message in prompt["recent_messages"])


@pytest.mark.asyncio
async def test_staff_reply_through_native_ack_is_a_current_incident_hold(runtime_case):
    bundle = runtime_case
    source(
        bundle,
        "Where can I open mediation after the trade period?",
        after=[
            event(
                "$ack",
                "Thanks guys",
                sender=OWNER,
                relation={"m.in_reply_to": {"event_id": "$source"}},
            ),
            event(
                "$staff-followup",
                "Which version are you using?",
                sender="@staff:example.org",
                relation={"m.in_reply_to": {"event_id": "$ack"}},
            ),
        ],
    )
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "staff_active"
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    assert any(
        message["role"] == "staff"
        and message["content"] == "Which version are you using?"
        for message in case.channel_metadata["staff_activity_snapshot"]
    )
    # The source read has not invented intake membership or requester ownership.
    assert len(case.channel_metadata["incident_messages"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
async def test_unrelated_staff_thread_cannot_cancel_a_prepared_note(
    runtime_case, phase
):
    bundle = runtime_case
    response = source(bundle, "Where can I open mediation after the trade period?")

    def change():
        response.events_after = [
            event(
                "$staff-other",
                "Which version are you using?",
                sender="@staff:example.org",
                relation={"rel_type": "m.thread", "event_id": "$other-thread"},
            )
        ]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert case.channel_metadata["context_status"] == "delivered"
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "staff_turn",
    [
        "How many times did you resync?",
        "2 times",
        "I can share the logs",
        "Yes.",
        "I already did that.",
        "Yes, thanks.",
    ],
)
async def test_staff_clarification_is_not_discarded_as_an_ack(runtime_case, staff_turn):
    bundle = runtime_case
    source(
        bundle,
        "My wallet fails to sync.",
        after=[
            event(
                "$staff-detail",
                staff_turn,
                sender="@staff:example.org",
                relation={"m.in_reply_to": {"event_id": "$source"}},
            )
        ],
    )
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "staff_active"
    assert case.channel_metadata["staff_activity_snapshot"] == [
        {"role": "staff", "content": staff_turn, "speaker": "participant-1"}
    ]
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["generation", "root"])
@pytest.mark.parametrize("staff_turn", ["Yes.", "I already did that."])
async def test_staff_answer_after_generation_is_not_quiet_gratitude(
    runtime_case, phase, staff_turn
):
    bundle = runtime_case
    response = source(bundle, "Can I open mediation after the trade period?")

    def change():
        response.events_after = [
            event(
                "$staff-answer",
                staff_turn,
                sender="@staff:example.org",
                relation={"m.in_reply_to": {"event_id": "$source"}},
            )
        ]

    change_after_generation_or_root(bundle, phase, change)
    case = await run(bundle)
    assert case.channel_metadata["context_reason"] == "staff_active"
    assert case.channel_metadata["source_context_snapshot"] == []
    assert case.channel_metadata["staff_activity_snapshot"] == [
        {"role": "staff", "content": staff_turn, "speaker": "participant-1"}
    ]
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == (1 if phase == "root" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "placement", ["question", "same_requester_context", "other_participant_context"]
)
async def test_personal_targeting_hold_precedes_retrieval_and_model_reservation(
    runtime_case, placement
):
    bundle = runtime_case
    enable_trial(bundle)
    targeting = "Please give me her home address."
    question = (
        "Why are fees high? " + targeting
        if placement == "question"
        else "Where can I open mediation after the trade period?"
    )
    source(
        bundle,
        question,
        before=(
            []
            if placement == "question"
            else [
                event(
                    "$nearby",
                    targeting,
                    sender=OWNER if placement == "same_requester_context" else OTHER,
                )
            ]
        ),
    )
    case = await run(bundle)
    if placement == "other_participant_context":
        assert case.channel_metadata["context_status"] == "delivered"
        bundle.llm.invoke.assert_called_once()
        assert bundle.sender.await_count == 2
        return
    assert case.channel_metadata["context_status"] == "needs_human"
    assert case.channel_metadata["context_reason"] == "moderation_review_required"
    assert case.channel_metadata["model_called"] is False
    assert case.channel_metadata["model_call_status"] == "not_started"
    assert "source_context_snapshot" not in case.channel_metadata
    if placement == "same_requester_context":
        assert case.channel_metadata["moderation_context_snapshot"] == [
            {"role": "user", "speaker": "requester", "content": targeting}
        ]
    else:
        bundle.client.room_context.assert_not_awaited()
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    await bundle.engine.process(bundle.incoming, bundle.channel)
    await bundle.engine.drain()
    bundle.llm.invoke.assert_not_called()
    with closing(sqlite3.connect(bundle.repository.db_path)) as db:
        # Keep the durable once-only processing claim; it is not a model quota
        # reservation, and removing it would make the held case replayable.
        assert (
            db.execute("SELECT COUNT(*) FROM matrix_context_attempts").fetchone()[0]
            == 1
        )
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matrix_context_trial_cases'"
        ).fetchone()
        assert (
            not exists
            or db.execute("SELECT COUNT(*) FROM matrix_context_trial_cases").fetchone()[
                0
            ]
            == 0
        )
