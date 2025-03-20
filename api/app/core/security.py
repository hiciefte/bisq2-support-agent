"""
Security utilities for the Bisq Support API.
"""

import os

from fastapi import Request, HTTPException, status

# Admin API key for accessing protected admin endpoints
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin access not configured"
        )

    # Check the Authorization header
    auth_header = request.headers.get("Authorization", "")

    # Simple API key validation
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        if token == ADMIN_API_KEY:
            return True

    # Check for API key in query params (for easier testing)
    api_key = request.query_params.get("api_key", "")
    if api_key == ADMIN_API_KEY:
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid admin credentials"
    )
