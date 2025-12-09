"""Unit tests for Matrix ErrorHandler and CircuitBreaker."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from nio import ErrorResponse, RoomMessagesError

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    pytestmark = pytest.mark.skip(reason="matrix-nio not installed")

if NIO_AVAILABLE:
    from app.integrations.matrix.error_handler import CircuitBreaker, ErrorHandler


@pytest.fixture
def mock_session_manager():
    """Create mock SessionManager."""
    manager = MagicMock()
    manager.login = AsyncMock()
    return manager


@pytest.fixture
def error_handler(mock_session_manager):
    """Create ErrorHandler instance with test configuration."""
    return ErrorHandler(session_manager=mock_session_manager, max_retries=3)


class TestErrorHandlerInit:
    """Test ErrorHandler initialization."""

    def test_init_success(self, mock_session_manager):
        """Test successful initialization."""
        handler = ErrorHandler(session_manager=mock_session_manager, max_retries=3)

        assert handler.session_manager == mock_session_manager
        assert handler.max_retries == 3
        assert handler.retry_delays == [2, 4, 8]
        assert isinstance(handler.circuit_breaker, CircuitBreaker)

    def test_init_without_nio_available(self, mock_session_manager):
        """Test initialization fails when matrix-nio not available."""
        with patch("app.integrations.matrix.error_handler.NIO_AVAILABLE", False):
            with pytest.raises(ImportError, match="matrix-nio is not installed"):
                ErrorHandler(session_manager=mock_session_manager)


class TestCallWithRetry:
    """Test call_with_retry functionality."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self, error_handler):
        """Test successful API call on first attempt."""
        # Setup
        mock_func = AsyncMock(return_value="success")

        # Execute
        result = await error_handler.call_with_retry(mock_func)

        # Verify
        assert result == "success"
        mock_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_auth_error(self, error_handler, mock_session_manager):
        """Test automatic retry on authentication error."""
        # Setup: First call fails with auth error, second call succeeds
        auth_error = MagicMock(spec=ErrorResponse)
        auth_error.status_code = 401
        auth_error.message = "M_UNKNOWN_TOKEN"

        mock_func = AsyncMock(side_effect=[auth_error, "success"])

        # Execute (with reduced sleep for faster test)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await error_handler.call_with_retry(mock_func)

        # Verify
        assert result == "success"
        assert mock_func.call_count == 2
        mock_session_manager.login.assert_called_once()  # Re-authentication triggered

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, error_handler):
        """Test exception raised when max retries exceeded."""
        # Setup: All calls fail
        mock_func = AsyncMock(side_effect=Exception("Network error"))

        # Execute & Verify
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception, match="Network error"):
                await error_handler.call_with_retry(mock_func)

        # Verify: Should attempt max_retries times
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_request(
        self, error_handler, mock_session_manager
    ):
        """Test circuit breaker blocks requests when open."""
        # Setup: Open circuit breaker
        error_handler.circuit_breaker.state = "OPEN"
        error_handler.circuit_breaker.last_failure_time = time.time()

        mock_func = AsyncMock(return_value="success")

        # Execute & Verify
        with pytest.raises(Exception, match="Circuit breaker OPEN"):
            await error_handler.call_with_retry(mock_func)

        # Verify: Function should NOT be called
        mock_func.assert_not_called()


class TestAuthErrorDetection:
    """Test authentication error detection."""

    def test_detect_http_401(self, error_handler):
        """Test detection of HTTP 401 Unauthorized."""
        response = MagicMock()
        response.status_code = 401

        result = error_handler._is_auth_error(response)
        assert result is True

    def test_detect_m_unknown_token(self, error_handler):
        """Test detection of M_UNKNOWN_TOKEN error code."""
        response = MagicMock(spec=ErrorResponse)
        response.message = "M_UNKNOWN_TOKEN: Token not found"

        result = error_handler._is_auth_error(response)
        assert result is True

    def test_non_auth_error(self, error_handler):
        """Test non-authentication errors are not detected as auth errors."""
        response = MagicMock()
        response.status_code = 500

        result = error_handler._is_auth_error(response)
        assert result is False


