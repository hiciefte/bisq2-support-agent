"""Durable, staff-only Matrix context reviews.

The source room is read-only. Each eligible incident is persisted before model
work, and every send is reserved before transport. An interrupted or uncertain
attempt remains visible in Admin; it is never automatically replayed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import aiosqlite
from app.channels.models import SendDiagnostic
from app.channels.plugins.matrix.context_text import context_relationships, context_text
from app.channels.policy import (
    get_first_response_delay_seconds,
    get_staff_active_cooldown_seconds,
    is_staff_context_enabled,
)
from app.channels.security import PIIDetector
from app.channels.staff import resolve_channel_staff_resolver
from app.channels.staff_assist.context_incidents import (
    ContextIncidentStore,
    answer_fragment,
    compatible,
    context_only,
    continuation,
    diagnostic_link,
    helper_question,
    incident_question,
    new_issue,
    quoted_question,
    speaker_labels,
)
from app.channels.staff_assist.context_trial import (
    ContextTrial,
    ContextTrialStore,
    utc_now,
)
from app.channels.staff_assist.public_context import (
    STAFF_CONTEXT_PROMPT,
    PublicContextRequest,
    PublicContextService,
    PublicEvidence,
    RoomMessage,
    _markdown_literal,
)
from app.models.escalation import EscalationCreate

logger = logging.getLogger(__name__)


class PublicationSuppressed(Exception):
    """A known review/policy change stopped transport before it started."""


def matrix_link(room_id: str, event_id: str) -> str:
    return (
        "https://matrix.to/#/"
        + quote(room_id, safe="!:")
        + "/"
        + quote(event_id, safe="$:")
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def sanitize_question(text: str) -> str:
    """Remove known identifiers and neutralize mentions in copied public text."""
    return PIIDetector().redact(text).replace("@", "＠").strip()


def _source_event_version(event: Any, resolver: Any, bot_user_id: str | None) -> str:
    """Bind one event's identity and authored context without keeping raw text."""
    source = getattr(event, "source", None) or {}
    content = source.get("content", {})
    sender = getattr(event, "sender", None)
    return _digest(
        {
            "event_id": getattr(event, "event_id", None),
            "sender": sender,
            "staff": resolver.is_staff(sender),
            "bot": sender == bot_user_id,
            "text": sanitize_question(context_text(event)),
            "relations": content.get("m.relates_to", {}),
            "msgtype": content.get("msgtype", "m.text"),
            "redacted": bool(source.get("unsigned", {}).get("redacted_because")),
        }
    )


@dataclass
class _SourceContextSnapshot:
    """Per-generation selection; later reads validate it without selecting anew."""

    events: dict[str, str] | None = None
    messages: tuple[RoomMessage, ...] = ()
    visible_ids: frozenset[str] = frozenset()


def select_public_evidence(documents: list[Any]) -> list[PublicEvidence]:
    """Use public wiki bodies only; a public-looking URL cannot bless a FAQ.

    Compiled knowledge and code evidence need claim-to-origin review and are
    deliberately excluded from this first automatic staff-context path.
    """
    from app.services.rag.canonical_fixes import canonical_url_for_metadata
    from app.utils.wiki_url_generator import generate_wiki_url

    selected: list[PublicEvidence] = []
    seen: set[str] = set()
    for doc in documents[:32]:
        meta = getattr(doc, "metadata", {})
        if (
            not isinstance(meta, dict)
            or meta.get("type") != "wiki"
            or meta.get("audience") not in (None, "public")
            or meta.get("private") is True
            or meta.get("public") is False
        ):
            continue
        try:
            source = PublicEvidence(
                id=f"e{len(selected) + 1}",
                title=meta.get("title"),
                content=doc.page_content,
                url=meta.get("url")
                or canonical_url_for_metadata(meta)
                or generate_wiki_url(
                    title=meta.get("title"), section=meta.get("section")
                ),
            )
        except (TypeError, ValueError):
            continue
        key = _digest([source.content, source.url])
        if key in seen:
            continue
        selected.append(source)
        seen.add(key)
        if len(selected) == 8:
            break
    return selected


