"""Synthetic helper turns through the runtime and durable conversation store."""

import json

import pytest
from app.channels.models import SendResult
from app.channels.staff_assist.context_runtime import MatrixContextRuntime

from tests.channels.test_context_conversations_acceptance import (
    HELPER,
    REQUESTER,
    all_cases,
    assert_no_paid_work,
    authoritative_timeline,
)
from tests.channels.test_context_conversations_acceptance import (
    conversation as existing_conversation,
)
from tests.channels.test_context_conversations_acceptance import (
    hold_worker,
    incoming,
    no_public_delivery,
    process_all,
    reservations,
)

pytestmark = pytest.mark.unit

QUESTION = "How do I check why my wallet shows WalletSyncError?"
HELP = "Check the wallet network panel for the WalletSyncError status."
ADVICE = [
    "If you restart the client, you may need to wait for the wallet to reconnect.",
    "Also check the wallet network panel before changing anything.",
    "The wallet network panel provides useful status details.",
    "I recommend checking the wallet network panel.",
    "In my experience you should check the wallet network panel first.",
    "Have you checked the wallet network panel?",
    "What I suggest is checking the wallet connection panel.",
    "How about checking the wallet connection panel?",
    "My recommendation is not to change the wallet settings.",
    "My recommendation is to restart the wallet if it is locked.",
    "Check the wallet connection panel. What does it show?",
    "Try restarting the wallet. Does the error persist?",
]
REQUESTS = [
    "My wallet now reports WalletSyncError.",
    "I cannot get my wallet to connect",
    "I need help with my wallet connection",
    "How do you check wallet status?",
    "Can you explain how the wallet status works?",
    "Why does my wallet keep disconnecting?",
    "Also can I check wallet status without restarting?",
    "What does WalletSyncError mean?",
    'My wallet fails with the message "you must reconnect".',
    "Restart failed and my wallet is locked. How can I recover?",
    "If you restore a backup, does it also restore the wallet settings?",
    "Could you please explain the wallet status?",
]


@pytest.fixture
async def conversation(tmp_path):
    async for bundle in existing_conversation.__wrapped__(tmp_path):
        yield bundle


def requester_and_helper(bundle):
    return [
        incoming(bundle, "$request", QUESTION),
        incoming(
            bundle, "$helper-answer", HELP, user=HELPER, reply_to_event_id="$request"
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ADVICE)
@pytest.mark.parametrize("helper_after_freeze", [False, True])
async def test_known_helper_unthreaded_advice_is_held_without_a_second_attempt(
    conversation, text, helper_after_freeze
):
    bundle = conversation
    release = hold_worker(bundle)
    initial = requester_and_helper(bundle)
    advice = incoming(bundle, "$advice", text, user=HELPER)
    authoritative_timeline(bundle, [*initial, advice])
    await process_all(bundle, initial[:1] if helper_after_freeze else initial)
    release.set()
    await bundle.engine.drain()
    if helper_after_freeze:
        await process_all(bundle, initial[1:])
    original = (await all_cases(bundle))[0]
    frozen = original.channel_metadata["incident_generation_event_ids"]
    assert frozen == (
        ["$request"] if helper_after_freeze else ["$request", "$helper-answer"]
    )

    await bundle.engine.close()
    bundle.engine = MatrixContextRuntime(bundle.runtime)
    await process_all(bundle, [advice, advice])
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 2
    held = next(case for case in cases if case.id != original.id)
    retained = next(case for case in cases if case.id == original.id)
    assert held.channel_metadata["conversation_membership"] == "provisional"
    assert (
        held.channel_metadata["context_reason"] == "conversation_membership_unresolved"
    )
    assert held.channel_metadata["candidate_conversation_ids"] == [original.id]
    assert not held.channel_metadata.get("conversation_requester_id")
    assert not held.channel_metadata["model_called"]
    assert not held.channel_metadata.get("staff_root_event_id")
    assert retained.channel_metadata["conversation_requester_id"] == REQUESTER
    assert retained.channel_metadata["incident_generation_event_ids"] == frozen
    assert len(retained.channel_metadata["incident_messages"]) == 2
    assert held.id in retained.channel_metadata["conversation_pending_candidate_ids"]
    assert reservations(bundle) == 1
    bundle.llm.invoke.assert_called_once()
    assert bundle.sender.await_count == 2
    no_public_delivery(bundle)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", REQUESTS)
async def test_previous_helper_can_start_an_independent_request(conversation, text):
    bundle = conversation
    release = hold_worker(bundle)
    initial = requester_and_helper(bundle)
    request = incoming(bundle, "$own-request", text, user=HELPER)
    authoritative_timeline(bundle, [*initial, request])
    bundle.sender.side_effect = lambda *args, **kwargs: SendResult(
        True, f"$staff-{bundle.sender.await_count}"
    )
    await process_all(bundle, [*initial, request])
    release.set()
    await bundle.engine.drain()
    cases = await all_cases(bundle)
    assert len(cases) == 2
    own = next(case for case in cases if case.user_id == HELPER)
    original = next(case for case in cases if case.user_id == REQUESTER)
    assert own.channel_metadata["conversation_requester_id"] == HELPER
    assert own.channel_metadata["conversation_membership"] == "confirmed"
    assert not own.channel_metadata.get("candidate_conversation_ids")
    assert own.channel_metadata["context_status"] == "delivered"
    assert len(original.channel_metadata["incident_messages"]) == 2
    assert len(own.channel_metadata["incident_messages"]) == 1
    prompts = [json.loads(call.args[0]) for call in bundle.llm.invoke.call_args_list]
    own_prompt = next(prompt for prompt in prompts if prompt["question"] == text)
    assert QUESTION not in own_prompt["question"]
    assert reservations(bundle) == 2
    assert bundle.llm.invoke.call_count == 2
    assert bundle.sender.await_count == 4
    no_public_delivery(bundle)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        ADVICE[0],
        "You should check the wallet network panel.",
        "Try restarting the client before checking the wallet status.",
        "I recommend you inspect the network panel.",
        "In my experience you can wait for the wallet to reconnect.",
    ],
)
async def test_obvious_advice_before_membership_is_held_without_inventing_candidates(
    conversation, text
):
    bundle = conversation
    advice = incoming(bundle, "$early-advice", text, user=HELPER)
    initial = requester_and_helper(bundle)
    authoritative_timeline(bundle, [advice, *initial])
    await process_all(bundle, [advice])
    await bundle.engine.drain()
    held = (await all_cases(bundle))[0]
    assert held.channel_metadata["conversation_membership"] == "provisional"
    assert held.channel_metadata["context_reason"] == "conversation_helper_only"
    assert not held.channel_metadata.get("candidate_conversation_ids")
    assert_no_paid_work(bundle)

    release = hold_worker(bundle)
    await process_all(bundle, initial)
    release.set()
    await bundle.engine.drain()
    before = await bundle.repository.get_by_id(held.id)
    await process_all(bundle, [advice])
    await bundle.engine.drain()
    after = await bundle.repository.get_by_id(held.id)
    assert after.channel_metadata == before.channel_metadata
    assert not after.channel_metadata.get("conversation_requester_id")
    assert reservations(bundle) == 1
    bundle.llm.invoke.assert_called_once()
    no_public_delivery(bundle)
