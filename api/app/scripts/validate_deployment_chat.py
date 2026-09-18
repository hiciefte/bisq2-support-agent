"""Validate one ordinary deployment chat response without exposing private text."""

import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from app.channels.constants import REVIEW_QUEUE_ACTIONS
from app.channels.escalation_localization import render_escalation_notice
from app.channels.response_dispatcher import preserve_static_safety_warning


class SmokeFailure(ValueError):
    """A controlled failure code suitable for an operator log."""


def require(value: bool, code: str) -> None:
    if not value:
        raise SmokeFailure(code)


def has_sources(sources: object) -> bool:
    return (
        isinstance(sources, list)
        and bool(sources)
        and any(
            isinstance(source, dict)
            and isinstance(source.get("content"), str)
            and bool(source["content"].strip())
            for source in sources
        )
    )


def validate_response(
    response: dict,
    *,
    status: int,
    question: str,
    session: str,
    db_path: Path,
    live: bool = False,
    signals: tuple[str, ...] = ("bisq", "bitcoin|btc", "buy|purchase|seller|trade"),
) -> str:
    require(200 <= status < 300, "http_status")
    require(isinstance(response, dict), "response_schema")
    answer = response.get("answer")
    require(isinstance(answer, str) and bool(answer.strip()), "answer_missing")
    require(isinstance(response.get("sources"), list), "sources_schema")
    duration = response.get("response_time")
    require(
        type(duration) in (int, float) and math.isfinite(duration) and duration >= 0,
        "response_time_schema",
    )
    require(type(response.get("requires_human")) is bool, "routing_schema")
    routing = response.get("routing_action")
    review = response["requires_human"] or routing in REVIEW_QUEUE_ACTIONS
    sources = response["sources"]
    if review:
        require(
            response["requires_human"] and routing in REVIEW_QUEUE_ACTIONS,
            "review_routing",
        )
        message = response.get("message_id")
        require(
            isinstance(message, str)
            and re.fullmatch(
                r"web_[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                message,
            )
            is not None,
            "review_message_id",
        )
        require(
            response.get("escalation_message_id") == message, "review_message_mismatch"
        )
        with closing(
            sqlite3.connect(
                db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
            )
        ) as con:
            con.execute("PRAGMA query_only=ON")
            row = con.execute(
                """SELECT id, question_original, question, user_id,
                ai_draft_answer_original, user_language, sources, routing_action
                FROM escalations WHERE message_id=? AND channel='web'""",
                (message,),
            ).fetchone()
        require(row is not None, "review_draft_missing")
        (
            escalation_id,
            original_question,
            canonical_question,
            user,
            draft,
            language,
            stored_sources,
            stored_routing,
        ) = row
        require(
            (original_question or canonical_question) == question,
            "review_question_mismatch",
        )
        expected_user = (
            "user_" + hashlib.sha256(session.strip().encode()).hexdigest()[:24]
        )
        require(user == expected_user, "review_session_mismatch")
        require(stored_routing == routing, "review_stored_routing_mismatch")
        require(
            isinstance(draft, str) and 20 < len(draft.strip()) <= 10000,
            "review_draft_empty",
        )
        notice = render_escalation_notice(
            channel_id="web",
            escalation_id=escalation_id,
            support_handle="support",
            language_code=language,
        )
        require(
            answer.strip() == preserve_static_safety_warning(draft, notice).strip(),
            "review_notice_mismatch",
        )
        answer = draft
        sources = json.loads(stored_sources or "null")
    else:
        require(routing == "auto_send", "direct_routing")
    require(len(answer.strip()) > 20, "answer_not_substantive")
    require(has_sources(sources), "source_evidence_missing")
    if live:
        tools = response.get("mcp_tools_used")
        require(isinstance(tools, list), "tool_metadata_missing")
        valid = False
        for tool in tools:
            if not isinstance(tool, dict) or tool.get("tool") not in (
                "get_market_prices",
                "get_offerbook",
            ):
                continue
            result = tool.get("result")
            if (
                isinstance(result, str)
                and result.strip()
                and not re.search(
                    r"unavailable|^\s*error|timed?\s*out", result, re.IGNORECASE
                )
            ):
                valid = True
        require(valid, "successful_live_tool_missing")
    else:
        require(
            any(re.search(pattern, answer, re.IGNORECASE) for pattern in signals),
            "answer_content_weak",
        )
    return "review_draft_verified" if review else "direct_answer_verified"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", type=int, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--signal", action="append")
    args = parser.parse_args()
    try:
        from app.core.config import get_settings

        result = validate_response(
            json.load(sys.stdin),
            status=args.status,
            question=args.question,
            session=args.session,
            db_path=Path(get_settings().DATA_DIR) / "escalations.db",
            live=args.live,
            signals=(
                tuple(args.signal)
                if args.signal
                else ("bisq", "bitcoin|btc", "buy|purchase|seller|trade")
            ),
        )
        print("chat_smoke=" + result)
        return 0
    except SmokeFailure as exc:
        print("chat_smoke=" + str(exc))
    except Exception:
        print("chat_smoke=validation_failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
