"""
Security utilities for the Bisq Support API.
"""

import logging
import secrets

from fastapi import Request, HTTPException, status

from app.core.config import get_settings

# Get settings instance
settings = get_settings()

# Minimum length for secure API keys
MIN_API_KEY_LENGTH = 24

# Set up logging
logger = logging.getLogger(__name__)


def verify_admin_access(request: Request) -> bool:
    """Verify that the request has admin access.

    Args:
        request: The FastAPI request object

    Returns:
        bool: True if access is granted

    Raises:
        HTTPException: If access is denied with appropriate status code
    """
    admin_api_key = settings.ADMIN_API_KEY

    if not admin_api_key:
        # If ADMIN_API_KEY is not set, deny all access to admin endpoints
        logger.warning("Admin access attempted but ADMIN_API_KEY is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured",
        )

    if len(admin_api_key) < MIN_API_KEY_LENGTH:
        # If ADMIN_API_KEY is too short, warn about insecure key
        logger.warning(
            f"ADMIN_API_KEY is configured with insecure length: {len(admin_api_key)} (min: {MIN_API_KEY_LENGTH})"
        )

    # Check for API key in different locations
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
        if secrets.compare_digest(provided_key, admin_api_key):
            # Key is correct
            if len(provided_key) < MIN_API_KEY_LENGTH:
                logger.warning(
                    f"Successful login with insecure admin key length: {len(provided_key)} chars"
                )
            else:
                logger.debug(
                    f"Admin access granted from {request.client.host if request.client else 'unknown'}"
                )
            return True
        else:
            # Key is incorrect
            logger.warning(
                f"Invalid admin credentials provided from {request.client.host if request.client else 'unknown'}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid admin credentials",
            )

    # No key was provided
    logger.warning(
        f"Missing admin API key from {request.client.host if request.client else 'unknown'}"
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin authentication required"
    )


def generate_secure_key() -> str:
    """Generate a secure random key for use as an API key.

    Returns:
        str: A secure random string of appropriate length
    """
    return secrets.token_urlsafe(MIN_API_KEY_LENGTH)
