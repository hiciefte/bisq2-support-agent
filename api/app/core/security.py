"""
Security utilities for the Bisq Support API.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time

from app.core.config import Settings, get_settings
from fastapi import Depends, HTTPException, Request, Response, status

# Minimum length for secure API keys
MIN_API_KEY_LENGTH = 24

# Set up logging
logger = logging.getLogger(__name__)

# Cryptographically secure random number generator for timing delays
secure_random = secrets.SystemRandom()


async def verify_admin_key_with_delay(provided_key: str, request: Request) -> bool:
    """Verify API key with timing attack resistance.

    Implements constant-time comparison with random delay to prevent timing attacks
    and deferred logging to avoid information leakage.

    Args:
        provided_key: The API key to verify
        request: The FastAPI request object (for deferred logging)

    Returns:
        bool: True if the key is valid

    Raises:
        HTTPException: If admin access is not configured
    """
    settings = get_settings()
    admin_api_key = settings.ADMIN_API_KEY

    if not admin_api_key:
        # Deferred logging - log after delay
        log_message = "Admin access attempted but ADMIN_API_KEY is not configured"
        await asyncio.sleep(secure_random.uniform(0.05, 0.15))
        logger.warning(log_message)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured",
        )

    # Constant-time comparison (already implemented)
    is_valid = secrets.compare_digest(provided_key, admin_api_key)

    # Random delay to prevent timing attacks (50-150ms)
    await asyncio.sleep(secure_random.uniform(0.05, 0.15))

    # Deferred logging based on result
    if not is_valid:
        logger.warning(
            f"Invalid admin credentials from {request.client.host if request.client else 'unknown'}"
        )
    elif len(admin_api_key) < MIN_API_KEY_LENGTH:
        logger.warning(
            f"Successful login with insecure admin key length: {len(provided_key)} chars"
        )
    else:
        logger.debug(
            f"Admin access granted via header from {request.client.host if request.client else 'unknown'}"
        )

    return is_valid


def verify_admin_key(provided_key: str, settings: Settings) -> bool:
    """Verify that the provided API key is valid (synchronous version).

    Args:
        provided_key: The API key to verify
        settings: Application settings instance

    Returns:
        bool: True if the key is valid

    Raises:
        HTTPException: If admin access is not configured
    """
    admin_api_key = settings.ADMIN_API_KEY

    if not admin_api_key:
        logger.warning("Admin access attempted but ADMIN_API_KEY is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured",
        )

    if len(admin_api_key) < MIN_API_KEY_LENGTH:
        logger.warning(
            f"ADMIN_API_KEY is configured with insecure length: {len(admin_api_key)} (min: {MIN_API_KEY_LENGTH})"
        )

    return secrets.compare_digest(provided_key, admin_api_key)


def _b64url(data: bytes) -> str:
    """Base64 URL-safe encoding without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    """Base64 URL-safe decoding with padding restoration."""
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def _sign(data: bytes, key: str) -> str:
    """Create HMAC signature of data using the admin API key."""
    mac = hmac.new(key.encode(), data, hashlib.sha256).digest()
    return _b64url(mac)


