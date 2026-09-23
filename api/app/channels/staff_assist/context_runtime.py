"""Durable, staff-only Matrix context reviews.

The source room is read-only. Every eligible question is persisted before model
work, and every send is reserved before transport. An interrupted or uncertain
attempt remains visible in Admin; it is never automatically replayed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import quote

import aiosqlite
from app.channels.policy import (
    get_first_response_delay_seconds,
    get_staff_active_cooldown_seconds,
    is_staff_context_enabled,
)
from app.channels.security import PIIDetector
from app.channels.staff import resolve_channel_staff_resolver
from app.channels.staff_assist.public_context import (
    PUBLIC_CONTEXT_PROMPT,
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
        status: str,
        reason: str,
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
            merged.update(
                context_status=status,
                context_reason=reason,
                context_updated_at=datetime.now(timezone.utc).isoformat(),
            )
            await db.execute(
                "UPDATE escalations SET channel_metadata=?, routing_reason=?, "
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
            "matrix_client_unavailable",
        }
    )

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    def start(self) -> None:
        """Accept new events after shutdown without replaying reserved cases."""
        if self._closed and any(not task.done() for task in self._tasks):
            raise RuntimeError("Context workers have not finished stopping")
        self._closed = False

    async def drain(self) -> None:
        """Wait for in-flight work (used by deterministic integration tests)."""
        if self._tasks:
            await asyncio.gather(*self._tasks)

    async def close(self) -> None:
        """Stop workers; persisted interrupted cases remain available in Admin."""
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def process(self, incoming: Any, channel: Any) -> bool:
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
                },
            )
        )
        store = ContextReviewStore(service.repository.db_path)
        if not await store.reserve(case.id):
            return False
        if self._closed:
            await store.update(case.id, status="deferred", reason="runtime_stopped")
            return False
        if len(self._tasks) >= 100:
            await store.update(
                case.id, status="needs_human", reason="context_capacity_reached"
            )
            return False
        task = asyncio.create_task(
            self._run_case(incoming, channel, case.id, store, question, policy_service)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        # Persisted work is queued, not a delivered customer response.
        return False

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
            await self._prepare_and_publish(
                incoming, channel, case_id, store, question, policy_service
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
        if (
            getattr(getattr(incoming, "classification", None), "topic_risk", None)
            == "high"
        ):
            await store.update(case_id, status="needs_human", reason="high_risk_action")
            return False
        snapshot, reason = await self._read_source(incoming)
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
        documents, _ = await rag._run_retriever_call(
            rag.retriever, retriever.retrieve_with_scores, question
        )
        if not await self._case_is_open(case_id) or not is_staff_context_enabled(
            policy_service, "matrix"
        ):
            await store.update(
                case_id, status="deferred", reason="review_or_policy_changed"
            )
            return False
        evidence = select_public_evidence(documents)
        request = PublicContextRequest(
            question=question, recent_messages=snapshot, evidence=evidence
        )
        evidence_json = [entry.model_dump() for entry in evidence]
        versions: dict[str, Any] = {
            "evidence_version": _digest(evidence_json),
            "evidence_snapshot": evidence_json,
            "generation_version": _digest(PUBLIC_CONTEXT_PROMPT),
            "model_name": str(getattr(self.runtime.settings, "OPENAI_MODEL", "")),
            "source_context_version": _digest([m.model_dump() for m in snapshot]),
            "source_context_snapshot": [m.model_dump() for m in snapshot],
        }
        await store.update(
            case_id, status="preparing", reason="generation_reserved", **versions
        )
        preview = await asyncio.to_thread(
            PublicContextService(rag.llm).preview, request
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
        sources = [
            {"title": e.title, "url": e.url, "content": e.content, "type": "wiki"}
            for e in evidence
            if e.id in used
        ]
        await store.update(
            case_id,
            status="awaiting_review",
            reason=preview.decision.reason,
            answer=note,
            sources=sources,
            **versions,
        )
        # Refresh after model work. Source edits/redactions and intervening staff
        # participation suppress publication; the durable review remains available.
        _, reason = await self._read_source(incoming)
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
        root = (
            f"Support question · staff review #{case_id}\n\n"
            + _markdown_literal(question)
            + "\n\nSource: "
            + matrix_link(room_id, incoming.message_id)
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
        )
        try:
            result = await self._send_if_open(
                case_id,
                channel,
                root,
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
            _, reason = await self._read_source(incoming)
            if reason or not await self._case_is_open(case_id):
                await store.update(
                    case_id, status="deferred", reason=reason or "review_changed"
                )
                return False
            result = await self._send_if_open(
                case_id,
                channel,
                note,
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
        return case is not None and case.status.value in {"pending", "in_review"}

    async def _send_if_open(
        self, case_id: int, channel: Any, text: str, **kwargs: Any
    ) -> Any:
        """Serialize the last decision/send boundary with Admin review actions.

        A review completed before transport starts prevents that send. If a
        transport is already in flight, review waits for its outcome instead.
        """
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
            result = await channel.send_staff_context(text, **kwargs)
            reason = getattr(result, "error", None)
            if not result and reason in self.PRETRANSPORT_REFUSALS:
                raise PublicationSuppressed(reason)
            return result
        finally:
            await service._release_delivery_lock(case_id, lock)

    async def _read_source(self, incoming: Any) -> tuple[list[RoomMessage], str | None]:
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
        if str(getattr(event, "body", "") or "").strip() != incoming.question:
            return [], "source_changed_or_redacted"
        timestamp = getattr(event, "server_timestamp", 0)
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
            source = getattr(item, "source", {}) or {}
            if (
                item in after
                and source.get("content", {}).get("m.relates_to", {}).get("rel_type")
                == "m.replace"
            ):
                return [], "source_context_changed"
        messages = []
        for item in list(reversed(before[:10])) + after:
            sender = str(getattr(item, "sender", ""))
            body = getattr(item, "body", None)
            if not isinstance(body, str) or not body.strip() or len(body) > 4000:
                continue
            role: Literal["staff", "user"] = (
                "staff" if resolver.is_staff(sender) else "user"
            )
            messages.append(RoomMessage(role=role, content=sanitize_question(body)))
        return messages[-20:], None
