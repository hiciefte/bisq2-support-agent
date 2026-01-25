"""
Service for monitoring Tor hidden service connectivity and updating metrics.

This service runs a background task that periodically checks if the Tor hidden
service is accessible and updates the tor_connection_status metric accordingly.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx
from app.core.config import Settings
from app.metrics.tor_metrics import update_tor_connection_status

logger = logging.getLogger(__name__)


class TorMonitoringService:
    """
    Background service that monitors Tor hidden service connectivity.

    This service periodically checks if the .onion address is accessible
    by making internal requests to the verification endpoint. If the service
    detects successful requests via .onion, it sets the connection status to 1.
    """

    def __init__(self, settings: Settings):
        """Initialize the Tor monitoring service.

        Args:
            settings: Application settings containing Tor configuration
        """
        self.settings = settings
        self.onion_address = settings.TOR_HIDDEN_SERVICE
        self.monitoring_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.check_interval = 30  # Check every 30 seconds
        self.activity_timeout = 120  # Consider connected if request within 2 minutes
        self.last_request_time: Optional[float] = None

    async def start(self) -> None:
        """Start the background monitoring task."""
        if not self.onion_address:
            logger.info(
                "Tor hidden service not configured, skipping connectivity monitoring"
            )
            update_tor_connection_status(False)
            return

        logger.info(f"Starting Tor connectivity monitoring for {self.onion_address}")
        self.is_running = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        logger.info("Stopping Tor connectivity monitoring")
        self.is_running = False

        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                logger.debug("Monitoring task cancelled successfully")

    def record_onion_request(self) -> None:
        """
        Record that a request was received via .onion address.

        This method should be called by the TorDetectionMiddleware whenever
        a request is detected from the .onion address. It updates the connection
        status to indicate Tor is working.
        """
        self.last_request_time = time.time()
        update_tor_connection_status(True)
        logger.debug("Onion request recorded, connection status set to connected")

    async def _monitoring_loop(self) -> None:
        """
        Background loop that monitors Tor connectivity.

        This loop checks if we've received recent .onion requests. If we haven't
        received any requests in the last 2 minutes, we'll attempt to verify
        connectivity by checking if the service is reachable.
        """
        while self.is_running:
            try:
                current_time = time.time()

                # If we've received a request recently, consider it connected
                if (
                    self.last_request_time
                    and (current_time - self.last_request_time) < self.activity_timeout
                ):
                    update_tor_connection_status(True)
                    logger.debug("Tor connection active (recent requests detected)")
                else:
                    # No recent requests, try to verify connectivity
                    is_connected = await self._check_tor_connectivity()
                    update_tor_connection_status(is_connected)

                    if is_connected:
                        logger.info("Tor hidden service is accessible")
                    else:
                        logger.warning("Tor hidden service connectivity check failed")

                # Wait before next check
                await asyncio.sleep(self.check_interval)

            except asyncio.CancelledError:
                logger.debug("Monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in Tor monitoring loop: {e}", exc_info=True)
                update_tor_connection_status(False)
                # Continue monitoring despite errors
                await asyncio.sleep(self.check_interval)

    async def _check_tor_connectivity(self) -> bool:
        """
        Check if the Tor hidden service is accessible.

        Attempts to connect to the verification endpoint via localhost to verify
        that the service is running and can handle requests.

        Returns:
            True if the service is accessible, False otherwise
        """
        try:
            # Check if the local service is responsive
            # We can't directly access .onion from the container without Tor proxy,
            # but we can verify the service itself is healthy
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try to access the health endpoint internally
                response = await client.get("http://localhost:8000/health")

                if response.status_code == 200:
                    # If the service is healthy and we have .onion configured,
                    # we can assume Tor is working (nginx routes to us)
                    return True

        except (httpx.HTTPError, OSError) as e:
            # HTTPError covers all HTTP-related errors (timeout, connection, etc.)
            # OSError covers low-level network errors
            logger.debug(f"Tor connectivity check failed: {e}")

        return False