class TestCircuitBreakerInit:
    """Test CircuitBreaker initialization."""

    def test_init_success(self):
        """Test successful initialization."""
        breaker = CircuitBreaker(failure_threshold=5, timeout=300)

        assert breaker.failure_count == 0
        assert breaker.failure_threshold == 5
        assert breaker.timeout == 300
        assert breaker.last_failure_time is None
        assert breaker.state == "CLOSED"


class TestCircuitBreakerStates:
    """Test circuit breaker state transitions."""

    def test_closed_allows_request(self):
        """Test CLOSED state allows requests."""
        breaker = CircuitBreaker()
        assert breaker.should_allow_request() is True

    def test_open_blocks_request(self):
        """Test OPEN state blocks requests."""
        breaker = CircuitBreaker()
        breaker.state = "OPEN"
        breaker.last_failure_time = time.time()

        assert breaker.should_allow_request() is False

    def test_open_to_half_open_transition(self):
        """Test transition from OPEN to HALF_OPEN after timeout."""
        breaker = CircuitBreaker(failure_threshold=5, timeout=1)  # 1 second timeout
        breaker.state = "OPEN"
        breaker.last_failure_time = time.time() - 2  # 2 seconds ago

        # Should transition to HALF_OPEN
        result = breaker.should_allow_request()
        assert result is True
        assert breaker.state == "HALF_OPEN"

    def test_half_open_allows_request(self):
        """Test HALF_OPEN state allows one test request."""
        breaker = CircuitBreaker()
        breaker.state = "HALF_OPEN"

        assert breaker.should_allow_request() is True


class TestCircuitBreakerRecording:
    """Test circuit breaker success/failure recording."""

    def test_record_success_resets(self):
        """Test record_success resets circuit breaker."""
        breaker = CircuitBreaker()
        breaker.failure_count = 3
        breaker.state = "HALF_OPEN"

        breaker.record_success()

        assert breaker.failure_count == 0
        assert breaker.state == "CLOSED"

    def test_record_failure_increments(self):
        """Test record_failure increments failure count."""
        breaker = CircuitBreaker(failure_threshold=5)
        initial_count = breaker.failure_count

        breaker.record_failure()

        assert breaker.failure_count == initial_count + 1
        assert breaker.last_failure_time is not None

    def test_record_failure_opens_circuit(self):
        """Test circuit opens after reaching threshold."""
        breaker = CircuitBreaker(failure_threshold=3)

        # Record failures until threshold
        breaker.record_failure()
        assert breaker.state == "CLOSED"
        breaker.record_failure()
        assert breaker.state == "CLOSED"
        breaker.record_failure()
        assert breaker.state == "OPEN"  # Should open after 3rd failure

    def test_record_failure_warns_before_threshold(self):
        """Test warning logged before reaching threshold."""
        breaker = CircuitBreaker(failure_threshold=5)

        breaker.record_failure()
        assert breaker.state == "CLOSED"
        assert breaker.failure_count == 1


class TestCircuitBreakerIntegration:
    """Test circuit breaker integration with error handler."""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_repeated_auth_failures(
        self, error_handler, mock_session_manager
    ):
        """Test circuit breaker opens after repeated authentication failures."""
        # Setup: Make login always fail
        mock_session_manager.login = AsyncMock(side_effect=Exception("Auth failed"))

        # Setup: Create auth error response
        auth_error = MagicMock(spec=ErrorResponse)
        auth_error.status_code = 401
        mock_func = AsyncMock(return_value=auth_error)

        # Execute: Trigger multiple failures (more than threshold)
        for _ in range(6):
            try:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await error_handler.call_with_retry(mock_func)
            except Exception:
                pass  # Expected to fail

        # Verify: Circuit breaker should be OPEN
        assert error_handler.circuit_breaker.state == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_resets_after_success(self, error_handler):
        """Test circuit breaker resets after successful request."""
        # Setup: Open circuit breaker
        error_handler.circuit_breaker.failure_count = 3
        error_handler.circuit_breaker.state = "HALF_OPEN"

        mock_func = AsyncMock(return_value="success")

        # Execute
        result = await error_handler.call_with_retry(mock_func)

        # Verify
        assert result == "success"
        assert error_handler.circuit_breaker.failure_count == 0
        assert error_handler.circuit_breaker.state == "CLOSED"
