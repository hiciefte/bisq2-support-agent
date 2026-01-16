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
import unicodedata
from datetime import UTC, datetime
from typing import Any, ClassVar, Dict, List, Optional, Pattern, Tuple

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
    """Validate Bisq profile IDs (Base58 encoded or hex format)."""

    # Base58 alphabet (no 0, O, I, l)
    BASE58_PATTERN = re.compile(
        r"^[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{20,50}$"
    )

    # Hex-encoded profile ID pattern (40 hex characters = 20 bytes)
    HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")

    @classmethod
    def validate(cls, profile_id: str) -> Tuple[bool, str]:
        """Validate a Bisq profile ID.

        Args:
            profile_id: The profile ID to validate (Base58 or hex format)

        Returns:
            Tuple of (is_valid, sanitized_id_or_error)
        """
        if not profile_id:
            return False, "Profile ID is required"

        # Trim whitespace
        normalized = profile_id.strip()

        # Check if it's a valid Base58 profile ID
        if cls.BASE58_PATTERN.match(normalized):
            return True, normalized

        # Check if it's a valid hex-encoded profile ID
        if cls.HEX_PATTERN.match(normalized):
            return True, normalized.lower()  # Normalize to lowercase hex

        return False, f"Invalid profile ID format: {profile_id[:20]}..."


