"""
Security utilities for the Bisq Support API.
"""

import asyncio
import logging
import secrets

from app.core.config import get_settings
from fastapi import HTTPException, Request, Response, status

# Get settings instance
settings = get_settings()

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


def verify_admin_key(provided_key: str) -> bool:
    """Verify that the provided API key is valid (synchronous version).

    Args:
        provided_key: The API key to verify

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


def verify_admin_access(request: Request) -> bool:
    """Verify that the request has admin access via cookie or header.

    Args:
        request: The FastAPI request object

    Returns:
        bool: True if access is granted

    Raises:
        HTTPException: If access is denied with appropriate status code
    """
    # First, check for authentication cookie
    auth_cookie = request.cookies.get("admin_authenticated")
    if auth_cookie == "true":
        logger.debug(
            f"Admin access granted via cookie from {request.client.host if request.client else 'unknown'}"
        )
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
        if verify_admin_key(provided_key):
            if len(provided_key) < MIN_API_KEY_LENGTH:
                logger.warning(
                    f"Successful login with insecure admin key length: {len(provided_key)} chars"
                )
            else:
                logger.debug(
                    f"Admin access granted via header from {request.client.host if request.client else 'unknown'}"
                )
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
    """Set secure admin authentication cookie.

    This function sets a secure HTTP-only cookie with appropriate security flags
    based on the deployment environment. For Tor .onion domains or HTTP development
    environments, the secure flag can be disabled via COOKIE_SECURE setting.

    Args:
        response: FastAPI response object to set cookie on
    """
    response.set_cookie(
        key="admin_authenticated",
        value="true",
        max_age=24 * 60 * 60,  # 24 hours
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
