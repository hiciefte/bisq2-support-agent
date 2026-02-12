"""Matrix client — consolidated into channels/plugins/matrix/client/."""

from app.channels.plugins.matrix.client.connection_manager import ConnectionManager
from app.channels.plugins.matrix.client.error_handler import ErrorHandler
from app.channels.plugins.matrix.client.session_manager import SessionManager

__all__ = ["SessionManager", "ErrorHandler", "ConnectionManager"]
