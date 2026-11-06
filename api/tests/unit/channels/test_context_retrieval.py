"""Offline retrieval-query regressions using synthetic conversation text."""

import pytest
from app.channels.staff_assist.context_retrieval import (
    MAX_RETRIEVAL_CONTEXT_MESSAGES,
    MAX_RETRIEVAL_QUERY_CHARS,
    build_retrieval_query,
)
from app.channels.staff_assist.public_context import RoomMessage
from app.services.rag.code_evidence import explicit_product, explicit_user_version

pytestmark = pytest.mark.unit


def requester(content: str) -> RoomMessage:
    return RoomMessage(role="user", speaker="requester", content=content)


def test_confirmed_diagnostic_reaches_query_with_focal_conditions_intact():
    question = "If my payout is still pending tomorrow, should I retry in Bisq 1?"
    diagnostic = "My wallet reports SyntheticPayoutException only after reconnecting."

    query = build_retrieval_query(question, [requester(diagnostic)])

    assert query.startswith(question)
    assert diagnostic in query
    assert explicit_product(query) == "bisq1"


def test_no_confirmed_context_keeps_only_focal_question():
    question = "Why is my wallet still synchronizing?"

    assert build_retrieval_query(question) == question


@pytest.mark.parametrize(
    "message",
    [
        RoomMessage(
            role="staff",
            speaker="participant-1",
            content="Perhaps Bisq 2 version 2.5.0 has SyntheticHelperException.",
        ),
        RoomMessage(
            role="participant",
            speaker="participant-2",
            content="My Bisq 2 version 2.5.0 has SyntheticOtherException.",
        ),
        RoomMessage(role="assistant", content="SyntheticBotException explains it."),
        RoomMessage(
            role="user", content="My wallet has SyntheticUnattributedException."
        ),
    ],
)
def test_other_speakers_and_unattributed_turns_cannot_supply_requester_facts(message):
    question = "Why does my Bisq 1 wallet stop?"

    assert build_retrieval_query(question, [message]) == question


@pytest.mark.parametrize(
    "content",
    [
        "You should try restarting Bisq 1 for SyntheticHelperException.",
        "I have a separate issue with my Bisq 1 wallet: SyntheticOtherException.",
        "Thanks!",
    ],
)
def test_helper_or_separate_issue_wording_is_not_added_as_requester_context(content):
    question = "Why does my Bisq 1 wallet stop?"

    assert build_retrieval_query(question, [requester(content)]) == question


@pytest.mark.parametrize(
    ("question", "content"),
    [
        ("Why does Bisq 1 stop?", "My Bisq 2 reports SyntheticOtherException."),
        ("Why does Bisq 2 stop?", "Bisq 1 and Bisq 2 report SyntheticOtherException."),
        ("Does Bisq 1 or Bisq 2 support this?", "My Bisq 1 reports SyntheticError."),
        (
            "Why does Bisq 2 version 2.5.0 stop?",
            "I am running version 2.6.0 with SyntheticOtherException.",
        ),
        (
            "Does version 2.5.0 or version 2.6.0 support this?",
            "I am running version 2.5.0 with SyntheticError.",
        ),
    ],
)
def test_conflicting_or_ambiguous_focal_scope_is_not_overridden(question, content):
    assert build_retrieval_query(question, [requester(content)]) == question


@pytest.mark.parametrize(
    "context",
    [
        ["My Bisq 1 has SyntheticFirstError.", "My Bisq 2 has SyntheticSecondError."],
        [
            "I am running version 2.5.0 with SyntheticFirstError.",
            "I am running version 2.6.0 with SyntheticSecondError.",
        ],
    ],
)
def test_conflicting_context_without_focal_scope_is_order_independent(context):
    question = "Why does my wallet stop?"

    for texts in (context, list(reversed(context))):
        assert build_retrieval_query(question, list(map(requester, texts))) == question


def test_confirmed_requester_can_supply_previously_missing_product_and_version():
    query = build_retrieval_query(
        "Why does my wallet stop?",
        [requester("My Bisq 2 version 2.5.0 reports SyntheticWalletException.")],
    )

    assert explicit_product(query) == "bisq2"
    assert explicit_user_version(query) == "2.5.0"
    assert "SyntheticWalletException" in query


def test_exact_frozen_turns_are_deduplicated_without_dropping_negation():
    first = "My wallet reports SyntheticWalletException."
    second = "Should I reconnect only if it happens again?"
    correction = (
        "My wallet does not report SyntheticWalletException after reconnecting."
    )
    query = build_retrieval_query(
        first + "\n---\n" + second,
        [
            requester(first),
            requester(second),
            requester(correction),
            requester(correction),
        ],
    )

    assert query.count(first) == 1
    assert query.count(second) == 1
    assert query.count(correction) == 1


def test_query_redacts_known_identifiers_and_secrets_without_losing_diagnostic():
    query = build_retrieval_query(
        "Why does my wallet fail for synthetic@example.invalid?",
        [
            requester(
                "My log shows SyntheticWalletException at 192.0.2.44; "
                "trade 11111111-2222-3333-4444-555555555555; "
                "token=synthetic-secret-value; please ask @synthetic."
            )
        ],
    )

    assert "SyntheticWalletException" in query
    assert "synthetic@example.invalid" not in query
    assert "192.0.2.44" not in query
    assert "11111111-2222-3333-4444-555555555555" not in query
    assert "synthetic-secret-value" not in query
    assert "@" not in query
    assert "[REDACTED]" in query


