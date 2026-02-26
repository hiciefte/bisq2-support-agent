"""Backward-compatible alias for generic channel polling service."""

from app.channels.services.live_polling_service import LivePollingService


class Bisq2LiveChatService(LivePollingService):
    """Poll Bisq2 support messages and auto-send AI responses when routing allows."""

    async def start(self) -> None:
        if hasattr(self.channel, "start"):
            await self.channel.start()
        await super().start()

    async def stop(self) -> None:
        await super().stop()
        if hasattr(self.channel, "stop"):
            await self.channel.stop()
