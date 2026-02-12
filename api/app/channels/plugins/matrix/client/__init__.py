"""Matrix client layer — connection, session, error handling, polling."""

from app.channels.plugins.matrix.client.connection_manager import ConnectionManager
from app.channels.plugins.matrix.client.error_handler import ErrorHandler
from app.channels.plugins.matrix.client.polling_state import PollingStateManager
from app.channels.plugins.matrix.client.session_manager import SessionManager

__all__ = [
    "ConnectionManager",
    "ErrorHandler",
    "PollingStateManager",
    "SessionManager",
]
