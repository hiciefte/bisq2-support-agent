"""Matrix reply text must not become a second support question."""

from types import SimpleNamespace

import pytest
from app.channels.plugins.matrix.context_text import context_text, is_replacement

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "body,relation,expected",
    [
        (
            "> <@someone:example.org> Ask an arbitrator?\n> More quoted text\n\n2 times",
            {"m.in_reply_to": {"event_id": "$parent"}},
            "2 times",
        ),
        (
            "> Quoted error\n\nStill broken",
            {},
            "> Quoted error\n\nStill broken",
        ),
        (
            "> Not a reply\n\nStill broken",
            {"m.in_reply_to": {"event_id": 42}},
            "> Not a reply\n\nStill broken",
        ),
        (
            "> Original\n\nI still see this:\n> Actual new error",
            {"m.in_reply_to": {"event_id": "$parent"}},
            "I still see this:\n> Actual new error",
        ),
        (
            "> Original only\n\n",
            {"m.in_reply_to": {"event_id": "$parent"}},
            "",
        ),
        (
            "USD",
            {"m.in_reply_to": {"event_id": "$parent"}},
            "USD",
        ),
        (
            "> Original\n\nI already resynced five times.",
            {
                "rel_type": "m.thread",
                "event_id": "$root",
                "m.in_reply_to": {"event_id": "$previous"},
            },
            "I already resynced five times.",
        ),
        ("How do I back up?", [], "How do I back up?"),
    ],
)
def test_context_text_preserves_authored_reply(body, relation, expected):
    event = SimpleNamespace(body=body, source={"content": {"m.relates_to": relation}})
    assert context_text(event) == expected


def test_content_body_fallback_and_malformed_source():
    assert context_text(SimpleNamespace(source={"content": {"body": "Help"}})) == "Help"
    assert context_text(SimpleNamespace(body=None, source=[])) == ""
    assert not is_replacement(SimpleNamespace(source={"content": None}))


def test_edit_is_recognized_without_applying_unverified_replacement():
    event = SimpleNamespace(
        body="* Changed question",
        source={
            "content": {
                "m.relates_to": {"rel_type": "m.replace", "event_id": "$original"},
                "m.new_content": {"body": "Changed question"},
            }
        },
    )
    assert is_replacement(event)
