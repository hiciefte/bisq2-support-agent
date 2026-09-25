"""Bounded incident membership stored with the existing private Admin case.

No additional conversation archive or model classifier: same-owner Matrix
relations are authoritative; a small continuation rule covers split messages.
The existing escalation retention also removes these sanitized snapshots.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from app.channels.arbitration.coordinator import accumulate_question
from app.services.rag.code_evidence import explicit_product, explicit_user_version


def context_only(text: str) -> bool:
    text = text.strip().lower().rstrip(".! ")
    if re.search(r"\b(?:error|fails?|failed|cannot|locked)\b|can['’]t|not work", text):
        return False
    return bool(
        re.fullmatch(
            r"(?:ok(?:ay)?|thanks?(?: you)?|thank you|thx|yes|no|great|\d+\s*(?:times?)?)",
            text,
        )
        or re.fullmatch(
            r"i (?:can|could) (?:also )?(?:provide|send|share|upload) "
            r"(?:the |a |my )?(?:chat )?(?:logs?|screenshots?)"
            r"(?: (?:if (?:helpful|needed|you want(?: them)?)|(?:to|with) (?:you|staff|support)))?",
            text,
        )
        or re.fullmatch(
            r"how many times did you (?:resync|restart|update|try|rebuild)"
            r"(?: (?:it|that|bisq|spv|the (?:wallet|app|spv file|dao)))?\??",
            text,
        )
        or text == "i hope you did not discover another exploit"
    )


def new_issue(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:another|different|new|unrelated|separate) (?:issue|question|problem|trade)\b",
            text,
            re.I,
        )
    )


def continuation(text: str, previous: str) -> bool:
    """Require an explicit continuation plus diagnostic subject, never time alone."""
    if new_issue(text) or "?" in text:
        return False
    previous_product, current_product = explicit_product(previous), explicit_product(
        text
    )
    if current_product is not None and current_product != previous_product:
        return False
    previous_version, current_version = explicit_user_version(
        previous
    ), explicit_user_version(text)
    if previous_version and current_version and previous_version != current_version:
        return False
    if context_only(text):
        return True
    if not re.match(
        r"(?:and\b|also\b|i (?:already|still|also|tried|have tried)\b|it (?:still|also)\b|same\b)",
        text,
        re.I,
    ):
        return False
    # Product-independent topic anchors keep unrelated profile/network/offer
    # incidents separate from an existing trade-wallet investigation.
    groups = (
        {"trade", "wallet", "deposit", "payout", "balance", "mediation", "spv", "dao"},
        {"profile", "notification", "notifications", "identity"},
        {"tor", "connection", "connectivity", "bootstrap", "node"},
        {"offer", "offers", "price", "reputation"},
    )
    words, old_words = set(re.findall(r"[a-z]+", text.lower())), set(
        re.findall(r"[a-z]+", previous.lower())
    )
    topics = {index for index, group in enumerate(groups) if words & group}
    old_topics = {index for index, group in enumerate(groups) if old_words & group}
    if topics and old_topics and not topics & old_topics:
        return False
    # Recovery attempts after a trade-wallet failure include the actual SPV
    # follow-up without requiring it to repeat the payout exception verbatim.
    if (
        re.search(r"\b(?:updated?|resync\w*|rebuild\w*|restart\w*|spv)\b", text, re.I)
        and 0 in old_topics
        and topics <= {0}
    ):
        return True
    if (words & old_words) & set().union(*groups):
        return True
    # A repeated exact exception/symbol is a diagnostic link, ordinary shared
    # vocabulary is not. No model is used to infer missing relationships.
    symbols = set(re.findall(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b", text))
    return any(symbol in previous for symbol in symbols)


def incident_texts(messages: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    positions: dict[str, int] = {}
    for message in messages:
        replacement = message.get("replaces_event_id")
        if replacement in positions:
            texts[positions[replacement]] = message["text"]
            positions[message["event_id"]] = positions[replacement]
        else:
            positions[message["event_id"]] = len(texts)
            texts.append(message["text"])
    return texts


def incident_question(messages: list[dict[str, Any]]) -> str:
    return accumulate_question(incident_texts(messages), max_chars=4000)


class ContextIncidentStore:
    """Scope every association to the same source room, author and trial."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def find(
        self, incoming: Any, trial_id: str | None
    ) -> tuple[int | None, bool]:
        metadata = incoming.channel_metadata
        # An edit target or native thread root wins over its reply fallback.
        # A fallback pointing elsewhere must not move an established thread.
        target = (
            metadata.get("replaces_event_id")
            or metadata.get("thread_root_event_id")
            or metadata.get("reply_to_event_id")
        )
        relations = {target} if target else set()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, channel_metadata, question, created_at, status FROM escalations "
                "WHERE channel='matrix' AND user_id=? ORDER BY id DESC LIMIT 100",
                (incoming.user.user_id,),
            )
            rows = await cursor.fetchall()
        candidates = []
        for case_id, raw, question, created_at, status in rows:
            saved = json.loads(raw or "{}")
            if (
                saved.get("response_kind") != "public_context"
                or saved.get("room_id") != metadata.get("room_id")
                or saved.get("context_trial_id") != trial_id
            ):
                continue
            messages = saved.get("incident_messages", [])
            ids = {message["event_id"] for message in messages} | {
                saved.get("source_event_id")
            }
            if incoming.message_id in ids:
                return case_id, True
            if relations & ids:
                # A new issue explicitly starts a new case, even when entered
                # as a reply. Edits always belong to their original case.
                if not new_issue(incoming.question) or metadata.get(
                    "replaces_event_id"
                ):
                    return case_id, False
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(created_at)
            ).total_seconds()
            if (
                status in {"pending", "in_review"}
                and age <= 900
                and continuation(incoming.question, question)
            ):
                candidates.append(case_id)
        # An unresolved explicit relation is not permission to associate with
        # a different incident, even for the same author.
        if relations or len(candidates) != 1:
            return None, False
        return candidates[0], False

    @staticmethod
    def message(incoming: Any, sanitized: str) -> dict[str, Any]:
        return {
            "event_id": incoming.message_id,
            "text": sanitized,
            "high_risk": getattr(
                getattr(incoming, "classification", None), "topic_risk", None
            )
            == "high",
            **(
                {"replaces_event_id": incoming.channel_metadata["replaces_event_id"]}
                if incoming.channel_metadata.get("replaces_event_id")
                else {}
            ),
        }

    async def append(
        self,
        case_id: int,
        incoming: Any,
        sanitized: str,
        *,
        worker_active: bool = False,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT channel_metadata FROM escalations WHERE id=?", (case_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Incident case no longer exists")
            metadata = json.loads(row[0] or "{}")
            messages = metadata.get("incident_messages", [])
            if any(message["event_id"] == incoming.message_id for message in messages):
                return
            if len(messages) >= 10:
                metadata["incident_context_overflow"] = True
            else:
                messages.append(self.message(incoming, sanitized))
                metadata["incident_messages"] = messages
            metadata["incident_updated_at"] = datetime.now(timezone.utc).isoformat()
            if metadata.get("incident_frozen") or not worker_active:
                metadata["incident_late_update_status"] = (
                    "needs_review_no_additional_generation"
                )
                if not context_only(sanitized):
                    metadata["incident_late_meaningful_update"] = True
            await db.execute(
                "UPDATE escalations SET channel_metadata=?, question=? WHERE id=?",
                (json.dumps(metadata), incident_question(messages), case_id),
            )
            await db.commit()

    async def freeze(self, case_id: int) -> tuple[str, list[dict[str, Any]], bool]:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT channel_metadata, question FROM escalations WHERE id=?",
                (case_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Incident case no longer exists")
            metadata = json.loads(row[0] or "{}")
            messages = metadata.get("incident_messages", [])
            # Keep fragments in Admin, but a bare count or log offer is not
            # evidence about a particular diagnostic step without its referent.
            generation_texts = [
                text for text in incident_texts(messages) if not context_only(text)
            ]
            question = (
                accumulate_question(generation_texts, max_chars=4000)
                if messages
                else row[1]
            )
            overflow = (
                bool(metadata.get("incident_context_overflow"))
                or len("\n---\n".join(incident_texts(messages))) > 4000
            )
            metadata["incident_frozen"] = True
            metadata["incident_context_overflow"] = overflow
            metadata["incident_generation_question"] = question
            metadata["incident_generation_event_ids"] = [
                message["event_id"] for message in messages
            ]
            await db.execute(
                "UPDATE escalations SET channel_metadata=? WHERE id=?",
                (json.dumps(metadata), case_id),
            )
            await db.commit()
            return question, messages, overflow
