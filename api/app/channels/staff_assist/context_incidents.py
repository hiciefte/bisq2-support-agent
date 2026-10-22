"""Bounded incident membership stored with the existing private Admin case.

No additional conversation archive or model classifier: explicit Matrix and
quoted-question relationships establish membership, with each sender retained.
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

_GRATITUDE = (
    r"(?:thanks?(?: you)?|thx)"
    r"(?: (?:again|a lot|so much|very much))?"
    r"(?:,? (?:guys|everyone|all|folks|both))?"
    r"(?: (?:for )?(?:the )?(?:quick|speedy|prompt|fast) (?:response|reply))?"
)


def _acknowledgement_clauses(text: str, clause: str) -> bool:
    # Match entire clauses; never discard arbitrary words or question marks.
    return bool(
        re.fullmatch(
            rf"{clause}(?:(?:[,!.]\s*|\s+){clause})*"
            r"(?:[.!]?\s*[👍🙏🤙👌]\ufe0f?[\U0001f3fb-\U0001f3ff]?)*",
            text.strip().lower().rstrip(".! "),
        )
    )


def acknowledgement_only(text: str) -> bool:
    """Existing requester acknowledgements, without substantive suffixes."""
    return _acknowledgement_clauses(
        text,
        rf"(?:ok(?:ay)?|yes|yeah|great|{_GRATITUDE}|"
        r"i (?:already )?did that(?: (?:as well|too))?)",
    )


def gratitude_only(text: str) -> bool:
    """Staff thanks are quiet; yes/action confirmations may answer a question."""
    return _acknowledgement_clauses(text, _GRATITUDE)


def context_only(text: str) -> bool:
    text = text.strip().lower().rstrip(".! ")
    if re.search(r"\b(?:error|fails?|failed|cannot|locked)\b|can['’]t|not work", text):
        return False
    return bool(
        acknowledgement_only(text)
        or re.fullmatch(r"(?:no|\d+\s*(?:times?)?)", text)
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


def helper_question(text: str) -> bool:
    """Conservative second-person diagnostic turn, not a general how-to request."""
    return bool(
        "?" in text
        and not quoted_question(text)
        and re.search(r"\b(?:did|have|are|were) you\b", text, re.I)
        and not re.search(r"\b(?:i|my|me|we|our)\b", text, re.I)
    )


def answer_fragment(text: str) -> bool:
    return bool(
        re.match(
            r"(?:yes|yeah|yep|nope)\b|"
            r"(?:no|correct|exactly|right)(?=\s*[,!.;:]|\s+(?:i|it|that|this|we)\b)|"
            r"(?:i (?:did|tried|used) (?:that|it)|"
            r"(?:it|that|this) (?:is|was|does|did|still)|"
            r"(?:does|did|would) (?:that|this))\b",
            text.strip(),
            re.I,
        )
    )


def quoted_question(text: str) -> str | None:
    """Recognize an explicit answer to a complete quoted human question."""
    match = re.match(
        r"\s*(?:you asked|answering your question|in reply to your question)\s*:?\s*"
        r'["“]([^"“”\n]{12,500}\?)["”]\s*[.:,-]?\s*(.+)',
        text,
        re.I | re.S,
    )
    if match and len(match[1].split()) >= 4 and match[2].strip():
        return " ".join(match[1].split())
    return None


def _advisory_start(text: str) -> bool:
    return bool(
        re.match(
            r"you (?:should|could|can|may|must|need to|have to)\b|"
            r"(?:please )?(?:try|check|restart|inspect|make sure)\b"
            r"(?!\s+(?:failed|fails|did(?:n['’]t| not)|does(?:n['’]t| not)|"
            r"won['’]t|will not|is(?:n['’]t| not)|was(?:n['’]t| not)?|keeps|hangs|"
            r"never)\b)|"
            r"i (?:recommend|suggest)\b|"
            r"my (?:recommendation|suggestion|advice)\b|"
            r"in my experience[,]? you\b",
            text,
            re.I,
        )
    )


def standalone_request(text: str) -> bool:
    """Positive request evidence, not a global question/admission classifier.

    A participant's earlier helper role must not suppress their own new request.
    Punctuation or a first-person pronoun alone cannot establish that transition.
    """
    if (
        context_only(text)
        or helper_question(text)
        or answer_fragment(text)
        or quoted_question(text)
    ):
        return False
    text = re.sub(r"^(?:also|and)\b[\s,:;-]*", "", text.strip(), flags=re.I)
    # A diagnostic question after explicit advice still addresses the other
    # participant. A later question mark must not manufacture request ownership.
    if _advisory_start(text):
        return False
    question = (
        r"(?:what|which|where|when|why|how) "
        r"(?:do|does|did|is|are|was|were|can|could|should|would|will|has|have)\b|"
        r"how to\b|"
        r"(?:can|could|would) you (?:please )?(?:explain|help|tell|show)\b|"
        r"(?:can|could|should|may|do|does|is|are|will|would) "
        r"(?:i|we|my|our|the|a|an)\b"
    )
    # A factual lead-in or conditional can precede a clear request. Avoid
    # treating "what I suggest" or "how about checking" as question grammar.
    if re.search(
        rf"(?:^|[.!]\s+|^(?:restart|check)\b[^?\n]{{0,160}},\s*)(?:{question})",
        text,
        re.I,
    ) or re.match(
        rf"(?:if|when)\b[^?\n]{{1,160}},\s*(?:{question}|"
        r"(?:does|would|will|can|could|is) it\b)",
        text,
        re.I,
    ):
        return True
    return bool(
        re.match(
            r"(?:i|we) (?:cannot|can't|can’t|need help|am unable|are unable|"
            r"have (?:a |an )?(?:problem|issue|error)|"
            r"get (?:a |an )?(?:error|exception))\b|"
            r"(?:my|our)\b[^.!?\n]{0,100}\b"
            r"(?:[a-z]*error|[a-z]*exception|fails?|failed|stuck|locked|"
            r"missing|broken|cannot|can't|can’t|"
            r"not (?:work\w*|connect\w*|respond\w*)|"
            r"(?:doesn't|doesn’t|won't|won’t) (?:work|connect|sync|start|open|load))\b",
            text,
            re.I,
        )
    )


def helper_turn(text: str) -> bool:
    """Recognize explicit advice even before conversation membership is known.

    This is a narrow deterministic hold, not a claim to classify arbitrary prose.
    Established non-requester participation supplies the broader review hint.
    """
    if helper_question(text):
        return True
    if standalone_request(text) or quoted_question(text):
        return False
    text = re.sub(r"^(?:also|and)\b[\s,:;-]*", "", text.strip(), flags=re.I)
    return bool(_advisory_start(text) or re.match(r"(?:if|when) you\b", text, re.I))


def compatible(text: str, previous: str) -> bool:
    old_product, product = explicit_product(previous), explicit_product(text)
    old_version, version = explicit_user_version(previous), explicit_user_version(text)
    groups = (
        {"trade", "wallet", "deposit", "payout", "balance", "mediation", "spv", "dao"},
        {"profile", "notification", "notifications", "identity"},
        {"tor", "connection", "connectivity", "bootstrap", "node"},
        {"offer", "offers", "price", "reputation"},
    )
    topics = {
        index
        for index, group in enumerate(groups)
        if set(re.findall(r"[a-z]+", text.lower())) & group
    }
    old_topics = {
        index
        for index, group in enumerate(groups)
        if set(re.findall(r"[a-z]+", previous.lower())) & group
    }
    return not (
        (product and old_product and product != old_product)
        or (version and old_version and version != old_version)
        or (topics and old_topics and not topics & old_topics)
    )


def diagnostic_link(text: str, previous: str) -> bool:
    """A repeated exact diagnostic, not a broad topic or ordinary shared word."""
    # CamelCase alone includes product names and payment methods. Only names
    # explicitly shaped as diagnostics can support heuristic association.
    symbols = set(
        re.findall(
            r"\b[A-Za-z]{3,}(?:Error|Exception|Mismatch|Failure|Fault|Timeout|Unavailable|NotFound)\b",
            text,
        )
    )
    if any(re.search(rf"\b{re.escape(symbol)}\b", previous) for symbol in symbols):
        return True
    diagnostics = re.findall(r'["`“]([^"`“”\n]{8,120})["`”]', text)
    return any(
        len(diagnostic.split()) >= 2
        and re.search(
            r"\b(?:error|fails?|failed|missing|mismatch|locked|cannot|unavailable)\b",
            diagnostic,
            re.I,
        )
        and diagnostic in previous
        for diagnostic in diagnostics
    )


def continuation(text: str, previous: str) -> bool:
    """Require an explicit continuation plus diagnostic subject, never time alone."""
    text = text.strip()
    if new_issue(text):
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
        r"(?:and\b|also\b|i (?:already|still|also|tried|have tried)\b|"
        r"it (?:still|also)\b|same\b|"
        r"(?:can|could|does|do|should|would|will|is|are) (?:this|that|the same|it)\b)",
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
    if "?" in text or re.match(
        r"(?:(?:and|also)\b[\s,:;-]*)?"
        r"(?:what|which|where|when|why|how|can|could|does|do|should|would|will|is|are)\b",
        text,
        re.I,
    ):
        # A question may continue an incident, but a shared broad subject or
        # recovery verb cannot distinguish it from another wallet/trade question.
        # Require a repeated exact symbol or explicitly quoted diagnostic.
        return diagnostic_link(text, previous)
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
    # vocabulary is not. Preserve the established statement-only method/field
    # continuation rule; question and antecedent admission above is stricter.
    symbols = set(re.findall(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]*\b", text))
    return any(re.search(rf"\b{re.escape(symbol)}\b", previous) for symbol in symbols)


def incident_entries(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for message in messages:
        replacement = message.get("replaces_event_id")
        if replacement in positions:
            entries[positions[replacement]] = message
            positions[message["event_id"]] = positions[replacement]
        else:
            positions[message["event_id"]] = len(entries)
            entries.append(message)
    return entries


def incident_texts(messages: list[dict[str, Any]]) -> list[str]:
    return [message["text"] for message in incident_entries(messages)]


def speaker_labels(
    messages: list[dict[str, Any]],
    *,
    focal_sender: str | None = None,
    legacy_sender: str | None = None,
) -> dict[str | None, str]:
    """Keep confirmed speakers stable across Admin, Staff and model context."""
    labels: dict[str | None, str] = {focal_sender: "requester"} if focal_sender else {}
    participant = 1
    for message in messages:
        sender = message.get("sender_id", legacy_sender)
        if sender not in labels:
            labels[sender] = f"participant-{participant}"
            participant += 1
    return labels


def incident_question(
    messages: list[dict[str, Any]],
    *,
    legacy_sender: str | None = None,
    focal_sender: str | None = None,
) -> str:
    if legacy_sender:
        messages = [{"sender_id": legacy_sender, **message} for message in messages]
    messages = incident_entries(messages)
    labels = speaker_labels(
        messages, focal_sender=focal_sender, legacy_sender=legacy_sender
    )
    if len(labels) > 1:
        return accumulate_question(
            [
                f"{labels[message.get('sender_id')]}: {message['text']}"
                for message in messages
            ],
            max_chars=4000,
        )
    return accumulate_question(incident_texts(messages), max_chars=4000)


class ContextIncidentStore:
    """Resolve explicit membership within one source room and trial."""

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
                "SELECT id, channel_metadata, question, created_at, status, user_id FROM escalations "
                "WHERE channel='matrix' AND json_extract(channel_metadata, '$.response_kind')='public_context' "
                "AND json_extract(channel_metadata, '$.room_id')=? "
                "AND json_extract(channel_metadata, '$.context_trial_id') IS ? "
                "ORDER BY id DESC LIMIT 100",
                (metadata.get("room_id"), trial_id),
            )
            rows = await cursor.fetchall()
        candidates = []
        quoted_candidates = []
        quote = quoted_question(incoming.question)
        now = datetime.now(timezone.utc)
        for case_id, raw, question, created_at, status, owner in rows:
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
            known = {message["event_id"]: message for message in messages}
            if incoming.message_id in ids:
                if (
                    known.get(incoming.message_id, {}).get("sender_id", owner)
                    == incoming.user.user_id
                ):
                    return case_id, True
                continue
            if relations & ids:
                # A new issue explicitly starts a new case, even when entered
                # as a reply. Edits always belong to their original case.
                edit = metadata.get("replaces_event_id")
                if (
                    edit
                    and known.get(edit, {}).get("sender_id", owner)
                    != incoming.user.user_id
                ):
                    continue
                if edit or (
                    not new_issue(incoming.question)
                    and compatible(incoming.question, question)
                ):
                    return case_id, False
            age = (now - datetime.fromisoformat(created_at)).total_seconds()
            idle = (
                now
                - datetime.fromisoformat(
                    saved.get("incident_last_meaningful_at", created_at)
                )
            ).total_seconds()
            if (
                status in {"pending", "in_review"}
                # Recent substantive activity can keep an incident together,
                # but never extends heuristic ownership past one hour. Native
                # relations above remain authoritative for older follow-ups.
                and 0 <= age <= 3600
                and 0 <= idle <= 900
            ):
                if (
                    quote
                    and not new_issue(incoming.question)
                    and compatible(incoming.question, question)
                ):
                    if any(
                        " ".join(message["text"].split()) == quote
                        for message in messages
                    ):
                        quoted_candidates.append(case_id)
                own_texts = [
                    message["text"]
                    for message in messages
                    if message.get("sender_id", owner) == incoming.user.user_id
                ]
                requester = saved.get("conversation_requester_id")
                if (
                    not requester
                    and saved.get("conversation_membership") != "provisional"
                ):
                    requester = owner
                # A retained helper is not the requester. Their substantive
                # unthreaded turn needs a confirmed relation or Admin review.
                # Quiet acknowledgements can still use the bounded association.
                can_continue = requester == incoming.user.user_id or context_only(
                    incoming.question
                )
                if (
                    can_continue
                    and (own_texts or owner == incoming.user.user_id)
                    and continuation(
                        incoming.question,
                        "\n".join(own_texts) if own_texts else question,
                    )
                ):
                    candidates.append(case_id)
        # An unresolved explicit relation is not permission to associate with
        # a different incident, even for the same author.
        if relations:
            return None, False
        if quote:
            return (
                (quoted_candidates[0], False)
                if len(quoted_candidates) == 1
                else (None, False)
            )
        if len(candidates) != 1:
            return None, False
        return candidates[0], False

    async def candidate_links(self, incoming: Any, trial_id: str | None) -> list[int]:
        """Review hints only: never make room/topic proximity into membership."""
        text = incoming.question
        if (
            new_issue(text)
            or context_only(text)
            or any(
                incoming.channel_metadata.get(key)
                for key in (
                    "reply_to_event_id",
                    "thread_root_event_id",
                    "replaces_event_id",
                )
            )
        ):
            return []
        response_like = answer_fragment(text)
        dependent = response_like or helper_question(text) or quoted_question(text)
        independent_request = standalone_request(text)
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, channel_metadata, question, created_at FROM escalations "
                "WHERE channel='matrix' AND status IN ('pending', 'in_review') "
                "AND json_extract(channel_metadata, '$.response_kind')='public_context' "
                "AND json_extract(channel_metadata, '$.room_id')=? "
                "AND json_extract(channel_metadata, '$.context_trial_id') IS ? "
                "ORDER BY id DESC LIMIT 100",
                (incoming.channel_metadata.get("room_id"), trial_id),
            )
            rows = await cursor.fetchall()
        ignored = set(
            "what which where when why how have were are does did do you your this that with from about after before still then only also tried used checked entered tested the and but for can could would should yes yeah not see saw using".split()
        )
        words = set(re.findall(r"[a-z]{4,}", text.lower())) - ignored
        matches = []
        now = datetime.now(timezone.utc)
        for case_id, raw, previous, created_at in rows:
            saved = json.loads(raw or "{}")
            age = (now - datetime.fromisoformat(created_at)).total_seconds()
            idle = (
                now
                - datetime.fromisoformat(
                    saved.get("incident_last_meaningful_at", created_at)
                )
            ).total_seconds()
            if (
                saved.get("response_kind") != "public_context"
                or saved.get("room_id") != incoming.channel_metadata.get("room_id")
                or saved.get("context_trial_id") != trial_id
                or not 0 <= age <= 3600
                or not 0 <= idle <= 900
                or not compatible(text, previous)
            ):
                continue
            messages = saved.get("incident_messages", [])
            requester = saved.get("conversation_requester_id")
            known_helper = (
                saved.get("conversation_membership") == "confirmed"
                and requester
                and requester != incoming.user.user_id
                and any(
                    message.get("sender_id") == incoming.user.user_id
                    for message in messages
                )
            )
            if known_helper and not independent_request:
                matches.append(case_id)
            elif (
                dependent
                and any(helper_question(message["text"]) for message in messages)
                and words & (set(re.findall(r"[a-z]{4,}", previous.lower())) - ignored)
            ):
                matches.append(case_id)
        return matches

    @staticmethod
    def message(incoming: Any, sanitized: str) -> dict[str, Any]:
        return {
            "event_id": incoming.message_id,
            "sender_id": incoming.user.user_id,
            "text": sanitized,
            **{
                key: incoming.channel_metadata[key]
                for key in ("reply_to_event_id", "thread_root_event_id")
                if incoming.channel_metadata.get(key)
            },
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
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT channel_metadata, status, user_id FROM escalations WHERE id=?",
                (case_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Incident case no longer exists")
            metadata = json.loads(row[0] or "{}")
            if metadata.get("conversation_membership") != "provisional":
                metadata.setdefault("conversation_requester_id", row[2])
            messages = metadata.get("incident_messages", [])
            if any(message["event_id"] == incoming.message_id for message in messages):
                await db.rollback()
                return False
            attempts_exist = await (
                await db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='matrix_context_attempts'"
                )
            ).fetchone()
            attempted = (
                attempts_exist
                and await (
                    await db.execute(
                        "SELECT 1 FROM matrix_context_attempts WHERE escalation_id=?",
                        (case_id,),
                    )
                ).fetchone()
            )
            # A helper's later statement or edit is still helper context. Keep
            # this role from the full history, including replaced advice,
            # so only a different participant can activate the held case.
            helper_senders = {row[2]} | {
                message.get("sender_id", row[2])
                for message in messages
                if helper_turn(message["text"])
            }
            activated = (
                metadata.get("conversation_membership") == "provisional"
                and incoming.user.user_id not in helper_senders
                and row[1] in {"pending", "in_review"}
                and metadata.get("context_reason")
                in {"conversation_helper_only", "context_preparing"}
                and not attempted
                and not metadata.get("incident_frozen")
                and not context_only(sanitized)
                and not helper_turn(sanitized)
                and not metadata.get("candidate_conversation_ids")
            )
            if activated:
                metadata["conversation_membership"] = "confirmed"
                metadata["conversation_requester_id"] = incoming.user.user_id
                metadata["context_status"] = "preparing"
                metadata["context_reason"] = "context_preparing"
            metadata["conversation_id"] = str(case_id)
            updated_at = datetime.now(timezone.utc).isoformat()
            if len(messages) >= 10:
                metadata["incident_context_overflow"] = True
            else:
                messages.append(self.message(incoming, sanitized))
                metadata["incident_messages"] = messages
                if not context_only(sanitized):
                    metadata["incident_last_meaningful_at"] = updated_at
            metadata["incident_updated_at"] = updated_at
            if not context_only(sanitized) and (
                metadata.get("incident_frozen")
                or (
                    not worker_active
                    and not activated
                    and metadata.get("conversation_membership") != "provisional"
                )
            ):
                metadata["incident_late_update_status"] = (
                    "needs_review_no_additional_generation"
                )
                metadata["incident_late_meaningful_update"] = True
            await db.execute(
                "UPDATE escalations SET channel_metadata=?, question=? WHERE id=?",
                (
                    json.dumps(metadata),
                    incident_question(
                        messages,
                        legacy_sender=row[2],
                        focal_sender=metadata.get("conversation_requester_id"),
                    ),
                    case_id,
                ),
            )
            await db.commit()
            return activated

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
            requester = metadata.get("conversation_requester_id")
            requester_messages = [
                message
                for message in incident_entries(messages)
                if not requester or message.get("sender_id", requester) == requester
            ]
            generation_texts = [
                text
                for text in incident_texts(requester_messages)
                if not context_only(text)
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
