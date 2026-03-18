"""Channel-agnostic ChatOps command dispatcher."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.channels.chatops.models import (
    ChatOpsCommand,
    ChatOpsCommandName,
    ChatOpsResult,
)
from app.models.escalation import EscalationPriority, EscalationStatus


class ChatOpsDispatcher:
    """Dispatch parsed ChatOps commands using shared escalation services."""

    def __init__(
        self,
        *,
        escalation_service: Any,
        arbitration_service: Any | None = None,
        stale_after_minutes: int = 30,
    ) -> None:
        self.escalation_service = escalation_service
        self.arbitration_service = arbitration_service
        self.stale_after_minutes = max(1, int(stale_after_minutes))
        self._idempotent_results: dict[str, ChatOpsResult] = {}
        self._inflight_results: dict[str, asyncio.Task[ChatOpsResult]] = {}

    async def dispatch(self, command: ChatOpsCommand) -> ChatOpsResult:
        cached = self._idempotent_results.get(command.source_message_id)
        if cached is not None:
            return ChatOpsResult(
                handled=cached.handled,
                ok=cached.ok,
                message=cached.message,
                command_name=cached.command_name,
                case_id=cached.case_id,
                idempotent=True,
                metadata=dict(cached.metadata),
            )

        inflight = self._inflight_results.get(command.source_message_id)
        if inflight is not None:
            cached = await inflight
            return ChatOpsResult(
                handled=cached.handled,
                ok=cached.ok,
                message=cached.message,
                command_name=cached.command_name,
                case_id=cached.case_id,
                idempotent=True,
                metadata=dict(cached.metadata),
            )

        task = asyncio.create_task(self._dispatch_uncached(command))
        self._inflight_results[command.source_message_id] = task
        try:
            result = await task
            self._idempotent_results[command.source_message_id] = result
            return result
        finally:
            self._inflight_results.pop(command.source_message_id, None)

    async def _dispatch_uncached(self, command: ChatOpsCommand) -> ChatOpsResult:
        handler_map = {
            ChatOpsCommandName.HELP: self._handle_help,
            ChatOpsCommandName.LIST: self._handle_list,
            ChatOpsCommandName.VIEW: self._handle_view,
            ChatOpsCommandName.CLAIM: self._handle_claim,
            ChatOpsCommandName.UNCLAIM: self._handle_unclaim,
            ChatOpsCommandName.SEND: self._handle_send,
            ChatOpsCommandName.EDIT_SEND: self._handle_edit_send,
            ChatOpsCommandName.ESCALATE: self._handle_escalate,
            ChatOpsCommandName.RESOLVE: self._handle_resolve,
        }
        handler = handler_map.get(command.name)
        if handler is None:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message=(
                    f"`!case {command.name.value}` is parsed but not implemented yet. "
                    "Available now: list, view, claim, unclaim, send, edit-send, escalate, resolve, help."
                ),
                command_name=command.name.value,
                case_id=command.case_id,
            )
        return await handler(command)

    async def _handle_help(self, command: ChatOpsCommand) -> ChatOpsResult:
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=(
                "ChatOps commands:\n"
                "!case list [new|mine|stale|escalated] [channel=matrix|bisq2] [limit=20]\n"
                "!case view <case_id>\n"
                "!case claim <case_id>\n"
                "!case unclaim <case_id>\n"
                "!case send <case_id>\n"
                "!case edit-send <case_id> :: <message>\n"
                "!case escalate <case_id> [reason=...]\n"
                "!case resolve <case_id> [note=...]\n"
                "!case help"
            ),
            command_name=command.name.value,
        )

    async def _handle_list(self, command: ChatOpsCommand) -> ChatOpsResult:
        scope = str(command.options.get("scope", "new")).strip().lower() or "new"
        channel = command.options.get("channel")
        limit = int(command.options.get("limit", "20"))
        service = self.escalation_service

        if scope == "mine":
            response = await service.list_escalations(
                staff_id=command.actor_id,
                channel=channel,
                limit=limit,
                offset=0,
            )
            escalations = response.escalations
        elif scope == "stale":
            response = await service.list_escalations(
                status=EscalationStatus.PENDING,
                channel=channel,
                limit=max(limit * 3, limit),
                offset=0,
            )
            cutoff = datetime.now(timezone.utc) - timedelta(
                minutes=self.stale_after_minutes
            )
            escalations = [
                escalation
                for escalation in response.escalations
                if getattr(escalation, "created_at", None)
                and escalation.created_at <= cutoff
            ][:limit]
        elif scope == "escalated":
            response = await service.list_escalations(
                status=EscalationStatus.PENDING,
                channel=channel,
                limit=max(limit * 3, limit),
                offset=0,
            )
            escalations = [
                escalation
                for escalation in response.escalations
                if getattr(escalation, "priority", None) == EscalationPriority.HIGH
            ][:limit]
        else:
            status_filter = EscalationStatus.PENDING
            response = await service.list_escalations(
                status=status_filter,
                channel=channel,
                limit=limit,
                offset=0,
            )
            escalations = response.escalations

        if not escalations:
            return ChatOpsResult(
                handled=True,
                ok=True,
                message="No matching cases found.",
                command_name=command.name.value,
            )

        lines = ["Cases:"]
        for escalation in escalations[:limit]:
            state = self._derive_case_state(escalation)
            question = (
                str(getattr(escalation, "question", "") or "")
                .strip()
                .replace("\n", " ")
            )
            shortened = question[:72] + ("…" if len(question) > 72 else "")
            lines.append(
                f'#{escalation.id} [{state}] channel={escalation.channel} user={escalation.user_id} q="{shortened}"'
            )
        return ChatOpsResult(
            handled=True,
            ok=True,
            message="\n".join(lines),
            command_name=command.name.value,
        )

    async def _handle_view(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.repository.get_by_id(command.case_id)
        if escalation is None:
            return self._not_found(command)
        state = self._derive_case_state(escalation)
        draft = str(getattr(escalation, "ai_draft_answer", "") or "").strip()
        sources = getattr(escalation, "sources", None) or []
        message = (
            f"Case #{escalation.id} [{state}]\n"
            f"Channel: {escalation.channel}\n"
            f"User: {escalation.user_id}\n"
            f"Question: {escalation.question}\n"
            f"Draft: {draft or '—'}\n"
            f"Sources: {len(sources)}\n"
            f"Owner: {getattr(escalation, 'staff_id', None) or 'unclaimed'}"
        )
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=message,
            command_name=command.name.value,
            case_id=command.case_id,
        )

    async def _handle_claim(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.claim_escalation(
            command.case_id,
            command.actor_id,
        )
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=f"Claimed case #{escalation.id}.",
            command_name=command.name.value,
            case_id=escalation.id,
        )

    async def _handle_unclaim(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.unclaim_escalation(
            command.case_id,
            command.actor_id,
        )
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=f"Released case #{escalation.id}.",
            command_name=command.name.value,
            case_id=escalation.id,
        )

    async def _handle_send(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.repository.get_by_id(command.case_id)
        if escalation is None:
            return self._not_found(command)
        draft = str(getattr(escalation, "ai_draft_answer", "") or "").strip()
        if not draft:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message=f"Case #{command.case_id} has no AI draft to send.",
                command_name=command.name.value,
                case_id=command.case_id,
            )
        await self._cancel_arbitration_if_possible(escalation)
        updated = await self.escalation_service.respond_to_escalation(
            command.case_id,
            draft,
            command.actor_id,
        )
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=f"Sent case #{updated.id} to the user.",
            command_name=command.name.value,
            case_id=updated.id,
        )

    async def _handle_edit_send(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.repository.get_by_id(command.case_id)
        if escalation is None:
            return self._not_found(command)
        edited_message = str(command.message or "").strip()
        if not edited_message:
            return ChatOpsResult(
                handled=True,
                ok=False,
                message=f"Case #{command.case_id} requires a non-empty edited message.",
                command_name=command.name.value,
                case_id=command.case_id,
            )
        await self._cancel_arbitration_if_possible(escalation)
        updated = await self.escalation_service.respond_to_escalation(
            command.case_id,
            edited_message,
            command.actor_id,
        )
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=f"Edited and sent case #{updated.id}.",
            command_name=command.name.value,
            case_id=updated.id,
        )

    async def _handle_escalate(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.prioritize_escalation(
            command.case_id,
            EscalationPriority.HIGH,
        )
        reason = str(command.options.get("reason", "") or "").strip()
        suffix = f" Reason: {reason}" if reason else ""
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=f"Marked case #{escalation.id} as high priority.{suffix}",
            command_name=command.name.value,
            case_id=escalation.id,
        )

    async def _handle_resolve(self, command: ChatOpsCommand) -> ChatOpsResult:
        escalation = await self.escalation_service.close_escalation(command.case_id)
        note = str(command.options.get("note", "") or "").strip()
        suffix = f" Note: {note}" if note else ""
        return ChatOpsResult(
            handled=True,
            ok=True,
            message=f"Resolved case #{escalation.id}.{suffix}",
            command_name=command.name.value,
            case_id=escalation.id,
        )

    async def _cancel_arbitration_if_possible(self, escalation: Any) -> None:
        coordinator = self.arbitration_service
        if coordinator is None:
            return
        cancel = getattr(coordinator, "cancel_for_chatops_send", None)
        if not callable(cancel):
            return
        metadata = getattr(escalation, "channel_metadata", None) or {}
        thread_id = (
            metadata.get("thread_id")
            or metadata.get("conversation_id")
            or metadata.get("room_id")
            or ""
        )
        thread_id = str(thread_id or "").strip()
        if not thread_id:
            return
        await cancel(thread_id)

    @staticmethod
    def _derive_case_state(escalation: Any) -> str:
        status = getattr(escalation, "status", None)
        staff_id = str(getattr(escalation, "staff_id", "") or "").strip()
        staff_answer = str(getattr(escalation, "staff_answer", "") or "").strip()
        priority = getattr(escalation, "priority", None)
        if status == EscalationStatus.CLOSED:
            return "resolved" if staff_answer else "closed_no_ai"
        if status == EscalationStatus.RESPONDED:
            return "sent"
        if status == EscalationStatus.IN_REVIEW and staff_id:
            return "claimed"
        if priority == EscalationPriority.HIGH:
            return "escalated"
        return "new"

    @staticmethod
    def _not_found(command: ChatOpsCommand) -> ChatOpsResult:
        return ChatOpsResult(
            handled=True,
            ok=False,
            message=f"Case #{command.case_id} was not found.",
            command_name=command.name.value,
            case_id=command.case_id,
        )
