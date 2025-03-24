"""
Security utilities for the Bisq Support API.
"""

import os
import secrets
import logging

from fastapi import Request, HTTPException, status

from app.core.config import get_settings

# Get settings instance
settings = get_settings()

# Admin API key for accessing protected admin endpoints
# No default value for better security - must be set in environment
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

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
    if not ADMIN_API_KEY:
        # If ADMIN_API_KEY is not set, deny all access to admin endpoints
        logger.warning("Admin access attempted but ADMIN_API_KEY is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured"
        )

    if len(ADMIN_API_KEY) < MIN_API_KEY_LENGTH:
        # If ADMIN_API_KEY is too short, warn about insecure key
        logger.warning(
            f"ADMIN_API_KEY is configured with insecure length: {len(ADMIN_API_KEY)} (min: {MIN_API_KEY_LENGTH})")

    # Check the Authorization header
    auth_header = request.headers.get("Authorization", "")

    # Simple API key validation
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        if token and token == ADMIN_API_KEY and len(token) >= MIN_API_KEY_LENGTH:
            # Record successful login attempts at debug level for audit
            logger.debug(
                f"Admin access granted via Bearer token from {request.client.host if request.client else 'unknown'}")
            return True
        elif token and token == ADMIN_API_KEY and len(token) < MIN_API_KEY_LENGTH:
            logger.warning(f"Insecure admin key length: {len(token)} chars")
            # Allow access but warn that key is too short
            return True

    # Only allow query parameter authentication in development environments
    is_production = settings.ENVIRONMENT.lower() == 'production'
    if not is_production:
        # Check for API key in query params (for easier testing)
        api_key = request.query_params.get("api_key", "")
        if api_key and api_key == ADMIN_API_KEY and len(api_key) >= MIN_API_KEY_LENGTH:
            logger.debug(
                f"Admin access granted via query parameter from {request.client.host if request.client else 'unknown'}")
            return True
        elif api_key and api_key == ADMIN_API_KEY and len(api_key) < MIN_API_KEY_LENGTH:
            logger.warning(f"Insecure admin key length: {len(api_key)} chars")
            # Allow access but warn that key is too short
            return True

    # Log failed access attempts (but don't include the actual credentials)
    logger.warning(
        f"Invalid admin access attempt from {request.client.host if request.client else 'unknown'}")

    # Check if the user provided a key that was incorrect vs. no key at all
    has_key_attempt = auth_header.startswith("Bearer ") or (
            not is_production and request.query_params.get("api_key", "") != "")

    if has_key_attempt:
        # User tried to authenticate but used wrong credentials - 403 Forbidden
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin credentials"
        )
    else:
        # User didn't provide any credentials - 401 Unauthorized
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )


def generate_secure_key() -> str:
    """Generate a secure random key for use as an API key.

    Returns:
        str: A secure random string of appropriate length
    """
    return secrets.token_urlsafe(MIN_API_KEY_LENGTH)