class ContextReviewStore:
    """Atomic claims and snapshots alongside the existing escalation records."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def reserve(self, case_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS matrix_context_attempts "
                "(escalation_id INTEGER PRIMARY KEY REFERENCES escalations(id) "
                "ON DELETE CASCADE, reserved_at TEXT NOT NULL)"
            )
            cursor = await db.execute(
                "INSERT OR IGNORE INTO matrix_context_attempts VALUES (?, ?)",
                (case_id, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def update(
        self,
        case_id: int,
        *,
        status: str | None = None,
        reason: str | None = None,
        answer: str | None = None,
        sources: list[dict[str, Any]] | None = None,
        **metadata: Any,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT channel_metadata FROM escalations WHERE id=?", (case_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Context case no longer exists")
            merged = json.loads(row[0] or "{}")
            merged.update(metadata)
            if status is not None:
                merged["context_status"] = status
            if reason is not None:
                merged["context_reason"] = reason
            merged["context_updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "UPDATE escalations SET channel_metadata=?, routing_reason=COALESCE(?, routing_reason), "
                "ai_draft_answer=COALESCE(?, ai_draft_answer), "
                "sources=COALESCE(?, sources) WHERE id=?",
                (
                    json.dumps(merged),
                    reason,
                    answer,
                    json.dumps(sources) if sources is not None else None,
                    case_id,
                ),
            )
            await db.commit()


class MatrixContextRuntime:
    """Generate one cited note, persist it, and publish only a staff thread."""

    CONTEXT_READ_TIMEOUT_SECONDS = 30.0
    PRETRANSPORT_REFUSALS = frozenset(
        {
            "matrix_channel_inactive",
            "staff_context_disabled",
            "staff_context_destination_changed",
            "staff_context_destination_invalid",
            "staff_context_content_invalid",
            "staff_context_thread_invalid",
            "staff_context_case_changed",
            "matrix_client_unavailable",
            "staff_context_room_state_unavailable",
        }
    )

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        from app.services.bisq_network_status_service import BisqNetworkStatusService

        self._network_status_service = BisqNetworkStatusService()
        self._tasks: set[asyncio.Task] = set()
        self._intake_lock = asyncio.Lock()
        self._active_cases: set[int] = set()
        self._closed = False
        self._trial = ContextTrial.from_settings(runtime.settings)
        self._expiry_task: asyncio.Task | None = None

    def start(self) -> None:
        """Accept new events after shutdown without replaying reserved cases."""
        if self._closed and any(not task.done() for task in self._tasks):
            raise RuntimeError("Context workers have not finished stopping")
        self._closed = False
        self._schedule_expiry()

    def _schedule_expiry(self) -> None:
        if self._trial and (self._expiry_task is None or self._expiry_task.done()):
            self._expiry_task = asyncio.create_task(self._expire_trial())

    async def _expire_trial(self) -> None:
        assert self._trial is not None
        await asyncio.sleep(max(0, (self._trial.end_at - utc_now()).total_seconds()))
        policy = self.runtime.resolve_optional("channel_autoresponse_policy_service")
        try:
            if policy is not None:
                policy.set_policy("matrix", generation_enabled=False, enabled=False)
        except Exception:
            logger.exception("Could not persist Matrix trial expiry policy")
        finally:
            await self.close()

    def _trial_store(self) -> ContextTrialStore:
        assert self._trial is not None
        service = self.runtime.resolve_optional("escalation_service")
        return ContextTrialStore(service.repository.db_path, self._trial)

    async def _trial_reason(self, case_id: int | None = None) -> str | None:
        if self._trial is None:
            return None
        if self._closed:
            return "context_trial_stopped"
        try:
            current = ContextTrial.from_settings(self.runtime.settings)
        except (TypeError, ValueError):
            return "context_trial_configuration_changed"
        if current != self._trial:
            return "context_trial_configuration_changed"
        return await self._trial_store().check(case_id)

    async def check_trial_delivery(self, transaction_id: str) -> str | None:
        """Called again inside the publisher lifecycle lock before transport."""
        match = re.fullmatch(r"context-(\d+)-(?:root|note)", transaction_id)
        if match is None:
            return "context_trial_case_not_reserved"
        case_id = int(match.group(1))
        reason = await self._trial_reason(case_id)
        if reason:
            return reason
        if self._closed or not await self._case_is_open(case_id):
            return "staff_context_case_changed"
        return None

    async def drain(self) -> None:
        """Wait for in-flight work (used by deterministic integration tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks)

    async def close(self) -> None:
        """Stop workers; persisted interrupted cases remain available in Admin."""
        self._closed = True
        expiry = self._expiry_task
        if expiry is not None and expiry is not asyncio.current_task():
            expiry.cancel()
            await asyncio.gather(expiry, return_exceptions=True)
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def process(self, incoming: Any, channel: Any) -> bool:
        # The coordinator's room/user accumulation is durable here in the Admin
        # case. Serializing only intake prevents two callbacks creating roots.
        async with self._intake_lock:
            return await self._process_incident(incoming, channel)

    async def _process_incident(self, incoming: Any, channel: Any) -> bool:
        if self._closed:
            return False
        policy_service = self.runtime.resolve_optional(
            "channel_autoresponse_policy_service"
        )
        if not is_staff_context_enabled(policy_service, "matrix"):
            return False
        from app.channels.plugins.matrix.room_filter import (
            resolve_allowed_context_source_rooms,
        )

        room_id = incoming.channel_metadata.get("room_id", "")
        if room_id not in resolve_allowed_context_source_rooms(self.runtime.settings):
            return False
        service = self.runtime.resolve_optional("escalation_service")
        if service is None:
            logger.error("Matrix context requires durable Admin escalations")
            return False
        question = sanitize_question(incoming.question)
        incidents = ContextIncidentStore(service.repository.db_path)
        case_id, duplicate = await incidents.find(
            incoming, self._trial.trial_id if self._trial else None
        )
        if case_id is not None:
            activated = False
            if not duplicate:
                # Order: intake lock, per-case delivery lock, then DB write.
                # The final publication decision and transport own this same
                # lock, so an append cannot commit between their last read and
                # send. An update arriving after that boundary waits for the
                # in-flight result and is retained for review, never replayed.
                lock = await service._acquire_delivery_lock(case_id)
                try:
                    activated = await incidents.append(
                        case_id,
                        incoming,
                        question,
                        worker_active=case_id in self._active_cases,
                    )
                finally:
                    await service._release_delivery_lock(case_id, lock)
            if activated:
                await self._start_case(
                    incoming, channel, case_id, question, policy_service
                )
            return False
        # Detached edits, counts, offers and acknowledgments are not incidents.
        # Non-question inputs still reach this path so they can enrich a known
        # incident even when the shared prefilter would discard them.
        if incoming.channel_metadata.get("replaces_event_id") or context_only(question):
            return False
        classification = getattr(incoming, "classification", None)
        if classification is not None and not classification.should_process:
            return False
        # Do not assume a native reply is standalone when its incident was not
        # captured: the reply fallback has already been removed from its text.
        # Preserve the missing relationship for Admin instead of spending a
        # reservation on a guessed referent. Keep the existing explicit-new-
        # issue exception; it deliberately starts a separate incident.
        unresolved_relation = (
            (
                incoming.channel_metadata.get("thread_root_event_id")
                or incoming.channel_metadata.get("reply_to_event_id")
            )
            if not new_issue(question)
            else None
        )
        candidate_ids = await incidents.candidate_links(
            incoming, self._trial.trial_id if self._trial else None
        )
        unresolved_quote = quoted_question(question) is not None
        provisional = (
            helper_question(question) or bool(candidate_ids) or unresolved_quote
        )
        case = await service.create_escalation(
            EscalationCreate(
                message_id="matrix-context:" + _digest([room_id, incoming.message_id]),
                channel="matrix",
                user_id=incoming.user.user_id,
                username=None,
                question=question,
                ai_draft_answer="No AI context generated yet; review the source question.",
                confidence_score=0,
                routing_action="needs_human",
                routing_reason="context_preparing",
                channel_metadata={
                    "response_kind": "public_context",
                    "delivery_audience": "staff_room",
                    "room_id": room_id,
                    "source_event_id": incoming.message_id,
                    "source_url": matrix_link(room_id, incoming.message_id),
                    "context_status": "preparing",
                    "context_reason": "context_preparing",
                    "model_called": False,
                    "model_call_status": "not_started",
                    "incident_messages": [incidents.message(incoming, question)],
                    "incident_frozen": False,
                    "conversation_membership": (
                        "provisional" if provisional else "confirmed"
                    ),
                    **(
                        {"conversation_requester_id": incoming.user.user_id}
                        if not provisional
                        else {}
                    ),
                    **(
                        {"candidate_conversation_ids": candidate_ids}
                        if candidate_ids
                        else {}
                    ),
                    **(
                        {"incident_unresolved_relation": unresolved_relation}
                        if unresolved_relation
                        else {}
                    ),
                    **(
                        {"context_trial_id": self._trial.trial_id}
                        if self._trial
                        else {}
                    ),
                },
            )
        )
        store = ContextReviewStore(service.repository.db_path)
        await store.update(case.id, conversation_id=str(case.id))
        for candidate_id in candidate_ids:
            candidate = await service.repository.get_by_id(candidate_id)
            if candidate is not None:
                pending = (candidate.channel_metadata or {}).get(
                    "conversation_pending_candidate_ids", []
                )
                await store.update(
                    candidate_id,
                    conversation_pending_candidate_ids=list(
                        dict.fromkeys([*pending, case.id])
                    ),
                )
        if unresolved_relation:
            await store.update(
                case.id, status="deferred", reason="incident_relation_unresolved"
            )
            return False
        if provisional:
            await store.update(
                case.id,
                status="deferred",
                reason=(
                    "conversation_membership_unresolved"
                    if candidate_ids or unresolved_quote
                    else "conversation_helper_only"
                ),
            )
            return False
        await self._start_case(incoming, channel, case.id, question, policy_service)
        return False

    async def _start_case(
        self,
        incoming: Any,
        channel: Any,
        case_id: int,
        question: str,
        policy_service: Any,
    ) -> None:
        service = self.runtime.resolve_optional("escalation_service")
        store = ContextReviewStore(service.repository.db_path)
        if not await self._case_is_open(case_id):
            return
        if not await store.reserve(case_id):
            return
        reason = await self._trial_reason()
        if reason:
            await store.update(case_id, status="deferred", reason=reason)
            return
        self._schedule_expiry()
        if self._closed:
            await store.update(case_id, status="deferred", reason="runtime_stopped")
            return
        if len(self._tasks) >= 100:
            await store.update(
                case_id, status="needs_human", reason="context_capacity_reached"
            )
            return
        task = asyncio.create_task(
            self._run_case(incoming, channel, case_id, store, question, policy_service)
        )
        self._tasks.add(task)
        self._active_cases.add(case_id)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda _: self._active_cases.discard(case_id))
        # Persisted work is queued, not a delivered customer response.

    async def _run_case(
        self,
        incoming: Any,
        channel: Any,
        case_id: int,
        store: ContextReviewStore,
        question: str,
        policy_service: Any,
    ) -> None:
        try:
            delay = get_first_response_delay_seconds(policy_service, "matrix")
            if delay:
                await asyncio.sleep(delay)
            if not is_staff_context_enabled(policy_service, "matrix"):
                await store.update(case_id, status="deferred", reason="policy_changed")
                return
            question, messages, overflow = await ContextIncidentStore(
                store.db_path
            ).freeze(case_id)
            if overflow:
                await store.update(
                    case_id,
                    status="needs_human",
                    reason="incident_context_capacity_reached",
                )
                return
            if not question:
                await store.update(
                    case_id,
                    status="needs_human",
                    reason="incident_no_substantive_context",
                )
                return
            if messages:
                service = self.runtime.resolve_optional("escalation_service")
                case = await service.repository.get_by_id(case_id)
                requester = (case.channel_metadata or {}).get(
                    "conversation_requester_id", case.user_id
                )
                anchor = next(
                    (
                        message
                        for message in reversed(messages)
                        if message.get("sender_id", case.user_id) == requester
                    ),
                    messages[-1],
                )
                relations = {
                    key: anchor[key]
                    for key in (
                        "reply_to_event_id",
                        "thread_root_event_id",
                        "replaces_event_id",
                    )
                    if anchor.get(key)
                }
                source_metadata = {
                    key: value
                    for key, value in incoming.channel_metadata.items()
                    if key
                    not in {
                        "reply_to_event_id",
                        "thread_root_event_id",
                        "replaces_event_id",
                    }
                }
                incoming = incoming.model_copy(
                    update={
                        "message_id": anchor["event_id"],
                        "question": anchor["text"],
                        "user": incoming.user.model_copy(
                            update={"user_id": anchor.get("sender_id", case.user_id)}
                        ),
                        "channel_metadata": {
                            **source_metadata,
                            **relations,
                            "incident_original_owner": case.user_id,
                            "conversation_requester_id": requester,
                            "incident_source_ids": [
                                message["event_id"] for message in messages
                            ],
                            "incident_context": messages,
                            "incident_high_risk": any(
                                message.get("high_risk") for message in messages
                            ),
                        },
                    }
                )
            await self._prepare_and_publish(
                incoming, channel, case_id, store, question, policy_service
            )
        except PublicationSuppressed as exc:
            await store.update(
                case_id,
                status="deferred",
                reason=str(exc),
                model_called=False,
                model_call_status="not_started",
            )
        except asyncio.CancelledError:
            # Never turn an interrupted send into an automatically retryable case.
            await store.update(
                case_id,
                status="delivery_uncertain",
                reason="processing_interrupted_review_required",
            )
            raise
        except Exception:
            logger.exception("Staff context failed for case=%s", case_id)
            await store.update(
                case_id, status="needs_human", reason="context_processing_failed"
            )

    async def _prepare_and_publish(
        self,
        incoming: Any,
        channel: Any,
        case_id: int,
        store: ContextReviewStore,
        question: str,
        policy_service: Any,
    ) -> bool:
        if not await self._case_is_open(case_id):
            return False
        from app.channels.plugins.matrix.room_filter import (
            resolve_allowed_context_source_rooms,
        )

        staff_room = str(
            getattr(self.runtime.settings, "MATRIX_STAFF_ROOM", "") or ""
        ).strip()
        # Match the transport guard before retrieval or paid generation. Keep
        # this destination pinned so a later change is refused at send time.
        if (
            not staff_room.startswith("!")
            or ":" not in staff_room
            or any(char.isspace() for char in staff_room)
            or staff_room in resolve_allowed_context_source_rooms(self.runtime.settings)
        ):
            await store.update(
                case_id, status="deferred", reason="staff_context_destination_invalid"
            )
            return False
        if getattr(
            getattr(incoming, "classification", None), "topic_risk", None
        ) == "high" or incoming.channel_metadata.get("incident_high_risk"):
            await store.update(case_id, status="needs_human", reason="high_risk_action")
            return False
        source_snapshot = _SourceContextSnapshot()
        snapshot, reason = await self._read_source(incoming, snapshot=source_snapshot)
        if reason:
            await store.update(case_id, status="deferred", reason=reason)
            return False
        rag = self.runtime.rag_service
        retriever = rag.document_retriever
        if retriever is None or rag.llm is None:
            await store.update(
                case_id, status="needs_human", reason="generation_unavailable"
            )
            return False
        if self._trial is not None:
            reason = await self._trial_reason() or await self._trial_store().reserve(
                case_id
            )
            if reason:
                await store.update(case_id, status="deferred", reason=reason)
                return False
        reason = await self._trial_reason(case_id)
        if reason:
            await store.update(case_id, status="deferred", reason=reason)
            return False

        def retrieve_documents(query):
            if self._trial:
                reason = (
                    "context_trial_stopped" if self._closed else self._trial.reason()
                )
                if reason:
                    raise PublicationSuppressed(reason)
            return retriever.retrieve_with_scores(query)

        documents, _ = await rag._run_retriever_call(
            rag.retriever, retrieve_documents, question
        )
        if not await self._case_is_open(case_id) or not is_staff_context_enabled(
            policy_service, "matrix"
        ):
            await store.update(
                case_id, status="deferred", reason="review_or_policy_changed"
            )
            return False
        from app.channels.staff_assist.evidence_resolver import StaffEvidenceResolver

        async def allow_live_read() -> bool:
            return (
                not self._closed
                and not await self._trial_reason(case_id)
                and await self._case_is_open(case_id)
                and is_staff_context_enabled(policy_service, "matrix")
            )

        resolver = StaffEvidenceResolver(
            faq_service=getattr(rag, "faq_service", None),
            public_faq_service=self.runtime.resolve_optional("public_faq_service"),
            public_knowledge_service=self.runtime.resolve_optional(
                "public_knowledge_service"
            ),
            grounding_service=self.runtime.resolve_optional(
                "staff_grounding_brief_service"
            ),
            network_status_service=self._network_status_service,
            bisq_service=(
                getattr(rag, "bisq_mcp_service", None)
                if getattr(rag, "mcp_enabled", False)
                else None
            ),
            before_live_read=allow_live_read,
            llm_wiki_loader=getattr(rag, "llm_wiki_loader", None),
            llm_wiki_dir=getattr(self.runtime.settings, "LLM_WIKI_DIR_PATH", None),
        )
        resolved = await resolver.resolve(question=question, documents=documents)
        if not await self._case_is_open(case_id) or not is_staff_context_enabled(
            policy_service, "matrix"
        ):
            await store.update(
                case_id,
                status="deferred",
                reason="review_or_policy_changed",
                model_called=False,
                model_call_status="not_started",
            )
            return False
        evidence = resolved.evidence
        request = PublicContextRequest(
            question=question,
            recent_messages=snapshot,
            evidence=evidence,
            audience="staff_only",
        )
        evidence_json = [entry.model_dump() for entry in evidence]
        versions: dict[str, Any] = {
            "evidence_version": _digest(evidence_json),
            "evidence_snapshot": evidence_json,
            "generation_version": _digest(STAFF_CONTEXT_PROMPT),
            "evidence_diagnostics": resolved.diagnostics,
            "staff_grounding_brief": resolved.internal_grounding,
            "model_name": str(getattr(self.runtime.settings, "OPENAI_MODEL", "")),
            "source_context_version": _digest([m.model_dump() for m in snapshot]),
            "source_context_snapshot": [m.model_dump() for m in snapshot],
        }
        await store.update(
            case_id,
            status="preparing",
            reason="generation_reserved",
            model_called=None,
            model_call_status="reserved",
            **versions,
        )
        reason = await self._trial_reason(case_id)
        if reason:
            await store.update(
                case_id,
                status="deferred",
                reason=reason,
                model_called=False,
                model_call_status="not_started",
            )
            return False

        def generate_preview():
            # A queued executor thread may start after the async check.
            if self._closed or not is_staff_context_enabled(policy_service, "matrix"):
                raise PublicationSuppressed("review_or_policy_changed")
            reason = (
                ("context_trial_stopped" if self._closed else self._trial.reason())
                if self._trial
                else None
            )
            if reason:
                raise PublicationSuppressed(reason)
            return PublicContextService(rag.llm).preview(request)

        preview = await asyncio.to_thread(generate_preview)
        usage = preview.usage
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        counters = {}
        for name in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "input_tokens",
            "output_tokens",
        ):
            value = (
                usage.get(name)
                if isinstance(usage, dict)
                else getattr(usage, name, None)
            )
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                counters[name] = value
        versions.update(
            model_called=preview.model_called,
            model_call_status=(
                "outcome_unknown"
                if preview.model_called
                and preview.decision.reason == "generation_unavailable"
                else "completed" if preview.model_called else "not_started"
            ),
            model_usage=counters or None,
            model_decision=preview.decision.model_dump(),
            validation_diagnostic=getattr(preview, "validation_diagnostic", None),
        )
        if not preview.rendered_note:
            # Model silence is not evidence the customer's issue was resolved.
            await store.update(
                case_id,
                status="needs_human",
                reason=preview.decision.reason,
                **versions,
            )
            return False
        note = preview.rendered_note
        if PIIDetector().contains_pii(note):
            await store.update(
                case_id, status="needs_human", reason="context_pii_detected", **versions
            )
            return False
        used = set(preview.decision.source_ids)
        sources = [{**e.model_dump(), "type": e.kind} for e in evidence if e.id in used]
        await store.update(
            case_id,
            status="awaiting_review",
            reason=preview.decision.reason,
            answer=note,
            sources=sources,
            **versions,
        )
        current_case = await self.runtime.resolve_optional(
            "escalation_service"
        ).repository.get_by_id(case_id)
        if current_case is not None and (current_case.channel_metadata or {}).get(
            "incident_late_meaningful_update"
        ):
            await store.update(
                case_id, status="deferred", reason="incident_updated_after_generation"
            )
            return False
        # Refresh after model work. Source edits/redactions and intervening staff
        # participation suppress publication; the durable review remains available.
        current_snapshot, reason = await self._read_source(
            incoming, snapshot=source_snapshot
        )
        if (
            not reason
            and _digest([m.model_dump() for m in current_snapshot])
            != versions["source_context_version"]
        ):
            reason = "source_context_changed"
        if (
            reason
            or not is_staff_context_enabled(policy_service, "matrix")
            or not await self._case_is_open(case_id)
        ):
            await store.update(
                case_id, status="deferred", reason=reason or "review_or_policy_changed"
            )
            return False
        room_id = incoming.channel_metadata["room_id"]
        source_event_id = (getattr(current_case, "channel_metadata", None) or {}).get(
            "source_event_id", incoming.message_id
        )
        captured = incoming.channel_metadata.get("incident_context", [])
        multiple_speakers = (
            len(
                {
                    message.get("sender_id", incoming.user.user_id)
                    for message in captured
                }
            )
            > 1
        )
        root_question = (
            incident_question(
                captured,
                focal_sender=incoming.channel_metadata.get(
                    "conversation_requester_id", incoming.user.user_id
                ),
                legacy_sender=incoming.channel_metadata.get(
                    "incident_original_owner", incoming.user.user_id
                ),
            )
            if multiple_speakers
            else question
        )
        root = (
            f"Support question · staff review #{case_id}\n\n"
            + _markdown_literal(root_question)
            + "\n\nSource: "
            + matrix_link(room_id, source_event_id)
            + "\n\nAI context is in this thread. Review in Admin; approval stays internal."
        )
        await store.update(
            case_id,
            status="delivery_pending",
            reason="staff_root_reserved",
            staff_room_id=staff_room,
            staff_root_content=root,
            staff_note_content=note,
            staff_root_transaction_id=f"context-{case_id}-root",
            staff_note_transaction_id=f"context-{case_id}-note",
            staff_root_delivery=SendDiagnostic(
                operation_started=False,
                response_received=False,
                reason_category="reserved",
            ).model_dump(),
            staff_note_delivery=SendDiagnostic(
                operation_started=False,
                response_received=False,
                reason_category="reserved",
            ).model_dump(),
        )
        try:
            result = await self._send_if_open(
                case_id,
                channel,
                root,
                store=store,
                phase="root",
                transaction_id=f"context-{case_id}-root",
                expected_room_id=staff_room,
            )
            root_id = getattr(result, "external_message_id", None)
            if not result or not root_id:
                raise RuntimeError("Staff root outcome unavailable")
            await store.update(
                case_id,
                status="delivery_pending",
                reason="staff_note_reserved",
                staff_root_event_id=root_id,
                staff_thread_url=matrix_link(staff_room, root_id),
            )
            current_snapshot, reason = await self._read_source(
                incoming, snapshot=source_snapshot
            )
            if (
                not reason
                and _digest([m.model_dump() for m in current_snapshot])
                != versions["source_context_version"]
            ):
                reason = "source_context_changed"
            if reason or not await self._case_is_open(case_id):
                await store.update(
                    case_id, status="deferred", reason=reason or "review_changed"
                )
                return False
            result = await self._send_if_open(
                case_id,
                channel,
                note,
                store=store,
                phase="note",
                thread_root_event_id=root_id,
                transaction_id=f"context-{case_id}-note",
                expected_room_id=staff_room,
            )
            note_id = getattr(result, "external_message_id", None)
            if not result or not note_id:
                raise RuntimeError("Staff context outcome unavailable")
            await store.update(
                case_id,
                status="delivered",
                reason="staff_context_delivered",
                staff_note_event_id=note_id,
            )
            return True
        except PublicationSuppressed as exc:
            await store.update(
                case_id, status="deferred", reason=str(exc) or "review_or_scope_changed"
            )
            return False
        except Exception:
            await store.update(
                case_id,
                status="delivery_uncertain",
                reason="staff_delivery_requires_reconciliation",
            )
            return False

    async def _case_is_open(self, case_id: int) -> bool:
        service = self.runtime.resolve_optional("escalation_service")
        case = await service.repository.get_by_id(case_id)
        return (
            case is not None
            and case.status.value in {"pending", "in_review"}
            and not (case.channel_metadata or {}).get("incident_late_meaningful_update")
        )

    async def _send_if_open(
        self,
        case_id: int,
        channel: Any,
        text: str,
        *,
        store: ContextReviewStore,
        phase: str,
        **kwargs: Any,
    ) -> Any:
        """Serialize the final decision/send with Admin review and incident writes.

        A review or meaningful update committed before this lock is acquired
        prevents the send. Later updates wait for this decision/transport to
        finish and remain reviewable; an in-flight message cannot be recalled.
        """
        if phase not in {"root", "note"}:
            raise ValueError("Unknown staff delivery phase")
        latest = SendDiagnostic(
            operation_started=False,
            response_received=False,
            reason_category="reserved",
        )

        async def record(diagnostic: SendDiagnostic) -> None:
            nonlocal latest
            latest = diagnostic
            metadata: dict[str, Any] = {
                f"staff_{phase}_delivery": diagnostic.model_dump()
            }
            if diagnostic.response_event_id:
                metadata[f"staff_{phase}_event_id"] = diagnostic.response_event_id
            await store.update(case_id, **metadata)

        service = self.runtime.resolve_optional("escalation_service")
        lock = await service._acquire_delivery_lock(case_id)
        try:
            if self._closed or not await self._case_is_open(case_id):
                raise PublicationSuppressed
            from app.channels.plugins.matrix.room_filter import (
                resolve_allowed_context_source_rooms,
            )

            case = await service.repository.get_by_id(case_id)
            if (case.channel_metadata or {}).get(
                "room_id"
            ) not in resolve_allowed_context_source_rooms(self.runtime.settings):
                raise PublicationSuppressed
            reason = await self.check_trial_delivery(kwargs.get("transaction_id", ""))
            if reason:
                raise PublicationSuppressed(reason)
            # Recheck after the awaited trial storage check. Incident writes
            # and Admin actions share this lock through the transport result.
            if self._closed or not await self._case_is_open(case_id):
                raise PublicationSuppressed("staff_context_case_changed")
            await record(SendDiagnostic(reason_category="adapter_invocation_reserved"))
            result = await channel.send_staff_context(
                text, record_diagnostic=record, **kwargs
            )
            diagnostic = getattr(result, "diagnostic", None)
            if not isinstance(diagnostic, SendDiagnostic):
                # Legacy adapters/mocks expose no operation boundary. Do not
                # turn their false result into evidence that no send occurred.
                try:
                    event_id = getattr(result, "external_message_id", None)
                    diagnostic = SendDiagnostic(
                        operation_started=True if result and event_id else None,
                        response_received=True if result and event_id else None,
                        reason_category=(
                            "acknowledged"
                            if result and event_id
                            else "legacy_outcome_unknown"
                        ),
                        response_event_id=event_id,
                    )
                except (TypeError, ValueError):
                    diagnostic = SendDiagnostic(
                        reason_category="legacy_outcome_unknown"
                    )
            await record(diagnostic)
            if result and not diagnostic.response_event_id:
                raise RuntimeError("Staff response event ID unavailable")
            reason = getattr(result, "error", None)
            if not result and (
                reason in self.PRETRANSPORT_REFUSALS
                or (isinstance(reason, str) and reason.startswith("context_trial_"))
            ):
                raise PublicationSuppressed(reason)
            return result
        except PublicationSuppressed:
            if latest.reason_category == "pretransport_refused":
                raise
            await record(
                SendDiagnostic(
                    operation_started=False,
                    response_received=False,
                    reason_category="suppressed",
                )
            )
            raise
        except (asyncio.CancelledError, Exception) as exc:
            # Salvage a received acknowledgement after a transient storage
            # error. This retries only the local snapshot, never transport; the
            # caller still records uncertainty and does not send another phase.
            if latest.reason_category == "acknowledged":
                await record(latest)
            elif latest.reason_category not in {
                "transport_timeout",
                "transport_exception",
                "response_error",
                "response_missing_event_id",
                "cancelled",
                "client_protocol_error",
                "client_encryption_error",
            }:
                await record(
                    latest.model_copy(
                        update={
                            "reason_category": (
                                "cancelled"
                                if isinstance(exc, asyncio.CancelledError)
                                else "adapter_exception"
                            )
                        }
                    )
                )
            raise
        finally:
            await service._release_delivery_lock(case_id, lock)

    async def _read_source(
        self, incoming: Any, *, snapshot: _SourceContextSnapshot | None = None
    ) -> tuple[list[RoomMessage], str | None]:
        """Read current server context; do not trust activity flags from text."""
        from app.channels.plugins.matrix.room_filter import (
            resolve_allowed_context_source_rooms,
        )

        if incoming.channel_metadata[
            "room_id"
        ] not in resolve_allowed_context_source_rooms(self.runtime.settings):
            return [], "source_room_removed"
        client = self.runtime.resolve_optional("matrix_client")
        if client is None:
            return [], "source_unavailable"
        try:
            response = await asyncio.wait_for(
                client.room_context(
                    incoming.channel_metadata["room_id"], incoming.message_id, limit=40
                ),
                timeout=self.CONTEXT_READ_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return [], "source_context_timeout"
        event = getattr(response, "event", None)
        if event is None or getattr(event, "event_id", None) != incoming.message_id:
            return [], "source_unavailable"
        if sanitize_question(context_text(event)) != sanitize_question(
            incoming.question
        ):
            return [], "source_changed_or_redacted"
        if getattr(event, "sender", incoming.user.user_id) != incoming.user.user_id:
            return [], "source_author_changed"
        timestamp = getattr(event, "server_timestamp", 0)
        if self._trial and (
            not timestamp or timestamp / 1000 < self._trial.start_at.timestamp()
        ):
            return [], "context_trial_before_activation"
        if (
            not timestamp
            or datetime.now(timezone.utc).timestamp() - timestamp / 1000 > 3600
        ):
            return [], "source_stale"
        after = list(getattr(response, "events_after", []) or [])
        before = list(getattr(response, "events_before", []) or [])
        if len(after) >= 20:
            return [], "source_context_incomplete"
        resolver = resolve_channel_staff_resolver(self.runtime, "matrix")
        if resolver is None:
            return [], "staff_identity_unavailable"
        cooldown = get_staff_active_cooldown_seconds(
            self.runtime.resolve_optional("channel_autoresponse_policy_service"),
            "matrix",
        )
        incident_ids = set(
            incoming.channel_metadata.get("incident_source_ids", [incoming.message_id])
        )
        saved = incoming.channel_metadata.get("incident_context", [])
        visible = {
            getattr(item, "event_id", None): item for item in before + after + [event]
        }
        for message in saved:
            observed = visible.get(message["event_id"])
            if observed is None:
                return [], "incident_source_context_incomplete"
            observed_at = getattr(observed, "server_timestamp", 0)
            if self._trial and (
                not observed_at or observed_at / 1000 < self._trial.start_at.timestamp()
            ):
                return [], "context_trial_before_activation"
            if (
                not observed_at
                or datetime.now(timezone.utc).timestamp() - observed_at / 1000 > 3600
            ):
                return [], "source_stale"
            if (
                getattr(observed, "sender", None)
                != message.get(
                    "sender_id",
                    incoming.channel_metadata.get(
                        "incident_original_owner", incoming.user.user_id
                    ),
                )
                or sanitize_question(context_text(observed)) != message["text"]
            ):
                return [], "source_changed_or_redacted"
            if "sender_id" in message:
                saved_relations = {
                    key: message[key]
                    for key in (
                        "reply_to_event_id",
                        "thread_root_event_id",
                        "replaces_event_id",
                    )
                    if message.get(key)
                }
                if context_relationships(observed) != saved_relations:
                    return [], "source_relationship_changed"
        # Matrix returns preceding events newest first. Check the complete
        # bounded window before selecting a smaller chronological prompt history.
        for item in before + after:
            sender = str(getattr(item, "sender", ""))
            if item in after and resolver.is_staff(sender):
                return [], "staff_active"
            if (
                resolver.is_staff(sender)
                and datetime.now(timezone.utc).timestamp()
                - getattr(item, "server_timestamp", 0) / 1000
                < cooldown
            ):
                return [], "staff_active"
            if item in after and sender == getattr(client, "user_id", None):
                return [], "recent_bot_reply"
            replacement = context_relationships(item).get("replaces_event_id")
            if (
                replacement in incident_ids
                and getattr(item, "event_id", None) not in incident_ids
            ):
                return [], "source_context_changed"
        if snapshot is not None and snapshot.events is not None:
            # Recheck the exact events used for generation. Room activity and
            # selection age/capacity must not replace that evidence, while an
            # unavailable, edited, redacted or reassigned event still withholds.
            timeline = before + after + [event]
            invalidated_ids = {
                context_relationships(item).get("replaces_event_id")
                or getattr(item, "redacts", None)
                or (getattr(item, "source", None) or {}).get("redacts")
                for item in timeline
            }
            for event_id, version in snapshot.events.items():
                matches = [
                    item
                    for item in timeline
                    if getattr(item, "event_id", None) == event_id
                ]
                if (
                    event_id in invalidated_ids
                    or len(matches) != 1
                    or _source_event_version(
                        matches[0], resolver, getattr(client, "user_id", None)
                    )
                    != version
                ):
                    return [], "source_context_changed"
            # A follow-up may reach server context before its intake
            # callback sets the durable late-update flag. Keep that safety
            # boundary without treating unrelated room chatter as new evidence.
            relations = context_relationships(event)
            targets = incident_ids | {
                relations.get("thread_root_event_id")
                or incoming.channel_metadata.get("thread_root_event_id")
                or relations.get("reply_to_event_id")
                or incoming.channel_metadata.get("reply_to_event_id")
            }
            captured = saved or [
                {"sender_id": incoming.user.user_id, "text": incoming.question}
            ]
            previous = incident_question(saved) if saved else incoming.question
            now = datetime.now(timezone.utc).timestamp()
            updates = []
            for item in before + after:
                relation = context_relationships(item)
                target = (
                    relation.get("replaces_event_id")
                    or relation.get("thread_root_event_id")
                    or relation.get("reply_to_event_id")
                )
                observed = (getattr(item, "server_timestamp", 0) or 0) / 1000
                content = (getattr(item, "source", None) or {}).get("content", {})
                sender = getattr(item, "sender", None)
                if (
                    not getattr(item, "event_id", None)
                    or not sender
                    or sender == getattr(client, "user_id", None)
                    or not 0 <= now - observed <= 3600
                    or content.get("msgtype", "m.text") != "m.text"
                    or (
                        self._trial
                        and not self._trial.start_at.timestamp()
                        <= observed
                        < self._trial.end_at.timestamp()
                    )
                ):
                    continue
                text = sanitize_question(context_text(item))
                if not text or new_issue(text) or not compatible(text, previous):
                    continue
                updates.append((item.event_id, target, sender, text))
            # Native ACKs can be intermediates even though they add no model
            # context. Follow only bounded explicit edges from incident roots;
            # optional unrelated neighbors never become roots of this graph.
            for _ in updates:
                previous_size = len(targets)
                targets.update(
                    event_id
                    for event_id, target, _, _ in updates
                    if target and target in targets
                )
                if len(targets) == previous_size:
                    break
            for event_id, target, sender, text in updates:
                if event_id in snapshot.visible_ids or context_only(text):
                    continue
                # Match intake's relation priority and conservative continuation
                # rules. This only withholds; it never establishes membership.
                if target:
                    if target in targets:
                        return [], "incident_updated_after_generation"
                    continue
                quote = quoted_question(text)
                if quote:
                    if any(
                        " ".join(message["text"].split()) == quote
                        for message in captured
                    ):
                        return [], "incident_updated_after_generation"
                    continue
                own_texts = [
                    message["text"]
                    for message in captured
                    if message.get(
                        "sender_id",
                        incoming.channel_metadata.get(
                            "incident_original_owner", incoming.user.user_id
                        ),
                    )
                    == sender
                ]
                if own_texts and continuation(text, "\n".join(own_texts)):
                    return [], "incident_updated_after_generation"
            return list(snapshot.messages), None
        return self._source_discussion(
            incoming, event, before, after, saved, resolver, snapshot=snapshot
        )

    def _source_discussion(
        self,
        incoming: Any,
        event: Any,
        before: list[Any],
        after: list[Any],
        saved: list[dict[str, Any]],
        resolver: Any,
        *,
        snapshot: _SourceContextSnapshot | None = None,
    ) -> tuple[list[RoomMessage], str | None]:
        """Bound possibly unrelated surrounding discussion without assigning ownership."""
        owner = incoming.user.user_id
        client = self.runtime.resolve_optional("matrix_client")
        anchor_time = event.server_timestamp / 1000
        now = datetime.now(timezone.utc).timestamp()
        timeline = list(reversed(before)) + [event] + after
        visible = {getattr(item, "event_id", None): item for item in timeline}
        prior_ids = {getattr(item, "event_id", None) for item in before}
        replaced_ids = {item.get("replaces_event_id") for item in saved}
        invalidated_ids = replaced_ids | {
            context_relationships(item).get("replaces_event_id")
            or getattr(item, "redacts", None)
            or (getattr(item, "source", None) or {}).get("redacts")
            for item in timeline
        }
        captured = {
            item["event_id"]: (
                item.get(
                    "sender_id",
                    incoming.channel_metadata.get("incident_original_owner", owner),
                ),
                item["text"],
            )
            for item in saved
            if item["event_id"] not in replaced_ids
            and item["event_id"] != incoming.message_id
            and not context_only(item["text"])
        }
        relations = context_relationships(event)
        reply_target = relations.get(
            "reply_to_event_id"
        ) or incoming.channel_metadata.get("reply_to_event_id")
        native_root = (
            relations.get("thread_root_event_id")
            or incoming.channel_metadata.get("thread_root_event_id")
            or reply_target
        )
        scoped_ids = {incoming.message_id, *captured}
        if native_root:
            scoped_ids.add(native_root)
            # Follow only explicit edges within the already bounded server read.
            for _ in timeline:
                previous_size = len(scoped_ids)
                for item in timeline:
                    relation = context_relationships(item)
                    target = relation.get("thread_root_event_id") or relation.get(
                        "reply_to_event_id"
                    )
                    if target in scoped_ids:
                        scoped_ids.add(getattr(item, "event_id", None))
                if len(scoped_ids) == previous_size:
                    break

        candidates: dict[str, tuple[str, str]] = {}
        for item in timeline:
            event_id = getattr(item, "event_id", None)
            if not event_id or event_id == incoming.message_id:
                continue
            if event_id in captured:
                # Verified member history is required even outside the optional
                # neighborhood window; never trade it for nearby room chatter.
                candidates[event_id] = captured[event_id]
                continue
            sender = getattr(item, "sender", None)
            observed = (getattr(item, "server_timestamp", 0) or 0) / 1000
            relation = context_relationships(item)
            content = (getattr(item, "source", None) or {}).get("content", {})
            if (
                not sender
                or sender == getattr(client, "user_id", None)
                or not 0 <= now - observed <= 3600
                or abs(anchor_time - observed) > 900
                or (
                    self._trial
                    and not self._trial.start_at.timestamp()
                    <= observed
                    < self._trial.end_at.timestamp()
                )
                or relation.get("replaces_event_id")
                or event_id in invalidated_ids
                or content.get("msgtype", "m.text") != "m.text"
                or (native_root and event_id not in scoped_ids)
                or (
                    not native_root
                    and (
                        relation.get("thread_root_event_id")
                        or relation.get("reply_to_event_id")
                    )
                    not in (None, *scoped_ids)
                )
            ):
                continue
            text = sanitize_question(context_text(item))
            if text and not context_only(text):
                candidates[event_id] = (sender, text)

        required = set(captured)
        # An unrelated neighboring message cannot resolve an answer fragment.
        # Without an explicit relation, only one specific diagnostic antecedent
        # is sufficient for admission; semantic uncertainty stays with humans.
        answer_like = answer_fragment(incoming.question)
        if (
            answer_like
            and not context_only(incoming.question)
            and not new_issue(incoming.question)
        ):
            # Thread membership and the immediate question being answered are
            # different edges. A dependent reply needs its actual antecedent;
            # a self-contained update does not depend on a thread's ACK fallback.
            if reply_target:
                if reply_target not in candidates or reply_target not in prior_ids:
                    return [], "source_followup_antecedent_unavailable"
                required.add(reply_target)
            # Durable conversation membership has already been established and
            # every captured sender/message verified. Other members' statements
            # stay attributed to them; membership does not imply a shared owner.
            member_context = set(captured) & prior_ids if not native_root else set()
            antecedents = member_context or {
                event_id
                for event_id, (_, text) in candidates.items()
                if event_id in prior_ids
                and (
                    (native_root and event_id == (reply_target or native_root))
                    or (not native_root and diagnostic_link(incoming.question, text))
                )
            }
            if not antecedents or (not member_context and len(antecedents) != 1):
                return [], "source_followup_antecedent_unavailable"
            required.update(antecedents)
        if (
            len(required) > 10
            or sum(len(candidates[key][1]) for key in required) > 4000
        ):
            return [], "source_discussion_capacity_reached"
        selected = set(required)
        chars = sum(len(candidates[key][1]) for key in selected)
        for event_id in sorted(
            candidates,
            key=lambda key: abs(visible[key].server_timestamp / 1000 - anchor_time),
        ):
            if event_id in selected:
                continue
            length = len(candidates[event_id][1])
            if len(selected) < 10 and chars + length <= 4000:
                selected.add(event_id)
                chars += length
        speakers = speaker_labels(
            saved,
            focal_sender=owner,
            legacy_sender=incoming.channel_metadata.get(
                "incident_original_owner", owner
            ),
        )
        messages = []
        for event_id in dict.fromkeys(
            getattr(item, "event_id", None) for item in timeline
        ):
            if event_id not in selected:
                continue
            sender, text = candidates[event_id]
            if sender not in speakers:
                speakers[sender] = f"participant-{len(speakers)}"
            messages.append(
                RoomMessage(
                    role=(
                        "user"
                        if sender == owner
                        else "staff" if resolver.is_staff(sender) else "participant"
                    ),
                    content=text,
                    speaker=speakers[sender],
                )
            )
        if snapshot is not None:
            selected_ids = selected | {incoming.message_id}
            if any(
                sum(getattr(item, "event_id", None) == key for item in timeline) != 1
                for key in selected_ids
            ):
                return [], "source_context_changed"
            snapshot.events = {
                key: _source_event_version(
                    visible[key], resolver, getattr(client, "user_id", None)
                )
                for key in selected_ids
            }
            snapshot.messages = tuple(messages)
            snapshot.visible_ids = frozenset(key for key in visible if key)
        return messages, None