class PromptSanitizer:
    """Sanitize external data before prompt injection."""

    # Patterns that could indicate injection attempts
    INJECTION_PATTERNS: ClassVar[List[Pattern[str]]] = [
        re.compile(r"ignore\s+(previous|all|above)", re.IGNORECASE),
        re.compile(r"forget\s+(everything|all|instructions)", re.IGNORECASE),
        re.compile(r"system\s*:\s*", re.IGNORECASE),
        re.compile(r"<\s*script", re.IGNORECASE),
        re.compile(r"\{\{.*\}\}"),  # Template injection
        re.compile(r"\$\{.*\}"),  # Variable injection
        re.compile(r"```.*```", re.DOTALL),  # Code blocks
    ]

    # Maximum lengths for different field types
    MAX_LENGTHS: ClassVar[Dict[str, int]] = {
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

        # Normalize Unicode FIRST to prevent bypass attacks using homographs
        # NFKC normalizes compatibility characters (e.g., ﬁ → fi, ① → 1)
        sanitized = unicodedata.normalize("NFKC", sanitized)

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
# Reputation Score Conversion
# =============================================================================


def get_five_system_score(total_score: int) -> float:
    """Convert Bisq 2 total reputation score to 0-5 star rating.

    This implements the same logic as Bisq 2's ReputationService.getFiveSystemScore().
    The thresholds are defined in the Bisq 2 Java codebase.

    Args:
        total_score: Raw reputation score (can be 0 to millions)

    Returns:
        Star rating from 0.0 to 5.0 in 0.5 increments
    """
    if total_score < 1_200:
        return 0.0
    elif total_score < 5_000:
        return 0.5
    elif total_score < 15_000:
        return 1.0
    elif total_score < 20_000:
        return 1.5
    elif total_score < 25_000:
        return 2.0
    elif total_score < 30_000:
        return 2.5
    elif total_score < 35_000:
        return 3.0
    elif total_score < 40_000:
        return 3.5
    elif total_score < 60_000:
        return 4.0
    elif total_score < 100_000:
        return 4.5
    else:
        return 5.0


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
        if self._rate_limiter is None:
            self._rate_limiter = asyncio.Semaphore(5)  # Max 5 concurrent requests
        return self._rate_limiter

    def _sync_request_wrapper(self, endpoint: str, params: Optional[Dict] = None):
        """Synchronous wrapper for the circuit breaker.

        This wrapper allows pybreaker to track success/failure of our requests.
        Uses synchronous httpx client to avoid event loop conflicts.

        Args:
            endpoint: API endpoint path
            params: Optional query parameters

        Returns:
            JSON response as dictionary
        """
        # Use synchronous httpx to avoid event loop conflicts
        # The circuit breaker and retry decorators are sync, so this fits better
        with httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
        ) as client:
            response = client.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()

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
                # tracks failures and successes.
                # Wrap in asyncio.to_thread to avoid blocking the event loop
                # since circuit_breaker.call and _sync_request_wrapper are sync.
                return await asyncio.to_thread(
                    self._circuit_breaker.call,
                    self._sync_request_wrapper,
                    endpoint,
                    params,
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
        """Get current market prices from Bisq 2 network.

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
            # Correct Bisq 2 endpoint: /api/v1/market-price/quotes
            response = await self._make_request("/api/v1/market-price/quotes")

            # Parse Bisq 2 response format: {"quotes": {"EUR": {"value": X}, "USD": {"value": Y}, ...}}
            quotes = response.get("quotes", {})

            # Transform to our standard format
            prices = []
            for curr_code, quote_data in quotes.items():
                # Value is in satoshi precision (8 decimals)
                # Convert to human-readable price
                raw_value = quote_data.get("value", 0)
                # The value is stored as: price * 10000 (4 decimal precision for fiat)
                price_value = raw_value / 10000.0 if raw_value else 0
                prices.append({"currency": curr_code, "rate": price_value})

            # Sort by currency code for consistent output
            prices.sort(key=lambda x: x["currency"])

            # Filter by currency if specified
            if currency:
                prices = [p for p in prices if p["currency"] == currency]

            api_result: Dict[str, Any] = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "prices": prices,
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
        """Get current offerbook from Bisq 2 network.

        Args:
            currency: Currency code to filter offers (e.g., "EUR", "USD").
                     If not provided, returns empty with message to specify currency.
            direction: Optional direction filter ("buy" or "sell") - applied client-side

        Returns:
            Dictionary with offers
        """
        if not self.enabled:
            return {"error": "Bisq MCP integration disabled", "offers": []}

        # Currency is required for the Bisq 2 API endpoint
        if not currency:
            return {
                "success": False,
                "error": "Currency code is required (e.g., EUR, USD, CHF)",
                "offers": [],
            }

        # Validate currency
        is_valid, validated = CurrencyValidator.validate(currency)
        if not is_valid:
            return {"error": validated, "offers": []}
        currency = validated

        # Validate direction if provided (for client-side filtering)
        if direction and direction.lower() not in ("buy", "sell"):
            return {"error": "Direction must be 'buy' or 'sell'", "offers": []}
        if direction:
            direction = direction.lower()

        # Check cache
        cache_key = f"offers_{currency}_{direction or 'all'}"
        if cache_key in self._offers_cache:
            logger.debug(f"Cache hit for {cache_key}")
            return self._offers_cache[cache_key]

        try:
            # Correct Bisq 2 endpoint: /api/v1/offerbook/markets/{currencyCode}/offers
            response = await self._make_request(
                f"/api/v1/offerbook/markets/{currency}/offers"
            )

            # Response is a list of OfferItemPresentationDto objects
            # Each contains: bisqEasyOffer, formattedPrice, formattedQuoteAmount, etc.
            raw_offers: list[Any] = response if isinstance(response, list) else []

            # Transform to our standard format
            # Track total count BEFORE direction filtering
            total_before_filter = len(raw_offers)
            offers = []
            for offer_item in raw_offers:
                bisq_offer = offer_item.get("bisqEasyOffer", {})
                offer_direction = bisq_offer.get("direction", "UNKNOWN")

                # Apply client-side direction filter
                if direction:
                    offer_dir_lower = offer_direction.lower() if offer_direction else ""
                    if direction != offer_dir_lower:
                        continue

                # Get market info
                market = bisq_offer.get("market", {})

                # Extract maker profile info from nested structure
                # Path: bisqEasyOffer.makerNetworkId.pubKey.id
                maker_network_id = bisq_offer.get("makerNetworkId", {})
                maker_pub_key = maker_network_id.get("pubKey", {})
                maker_profile_id = maker_pub_key.get("id", "")

                # Extract maker nickname from userProfile
                user_profile = offer_item.get("userProfile", {})
                maker_nickname = user_profile.get("nickName") or user_profile.get(
                    "userName", ""
                )

                offers.append(
                    {
                        "id": bisq_offer.get("id", ""),
                        "direction": offer_direction,
                        "currency": market.get("quoteCurrencyCode", currency),
                        "formattedPrice": offer_item.get("formattedPrice", "N/A"),
                        "formattedQuoteAmount": offer_item.get(
                            "formattedQuoteAmount", "N/A"
                        ),
                        "formattedBaseAmount": offer_item.get(
                            "formattedBaseAmount", "N/A"
                        ),
                        "paymentMethods": offer_item.get("quoteSidePaymentMethods", []),
                        "reputationScore": get_five_system_score(
                            offer_item.get("reputationScore", {}).get("totalScore", 0)
                        ),
                        "formattedDate": offer_item.get("formattedDate", ""),
                        # Price spec percentage (e.g., "+1.00%", "-2.50%", "0.00%")
                        "formattedPriceSpec": offer_item.get(
                            "formattedPriceSpec", "0.00%"
                        ),
                        # Maker profile info for reputation tooltip
                        "makerProfileId": maker_profile_id,
                        "makerNickName": maker_nickname,
                    }
                )

            # Sort offers by reputation score (highest first)
            # This ensures users see the most reputable offers first
            offers.sort(key=lambda o: o.get("reputationScore", 0), reverse=True)

            api_result: Dict[str, Any] = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "offers": offers,
                "currency_filter": currency,
                "direction_filter": direction,
                "total_count": total_before_filter,  # Total BEFORE direction filter
                "filtered_count": len(offers),  # Count AFTER direction filter
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
        """Get reputation score for a user profile from Bisq 2 network.

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
            # Correct Bisq 2 endpoint: /api/v1/reputation/score/{userProfileId}
            response = await self._make_request(
                f"/api/v1/reputation/score/{profile_id}"
            )

            # Response is ReputationScoreDto: {totalScore, fiveSystemScore, ranking}
            # Transform to our standard format
            reputation = {
                "totalScore": response.get("totalScore", 0),
                "fiveSystemScore": response.get("fiveSystemScore", 0.0),
                "ranking": response.get("ranking", 0),
            }

            # Optionally fetch profile age (separate endpoint)
            try:
                age_response = await self._make_request(
                    f"/api/v1/reputation/profile-age/{profile_id}"
                )
                # Response is a Long timestamp or null
                if age_response is not None:
                    # Convert timestamp to days
                    profile_age_ms = (
                        age_response if isinstance(age_response, int) else 0
                    )
                    if profile_age_ms > 0:
                        now_ms = int(datetime.now(UTC).timestamp() * 1000)
                        age_days = (now_ms - profile_age_ms) // (1000 * 60 * 60 * 24)
                        # Clamp to 0 if future timestamp (clock skew protection)
                        reputation["profileAgeDays"] = max(0, age_days)
            except Exception as e:
                logger.debug(f"Could not fetch profile age for {profile_id}: {e}")
                # Profile age is optional, don't fail the whole request

            # Optionally fetch user profile for nickname (separate endpoint)
            try:
                profile_response = await self._make_request(
                    f"/api/v1/user-profiles?ids={profile_id}"
                )
                # Response is array of UserProfileDto
                if profile_response and isinstance(profile_response, list):
                    if len(profile_response) > 0:
                        user_profile = profile_response[0]
                        # Use nickName or userName (they're usually the same)
                        nickname = user_profile.get("nickName") or user_profile.get(
                            "userName"
                        )
                        if nickname:
                            reputation["nickName"] = nickname
                        # Also get nym (randomly generated name)
                        nym = user_profile.get("nym")
                        if nym:
                            reputation["nym"] = nym
            except Exception as e:
                logger.debug(f"Could not fetch user profile for {profile_id}: {e}")
                # User profile is optional, don't fail the whole request

            api_result: Dict[str, Any] = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "profile_id": profile_id,
                "reputation": reputation,
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
        """Get list of available markets from Bisq 2 network.

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
            # Correct Bisq 2 endpoint: /api/v1/offerbook/markets
            response = await self._make_request("/api/v1/offerbook/markets")

            # Response is a list of Market objects:
            # [{"baseCurrencyCode": "BTC", "quoteCurrencyCode": "EUR", ...}, ...]
            raw_markets: list[Any] = response if isinstance(response, list) else []

            # Transform to our standard format
            markets = []
            for market in raw_markets:
                base = market.get("baseCurrencyCode", "BTC")
                quote = market.get("quoteCurrencyCode", "")
                quote_name = market.get("quoteCurrencyName", quote)
                markets.append(
                    {
                        "currency": quote,
                        "name": quote_name,
                        "pair": f"{base}/{quote}",
                    }
                )

            # Sort by currency code
            markets.sort(key=lambda x: x["currency"])

            result = {
                "success": True,
                "timestamp": datetime.now(UTC).isoformat(),
                "markets": markets,
                "total_count": len(markets),
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
            currency: Currency code to filter offers (required)
            direction: Optional direction filter ("buy" or "sell")
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

        # Format offers for context using Bisq 2 formatted fields
        # Use user-centric direction labels to avoid confusion:
        # - Maker's "BUY" offer = User can SELL BTC to them
        # - Maker's "SELL" offer = User can BUY BTC from them
        lines = ["[LIVE OFFERBOOK]"]
        for offer in offers[:max_offers]:
            maker_direction = offer.get("direction", "???").upper()
            # Convert maker direction to user action
            if maker_direction == "BUY":
                offer_dir = "SELL"  # User sells BTC to maker who wants to buy
            elif maker_direction == "SELL":
                offer_dir = "BUY"  # User buys BTC from maker who wants to sell
            else:
                offer_dir = maker_direction
            # Sanitize all external values to prevent prompt injection
            formatted_amount = PromptSanitizer.sanitize(
                offer.get("formattedBaseAmount", "N/A"), "general"
            )
            formatted_price = PromptSanitizer.sanitize(
                offer.get("formattedPrice", "N/A"), "general"
            )
            formatted_quote = PromptSanitizer.sanitize(
                offer.get("formattedQuoteAmount", "N/A"), "general"
            )
            # Join and sanitize payment methods list
            payment_methods = offer.get("paymentMethods", [])
            payment_str = (
                ", ".join(
                    PromptSanitizer.sanitize(pm, "general")
                    for pm in payment_methods[:2]
                )
                if payment_methods
                else "N/A"
            )
            if len(payment_methods) > 2:
                payment_str += f" +{len(payment_methods) - 2} more"
            # Use reputationScore (0.0-5.0 stars) for display
            # Note: get_offerbook stores the fiveSystemScore as 'reputationScore'
            star_raw = offer.get("reputationScore", 0.0)
            star_rating = star_raw if isinstance(star_raw, (int, float)) else 0.0
            price_spec = PromptSanitizer.sanitize(
                offer.get("formattedPriceSpec", "0.00%"), "general"
            )
            # Get maker info for attribution
            maker_id = offer.get("makerProfileId", "")
            maker_name = PromptSanitizer.sanitize(
                offer.get("makerNickName", ""), "general"
            )
            maker_str = f" Maker:{maker_name}" if maker_name else ""
            if maker_id:
                maker_str += f"({maker_id})"
            lines.append(
                f"  {offer_dir.upper()}: {formatted_amount} @ {formatted_price} "
                f"({price_spec}) ({formatted_quote}) via {payment_str} "
                f"[Rep: {star_rating:.1f}]{maker_str}"
            )

        # Show total offers (before any direction filter)
        total_count = result.get("total_count", 0)
        filtered_count = result.get("filtered_count", total_count)
        direction_filter = result.get("direction_filter")
        if direction_filter and filtered_count != total_count:
            # User-centric label for direction filter
            user_action = "SELL" if direction_filter.lower() == "buy" else "BUY"
            lines.append(
                f"[Showing {filtered_count} {user_action} offers out of {total_count} total]"
            )
        else:
            lines.append(f"[Total offers: {total_count}]")
        lines.append(f"[Updated: {result.get('timestamp', 'Unknown')}]")
        return "\n".join(lines)

    async def get_reputation_formatted(self, profile_id: str) -> str:
        """Get reputation data formatted for LLM context.

        Args:
            profile_id: Bisq user profile ID

        Returns:
            Formatted string suitable for prompt context
        """
        result = await self.get_reputation(profile_id)

        if not result.get("success"):
            return (
                f"[Reputation Data Unavailable: {result.get('error', 'Unknown error')}]"
            )

        reputation = result.get("reputation", {})
        if not reputation:
            return f"[No reputation data found for profile {profile_id[:20]}...]"

        # Format reputation for context using Bisq 2 reputation fields
        lines = ["[REPUTATION DATA]"]
        lines.append(f"  Profile ID: {profile_id[:20]}...")
        # Include nickname if available
        if "nickName" in reputation:
            lines.append(f"  Nickname: {reputation.get('nickName')}")
        lines.append(f"  Total Score: {reputation.get('totalScore', 0):,}")
        lines.append(f"  Star Rating: {reputation.get('fiveSystemScore', 0):.1f}/5.0")
        lines.append(f"  Ranking: #{reputation.get('ranking', 'N/A')}")
        if "profileAgeDays" in reputation:
            lines.append(f"  Profile Age: {reputation.get('profileAgeDays')} days")
        lines.append(f"[Updated: {result.get('timestamp', 'Unknown')}]")
        return "\n".join(lines)

    async def get_markets_formatted(self) -> str:
        """Get available markets formatted for LLM context.

        Returns:
            Formatted string suitable for prompt context
        """
        result = await self.get_markets()

        if not result.get("success"):
            return f"[Markets Data Unavailable: {result.get('error', 'Unknown error')}]"

        markets = result.get("markets", [])
        if not markets:
            return "[No markets currently available]"

        # Format markets for context
        lines = ["[AVAILABLE MARKETS]"]
        for market in markets[:15]:  # Limit to 15 for context size
            market_code = PromptSanitizer.sanitize(
                market.get("currency", "???"), "currency"
            )
            market_name = PromptSanitizer.sanitize(market.get("name", ""), "general")
            lines.append(f"  BTC/{market_code}: {market_name}")

        lines.append(f"[Total markets: {result.get('total_count', 0)}]")
        lines.append(f"[Updated: {result.get('timestamp', 'Unknown')}]")
        return "\n".join(lines)

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
