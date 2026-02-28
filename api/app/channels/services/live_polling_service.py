"""Generic polling loop for channel plugins with POLL_CONVERSATIONS support."""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import suppress
from typing import Any

from app.channels.inbound_orchestrator import InboundMessageOrchestrator
from app.channels.policy import (
    is_autosend_enabled,
    is_generation_enabled,
)
from app.channels.response_dispatcher import ChannelResponseDispatcher

logger = logging.getLogger(__name__)
_MISSING = object()


class LivePollingService:
    """Poll channel conversations and dispatch responses."""

    def __init__(
        self,
        channel: Any,
        autoresponse_policy_service: Any | None = None,
        escalation_service: Any | None = None,
        channel_id: str = "",
        poll_interval_seconds: float = 3.0,
        restart_delay_seconds: float = 3.0,
        orchestrator: InboundMessageOrchestrator | None = None,
    ) -> None:
        self.channel = channel
        self.autoresponse_policy_service = autoresponse_policy_service
        self.escalation_service = escalation_service
        self.channel_id = str(channel_id or getattr(channel, "channel_id", "")).strip()
        self.poll_interval_seconds = poll_interval_seconds
        self.restart_delay_seconds = restart_delay_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self.dispatcher = ChannelResponseDispatcher(
            channel=channel,
            channel_id=self.channel_id,
            escalation_service=escalation_service,
        )
        self.orchestrator = orchestrator or InboundMessageOrchestrator(
            channel=channel,
            channel_id=self.channel_id,
            dispatcher=self.dispatcher,
            autoresponse_policy_service=self.autoresponse_policy_service,
            coordination_store=self._resolve_coordination_store(channel),
        )

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Live polling service started for channel=%s", self.channel_id)

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Live polling service stopped for channel=%s", self.channel_id)

    async def run_once(self) -> int:
        if not is_generation_enabled(self.autoresponse_policy_service, self.channel_id):
            logger.debug(
                "AI generation disabled for channel=%s; ignoring inbound messages",
                self.channel_id,
            )
            return 0

        messages = await self.channel.poll_conversations()
        if messages is None:
            return 0
        if not isinstance(messages, list):
            try:
                messages = list(messages)
            except TypeError:
                logger.warning(
                    "Invalid poll payload for channel=%s (type=%s)",
                    self.channel_id,
                    type(messages).__name__,
                )
                return 0
        processed = 0
        # Preserve policy evaluation here so tests and diagnostics can patch/read
        # both generation and auto-send flags at service level.
        _ = is_autosend_enabled(
            self.autoresponse_policy_service,
            self.channel_id,
        )

        for incoming in messages:
            if await self.orchestrator.process_incoming(incoming):
                processed += 1
        return processed

    @staticmethod
    def _resolve_coordination_store(channel: Any) -> Any | None:
        runtime = getattr(channel, "runtime", None)
        if runtime is None:
            return None
        resolve_optional = getattr(runtime, "resolve_optional", None)
        if not callable(resolve_optional):
            return None
        try:
            candidate = resolve_optional("channel_coordination_store")
        except Exception:
            logger.debug(
                "Failed to resolve channel_coordination_store from runtime",
                exc_info=True,
            )
            return None
        if candidate is None:
            return None
        required = (
            "reserve_dedup",
            "acquire_lock",
            "release_lock",
            "get_thread_state",
            "set_thread_state",
        )
        for attr in required:
            if inspect.getattr_static(candidate, attr, _MISSING) is _MISSING:
                return None
        return candidate

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Live polling loop crashed for channel=%s; retrying",
                    self.channel_id,
                )
                await asyncio.sleep(self.restart_delay_seconds)
