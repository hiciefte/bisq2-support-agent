"""
Admin authentication routes for the Bisq Support API.
"""

import logging
from typing import Any, Dict

from app.core.exceptions import AuthenticationError, BaseAppException
from app.core.security import (
    clear_admin_cookie,
    set_admin_cookie,
    verify_admin_key_with_delay,
)
from app.models.feedback import AdminLoginRequest, AdminLoginResponse
from fastapi import APIRouter, Request, status
from fastapi.responses import Response

# Setup logging
logger = logging.getLogger(__name__)

# Create authentication router without dependencies for login/logout endpoints
router = APIRouter(
    prefix="/admin/auth",
    tags=["Admin Auth"],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(
    login_request: AdminLoginRequest, response: Response, request: Request
):
    """Authenticate admin user and set secure session cookie.

    This endpoint validates the provided API key with timing attack resistance
    and sets an HTTP-only cookie for secure session management. The cookie prevents
    XSS attacks and provides automatic CSRF protection.

    Security features:
    - Constant-time key comparison
    - Random delay to prevent timing attacks (50-150ms)
    - Deferred logging to avoid information leakage

    Args:
        login_request: Login credentials containing API key
        response: FastAPI response object for setting cookies
        request: FastAPI request object for logging

    Returns:
        AdminLoginResponse: Login success confirmation

    Raises:
        AuthenticationError: If credentials are invalid or admin access not configured
        BaseAppException: If an unexpected error occurs during login
    """
    # No logging before verification to prevent timing attacks

    try:
        # Verify the API key with timing attack resistance
        if await verify_admin_key_with_delay(login_request.api_key, request):
            # Set secure authentication cookie
            set_admin_cookie(response)
            return AdminLoginResponse(message="Login successful", authenticated=True)
        else:
            raise AuthenticationError("Invalid credentials")
    except BaseAppException:
        # Re-raise application exceptions (like authentication errors)
        raise
    except Exception as e:
        logger.error(f"Admin login error: {e}", exc_info=True)
        raise BaseAppException(
            detail="Login failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="LOGIN_FAILED",
        ) from e


@router.post("/logout")
async def admin_logout(response: Response) -> Dict[str, Any]:
    """Logout admin user by clearing authentication cookie.

    This endpoint clears the secure session cookie, effectively logging out
    the admin user. No authentication is required for logout.

    Args:
        response: FastAPI response object for clearing cookies

    Returns:
        dict: Logout confirmation message
    """
    logger.info("Admin logout")
    clear_admin_cookie(response)
    return {"message": "Logout successful", "authenticated": False}
