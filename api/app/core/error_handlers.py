"""
Centralized error handlers for the Bisq Support API.

This module provides consistent error handling and formatting
for all application exceptions.
"""

import logging

from app.core.exceptions import BaseAppException
from fastapi import Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def base_exception_handler(
    request: Request, exc: BaseAppException
) -> JSONResponse:
    """Handle all application-specific exceptions.

    Args:
        request: The incoming request that caused the exception
        exc: The application exception that was raised

    Returns:
        JSON response with standardized error format
    """
    logger.error(
        f"Application error: {exc.error_code} - {exc.detail}",
        extra={
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.detail,
                "status_code": exc.status_code,
            }
        },
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors.

    Args:
        request: The incoming request that caused the exception
        exc: The unhandled exception that was raised

    Returns:
        JSON response with generic error message (no sensitive details)
    """
    logger.exception(
        f"Unhandled exception: {str(exc)}",
        extra={
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "status_code": 500,
            }
        },
    )
