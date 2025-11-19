"""
Cache control middleware for API responses.

Ensures API responses are never cached by browsers or proxies to prevent
stale data issues after deployments.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class CacheControlMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add Cache-Control headers to API responses.

    Prevents browser and proxy caching of API responses to ensure users
    always receive fresh data after deployments.

    Headers added:
    - Cache-Control: no-store, no-cache, must-revalidate, private
    - Pragma: no-cache (for HTTP/1.0 compatibility)
    - Expires: 0 (for HTTP/1.0 compatibility)
    """

    def __init__(self, app: ASGIApp):
        """
        Initialize the cache control middleware.

        Args:
            app: The ASGI application to wrap
        """
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process the request and add cache control headers to the response.

        Args:
            request: The incoming HTTP request
            call_next: The next middleware or route handler

        Returns:
            Response with cache control headers added

        Note:
            Currently applies no-cache headers to ALL API responses.
            For selective caching (e.g., public static JSON endpoints),
            consider implementing path-based or method-based conditional
            header application in future iterations.
        """
        # Call the next middleware or route handler
        response = await call_next(request)

        # Add cache control headers to prevent caching
        # no-store: Don't store in cache at all
        # no-cache: Revalidate with server before using cached response
        # must-revalidate: Once stale, must revalidate before using
        # private: Only browser can cache, not shared/proxy caches
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, private"
        )

        # HTTP/1.0 compatibility headers
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        return response
