"""Offline shared-conversation acceptance with real runtime and durable SQLite.

These checks prove structural grouping and once-only delivery. The provider and
Matrix transports are mocked; generated answer quality is outside their scope.
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest
from app.channels.models import SendResult
from app.channels.staff_assist.context_runtime import MatrixContextRuntime
from app.models.escalation import EscalationFilters, EscalationStatus

from tests.channels.test_context_incidents import hold_worker, incoming
from tests.channels.test_context_runtime_integration import (
    SOURCE_ROOM,
    no_public_delivery,
)
from tests.channels.test_context_runtime_integration import (
    runtime_case as existing_runtime_case,
)
from tests.channels.test_context_trial import enable_trial

pytestmark = pytest.mark.unit
HELPER = "@helper:example.org"
REQUESTER = "@user:example.org"
OTHER = "@other:example.org"
HELPER_QUESTION = "How did you check whether the trade transaction was confirmed?"
SYMPTOM = "My trade is stuck after the payment period and mediation is unavailable."
ANSWER = "I checked the transaction in an explorer; it has six confirmations."


@pytest.fixture
async def conversation(tmp_path):
    async for bundle in existing_runtime_case.__wrapped__(tmp_path):
        await bundle.engine.close()
        enable_trial(bundle)
        try:
            yield bundle
        finally:
            await bundle.engine.close()


def authoritative_timeline(bundle, messages, *, mutate=None):
    """Return stable synthetic Matrix events, preserving every actual author."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 5000
    by_id = {message.message_id: index for index, message in enumerate(messages)}
    bundle.timeline_received = set()

    def event(index):
        entry = messages[index]
        metadata = entry.channel_metadata
        relation = {}
        if metadata.get("reply_to_event_id"):
            relation["m.in_reply_to"] = {"event_id": metadata["reply_to_event_id"]}
        if metadata.get("thread_root_event_id"):
            relation.update(
                rel_type="m.thread", event_id=metadata["thread_root_event_id"]
            )
        if metadata.get("replaces_event_id"):
            relation.update(
                rel_type="m.replace", event_id=metadata["replaces_event_id"]
            )
        content = {
            "body": entry.question,
            "msgtype": "m.text",
            "m.relates_to": relation,
        }
        if metadata.get("replaces_event_id"):
            content["m.new_content"] = {"body": entry.question, "msgtype": "m.text"}
        result = NS(
            event_id=entry.message_id,
            body=entry.question,
            sender=entry.user.user_id,
            server_timestamp=now_ms + index * 100,
            source={"content": content},
        )
        if mutate:
            mutate(result)
        return result

    async def read(room, event_id, **kwargs):
        assert room == SOURCE_ROOM
        index = by_id[event_id]
        return NS(
            event=event(index),
            events_before=[
                event(i)
                for i in reversed(range(index))
                if messages[i].message_id in bundle.timeline_received
            ],
            events_after=[
                event(i)
                for i in range(index + 1, len(messages))
                if messages[i].message_id in bundle.timeline_received
            ],
        )

    bundle.client.room_context.side_effect = read


def native_conversation(bundle):
    return [
        incoming(bundle, "$helper", HELPER_QUESTION, user=HELPER),
        incoming(bundle, "$symptom", SYMPTOM, reply_to_event_id="$helper"),
        incoming(
            bundle,
            "$answer",
            ANSWER,
            thread_root_event_id="$helper",
            reply_to_event_id="$helper",
        ),
        incoming(bundle, "$thanks", "Thanks"),
    ]


async def all_cases(bundle):
    rows, count = await bundle.repository.list_escalations(EscalationFilters())
    assert count == len(rows)
    return rows


def reservations(bundle):
    with closing(sqlite3.connect(bundle.repository.db_path)) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'matrix_context_trial_cases'"
        ).fetchone()
        if not exists:
            return 0
        return connection.execute(
            "SELECT COUNT(*) FROM matrix_context_trial_cases"
        ).fetchone()[0]


async def process_all(bundle, messages):
    for message in messages:
        bundle.timeline_received.add(message.message_id)
        assert await bundle.engine.process(message, bundle.channel) is False


