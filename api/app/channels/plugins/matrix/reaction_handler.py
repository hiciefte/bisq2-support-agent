"""Matrix reaction handler for feedback collection.

Listens for m.reaction events via nio callbacks and converts them
into normalized ReactionEvents for processing.
"""

import logging
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.channels.plugins.matrix.room_filter import normalize_room_ids
from app.channels.reactions import (
    ReactionEvent,
    ReactionHandlerBase,
    ReactionProcessor,
    ReactionRating,
)

NioReactionEventType: Any = object
NioRedactionEventType: Any = object

try:
    from nio import ReactionEvent as _NioReactionEvent
    from nio import RedactionEvent as _NioRedactionEvent
except ImportError:  # pragma: no cover - exercised in environments without nio
    pass
else:
    NioReactionEventType = _NioReactionEvent
    NioRedactionEventType = _NioRedactionEvent

# Backward-compatible exported symbols used by tests and callers.
NioReactionEvent = NioReactionEventType
NioRedactionEvent = NioRedactionEventType


logger = logging.getLogger(__name__)


class MatrixReactionHandler(ReactionHandlerBase):
    """Push-based reaction handler using nio event callbacks.

    Registers a callback on the Matrix nio AsyncClient for m.reaction
    events and converts them into ReactionEvents for the processor.
    Also tracks reaction event_ids for redaction/removal handling.
    """

    channel_id: str = "matrix"
    _MAX_TRACKED_REACTIONS: int = 10_000
    _STAFF_ESCALATION_ID_PATTERN = re.compile(r"^staff-escalation-(\d+)$")
    _NOTICE_ESCALATION_ID_PATTERN = re.compile(r"Escalation\s+#(\d+)\b")

    def __init__(
        self,
        runtime: Any,
        processor: "ReactionProcessor",
        allowed_room_ids: Any | None = None,
        emoji_rating_map: Optional[Dict[str, ReactionRating]] = None,
    ):
        super().__init__(runtime, processor, emoji_rating_map)
        self.allowed_room_ids = normalize_room_ids(allowed_room_ids)
        self._callback_registered = False
        # Track reaction_event_id -> target message_event_id for redaction (bounded)
        self._reaction_to_message: OrderedDict[str, str] = OrderedDict()
        # Track reaction_event_id -> sender for redaction (bounded)
        self._reaction_to_sender: OrderedDict[str, str] = OrderedDict()
        # Track reaction_event_id -> reaction key for redaction (bounded)
        self._reaction_to_key: OrderedDict[str, str] = OrderedDict()

    async def start_listening(self) -> None:
        """Register nio callbacks for m.reaction and m.room.redaction events."""
        client = self.runtime.resolve("matrix_client")
        client.add_event_callback(self._on_reaction_event, NioReactionEvent)
        client.add_event_callback(self._on_redaction_event, NioRedactionEvent)
        self._callback_registered = True
        self._logger.info("Matrix reaction listener started")

    async def stop_listening(self) -> None:
        """Remove nio callbacks."""
        client = self.runtime.resolve_optional("matrix_client")
        if (
            client
            and self._callback_registered
            and hasattr(client, "remove_event_callback")
        ):
            client.remove_event_callback(self._on_reaction_event)
            client.remove_event_callback(self._on_redaction_event)
            self._callback_registered = False
            self._reaction_to_message.clear()
            self._reaction_to_sender.clear()
            self._reaction_to_key.clear()
            self._logger.info("Matrix reaction listener stopped")

    async def _on_reaction_event(self, room: Any, event: Any) -> None:
        """Handle an incoming m.reaction event.

        Extracts m.relates_to.event_id and key, maps the emoji to a
        rating, and delegates to the processor.
        """
        try:
            room_id = str(getattr(room, "room_id", "") or "").strip()
            if not room_id or room_id not in self.allowed_room_ids:
                return

            source = getattr(event, "source", {})
            content = source.get("content", {})
            relates_to = content.get("m.relates_to")

            if not relates_to:
                return

            target_event_id = relates_to.get("event_id")
            key = relates_to.get("key")
            sender = getattr(event, "sender", "unknown")

            if not target_event_id or not key:
                return

            handled_staff_action = await self._handle_staff_room_escalation_action(
                room_id=room_id,
                target_event_id=target_event_id,
                key=str(key),
                sender=str(sender),
            )
            if handled_staff_action:
                return

            rating = self.map_emoji_to_rating(key)
            if rating is None:
                self._logger.debug(
                    "Unmapped Matrix reaction emoji: %s from %s",
                    key,
                    sender,
                )
                return

            # Track for redaction handling (bounded to prevent memory leak)
            reaction_event_id = getattr(event, "event_id", None)
            if reaction_event_id:
                self._reaction_to_message[reaction_event_id] = target_event_id
                self._reaction_to_sender[reaction_event_id] = sender
                self._reaction_to_key[reaction_event_id] = str(key)
                # Evict oldest entries if over limit
                while len(self._reaction_to_message) > self._MAX_TRACKED_REACTIONS:
                    self._reaction_to_message.popitem(last=False)
                    self._reaction_to_sender.popitem(last=False)
                    self._reaction_to_key.popitem(last=False)

            ts = getattr(event, "server_timestamp", None)
            if ts:
                timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            reaction_event = ReactionEvent(
                channel_id="matrix",
                external_message_id=target_event_id,
                reactor_id=sender,
                rating=rating,
                raw_reaction=key,
                timestamp=timestamp,
            )

            await self.processor.process(reaction_event)

        except Exception:
            self._logger.exception(
                "Error processing Matrix reaction event: %s",
                getattr(event, "event_id", "unknown"),
            )

    @staticmethod
    def _normalize_staff_action_key(key: str) -> str:
        normalized = str(key or "").strip().replace("\ufe0f", "")
        # Remove Fitzpatrick skin-tone modifiers.
        for tone in (
            "\U0001f3fb",
            "\U0001f3fc",
            "\U0001f3fd",
            "\U0001f3fe",
            "\U0001f3ff",
        ):
            normalized = normalized.replace(tone, "")
        return normalized

    def _extract_staff_escalation_id(self, record: Any) -> Optional[int]:
        internal_message_id = str(
            getattr(record, "internal_message_id", "") or ""
        ).strip()
        match = self._STAFF_ESCALATION_ID_PATTERN.match(internal_message_id)
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return None

        answer_text = str(getattr(record, "answer", "") or "")
        fallback = self._NOTICE_ESCALATION_ID_PATTERN.search(answer_text)
        if not fallback:
            return None
        try:
            return int(fallback.group(1))
        except (TypeError, ValueError):
            return None

    def _lookup_staff_escalation_record(self, target_event_id: str) -> Any | None:
        tracker = self.runtime.resolve_optional("sent_message_tracker")
        if tracker is None:
            return None
        record = tracker.lookup("matrix", str(target_event_id))
        if record is None:
            return None
        routing_action = (
            str(getattr(record, "routing_action", "") or "").strip().lower()
        )
        if routing_action != "staff_escalation_notice":
            return None
        return record

    def _is_staff_sender(self, sender: str) -> bool:
        normalized = str(sender or "").strip()
        if not normalized:
            return False
        resolver = self.runtime.resolve_optional("staff_resolver")
        if resolver is None:
            return False
        is_staff = getattr(resolver, "is_staff", None)
        if not callable(is_staff):
            return False
        try:
            return bool(is_staff(normalized))
        except Exception:
            self._logger.debug(
                "Failed staff sender check sender=%s",
                normalized,
                exc_info=True,
            )
            return False

    async def _load_escalation_draft_answer(
        self,
        *,
        escalation_service: Any,
        escalation_id: int,
    ) -> str:
        repository = getattr(escalation_service, "repository", None)
        get_by_id = getattr(repository, "get_by_id", None)
        if callable(get_by_id):
            escalation = await get_by_id(escalation_id)
        else:
            escalation = None
        return str(getattr(escalation, "ai_draft_answer", "") or "").strip()

    @staticmethod
    def _parse_staff_command(command_text: str) -> tuple[str, str]:
        text = str(command_text or "").strip()
        if not text:
            return "", ""

        lines = text.splitlines()
        while lines and str(lines[0]).lstrip().startswith(">"):
            lines.pop(0)
        while lines and not str(lines[0]).strip():
            lines.pop(0)
        normalized = "\n".join(lines).strip()
        if not normalized.startswith("/"):
            return "", ""

        parts = normalized.split(maxsplit=1)
        command = parts[0].strip().lower()
        payload = parts[1].strip() if len(parts) > 1 else ""
        return command, payload

    async def handle_staff_command(
        self,
        *,
        room_id: str,
        reply_to_event_id: str,
        command_text: str,
        sender: str,
    ) -> bool:
        command, payload = self._parse_staff_command(command_text)
        if command not in {"/send", "/dismiss"}:
            return False

        self._logger.info(
            "Received Matrix staff command room_id=%s reply_to=%s sender=%s command=%s has_payload=%s",
            room_id,
            reply_to_event_id,
            sender,
            command,
            bool(str(payload or "").strip()),
        )

        reply_event_id = str(reply_to_event_id or "").strip()
        if not reply_event_id:
            self._logger.warning(
                "Ignoring Matrix staff command without reply target sender=%s command=%s",
                sender,
                command,
            )
            return True

        record = self._lookup_staff_escalation_record(reply_event_id)
        if record is None:
            self._logger.warning(
                "Ignoring Matrix staff command without tracked staff notice reply_to=%s sender=%s command=%s",
                reply_event_id,
                sender,
                command,
            )
            return False
        if not self._is_staff_sender(sender):
            self._logger.warning(
                "Ignoring Matrix staff command from non-staff sender=%s",
                sender,
            )
            return True
        escalation_id = self._extract_staff_escalation_id(record)
        if escalation_id is None:
            self._logger.warning(
                "Ignoring Matrix staff command without resolvable escalation id reply_to=%s sender=%s command=%s",
                reply_event_id,
                sender,
                command,
            )
            return True

        escalation_service = self.runtime.resolve_optional("escalation_service")
        if escalation_service is None:
            self._logger.warning(
                "Ignoring Matrix staff command without escalation_service escalation_id=%s sender=%s command=%s",
                escalation_id,
                sender,
                command,
            )
            return True

        try:
            if command == "/dismiss":
                await escalation_service.close_escalation(escalation_id)
                await self._send_staff_thread_notice(
                    room_id=room_id,
                    root_event_id=reply_event_id,
                    body=f"Dismissed escalation #{escalation_id} with no reply.",
                )
                return True

            answer_text = str(payload or "").strip()
            if not answer_text:
                answer_text = await self._load_escalation_draft_answer(
                    escalation_service=escalation_service,
                    escalation_id=escalation_id,
                )
            if not answer_text:
                self._logger.warning(
                    "Ignoring Matrix /send command with empty final answer escalation_id=%s sender=%s",
                    escalation_id,
                    sender,
                )
                return True

            self._logger.info(
                "Processing Matrix /send command escalation_id=%s sender=%s answer_length=%s",
                escalation_id,
                sender,
                len(answer_text),
            )
            await escalation_service.respond_to_escalation(
                escalation_id,
                answer_text,
                sender,
            )
            await self._send_staff_thread_notice(
                room_id=room_id,
                root_event_id=reply_event_id,
                body=f"Sent escalation #{escalation_id} response to the user.",
            )
            return True
        except Exception:
            self._logger.exception(
                "Failed processing Matrix staff command escalation_id=%s command=%s",
                escalation_id,
                command,
            )
            return True

    async def _send_staff_thread_notice(
        self,
        *,
        room_id: str,
        root_event_id: str,
        body: str,
    ) -> None:
        client = self.runtime.resolve_optional("matrix_client")
        if client is None:
            return
        normalized_room_id = str(room_id or "").strip()
        normalized_root_event_id = str(root_event_id or "").strip()
        text = str(body or "").strip()
        if not normalized_room_id or not normalized_root_event_id or not text:
            return
        runtime_settings = getattr(self.runtime, "settings", None)
        ignore_unverified_devices = bool(
            getattr(runtime_settings, "MATRIX_SYNC_IGNORE_UNVERIFIED_DEVICES", True)
        )
        content = {
            "msgtype": "m.notice",
            "body": text,
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": normalized_root_event_id,
                "is_falling_back": True,
                "m.in_reply_to": {"event_id": normalized_root_event_id},
            },
        }
        try:
            await client.room_send(
                room_id=normalized_room_id,
                message_type="m.room.message",
                content=content,
                ignore_unverified_devices=ignore_unverified_devices,
            )
        except Exception:
            self._logger.debug(
                "Failed sending Matrix staff-thread notice room_id=%s event_id=%s",
                normalized_room_id,
                normalized_root_event_id,
                exc_info=True,
            )

    async def _handle_staff_room_escalation_action(
        self,
        *,
        room_id: str,
        target_event_id: str,
        key: str,
        sender: str,
    ) -> bool:
        normalized_key = self._normalize_staff_action_key(key)
        if normalized_key not in {"\U0001f44d", "\U0001f44e"}:
            return False

        record = self._lookup_staff_escalation_record(target_event_id)
        if record is None:
            return False
        if not self._is_staff_sender(sender):
            self._logger.warning(
                "Ignoring Matrix staff escalation reaction from non-staff sender=%s",
                sender,
            )
            return True

        escalation_id = self._extract_staff_escalation_id(record)
        if escalation_id is None:
            self._logger.warning(
                "Dropping staff escalation reaction without resolvable escalation id event_id=%s",
                target_event_id,
            )
            return True

        escalation_service = self.runtime.resolve_optional("escalation_service")
        if escalation_service is None:
            self._logger.warning(
                "Dropping staff escalation reaction without escalation_service event_id=%s",
                target_event_id,
            )
            return True

        try:
            if normalized_key == "\U0001f44d":
                draft = await self._load_escalation_draft_answer(
                    escalation_service=escalation_service,
                    escalation_id=escalation_id,
                )
                if not draft:
                    self._logger.warning(
                        "Cannot approve escalation=%s due to missing ai_draft_answer",
                        escalation_id,
                    )
                    return True
                await escalation_service.respond_to_escalation(
                    escalation_id, draft, sender
                )
                await self._send_staff_thread_notice(
                    room_id=room_id,
                    root_event_id=str(target_event_id),
                    body=f"Approved escalation #{escalation_id} and sent response.",
                )
                self._logger.info(
                    "Approved escalation via Matrix reaction escalation_id=%s sender=%s",
                    escalation_id,
                    sender,
                )
                return True

            await escalation_service.close_escalation(escalation_id)
            await self._send_staff_thread_notice(
                room_id=room_id,
                root_event_id=str(target_event_id),
                body=f"Dismissed escalation #{escalation_id} with no reply.",
            )
            self._logger.info(
                "Dismissed escalation via Matrix reaction escalation_id=%s sender=%s",
                escalation_id,
                sender,
            )
            return True
        except Exception:
            self._logger.exception(
                "Failed processing Matrix staff escalation reaction escalation_id=%s",
                escalation_id,
            )
            return True

    async def _on_redaction_event(self, room: Any, event: Any) -> None:
        """Handle a redaction event (reaction removal).

        Looks up the redacted event_id in our tracking map and calls
        processor.revoke_reaction() if it was a tracked reaction.
        """
        redacts = getattr(event, "redacts", None)
        if not redacts:
            return
        room_id = str(getattr(room, "room_id", "") or "").strip()
        if not room_id or room_id not in self.allowed_room_ids:
            return

        target_msg_id = self._reaction_to_message.get(redacts)
        reactor_id = self._reaction_to_sender.get(redacts)
        reaction_key = self._reaction_to_key.get(redacts)

        if not target_msg_id or not reactor_id:
            return

        try:
            await self.processor.revoke_reaction(
                channel_id="matrix",
                external_message_id=target_msg_id,
                reactor_id=reactor_id,
                raw_reaction=reaction_key,
            )
            # Clean up tracking maps
            self._reaction_to_message.pop(redacts, None)
            self._reaction_to_sender.pop(redacts, None)
            self._reaction_to_key.pop(redacts, None)
        except Exception:
            self._logger.exception("Error revoking Matrix reaction: %s", redacts)
