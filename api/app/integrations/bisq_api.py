import logging
from datetime import datetime
from typing import Dict, Optional

import aiohttp
import asyncio

from app.core.config import Settings

logger = logging.getLogger(__name__)


class Bisq2API:
    """Integration with Bisq2 API for support chat export functionality."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BISQ_API_URL.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def setup(self):
        """Initialize the API client."""
        if not self._session:
            self._session = aiohttp.ClientSession()

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
            logger.error(f"Error making request to Bisq2 API: {e}")
            raise

    async def export_chat_messages(
        self,
        since: Optional[datetime] = None,
        max_retries: int = 3,
        retry_delay: int = 2,
    ) -> str:
        """Export chat messages from Bisq API with retries."""
        if not self._session:
            await self.setup()

        for attempt in range(max_retries):
            try:
                url = f"{self.base_url}/api/v1/support/export/csv"
                params = {}
                if since:
                    params["since"] = since.isoformat()

                async with self._session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.warning(
                            f"Attempt {attempt + 1}/{max_retries}: Error {response.status} from Bisq API"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            continue
                        return ""
                    return await response.text()

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries}: Failed to export chat messages: {str(e)}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                logger.error(
                    f"Failed to export chat messages after {max_retries} attempts: {str(e)}"
                )
                return ""