@pytest.mark.parametrize("as_context", [False, True])
@pytest.mark.parametrize(
    "question",
    [
        "How do I back up my seed phrase?",
        "What is the BSQ token?",
        "How do I change my wallet password?",
        "Where is my private key stored?",
        "What does mnemonic mean in the wallet backup instructions?",
        "Is a wallet seed the same as a seed phrase?",
        "My password is incorrect.",
        "My password is not accepted.",
        "My password is incorrect only after reconnecting.",
        "My seed phrase length is not recognized.",
        "My token is missing.",
    ],
)
def test_safe_credential_and_token_topics_are_preserved(question, as_context):
    if as_context:
        query = build_retrieval_query("Why does my wallet fail?", [requester(question)])
        assert question in query
        assert "[REDACTED]" not in query
    else:
        assert build_retrieval_query(question) == question


def test_actual_secret_value_is_redacted_without_losing_credential_topic():
    query = build_retrieval_query(
        "Why is my token=synthetic-secret-value rejected?",
        [
            requester(
                "My log contains skSyntheticSecretToken and SyntheticAuthException."
            )
        ],
    )

    assert query.startswith("Why is my token=[REDACTED] rejected?")
    assert "synthetic-secret-value" not in query
    assert "skSyntheticSecretToken" not in query
    assert "SyntheticAuthException" in query


@pytest.mark.parametrize("as_context", [False, True])
@pytest.mark.parametrize(
    ("text", "label", "secret_values"),
    [
        ("password=xy", "password", ["xy"]),
        (
            "My password is synthetic cedar violet amber",
            "password",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        (
            "password: synthetic cedar violet amber",
            "password",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        (
            "private key=synthetic.cedar violet amber",
            "private key",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        (
            "My seed phrase is synthetic cedar\nviolet amber",
            "seed phrase",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        ('password="synthetic quoted value"', "password", ["synthetic quoted value"]),
        ("private key: synthetic-key-value", "private key", ["synthetic-key-value"]),
        (
            "access_token=synthetic-token-value",
            "access_token",
            ["synthetic-token-value"],
        ),
        (
            "mnemonic: synthetic cedar violet amber",
            "mnemonic",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        (
            "seed phrase: synthetic cedar\nviolet amber",
            "seed phrase",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        (
            'wallet seed="synthetic cedar\nviolet amber"',
            "wallet seed",
            ["synthetic", "cedar", "violet", "amber"],
        ),
        ('password="synthetic unclosed value', "password", ["synthetic", "unclosed"]),
    ],
)
def test_complete_credential_values_are_redacted_in_focal_and_context(
    as_context, text, label, secret_values
):
    question = "Why does SyntheticAuthException occur?"
    query = (
        build_retrieval_query(question, [requester(text)])
        if as_context
        else build_retrieval_query(question + " " + text)
    )

    assert "SyntheticAuthException" in query
    assert label in query
    assert "[REDACTED]" in query
    assert all(value not in query for value in secret_values)


def test_known_matrix_credential_identifier_is_redacted_without_assignment():
    query = build_retrieval_query(
        "SyntheticAuthException appears beside syt_syntheticSessionValue."
    )

    assert "SyntheticAuthException" in query
    assert "syt_syntheticSessionValue" not in query
    assert "[REDACTED]" in query


def test_multiword_assignment_preserves_explicit_diagnostic_question_conditions():
    query = build_retrieval_query(
        "Why is my password: synthetic cedar violet amber "
        "not accepted only after reconnecting?"
    )

    assert (
        query == "Why is my password: [REDACTED] not accepted only after reconnecting?"
    )


@pytest.mark.parametrize("secret", ["password=xy", "password=x", "token=y"])
def test_redaction_expansion_cannot_reject_a_valid_length_focal_question(secret):
    suffix = " only when offline?"
    prefix = "Why does my wallet stop? "
    question = (
        prefix
        + "x" * (MAX_RETRIEVAL_QUERY_CHARS - len(prefix + " " + secret + "." + suffix))
        + " "
        + secret
        + "."
        + suffix
    )
    assert len(question) == MAX_RETRIEVAL_QUERY_CHARS

    query = build_retrieval_query(question, [requester("SyntheticExtraDiagnostic")])

    assert len(query) <= MAX_RETRIEVAL_QUERY_CHARS
    assert secret not in query
    assert query.startswith(prefix)
    assert query.endswith("." + suffix)
    assert secret.partition("=")[0] + "=*" in query
    assert "SyntheticExtraDiagnostic" not in query


def test_character_bound_retains_focal_request_and_complete_context_conditions():
    question = "Why does my wallet stop? " + "x" * 3800
    too_large = "SyntheticLargeException " + "y" * 300 + " only when offline."
    small = "SyntheticSmallException occurs only when offline."

    query = build_retrieval_query(question, [requester(too_large), requester(small)])

    assert len(query) <= MAX_RETRIEVAL_QUERY_CHARS
    assert query.startswith(question)
    assert "SyntheticLargeException" not in query
    assert small in query


def test_context_count_is_bounded():
    messages = [
        requester(f"My wallet reports SyntheticFailure{index} only when offline.")
        for index in range(MAX_RETRIEVAL_CONTEXT_MESSAGES + 1)
    ]

    query = build_retrieval_query("Why does my wallet stop?", messages)

    assert query.count("only when offline.") == MAX_RETRIEVAL_CONTEXT_MESSAGES
    assert "SyntheticFailure10" not in query


def test_full_focal_request_is_never_truncated_to_make_room_for_context():
    question = "x" * MAX_RETRIEVAL_QUERY_CHARS

    assert (
        build_retrieval_query(question, [requester("SyntheticWalletException")])
        == question
    )
    with pytest.raises(ValueError, match="complete focal query"):
        build_retrieval_query(question + "x")
