"""Generic polling loop for channel plugins with POLL_CONVERSATIONS support."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.channels.policy import (
    apply_autosend_policy,
    is_autosend_enabled,
    is_generation_enabled,
)
from app.channels.response_dispatcher import ChannelResponseDispatcher

logger = logging.getLogger(__name__)


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
        messages = await self.channel.poll_conversations()
        processed = 0

        if not is_generation_enabled(self.autoresponse_policy_service, self.channel_id):
            logger.debug(
                "AI generation disabled for channel=%s; ignoring inbound messages",
                self.channel_id,
            )
            return 0

        autosend_enabled = is_autosend_enabled(
            self.autoresponse_policy_service,
            self.channel_id,
        )
        for incoming in messages:
            if await self._consume_feedback_followup(incoming):
                processed += 1
                continue
            response = await self.channel.handle_incoming(incoming)
            response = apply_autosend_policy(response, autosend_enabled)
            sent = await self.dispatcher.dispatch(incoming, response)
            if sent:
                processed += 1
        return processed

    async def _consume_feedback_followup(self, incoming: Any) -> bool:
        runtime = getattr(self.channel, "runtime", None)
        if runtime is None:
            return False
        coordinator = runtime.resolve_optional("feedback_followup_coordinator")
        if coordinator is None:
            return False
        consume = getattr(coordinator, "consume_if_pending", None)
        if not callable(consume):
            return False
        try:
            return bool(await consume(incoming=incoming, channel=self.channel))
        except Exception:
            logger.exception(
                "Failed while consuming feedback follow-up for channel=%s message_id=%s",
                self.channel_id,
                getattr(incoming, "message_id", "<unknown>"),
            )
            return False

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
