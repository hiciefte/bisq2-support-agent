import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

import aiohttp
from app.core.config import Settings

logger = logging.getLogger(__name__)


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
                    if response.status != 200:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries}: Error {response.status} from Bisq API"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return {}
                    return await response.json()

            except Exception as e:
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
                return {}

        # Unreachable: loop always returns on success or terminal failure
        return {}
