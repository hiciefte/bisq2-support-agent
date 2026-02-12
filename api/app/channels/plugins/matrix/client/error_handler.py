"""Matrix API error handling with automatic retry logic."""

import asyncio
import logging
import time
from typing import Any, Callable, Optional

try:
    from nio import ErrorResponse, RoomMessagesError

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    ErrorResponse = None
    RoomMessagesError = None

from app.channels.plugins.matrix.metrics import (
    matrix_api_calls_total,
    matrix_api_retry_total,
    matrix_auth_failures_total,
    matrix_circuit_breaker_state,
)

logger = logging.getLogger(__name__)


class ErrorHandler:
    """Handles Matrix API errors with automatic retry and circuit breaker.

    Provides:
    - Automatic token refresh on M_UNKNOWN_TOKEN errors
    - Exponential backoff for network failures
    - Circuit breaker to prevent repeated failed authentication attempts

    Attributes:
        session_manager: SessionManager instance for re-authentication
        max_retries: Maximum retry attempts per API call (default: 3)
        retry_delays: Exponential backoff delays in seconds [2, 4, 8]
        circuit_breaker: Circuit breaker instance for auth failure protection
    """

    def __init__(self, session_manager, max_retries: int = 3):
        """Initialize error handler.

        Args:
            session_manager: SessionManager instance for re-authentication
            max_retries: Maximum retry attempts per API call (default: 3)
        """
        if not NIO_AVAILABLE:
            raise ImportError(
                "matrix-nio is not installed. Install with: pip install matrix-nio"
            )

        self.session_manager = session_manager
        self.max_retries = max_retries
        self.retry_delays = [2, 4, 8]  # Exponential backoff (seconds)
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5, timeout=300
        )  # 5 min timeout

    async def call_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """Wrap Matrix API calls with automatic retry on failures.

        Handles:
        - Authentication errors (M_UNKNOWN_TOKEN) with automatic re-login
        - Network errors with exponential backoff
        - Circuit breaker protection for repeated auth failures

        Args:
            func: Async function to call (Matrix API method)
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result from successful func execution

        Raises:
            Exception: If max retries exceeded or circuit breaker open
        """
        # Extract method name for metrics (default to "unknown")
        # Use pop() to remove method_name from kwargs so it's not passed to the underlying function
        method_name = kwargs.pop(
            "method_name", func.__name__ if hasattr(func, "__name__") else "unknown"
        )

        # Check circuit breaker before allowing request
        if not self.circuit_breaker.should_allow_request():
            raise Exception(
                "Circuit breaker OPEN - too many authentication failures. "
                f"Wait {self.circuit_breaker.timeout}s before retry."
            )

        for attempt in range(self.max_retries):
            try:
                response = await func(*args, **kwargs)

                # Check for authentication errors
                if self._is_auth_error(response):
                    matrix_auth_failures_total.labels(error_type="token_expired").inc()

                    if attempt < self.max_retries - 1:
                        matrix_api_retry_total.labels(method=method_name).inc()
                        logger.warning(
                            f"Auth error detected (attempt {attempt + 1}/{self.max_retries}), "
                            f"re-authenticating..."
                        )
                        try:
                            await self.session_manager.login()  # Re-authenticate
                            self.circuit_breaker.record_success()  # Reset circuit breaker
                        except Exception as auth_error:
                            self.circuit_breaker.record_failure()  # Increment failure count
                            raise auth_error

                        await asyncio.sleep(self.retry_delays[attempt])
                        continue
                    else:
                        self.circuit_breaker.record_failure()
                        matrix_api_calls_total.labels(
                            method=method_name, result="failure"
                        ).inc()
                        raise Exception("Max retries exceeded for authentication error")

                # Success - reset circuit breaker and return
                self.circuit_breaker.record_success()
                matrix_api_calls_total.labels(
                    method=method_name, result="success"
                ).inc()
                return response

            except Exception as e:
                if attempt < self.max_retries - 1:
                    delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                    matrix_api_retry_total.labels(method=method_name).inc()
                    matrix_auth_failures_total.labels(error_type="network_error").inc()
                    logger.error(
                        f"Request failed: {e} (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Request failed after {self.max_retries} attempts: {e}"
                    )
                    matrix_api_calls_total.labels(
                        method=method_name, result="failure"
                    ).inc()
                    raise

    def _is_auth_error(self, response) -> bool:
        """Detect authentication errors from Matrix API responses.

        Checks for:
        - HTTP 401 Unauthorized
        - M_UNKNOWN_TOKEN error code (token expired/invalid)

        Args:
            response: Matrix API response object

        Returns:
            True if response indicates authentication error, False otherwise
        """
        # Check for HTTP 401
        if hasattr(response, "status_code") and response.status_code == 401:
            logger.debug("Detected HTTP 401 Unauthorized")
            return True

        # Check for M_UNKNOWN_TOKEN error code
        if isinstance(response, (ErrorResponse, RoomMessagesError)):
            if hasattr(response, "message") and "M_UNKNOWN_TOKEN" in str(
                response.message
            ):
                logger.debug("Detected M_UNKNOWN_TOKEN error")
                return True

        return False


class CircuitBreaker:
    """Circuit breaker pattern for authentication failure protection.

    Prevents repeated failed authentication attempts that could:
    - Lock user accounts
    - Trigger rate limiting on Matrix homeserver
    - Waste resources on known-failing operations

    States:
    - CLOSED: Normal operation, requests allowed
    - OPEN: Too many failures, requests blocked for timeout period
    - HALF_OPEN: Testing recovery after timeout

    Attributes:
        failure_count: Current consecutive failure count
        failure_threshold: Failures before opening circuit (default: 5)
        timeout: Seconds to wait before allowing retry (default: 300)
        last_failure_time: Timestamp of last failure (for timeout calculation)
        state: Current circuit state (CLOSED, OPEN, HALF_OPEN)
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 300):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Consecutive failures before opening circuit (default: 5)
            timeout: Seconds to wait in OPEN state before HALF_OPEN (default: 300)
        """
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout  # seconds
        self.last_failure_time: Optional[float] = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def should_allow_request(self) -> bool:
        """Check if request should be allowed based on circuit state.

        Returns:
            True if request should proceed, False if blocked by circuit breaker
        """
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            # Check if timeout expired → transition to HALF_OPEN
            if time.time() - self.last_failure_time > self.timeout:
                logger.info(
                    "Circuit breaker transitioning to HALF_OPEN (timeout expired)"
                )
                self.state = "HALF_OPEN"
                matrix_circuit_breaker_state.set(2)  # 2 = HALF_OPEN
                return True
            logger.warning("Circuit breaker OPEN - request blocked")
            return False

        if self.state == "HALF_OPEN":
            # Allow one test request in HALF_OPEN state
            return True

        return False

    def record_success(self) -> None:
        """Record successful operation - reset circuit breaker."""
        if self.failure_count > 0 or self.state != "CLOSED":
            logger.info(
                f"Circuit breaker reset (was {self.state} with {self.failure_count} failures)"
            )
        self.failure_count = 0
        self.state = "CLOSED"
        matrix_circuit_breaker_state.set(0)  # 0 = CLOSED

    def record_failure(self) -> None:
        """Record failed operation - increment failure count and open circuit if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            logger.critical(
                f"Circuit breaker opened after {self.failure_count} consecutive failures "
                f"(threshold: {self.failure_threshold})"
            )
            self.state = "OPEN"
            matrix_circuit_breaker_state.set(1)  # 1 = OPEN
        else:
            logger.warning(
                f"Circuit breaker failure count: {self.failure_count}/{self.failure_threshold}"
            )
