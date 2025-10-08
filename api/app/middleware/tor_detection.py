"""
Middleware for detecting and tracking requests from Tor .onion addresses.

This middleware intercepts all HTTP requests and checks if they originated from
a .onion address by examining the Host header. When .onion requests are detected,
it records metrics for monitoring Tor traffic.
"""

import logging
import time
from typing import Callable

from app.core.config import get_settings
from app.core.tor_metrics import record_tor_request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class TorDetectionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to detect and track requests received via Tor .onion address.

    This middleware:
    1. Examines the Host header of incoming requests
    2. Detects if the request came through a .onion address
    3. Records metrics for .onion traffic (request count, duration, status)
    4. Passes the request through to the application
    """

    def __init__(self, app):
        super().__init__(app)
        settings = get_settings()
        self.onion_address = (
            settings.TOR_HIDDEN_SERVICE.lower() if settings.TOR_HIDDEN_SERVICE else ""
        )

        if self.onion_address:
            logger.info(
                f"Tor detection middleware initialized for: {self.onion_address}"
            )
        else:
            logger.info(
                "Tor detection middleware initialized (no .onion address configured)"
            )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process each request and track .onion traffic.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in the chain

        Returns:
            Response from the application
        """
        # Record start time for duration tracking
        start_time = time.time()

        # Check if this request came via .onion
        host_header = request.headers.get("host", "").lower()
        is_onion_request = False

        if self.onion_address and host_header:
            # Check if the host header matches our .onion address
            # Handle both "domain.onion" and "domain.onion:port" formats
            is_onion_request = (
                host_header == self.onion_address
                or host_header.startswith(f"{self.onion_address}:")
            )

        # Process the request
        response = await call_next(request)

        # If this was a .onion request, record metrics
        if is_onion_request:
            duration = time.time() - start_time
            method = request.method
            path = request.url.path
            status = response.status_code

            # Record the metrics
            record_tor_request(
                method=method, endpoint=path, status=status, duration=duration
            )

            logger.debug(
                f"Tor request tracked: {method} {path} -> {status} ({duration:.3f}s)"
            )

        return response
