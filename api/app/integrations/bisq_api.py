import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp
from app.core.config import Settings

logger = logging.getLogger(__name__)


def _record_bisq2_api_health(is_healthy: bool, response_time: Optional[float] = None):
    """Record Bisq2 API health metric (import lazily to avoid circular imports)."""
    try:
        from app.metrics.task_metrics import record_bisq2_api_health

        record_bisq2_api_health(is_healthy, response_time)
    except Exception as e:
        logger.debug(f"Could not record bisq2 API health metric: {e}")


class Bisq2API:
    """Integration with Bisq2 API for support chat export functionality."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BISQ_API_URL.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def setup(self):
        """Initialize the API client with timeouts."""
        if not self._session:
            timeout = aiohttp.ClientTimeout(total=10, connect=3, sock_read=10)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def cleanup(self):
        """Clean up resources."""
        if self._session:
            await self._session.close()
            self._session = None

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make an HTTP request to the Bisq2 API."""
        if not self._session:
            await self.setup()

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            async with self._session.request(method, url, **kwargs) as response:
                if response.status == 404:
                    return {}
                response.raise_for_status()
                if "application/json" in response.headers.get("content-type", ""):
                    return await response.json()
                return {"content": await response.text()}
        except aiohttp.ClientError as e:
            logger.error(f"Error making request to Bisq2 API: {e}", exc_info=True)
            raise

    async def export_chat_messages(
        self,
        since: Optional[datetime] = None,
        max_retries: int = 3,
        retry_delay: int = 2,
    ) -> Dict:
        """Export chat messages from Bisq API with retries.

        Returns:
            Dictionary containing export data with structure:
            {
                "exportDate": "2025-10-14T15:30:00Z",
                "exportMetadata": {
                    "channelCount": 2,
                    "messageCount": 100,
                    "dataRetentionDays": 10,
                    "timezone": "UTC"
                },
                "messages": [...]
            }
        """
        if not self._session:
            await self.setup()

        for attempt in range(max_retries):
            start_time = time.time()
            try:
                url = f"{self.base_url}/api/v1/support/export"
                params = {}
                if since:
                    # Ensure timezone-aware UTC, seconds precision, RFC3339 "Z"
                    if since.tzinfo is None:
                        since = since.replace(tzinfo=timezone.utc)
                    since_utc = (
                        since.astimezone(timezone.utc)
                        .replace(microsecond=0)
                        .isoformat()
                        .replace("+00:00", "Z")
                    )
                    params["since"] = since_utc

                async with self._session.get(
                    url, params=params, headers={"Accept": "application/json"}
                ) as response:
                    response_time = time.time() - start_time
                    if response.status != 200:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries}: Error {response.status} from Bisq API"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        # Final attempt failed - record unhealthy
                        _record_bisq2_api_health(False, response_time)
                        return {}
                    # Success - record healthy with response time
                    _record_bisq2_api_health(True, response_time)
                    return await response.json()

            except Exception as e:
                response_time = time.time() - start_time
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries}: Failed to export chat messages: {str(e)}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                logger.error(
                    f"Failed to export chat messages after {max_retries} attempts: {str(e)}",
                    exc_info=True,
                )
                # Final attempt failed - record unhealthy
                _record_bisq2_api_health(False, response_time)
                return {}

        # Unreachable: loop always returns on success or terminal failure
        return {}

    async def send_support_message(
        self,
        channel_id: str,
        text: str,
        citation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a support message to a Bisq2 channel.

        Args:
            channel_id: Bisq2 channel ID (e.g. "support.support").
            text: Message text to send.
            citation: Optional citation text (original question).

        Returns:
            Response dict with messageId and timestamp, or empty dict on 404.

        Raises:
            aiohttp.ClientError: On connection/HTTP errors.
        """
        endpoint = f"/api/v1/support/channels/{channel_id}/messages"
        body: Dict[str, Any] = {"text": text}
        if citation is not None:
            body["citation"] = citation
        return await self._make_request("POST", endpoint, json=body)

    async def send_reaction(
        self,
        channel_id: str,
        message_id: str,
        reaction_id: int,
        is_removed: bool = False,
    ) -> Dict[str, Any]:
        """Send a reaction to a message in a Bisq2 channel.

        Args:
            channel_id: Bisq2 channel ID.
            message_id: ID of the message to react to.
            reaction_id: Bisq2 Reaction enum ordinal (0=THUMBS_UP, etc.).
            is_removed: Whether to remove the reaction.

        Returns:
            Response dict (usually empty on 204).

        Raises:
            aiohttp.ClientError: On connection/HTTP errors.
        """
        endpoint = f"/api/v1/support/channels/{channel_id}/{message_id}/reactions"
        body: Dict[str, Any] = {
            "reactionId": reaction_id,
            "isRemoved": is_removed,
        }
        return await self._make_request("POST", endpoint, json=body)
