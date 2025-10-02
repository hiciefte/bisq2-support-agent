"""
Tor-specific Prometheus metrics for monitoring .onion service health.
"""

import logging
from typing import Optional

from prometheus_client import Counter, Gauge, Histogram, Info

logger = logging.getLogger(__name__)

# Tor connection metrics
tor_connection_status = Gauge(
    "tor_connection_status",
    "Status of Tor connection (1=connected, 0=disconnected)",
)

tor_hidden_service_configured = Gauge(
    "tor_hidden_service_configured",
    "Whether Tor hidden service is configured (1=yes, 0=no)",
)

tor_onion_address_info = Info(
    "tor_onion_address",
    "Information about the configured .onion address",
)

# Request metrics for .onion traffic
tor_requests_total = Counter(
    "tor_requests_total",
    "Total number of requests received via .onion address",
    ["method", "endpoint", "status"],
)

tor_request_duration_seconds = Histogram(
    "tor_request_duration_seconds",
    "Duration of requests received via .onion address",
    ["method", "endpoint"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Verification endpoint metrics
tor_verification_requests_total = Counter(
    "tor_verification_requests_total",
    "Total requests to .onion verification endpoints",
    ["endpoint", "status"],
)

# Cookie security metrics for Tor
tor_cookie_secure_mode = Gauge(
    "tor_cookie_secure_mode",
    "Cookie secure flag status (1=secure, 0=insecure for .onion)",
)


def update_tor_connection_status(connected: bool) -> None:
    """Update Tor connection status metric.

    Args:
        connected: True if Tor is connected, False otherwise
    """
    tor_connection_status.set(1 if connected else 0)
    logger.debug(f"Tor connection status updated: {connected}")


def update_tor_service_configured(configured: bool, onion_address: Optional[str] = None) -> None:
    """Update Tor hidden service configuration status.

    Args:
        configured: True if hidden service is configured
        onion_address: The .onion address if configured
    """
    tor_hidden_service_configured.set(1 if configured else 0)

    if configured and onion_address:
        # Store .onion address info (only domain, not full URL for privacy)
        tor_onion_address_info.info({
            "address": onion_address,
            "version": "v3",  # Assuming v3 onion addresses
        })
        logger.info(f"Tor hidden service configured: {onion_address}")
    else:
        tor_onion_address_info.info({
            "address": "not_configured",
            "version": "unknown",
        })
        logger.debug("Tor hidden service not configured")


def update_cookie_security_mode(secure: bool) -> None:
    """Update cookie security mode metric.

    Args:
        secure: True if cookies are in secure mode (HTTPS), False for .onion (HTTP)
    """
    tor_cookie_secure_mode.set(1 if secure else 0)
    logger.debug(f"Cookie secure mode: {secure}")


def record_tor_request(method: str, endpoint: str, status: int, duration: float) -> None:
    """Record metrics for a request received via .onion.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Request endpoint/path
        status: HTTP status code
        duration: Request duration in seconds
    """
    tor_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
    tor_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def record_verification_request(endpoint: str, status: int) -> None:
    """Record metrics for .onion verification endpoint requests.

    Args:
        endpoint: Verification endpoint path
        status: HTTP status code
    """
    tor_verification_requests_total.labels(endpoint=endpoint, status=status).inc()
    logger.debug(f"Verification request recorded: {endpoint} -> {status}")
