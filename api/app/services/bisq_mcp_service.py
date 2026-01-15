"""
Bisq 2 MCP Service for live data integration.

This service provides access to live Bisq 2 data including:
- Market prices (BTC/fiat rates)
- Offerbook (current buy/sell offers)
- User reputation scores
- Available markets

Features:
- TTL caching for optimal performance
- Circuit breaker for resilience
- Retry logic with exponential backoff
- Rate limiting
- Input validation and sanitization
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple

import httpx
from app.core.config import Settings
from cachetools import TTLCache  # type: ignore[import-untyped]
from pybreaker import CircuitBreaker, CircuitBreakerError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Security: Input Validation Classes
# =============================================================================


class CurrencyValidator:
    """Validate currency codes to prevent injection attacks."""

    # Valid currency code pattern: 2-5 uppercase letters
    CURRENCY_PATTERN = re.compile(r"^[A-Z]{2,5}$")

    # Known fiat currencies (subset for fast validation)
    KNOWN_FIAT = frozenset(
        [
            "USD",
            "EUR",
            "GBP",
            "CHF",
            "CAD",
            "AUD",
            "JPY",
            "CNY",
            "INR",
            "BRL",
            "MXN",
            "SEK",
            "NOK",
            "DKK",
            "PLN",
            "CZK",
            "HUF",
            "RON",
            "BGN",
            "HRK",
            "RUB",
            "TRY",
            "ZAR",
            "NZD",
            "SGD",
            "HKD",
            "KRW",
            "THB",
            "MYR",
            "PHP",
            "IDR",
            "VND",
            "ARS",
            "CLP",
            "COP",
            "PEN",
            "NGN",
            "KES",
            "GHS",
            "EGP",
            "ILS",
            "AED",
            "SAR",
            "QAR",
            "KWD",
            "BHD",
            "OMR",
        ]
    )

    # Known crypto currencies
    KNOWN_CRYPTO = frozenset(["BTC", "XMR", "LTC", "ETH", "USDT", "USDC", "BSQ"])

    @classmethod
    def validate(cls, currency: str) -> Tuple[bool, str]:
        """Validate a currency code.

        Args:
            currency: The currency code to validate

        Returns:
            Tuple of (is_valid, sanitized_currency_or_error)
        """
        if not currency:
            return False, "Currency code is required"

        # Normalize to uppercase
        normalized = currency.strip().upper()

        # Check pattern
        if not cls.CURRENCY_PATTERN.match(normalized):
            return False, f"Invalid currency code format: {currency}"

        # Allow known currencies or any matching pattern (for new currencies)
        if normalized in cls.KNOWN_FIAT or normalized in cls.KNOWN_CRYPTO:
            return True, normalized

        # For unknown currencies, still allow if pattern matches
        # This supports new currencies added to Bisq
        logger.debug(f"Unknown but valid currency code: {normalized}")
        return True, normalized


class ProfileIdValidator:
    """Validate Bisq profile IDs (Base58 encoded)."""

    # Base58 alphabet (no 0, O, I, l)
    BASE58_PATTERN = re.compile(
        r"^[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{20,50}$"
    )

    @classmethod
    def validate(cls, profile_id: str) -> Tuple[bool, str]:
        """Validate a Bisq profile ID.

        Args:
            profile_id: The profile ID to validate

        Returns:
            Tuple of (is_valid, sanitized_id_or_error)
        """
        if not profile_id:
            return False, "Profile ID is required"

        # Trim whitespace
        normalized = profile_id.strip()

        # Check pattern
        if not cls.BASE58_PATTERN.match(normalized):
            return False, f"Invalid profile ID format: {profile_id[:20]}..."

        return True, normalized


class PromptSanitizer:
    """Sanitize external data before prompt injection."""

    # Patterns that could indicate injection attempts
    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(previous|all|above)", re.IGNORECASE),
        re.compile(r"forget\s+(everything|all|instructions)", re.IGNORECASE),
        re.compile(r"system\s*:\s*", re.IGNORECASE),
        re.compile(r"<\s*script", re.IGNORECASE),
        re.compile(r"\{\{.*\}\}"),  # Template injection
        re.compile(r"\$\{.*\}"),  # Variable injection
        re.compile(r"```.*```", re.DOTALL),  # Code blocks
    ]

    # Maximum lengths for different field types
    MAX_LENGTHS = {
        "currency": 5,
        "profile_id": 50,
        "payment_method": 50,
        "offer_id": 100,
        "general": 500,
    }

    @classmethod
    def sanitize(cls, text: str, field_type: str = "general") -> str:
        """Sanitize text for safe prompt inclusion.

        Args:
            text: The text to sanitize
            field_type: Type of field for length limits

        Returns:
            Sanitized text safe for prompt inclusion
        """
        if not text:
            return ""

        # Convert to string and strip
        sanitized = str(text).strip()

        # Apply length limit
        max_len = cls.MAX_LENGTHS.get(field_type, cls.MAX_LENGTHS["general"])
        if len(sanitized) > max_len:
            sanitized = sanitized[:max_len]

        # Check for injection patterns
        for pattern in cls.INJECTION_PATTERNS:
            if pattern.search(sanitized):
                logger.warning(f"Potential injection pattern detected in {field_type}")
                # Replace with safe placeholder
                sanitized = pattern.sub("[FILTERED]", sanitized)

        # Escape special characters that could affect prompts
        sanitized = sanitized.replace("{", "{{").replace("}", "}}")

        return sanitized


class SecureErrorHandler:
    """Handle errors securely without exposing internals."""

    @staticmethod
    def handle_api_error(error: Exception, operation: str) -> Dict[str, Any]:
        """Create a secure error response.

        Args:
            error: The exception that occurred
            operation: The operation that failed

        Returns:
            Safe error dictionary without stack traces
        """
        error_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

        # Log detailed error internally
        logger.error(
            f"API Error [{error_id}] in {operation}: {type(error).__name__}: {error}",
            exc_info=True,
        )

        # Return safe error to client
        return {
            "success": False,
            "error": f"Service temporarily unavailable. Reference: {error_id}",
            "error_id": error_id,
        }


# =============================================================================
# Live Data Types
# =============================================================================


class LiveDataType(Enum):
    """Types of live data that can be detected in queries."""

    PRICE = "price"
    OFFERS = "offers"
    REPUTATION = "reputation"
    PAYMENT_METHODS = "payment_methods"
    NONE = "none"


# =============================================================================
# Bisq 2 MCP Service
# =============================================================================


class Bisq2MCPService:
    """Service for fetching live Bisq 2 data with caching and resilience."""

    def __init__(self, settings: Settings):
        """Initialize the Bisq 2 MCP Service.

        Args:
            settings: Application settings containing API configuration
        """
        self.settings = settings
        self.base_url = getattr(
            settings, "BISQ_API_URL", "http://bisq2-api:8090"
        ).rstrip("/")
        self.timeout = getattr(settings, "BISQ_API_TIMEOUT", 5)
        self.enabled = getattr(settings, "ENABLE_BISQ_MCP_INTEGRATION", False)

        # Initialize HTTP client with connection pooling
        self._client: Optional[httpx.AsyncClient] = None

        # Initialize caches with TTL
        cache_ttl_prices = getattr(settings, "BISQ_CACHE_TTL_PRICES", 120)
        cache_ttl_offers = getattr(settings, "BISQ_CACHE_TTL_OFFERS", 30)
        cache_ttl_reputation = getattr(settings, "BISQ_CACHE_TTL_REPUTATION", 300)

        self._price_cache: TTLCache = TTLCache(maxsize=100, ttl=cache_ttl_prices)
        self._offers_cache: TTLCache = TTLCache(maxsize=50, ttl=cache_ttl_offers)
        self._reputation_cache: TTLCache = TTLCache(
            maxsize=200, ttl=cache_ttl_reputation
        )
        self._markets_cache: TTLCache = TTLCache(maxsize=1, ttl=cache_ttl_prices)

        # Initialize circuit breaker
        self._circuit_breaker = CircuitBreaker(
            fail_max=5,  # Open after 5 failures
            reset_timeout=60,  # Try again after 60 seconds
        )

        # Rate limiting semaphore
        self._rate_limiter = None  # Will be initialized on first use

        logger.info(
            f"Bisq2MCPService initialized (enabled={self.enabled}, "
            f"base_url={self.base_url}, timeout={self.timeout}s)"
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def _get_rate_limiter(self):
        """Get or create the rate limiter."""
        import asyncio

        if self._rate_limiter is None:
            self._rate_limiter = asyncio.Semaphore(5)  # Max 5 concurrent requests
        return self._rate_limiter

    def _sync_request_wrapper(self, endpoint: str, params: Optional[Dict] = None):
        """Synchronous wrapper for the circuit breaker.

        This wrapper allows pybreaker to track success/failure of our requests.
        It creates a new event loop for synchronous execution.

        Args:
            endpoint: API endpoint path
            params: Optional query parameters

        Returns:
            JSON response as dictionary
        """

        async def _do_request():
            client = await self._get_client()
            response = await client.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()

        # Run the async request in a new event loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_do_request())
        finally:
            loop.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def _make_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an HTTP request with retry logic and circuit breaker.

        Args:
            endpoint: API endpoint path
            params: Optional query parameters

        Returns:
            JSON response as dictionary

        Raises:
            CircuitBreakerError: If circuit breaker is open
            httpx.HTTPError: If request fails after retries
        """
        if not self.enabled:
            logger.debug("Bisq MCP integration disabled, skipping request")
            return {}

        rate_limiter = await self._get_rate_limiter()

        async with rate_limiter:
            try:
                # Use circuit breaker's call method which automatically
                # tracks failures and successes
                return self._circuit_breaker.call(
                    self._sync_request_wrapper, endpoint, params
                )
            except CircuitBreakerError:
                logger.warning(f"Circuit breaker open for request to {endpoint}")
                raise
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                logger.warning(f"Request to {endpoint} failed: {e}")
                raise

    # =========================================================================
    # Core API Methods
    # =========================================================================

    async def get_market_prices(self, currency: Optional[str] = None) -> Dict[str, Any]:
        """Get current market prices.

        Args:
            currency: Optional currency code to filter (e.g., "USD", "EUR")

        Returns:
            Dictionary with market prices
        """
        if not self.enabled:
            return {"error": "Bisq MCP integration disabled", "prices": []}

        # Validate currency if provided
        if currency:
            is_valid, validated = CurrencyValidator.validate(currency)
            if not is_valid:
                return {"error": validated, "prices": []}
            currency = validated

        # Check cache
        cache_key = f"prices_{currency or 'all'}"
        if cache_key in self._price_cache:
            logger.debug(f"Cache hit for {cache_key}")
            return self._price_cache[cache_key]

        try:
            params = {"currency": currency} if currency else None
            response = await self._make_request("/api/v1/market/prices", params)

            # Transform response
            api_result: Dict[str, Any] = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "prices": response.get("prices", []),
                "currency_filter": currency,
            }

            # Cache result
            self._price_cache[cache_key] = api_result
            return api_result

        except CircuitBreakerError:
            return {
                "success": False,
                "error": "Service temporarily unavailable (circuit breaker open)",
                "prices": [],
            }
        except Exception as e:
            return SecureErrorHandler.handle_api_error(e, "get_market_prices")

    async def get_offerbook(
        self,
        currency: Optional[str] = None,
        direction: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get current offerbook.

        Args:
            currency: Optional currency code to filter
            direction: Optional direction filter ("buy" or "sell")

        Returns:
            Dictionary with offers
        """
        if not self.enabled:
            return {"error": "Bisq MCP integration disabled", "offers": []}

        # Validate currency if provided
        if currency:
            is_valid, validated = CurrencyValidator.validate(currency)
            if not is_valid:
                return {"error": validated, "offers": []}
            currency = validated

        # Validate direction if provided
        if direction and direction.lower() not in ("buy", "sell"):
            return {"error": "Direction must be 'buy' or 'sell'", "offers": []}
        if direction:
            direction = direction.lower()

        # Check cache
        cache_key = f"offers_{currency or 'all'}_{direction or 'all'}"
        if cache_key in self._offers_cache:
            logger.debug(f"Cache hit for {cache_key}")
            return self._offers_cache[cache_key]

        try:
            params = {}
            if currency:
                params["currency"] = currency
            if direction:
                params["direction"] = direction

            response = await self._make_request(
                "/api/v1/offerbook", params if params else None
            )

            # Transform response
            api_result: Dict[str, Any] = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "offers": response.get("offers", []),
                "currency_filter": currency,
                "direction_filter": direction,
                "total_count": len(response.get("offers", [])),
            }

            # Cache result
            self._offers_cache[cache_key] = api_result
            return api_result

        except CircuitBreakerError:
            return {
                "success": False,
                "error": "Service temporarily unavailable (circuit breaker open)",
                "offers": [],
            }
        except Exception as e:
            return SecureErrorHandler.handle_api_error(e, "get_offerbook")

    async def get_reputation(self, profile_id: str) -> Dict[str, Any]:
        """Get reputation score for a user profile.

        Args:
            profile_id: Bisq user profile ID (Base58 encoded)

        Returns:
            Dictionary with reputation data
        """
        if not self.enabled:
            return {"error": "Bisq MCP integration disabled", "reputation": None}

        # Validate profile ID
        is_valid, validated = ProfileIdValidator.validate(profile_id)
        if not is_valid:
            return {"error": validated, "reputation": None}
        profile_id = validated

        # Check cache
        cache_key = f"reputation_{profile_id}"
        if cache_key in self._reputation_cache:
            logger.debug(f"Cache hit for {cache_key}")
            return self._reputation_cache[cache_key]

        try:
            response = await self._make_request(
                f"/api/v1/reputation/score/{profile_id}"
            )

            # Transform response
            api_result: Dict[str, Any] = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "profile_id": profile_id,
                "reputation": response.get("reputation", {}),
            }

            # Cache result
            self._reputation_cache[cache_key] = api_result
            return api_result

        except CircuitBreakerError:
            return {
                "success": False,
                "error": "Service temporarily unavailable (circuit breaker open)",
                "reputation": None,
            }
        except Exception as e:
            return SecureErrorHandler.handle_api_error(e, "get_reputation")

    async def get_markets(self) -> Dict[str, Any]:
        """Get list of available markets.

        Returns:
            Dictionary with available markets
        """
        if not self.enabled:
            return {"error": "Bisq MCP integration disabled", "markets": []}

        # Check cache
        cache_key = "markets_all"
        if cache_key in self._markets_cache:
            logger.debug(f"Cache hit for {cache_key}")
            return self._markets_cache[cache_key]

        try:
            response = await self._make_request("/api/v1/markets")

            # Transform response
            result = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "markets": response.get("markets", []),
                "total_count": len(response.get("markets", [])),
            }

            # Cache result
            self._markets_cache[cache_key] = result
            return result

        except CircuitBreakerError:
            return {
                "success": False,
                "error": "Service temporarily unavailable (circuit breaker open)",
                "markets": [],
            }
        except Exception as e:
            return SecureErrorHandler.handle_api_error(e, "get_markets")

    # =========================================================================
    # Formatted Output Methods
    # =========================================================================

    async def get_market_prices_formatted(self, currency: Optional[str] = None) -> str:
        """Get market prices formatted for LLM context.

        Args:
            currency: Optional currency code to filter

        Returns:
            Formatted string suitable for prompt context
        """
        result = await self.get_market_prices(currency)

        if not result.get("success"):
            return (
                f"[Live Price Data Unavailable: {result.get('error', 'Unknown error')}]"
            )

        prices = result.get("prices", [])
        if not prices:
            filter_text = f" for {currency}" if currency else ""
            return f"[No price data available{filter_text}]"

        # Format prices for context
        lines = ["[LIVE MARKET PRICES]"]
        for price in prices[:10]:  # Limit to 10 for context size
            currency_code = PromptSanitizer.sanitize(
                price.get("currency", "???"), "currency"
            )
            rate = price.get("rate", 0)
            lines.append(f"  BTC/{currency_code}: {rate:,.2f}")

        lines.append(f"[Updated: {result.get('timestamp', 'Unknown')}]")
        return "\n".join(lines)

    async def get_offerbook_formatted(
        self,
        currency: Optional[str] = None,
        direction: Optional[str] = None,
        max_offers: int = 5,
    ) -> str:
        """Get offerbook formatted for LLM context.

        Args:
            currency: Optional currency code to filter
            direction: Optional direction filter
            max_offers: Maximum offers to include (default 5)

        Returns:
            Formatted string suitable for prompt context
        """
        result = await self.get_offerbook(currency, direction)

        if not result.get("success"):
            return (
                f"[Live Offer Data Unavailable: {result.get('error', 'Unknown error')}]"
            )

        offers = result.get("offers", [])
        if not offers:
            filter_text = ""
            if currency:
                filter_text += f" for {currency}"
            if direction:
                filter_text += f" ({direction})"
            return f"[No offers currently available{filter_text}]"

        # Format offers for context
        lines = ["[LIVE OFFERBOOK]"]
        for offer in offers[:max_offers]:
            offer_dir = PromptSanitizer.sanitize(
                offer.get("direction", "???"), "general"
            )
            offer_currency = PromptSanitizer.sanitize(
                offer.get("currency", "???"), "currency"
            )
            amount = offer.get("amount", 0)
            price = offer.get("price", 0)
            payment = PromptSanitizer.sanitize(
                offer.get("paymentMethod", "???"), "payment_method"
            )
            lines.append(
                f"  {offer_dir.upper()}: {amount} BTC @ {price:,.2f} {offer_currency} via {payment}"
            )

        lines.append(f"[Total offers: {result.get('total_count', 0)}]")
        lines.append(f"[Updated: {result.get('timestamp', 'Unknown')}]")
        return "\n".join(lines)

    # =========================================================================
    # Intent Detection
    # =========================================================================

    def detect_live_data_needs(
        self, question: str
    ) -> Tuple[LiveDataType, Optional[str]]:
        """Detect if a question requires live data.

        Args:
            question: The user's question

        Returns:
            Tuple of (data_type, extracted_currency)
        """
        if not question:
            return LiveDataType.NONE, None

        question_lower = question.lower()

        # Price-related keywords
        price_keywords = [
            "price",
            "rate",
            "cost",
            "worth",
            "value",
            "how much",
            "current",
            "today",
            "now",
            "btc/",
            "/btc",
        ]

        # Offer-related keywords
        offer_keywords = [
            "offer",
            "buy",
            "sell",
            "trade",
            "available",
            "listing",
            "offerbook",
        ]

        # Reputation keywords
        reputation_keywords = [
            "reputation",
            "trust",
            "score",
            "rating",
            "reliable",
            "profile",
        ]

        # Payment method keywords
        payment_keywords = [
            "payment method",
            "pay with",
            "accept",
            "sepa",
            "zelle",
            "revolut",
            "wise",
            "transferwise",
            "bank transfer",
        ]

        # Detect type
        data_type = LiveDataType.NONE

        if any(kw in question_lower for kw in price_keywords):
            data_type = LiveDataType.PRICE
        elif any(kw in question_lower for kw in offer_keywords):
            data_type = LiveDataType.OFFERS
        elif any(kw in question_lower for kw in reputation_keywords):
            data_type = LiveDataType.REPUTATION
        elif any(kw in question_lower for kw in payment_keywords):
            data_type = LiveDataType.PAYMENT_METHODS

        # Extract currency if detected
        currency = None
        if data_type in (LiveDataType.PRICE, LiveDataType.OFFERS):
            currency = self._extract_currency(question)

        return data_type, currency

    def _extract_currency(self, question: str) -> Optional[str]:
        """Extract currency code from question.

        Args:
            question: The user's question

        Returns:
            Extracted and validated currency code, or None
        """
        # Pattern to find currency codes
        # Look for patterns like "USD", "in EUR", "BTC/USD", etc.
        patterns = [
            r"\b(BTC)[/\\](USD|EUR|GBP|CHF|CAD|AUD|JPY)\b",
            r"\b(USD|EUR|GBP|CHF|CAD|AUD|JPY)\b",
            r"\bin\s+([A-Z]{3})\b",
        ]

        question_upper = question.upper()

        for pattern in patterns:
            match = re.search(pattern, question_upper)
            if match:
                # Get the currency (last group if multiple)
                currency = match.group(match.lastindex or 1)
                is_valid, result = CurrencyValidator.validate(currency)
                if is_valid:
                    return result

        return None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client and clean up resources."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("Bisq2MCPService HTTP client closed")

    async def health_check(self) -> Dict[str, Any]:
        """Check service health.

        Returns:
            Dictionary with health status
        """
        result = {
            "enabled": self.enabled,
            "circuit_breaker_state": self._circuit_breaker.current_state,
            "cache_stats": {
                "prices": len(self._price_cache),
                "offers": len(self._offers_cache),
                "reputation": len(self._reputation_cache),
            },
        }

        if self.enabled:
            try:
                # Try a simple request
                client = await self._get_client()
                response = await client.get("/api/v1/health", timeout=2.0)
                result["api_available"] = response.status_code == 200
            except Exception:
                result["api_available"] = False

        return result
