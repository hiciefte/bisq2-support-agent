"""Matrix authentication and session management components.

This package provides production-ready session persistence, error handling,
and connection management for Matrix client integrations.

Components:
    - SessionManager: Handles authentication and session file I/O with atomic writes
    - ErrorHandler: Detects authentication errors and implements retry logic
    - ConnectionManager: Manages Matrix connection lifecycle and health checks
"""

from app.integrations.matrix.connection_manager import ConnectionManager
from app.integrations.matrix.error_handler import ErrorHandler
from app.integrations.matrix.session_manager import SessionManager

__all__ = ["SessionManager", "ErrorHandler", "ConnectionManager"]
