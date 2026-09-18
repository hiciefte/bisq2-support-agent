"""Real read-only draft lookups and strict deployment-smoke outcomes."""

import copy
import hashlib
import json
import sqlite3

import pytest
from app.channels.escalation_localization import render_escalation_notice
from app.scripts.validate_deployment_chat import SmokeFailure, validate_response

QUESTION = "In Bisq 2, how do I buy bitcoin with Bisq Easy?"
SESSION = "fresh-smoke-session"
MESSAGE = "web_12345678-1234-4234-8234-123456789012"
SOURCE = {
    "title": "Bisq Easy",
    "type": "wiki",
    "content": "Choose a seller in Bisq Easy.",
}
DRAFT = "In Bisq Easy, choose a suitable seller and follow the trade instructions to buy bitcoin."


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "escalations.db"
    with sqlite3.connect(path) as con:
        con.execute(
            """CREATE TABLE escalations (id INTEGER, message_id TEXT, channel TEXT,
            question_original TEXT, question TEXT, user_id TEXT, ai_draft_answer_original TEXT,
            user_language TEXT, sources TEXT, routing_action TEXT)"""
        )
        con.execute(
            "INSERT INTO escalations VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                7,
                MESSAGE,
                "web",
                QUESTION,
                QUESTION,
                "user_" + hashlib.sha256(SESSION.encode()).hexdigest()[:24],
                DRAFT,
                "en",
                json.dumps([SOURCE]),
                "needs_human",
            ),
        )
    return path


def direct():
    return {
        "answer": DRAFT,
        "sources": [SOURCE],
        "response_time": 1.5,
        "requires_human": False,
        "routing_action": "auto_send",
        "message_id": MESSAGE,
    }


def reviewed():
    return {
        **direct(),
        "requires_human": True,
        "routing_action": "needs_human",
        "escalation_message_id": MESSAGE,
        "answer": render_escalation_notice(
            channel_id="web",
            escalation_id=7,
            support_handle="support",
            language_code="en",
        ),
    }


def check(body, database, **kwargs):
    return validate_response(
        body,
        status=kwargs.pop("status", 200),
        question=QUESTION,
        session=SESSION,
        db_path=database,
        **kwargs,
    )


def test_direct_and_exact_review_draft_are_valid(database):
    assert check(direct(), database) == "direct_answer_verified"
    before = database.read_bytes()
    assert check(reviewed(), database) == "review_draft_verified"
    assert database.read_bytes() == before


@pytest.mark.parametrize(
    "column,value,code",
    [
        ("question_original", "different question", "review_question_mismatch"),
        ("user_id", "different-user", "review_session_mismatch"),
        ("ai_draft_answer_original", "", "review_draft_empty"),
        ("sources", "[]", "source_evidence_missing"),
        ("routing_action", "auto_send", "review_stored_routing_mismatch"),
    ],
)
def test_review_requires_exact_persisted_evidence(database, column, value, code):
    with sqlite3.connect(database) as con:
        con.execute(f"UPDATE escalations SET {column}=?", (value,))
    with pytest.raises(SmokeFailure, match=code):
        check(reviewed(), database)


def test_missing_review_row_and_wrong_notice_fail(database):
    body = reviewed()
    body["answer"] = "This is a different queued review notice."
    with pytest.raises(SmokeFailure, match="review_notice_mismatch"):
        check(body, database)
    with sqlite3.connect(database) as con:
        con.execute("DELETE FROM escalations")
    with pytest.raises(SmokeFailure, match="review_draft_missing"):
        check(reviewed(), database)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("escalation_message_id", "wrong", "review_message_mismatch"),
        ("message_id", "not-a-web-message", "review_message_id"),
        ("requires_human", False, "review_routing"),
    ],
)
def test_review_response_identity_is_not_optional(database, field, value, code):
    body = reviewed()
    body[field] = value
    with pytest.raises(SmokeFailure, match=code):
        check(body, database)


@pytest.mark.parametrize(
    "body,code",
    [
        ({**direct(), "answer": ""}, "answer_missing"),
        ({**direct(), "sources": []}, "source_evidence_missing"),
        ({**direct(), "response_time": "slow"}, "response_time_schema"),
        ({**direct(), "requires_human": "false"}, "routing_schema"),
        ({**direct(), "routing_action": "needs_clarification"}, "direct_routing"),
    ],
)
def test_direct_schema_and_content_requirements(database, body, code):
    with pytest.raises(SmokeFailure, match=code):
        check(body, database)


@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_http_failure_never_passes_even_with_valid_body(database, status):
    with pytest.raises(SmokeFailure, match="http_status"):
        check(direct(), database, status=status)


@pytest.mark.parametrize("body", [direct(), reviewed()])
def test_live_requires_actual_successful_tool_metadata(database, body):
    body = copy.deepcopy(body)
    with pytest.raises(SmokeFailure, match="tool_metadata_missing"):
        check(body, database, live=True)
    body["mcp_tools_used"] = [
        {
            "tool": "get_market_prices",
            "result": "[Live Price Data Unavailable: timeout]",
        }
    ]
    with pytest.raises(SmokeFailure, match="successful_live_tool_missing"):
        check(body, database, live=True)
    body["mcp_tools_used"][0]["result"] = "[LIVE MARKET PRICES]\nBTC/EUR: 50,000.00"
    assert check(body, database, live=True).endswith("verified")
