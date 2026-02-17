"""Tests for escalation rating token signing and verification."""

import time

from app.services.escalation.rating_token import (
    generate_rating_token,
    verify_rating_token,
)


def test_generate_and_verify_rating_token_roundtrip() -> None:
    token = generate_rating_token(
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
        ttl_seconds=60,
    )

    payload = verify_rating_token(
        token=token,
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
    )

    assert payload is not None
    assert payload.message_id == "msg-1"
    assert payload.rater_id == "user-1"
    assert payload.purpose == "staff_rating"
    assert payload.exp > int(time.time())


def test_verify_rating_token_rejects_message_mismatch() -> None:
    token = generate_rating_token(
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
        ttl_seconds=60,
    )

    payload = verify_rating_token(
        token=token,
        message_id="msg-2",
        rater_id="user-1",
        signing_key="secret",
    )

    assert payload is None


def test_verify_rating_token_rejects_rater_mismatch() -> None:
    token = generate_rating_token(
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
        ttl_seconds=60,
    )

    payload = verify_rating_token(
        token=token,
        message_id="msg-1",
        rater_id="user-2",
        signing_key="secret",
    )

    assert payload is None


def test_verify_rating_token_rejects_tampered_signature() -> None:
    token = generate_rating_token(
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
        ttl_seconds=60,
    )

    payload = verify_rating_token(
        token=token,
        message_id="msg-1",
        rater_id="user-1",
        signing_key="wrong",
    )

    assert payload is None


def test_verify_rating_token_rejects_expired() -> None:
    token = generate_rating_token(
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
        ttl_seconds=0,
    )

    payload = verify_rating_token(
        token=token,
        message_id="msg-1",
        rater_id="user-1",
        signing_key="secret",
    )

    assert payload is None
