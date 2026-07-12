"""Focused tests for deterministic runtime support-policy behavior."""

import pytest
from app.prompts.runtime_policy import should_apply_safety_reflex


@pytest.mark.parametrize(
    "question",
    [
        "I received an unexpected private message from someone claiming to be support.",
        "I got a DM offering help after posting my problem.",
        "Is this a scam?",
        "Could this be phishing?",
        "Is someone impersonating support?",
        "I received a direct message from support.",
        "A support agent sent me a DM after I posted my trade issue.",
        "Someone contacted me and offered support with my stuck trade.",
        "Someone offered to help me with my trade.",
        "An external app is asking me to enter my seed words.",
        "They asked me to send my private key.",
        "I was asked to enter my recovery phrase.",
        "A stranger asked for my seed phrase.",
        "This user asked for my mnemonic.",
        "This website requests my wallet data.",
        "A support agent asked me for my seed.",
        "This website asks me to enter my seed.",
    ],
)
def test_suspicious_contact_or_wallet_request_requires_safety_reflex(
    question: str,
) -> None:
    assert should_apply_safety_reflex(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "How do I back up my Bisq wallet seed words?",
        "Where do I restore my own wallet from a seed phrase?",
        "What is a private key?",
        "Can someone help me understand account signing?",
        "I sent support a DM using the verified room link.",
        "The Bisq app asks me to enter my seed words to restore my own wallet.",
        "How do I restore my own Bisq wallet from seed?",
    ],
)
def test_ordinary_seed_setup_or_user_initiated_help_does_not_trigger(
    question: str,
) -> None:
    assert should_apply_safety_reflex(question) is False
