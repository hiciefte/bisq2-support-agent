"""
Security utilities for the Bisq Support API.
"""

import os
import secrets
import logging

from fastapi import Request, HTTPException, status

# Admin API key for accessing protected admin endpoints
# No default value for better security - must be set in environment
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# Set up logging
logger = logging.getLogger(__name__)

def verify_admin_access(request: Request) -> bool:
    """Verify that the request has admin access.
    
    Args:
        request: The FastAPI request object
        
    Returns:
        bool: True if access is granted
        
    Raises:
        HTTPException: If access is denied
    """
    if not ADMIN_API_KEY:
        # If ADMIN_API_KEY is not set, deny all access to admin endpoints
        logger.warning("Admin access attempted but ADMIN_API_KEY is not configured")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin access not configured"
        )

    # Check the Authorization header
    auth_header = request.headers.get("Authorization", "")

    # Simple API key validation
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        if token and token == ADMIN_API_KEY and len(token) >= 16:
            return True

    # Check for API key in query params (for easier testing)
    api_key = request.query_params.get("api_key", "")
    if api_key and api_key == ADMIN_API_KEY and len(api_key) >= 16:
        return True

    # Log failed access attempts (but don't include the actual credentials)
    logger.warning(f"Invalid admin access attempt from {request.client.host if request.client else 'unknown'}")
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid admin credentials"
    )

def generate_secure_key() -> str:
    """Generate a secure random key for use as an API key.
    
    Returns:
        str: A secure random string
    """
    return secrets.token_urlsafe(32)