def assert_no_paid_work(bundle):
    bundle.retrieve.assert_not_called()
    bundle.llm.invoke.assert_not_called()
    bundle.sender.assert_not_awaited()
    assert reservations(bundle) == 0
    no_public_delivery(bundle)


def assert_single_delivery(bundle, case):
    assert case.channel_metadata["context_status"] == "delivered"
    assert case.channel_metadata["conversation_membership"] == "confirmed"
    assert str(case.channel_metadata["conversation_id"]) == str(case.id)
    assert case.channel_metadata["conversation_requester_id"] == REQUESTER
    bundle.llm.invoke.assert_called_once()
    assert reservations(bundle) == 1
    assert bundle.sender.await_count == 2
    assert "thread_root_event_id" not in bundle.sender.await_args_list[0].kwargs
    assert (
        bundle.sender.await_args_list[1].kwargs["thread_root_event_id"] == "$staff-root"
    )
    assert case.channel_metadata["staff_root_event_id"] == "$staff-root"
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_native_helper_user_answer_and_plain_thanks_share_one_delivery(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = native_conversation(bundle)
    authoritative_timeline(bundle, messages)

    await process_all(bundle, messages[:1])
    provisional = await all_cases(bundle)
    assert len(provisional) == 1
    assert provisional[0].channel_metadata["conversation_membership"] == "provisional"
    assert_no_paid_work(bundle)
    await process_all(bundle, messages[1:])
    release.set()
    await bundle.engine.drain()

    cases = await all_cases(bundle)
    assert len(cases) == 1
    case = cases[0]
    assert case.id == provisional[0].id
    assert case.user_id == HELPER
    assert_single_delivery(bundle, case)
    saved = case.channel_metadata["incident_messages"]
    assert [message["event_id"] for message in saved] == [
        message.message_id for message in messages
    ]
    assert [message["sender_id"] for message in saved] == [
        HELPER,
        REQUESTER,
        REQUESTER,
        REQUESTER,
    ]
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert SYMPTOM in prompt["question"] and ANSWER in prompt["question"]
    assert HELPER_QUESTION not in prompt["question"]
    assert "Thanks" not in prompt["question"]
    helper = next(
        message
        for message in prompt["recent_messages"]
        if message["content"] == HELPER_QUESTION
    )
    assert helper["role"] == "participant"
    assert helper["speaker"].startswith("participant-")
    for message in prompt["recent_messages"]:
        if message["content"] in (SYMPTOM, ANSWER):
            assert message["role"] == "user" and message["speaker"] == "requester"
    assert HELPER not in json.dumps(prompt) and REQUESTER not in json.dumps(prompt)


@pytest.mark.asyncio
async def test_unique_full_quoted_question_joins_without_matrix_reply(conversation):
    bundle = conversation
    release = hold_worker(bundle)
    messages = [
        incoming(bundle, "$helper", HELPER_QUESTION, user=HELPER),
        incoming(
            bundle, "$answer", f'You asked "{HELPER_QUESTION}". {SYMPTOM} {ANSWER}'
        ),
        incoming(bundle, "$thanks", "Thanks"),
    ]
    assert all(
        not message.channel_metadata.get("reply_to_event_id") for message in messages
    )
    authoritative_timeline(bundle, messages)
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    assert_single_delivery(bundle, cases[0])
    assert {
        item["sender_id"] for item in cases[0].channel_metadata["incident_messages"]
    } == {
        HELPER,
        REQUESTER,
    }


@pytest.mark.asyncio
async def test_unknown_explicit_quoted_question_is_held_without_generation(
    conversation,
):
    bundle = conversation
    messages = [incoming(bundle, "$answer", f'You asked "{HELPER_QUESTION}". {ANSWER}')]
    authoritative_timeline(bundle, messages)
    await process_all(bundle, messages)
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    assert cases[0].channel_metadata["conversation_membership"] != "confirmed"
    assert cases[0].channel_metadata["context_reason"] == (
        "conversation_membership_unresolved"
    )
    assert not cases[0].channel_metadata.get("candidate_conversation_ids")
    assert_no_paid_work(bundle)


@pytest.mark.asyncio
async def test_duplicate_quoted_antecedents_are_candidates_not_membership(conversation):
    bundle = conversation
    messages = [
        incoming(bundle, "$helper-a", HELPER_QUESTION, user=HELPER),
        incoming(bundle, "$helper-b", HELPER_QUESTION, user=OTHER),
        incoming(bundle, "$answer", f'You asked "{HELPER_QUESTION}". {ANSWER}'),
    ]
    authoritative_timeline(bundle, messages)
    await process_all(bundle, messages)
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 3
    held = next(case for case in cases if case.user_id == REQUESTER)
    assert (
        held.channel_metadata["context_reason"] == "conversation_membership_unresolved"
    )
    assert held.channel_metadata["conversation_membership"] != "confirmed"
    helper_ids = {str(case.id) for case in cases if case.user_id in (HELPER, OTHER)}
    assert (
        set(map(str, held.channel_metadata["candidate_conversation_ids"])) == helper_ids
    )
    assert_no_paid_work(bundle)


@pytest.mark.asyncio
async def test_unthreaded_diagnostic_answer_is_held_without_inventing_membership(
    conversation,
):
    bundle = conversation
    messages = [
        incoming(bundle, "$helper", "Did you see PeerHandshakeMismatch?", user=HELPER),
        incoming(
            bundle, "$answer", "Yes, PeerHandshakeMismatch remains after the change."
        ),
    ]
    authoritative_timeline(bundle, messages)
    await process_all(bundle, messages)
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 2
    held = next(case for case in cases if case.user_id == REQUESTER)
    helper = next(case for case in cases if case.user_id == HELPER)
    assert (
        held.channel_metadata["context_reason"] == "conversation_membership_unresolved"
    )
    assert list(map(str, held.channel_metadata["candidate_conversation_ids"])) == [
        str(helper.id)
    ]
    assert_no_paid_work(bundle)


@pytest.mark.asyncio
async def test_two_independent_requesters_with_same_diagnostic_remain_separate(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = [
        incoming(
            bundle, "$one", "My client reports PeerHandshakeMismatch. How can I fix it?"
        ),
        incoming(
            bundle,
            "$two",
            "My client also reports PeerHandshakeMismatch. How do I fix my installation?",
            user=OTHER,
        ),
        incoming(
            bundle,
            "$two-update",
            "I tried restarting my client, but PeerHandshakeMismatch remains.",
            user=OTHER,
        ),
    ]
    authoritative_timeline(bundle, messages)
    bundle.sender.side_effect = lambda *args, **kwargs: SendResult(
        True, f"$staff-{bundle.sender.await_count}"
    )
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 2
    assert {case.user_id for case in cases} == {REQUESTER, OTHER}
    assert all(case.channel_metadata["context_status"] == "delivered" for case in cases)
    by_owner = {case.user_id: case for case in cases}
    assert len(by_owner[REQUESTER].channel_metadata["incident_messages"]) == 1
    assert [
        item["event_id"]
        for item in by_owner[OTHER].channel_metadata["incident_messages"]
    ] == [
        "$two",
        "$two-update",
    ]
    questions = [
        json.loads(call.args[0])["question"]
        for call in bundle.llm.invoke.call_args_list
    ]
    assert messages[0].question in questions
    other_question = next(
        question for question in questions if question != messages[0].question
    )
    assert (
        messages[1].question in other_question
        and messages[2].question in other_question
    )
    assert reservations(bundle) == 2
    assert bundle.sender.await_count == 4
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_interleaved_explicit_other_issue_does_not_join_native_conversation(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    shared = native_conversation(bundle)
    unrelated = incoming(
        bundle,
        "$other-issue",
        "Different issue: how can I restore my Bisq profile from a backup?",
        user=OTHER,
        reply_to_event_id="$helper",
    )
    messages = [*shared[:2], unrelated, *shared[2:]]
    authoritative_timeline(bundle, messages)
    bundle.sender.side_effect = lambda *args, **kwargs: SendResult(
        True, f"$staff-{bundle.sender.await_count}"
    )
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 2
    shared_case = next(
        case
        for case in cases
        if case.channel_metadata.get("conversation_requester_id") == REQUESTER
    )
    other_case = next(case for case in cases if case.user_id == OTHER)
    assert [
        item["event_id"] for item in shared_case.channel_metadata["incident_messages"]
    ] == [message.message_id for message in shared]
    assert [
        item["event_id"] for item in other_case.channel_metadata["incident_messages"]
    ] == ["$other-issue"]
    assert all(case.channel_metadata["context_status"] == "delivered" for case in cases)
    questions = [
        json.loads(call.args[0])["question"]
        for call in bundle.llm.invoke.call_args_list
    ]
    assert unrelated.question in questions
    shared_question = next(
        question for question in questions if question != unrelated.question
    )
    assert SYMPTOM in shared_question and ANSWER in shared_question
    assert "backup" not in shared_question
    assert reservations(bundle) == 2
    assert bundle.sender.await_count == 4
    no_public_delivery(bundle)


@pytest.mark.asyncio
async def test_helper_last_stays_attributed_context_with_requester_source_anchor(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = native_conversation(bundle)[:3]
    helper_last = incoming(
        bundle,
        "$helper-last",
        "I checked my own trade; its payment has not arrived yet.",
        user=HELPER,
        thread_root_event_id="$helper",
        reply_to_event_id="$answer",
    )
    messages.append(helper_last)
    authoritative_timeline(bundle, messages)
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    assert_single_delivery(bundle, cases[0])
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert SYMPTOM in prompt["question"] and ANSWER in prompt["question"]
    assert helper_last.question not in prompt["question"]
    last_context = next(
        item
        for item in prompt["recent_messages"]
        if item["content"] == helper_last.question
    )
    assert last_context["role"] == "participant"
    assert last_context["speaker"] != "requester"
    assert all(
        call.args[1] == "$answer" for call in bundle.client.room_context.await_args_list
    )


@pytest.mark.asyncio
async def test_requester_first_speaker_aliases_agree_in_prompt_admin_and_staff(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    neighbor = incoming(
        bundle,
        "$neighbor",
        "A separate participant is discussing offer prices.",
        user="@neighbor:example.org",
    )
    requester = incoming(bundle, "$symptom", SYMPTOM)
    helper_one = incoming(
        bundle,
        "$helper-one",
        "Have you checked the mediation menu?",
        user=HELPER,
        reply_to_event_id="$symptom",
    )
    helper_two = incoming(
        bundle,
        "$helper-two",
        "I checked my own trade; its payment has not arrived yet.",
        user=OTHER,
        thread_root_event_id="$symptom",
        reply_to_event_id="$helper-one",
    )
    authoritative_timeline(bundle, [neighbor, requester, helper_one, helper_two])
    # This event is visible in the room window but was never admitted as a member.
    bundle.timeline_received.add(neighbor.message_id)
    await process_all(bundle, [requester, helper_one, helper_two])
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    case = cases[0]
    assert_single_delivery(bundle, case)
    prompt = json.loads(bundle.llm.invoke.call_args.args[0])
    assert prompt["question"] == SYMPTOM
    staff_text = bundle.sender.await_args_list[0].args[0].replace("\\", "")
    aliases = []
    for helper in (helper_one, helper_two):
        context = next(
            item
            for item in prompt["recent_messages"]
            if item["content"] == helper.question
        )
        aliases.append(context["speaker"])
        attributed = f"{context['speaker']}: {helper.question}"
        assert attributed in case.question
        assert attributed in staff_text
        assert context["role"] == "participant"
    unrelated = next(
        item
        for item in prompt["recent_messages"]
        if item["content"] == neighbor.question
    )
    assert unrelated["speaker"] not in aliases
    assert neighbor.question not in case.question
    assert neighbor.question not in staff_text
    for identity in (REQUESTER, HELPER, OTHER, neighbor.user.user_id):
        assert identity not in json.dumps(prompt)
        assert identity not in case.question
        assert identity not in staff_text


@pytest.mark.asyncio
async def test_closed_provisional_helper_cannot_restart_on_native_answer(conversation):
    bundle = conversation
    messages = native_conversation(bundle)[:2]
    authoritative_timeline(bundle, messages)
    await process_all(bundle, messages[:1])
    provisional = (await all_cases(bundle))[0]
    await bundle.service.close_escalation(provisional.id)
    await process_all(bundle, messages[1:])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    original = next(case for case in cases if case.id == provisional.id)
    assert original.status == EscalationStatus.CLOSED
    assert original.channel_metadata.get("conversation_membership") != "confirmed"
    assert_no_paid_work(bundle)


@pytest.mark.asyncio
async def test_plain_thanks_after_delivery_does_not_request_meaningful_review(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = native_conversation(bundle)
    thanks = incoming(bundle, "$later-ack", "Thanks")
    authoritative_timeline(bundle, [*messages, thanks])
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    original = (await all_cases(bundle))[0]
    await process_all(bundle, [thanks])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    case = cases[0]
    assert_single_delivery(bundle, case)
    assert case.channel_metadata.get("incident_last_meaningful_at") == (
        original.channel_metadata.get("incident_last_meaningful_at")
    )
    assert case.channel_metadata.get("incident_late_update_status") == (
        original.channel_metadata.get("incident_late_update_status")
    )
    assert not case.channel_metadata.get("incident_late_meaningful_update")


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["body", "sender", "relation"])
async def test_every_members_source_text_and_author_are_rechecked(
    conversation, changed_field
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = native_conversation(bundle)

    def mutate(event):
        if event.event_id != "$helper":
            return
        if changed_field == "body":
            event.body = "How did you verify an unrelated payment instead?"
            event.source["content"]["body"] = event.body
        elif changed_field == "sender":
            event.sender = OTHER
        else:
            event.source["content"]["m.relates_to"] = {
                "m.in_reply_to": {"event_id": "$another-conversation"}
            }

    authoritative_timeline(bundle, messages, mutate=mutate)
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    assert cases[0].channel_metadata["context_status"] == "deferred"
    assert_no_paid_work(bundle)


@pytest.mark.asyncio
async def test_cross_author_edit_cannot_rewrite_member_or_trigger_another_delivery(
    conversation,
):
    bundle = conversation
    release = hold_worker(bundle)
    messages = native_conversation(bundle)
    hostile = incoming(
        bundle,
        "$hostile-edit",
        "My trade requires a completely different payment now.",
        user=HELPER,
        replaces_event_id="$symptom",
    )
    authoritative_timeline(bundle, [*messages, hostile])
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    original = (await all_cases(bundle))[0]
    assert_single_delivery(bundle, original)

    await bundle.engine.process(hostile, bundle.channel)
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    case = next(case for case in cases if case.id == original.id)
    saved = case.channel_metadata["incident_messages"]
    symptom = next(item for item in saved if item["event_id"] == "$symptom")
    assert symptom["text"] == SYMPTOM
    assert symptom["sender_id"] == REQUESTER
    assert not any(item["event_id"] == "$hostile-edit" for item in saved)
    assert_single_delivery(bundle, case)


@pytest.mark.asyncio
async def test_restart_late_member_update_and_plain_thanks_are_admin_only(conversation):
    bundle = conversation
    release = hold_worker(bundle)
    messages = native_conversation(bundle)
    late = incoming(
        bundle,
        "$late-helper",
        "The affected trade now shows the mediation option.",
        user=HELPER,
        reply_to_event_id="$symptom",
    )
    thanks = incoming(bundle, "$late-thanks", "Thanks again")
    authoritative_timeline(bundle, [*messages, late, thanks])
    await process_all(bundle, messages)
    release.set()
    await bundle.engine.drain()
    original = (await all_cases(bundle))[0]
    assert_single_delivery(bundle, original)
    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)

    await process_all(bundle, [late, late, thanks, thanks])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 1
    case = cases[0]
    assert case.id == original.id
    assert case.channel_metadata["incident_late_update_status"] == (
        "needs_review_no_additional_generation"
    )
    ids = [item["event_id"] for item in case.channel_metadata["incident_messages"]]
    assert ids.count("$late-helper") == ids.count("$late-thanks") == 1
    assert_single_delivery(bundle, case)