def generate_admin_session_token(now: int | None = None) -> str:
    """Generate a signed, time-bounded session token.

    Creates a stateless session token containing:
    - Subject: "admin"
    - Issued at: current timestamp
    - Expiration: issued at + ADMIN_SESSION_MAX_AGE

    The token is signed with HMAC-SHA256 using the ADMIN_API_KEY,
    preventing forgery without knowledge of the key.

    Args:
        now: Current timestamp (optional, for testing)

    Returns:
        Signed session token in format: base64(payload).base64(signature)
    """
    settings = get_settings()
    now = now or int(time.time())
    payload = {
        "sub": "admin",
        "iat": now,
        "exp": now + settings.ADMIN_SESSION_MAX_AGE,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = _sign(body.encode(), settings.ADMIN_API_KEY)
    return f"{body}.{sig}"


def verify_admin_session_token(token: str) -> bool:
    """Verify a signed session token.

    Validates:
    1. Token signature using HMAC-SHA256
    2. Token has not expired

    Args:
        token: Session token to verify

    Returns:
        True if token is valid and not expired, False otherwise
    """
    try:
        settings = get_settings()
        body_b64, sig = token.split(".", 1)
        expected = _sign(body_b64.encode(), settings.ADMIN_API_KEY)
        if not hmac.compare_digest(sig, expected):
            logger.warning("Invalid session token signature")
            return False
        payload = json.loads(_b64url_decode(body_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            logger.debug("Session token has expired")
            return False
        return True
    except Exception as e:
        logger.warning(f"Session token verification failed: {e}")
        return False


def verify_admin_access(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> bool:
    """Verify that the request has admin access via cookie or header.

    Implements sliding session window by refreshing the authentication cookie
    on each successful verification. This extends the session as long as the
    user remains active, while inactive sessions expire after ADMIN_SESSION_MAX_AGE.

    Args:
        request: The FastAPI request object
        response: The FastAPI response object (for refreshing cookie)
        settings: Application settings (injected via dependency)

    Returns:
        bool: True if access is granted

    Raises:
        HTTPException: If access is denied with appropriate status code
    """
    # First, check for authentication cookie
    auth_cookie = request.cookies.get("admin_authenticated")
    if auth_cookie and verify_admin_session_token(auth_cookie):
        logger.debug(
            f"Admin access granted via cookie from {request.client.host if request.client else 'unknown'}"
        )
        # Refresh cookie to implement sliding session window
        set_admin_cookie(response)
        return True

    # Fallback to API key in headers (for backward compatibility)
    provided_key = (
        request.headers.get("X-API-KEY")
        or request.query_params.get("api_key")
        or (
            request.headers.get("Authorization", "").replace("Bearer ", "")
            if request.headers.get("Authorization", "").startswith("Bearer ")
            else None
        )
    )

    if provided_key:
        if verify_admin_key(provided_key, settings):
            if len(provided_key) < MIN_API_KEY_LENGTH:
                logger.warning(
                    f"Successful login with insecure admin key length: {len(provided_key)} chars"
                )
            else:
                logger.debug(
                    f"Admin access granted via header from {request.client.host if request.client else 'unknown'}"
                )
            # Set session cookie after successful header-based auth for better UX
            set_admin_cookie(response)
            return True
        else:
            logger.warning(
                f"Invalid admin credentials provided from {request.client.host if request.client else 'unknown'}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin credentials",
            )

    # No authentication found
    logger.warning(
        f"Missing admin authentication from {request.client.host if request.client else 'unknown'}"
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required"
    )


def set_admin_cookie(response: Response) -> None:
    """Set secure admin authentication cookie with sliding session window.

    This function sets a secure HTTP-only cookie with appropriate security flags
    based on the deployment environment. For Tor .onion domains or HTTP development
    environments, the secure flag can be disabled via COOKIE_SECURE setting.

    The cookie implements a sliding session window - it is refreshed on each
    authenticated request, extending the session as long as the user remains active.
    Inactive sessions will expire after ADMIN_SESSION_MAX_AGE seconds.

    Args:
        response: FastAPI response object to set cookie on
    """
    settings = get_settings()
    token = generate_admin_session_token()
    response.set_cookie(
        key="admin_authenticated",
        value=token,
        max_age=settings.ADMIN_SESSION_MAX_AGE,  # Configurable session duration
        httponly=True,  # Prevents XSS access
        secure=settings.COOKIE_SECURE,  # Configurable for .onion/HTTP environments
        samesite="lax",  # Provides CSRF protection while allowing cross-site navigation
        path="/",  # Ensure cookie is available for all paths
    )


def clear_admin_cookie(response: Response) -> None:
    """Clear admin authentication cookie.

    Args:
        response: FastAPI response object to clear cookie on
    """
    # Use minimal parameters for maximum compatibility across FastAPI/Starlette versions
    response.delete_cookie(
        key="admin_authenticated",
        path="/",  # Ensure cookie is deleted from all paths
    )


def generate_secure_key() -> str:
    """Generate a secure random key for use as an API key.

    Returns:
        str: A secure random string of appropriate length
    """
    return secrets.token_urlsafe(MIN_API_KEY_LENGTH)
