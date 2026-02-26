"""Matrix session management with persistent authentication."""

import json
import logging
import os
from pathlib import Path

try:
    from nio import AsyncClient, LoginResponse, WhoamiError, WhoamiResponse

    NIO_AVAILABLE = True
except ImportError:
    NIO_AVAILABLE = False
    AsyncClient = None
    LoginResponse = None
    WhoamiError = None
    WhoamiResponse = None

from app.channels.plugins.matrix.metrics import (
    matrix_auth_total,
    matrix_fresh_logins_total,
    matrix_session_restores_total,
)

logger = logging.getLogger(__name__)


class MatrixAuthenticationError(Exception):
    """Raised when Matrix authentication fails."""

    pass


class SessionManager:
    """Manages Matrix authentication and session file persistence.

    Provides automatic session restoration across container restarts,
    atomic file writes to prevent corruption, and graceful fallback to
    password-based login when session files are invalid or missing.

    Attributes:
        client: Matrix AsyncClient instance
        password: User password for authentication
        session_file: Path to session persistence file
    """

    def __init__(
        self,
        client: "AsyncClient",
        password: str,
        session_file: str = "/data/matrix_session.json",
    ):
        """Initialize session manager.

        Args:
            client: Matrix AsyncClient instance
            password: User password for authentication
            session_file: Path to session persistence file (default: /data/matrix_session.json)
        """
        if not NIO_AVAILABLE:
            raise ImportError(
                "matrix-nio is not installed. Install with: pip install matrix-nio"
            )

        self.client = client
        self.password = password
        self.session_file = Path(session_file)

    async def login(self) -> None:
        """Login with password or restore from session file.

        Attempts session restoration first for efficiency. Validates
        restored tokens against the homeserver to detect stale/revoked
        tokens early. Falls back to password-based login if session file
        is missing, invalid, or token has expired.

        Raises:
            Exception: If login fails after all attempts
        """
        # Try session restoration first
        if self._load_session():
            # Validate the restored token against the homeserver
            if await self._validate_token():
                matrix_auth_total.labels(result="success").inc()
                matrix_session_restores_total.labels(result="success").inc()
                logger.info(
                    f"Session restored and validated from {self.session_file} "
                    f"for {self.client.user_id}"
                )
                return
            else:
                # Token invalid, clear credentials and fall through to fresh login
                logger.warning(
                    f"Restored token is invalid/expired for {self.client.user_id}, "
                    f"performing fresh login"
                )
                matrix_session_restores_total.labels(result="failure").inc()
                self.client.access_token = None
                self.client.device_id = None

        # Fall back to password login
        logger.info(
            f"No valid session found for {self.client.user_id}, performing fresh login"
        )
        resp = await self.client.login(
            self.password, device_name="Bisq Support Bot (Shadow Mode)"
        )

        if isinstance(resp, LoginResponse):
            self._save_session(resp)
            matrix_auth_total.labels(result="success").inc()
            matrix_fresh_logins_total.labels(result="success").inc()
            logger.info(f"Fresh login successful for {resp.user_id}")
        else:
            error_msg = f"Login failed: {resp}"
            logger.error(error_msg)
            matrix_auth_total.labels(result="failure").inc()
            matrix_fresh_logins_total.labels(result="failure").inc()
            raise MatrixAuthenticationError(error_msg)

    async def _validate_token(self) -> bool:
        """Validate the current access token against the Matrix homeserver.

        Uses the /account/whoami endpoint to verify the token is still valid.
        This detects stale/revoked tokens that would otherwise cause
        M_UNKNOWN_TOKEN errors on first API call.

        Returns:
            True if token is valid, False if invalid/expired/missing
        """
        if not self.client.access_token:
            logger.debug("No access token set, cannot validate")
            return False

        try:
            response = await self.client.whoami()

            if isinstance(response, WhoamiResponse):
                logger.debug(f"Token validated successfully for {response.user_id}")
                return True
            elif isinstance(response, WhoamiError):
                logger.warning(f"Token validation failed: {response.message}")
                return False
            else:
                # Unknown response type
                logger.warning(f"Unexpected whoami response type: {type(response)}")
                return False

        except Exception as e:
            logger.warning(f"Token validation error: {e}")
            return False

    def _load_session(self) -> bool:
        """Load session from disk if exists and valid.

        Validates session file structure before loading credentials into
        the Matrix client. Handles file corruption gracefully.

        Returns:
            True if session restored successfully, False otherwise
        """
        if not self.session_file.exists():
            logger.debug(f"Session file not found: {self.session_file}")
            return False

        try:
            with open(self.session_file, "r") as f:
                config = json.load(f)

            # Validate required fields
            required_fields = ["access_token", "device_id", "user_id"]
            if not all(field in config for field in required_fields):
                logger.warning(
                    f"Session file missing required fields: {required_fields}"
                )
                matrix_session_restores_total.labels(result="failure").inc()
                return False

            # Guard against restoring a session that belongs to a different user.
            # This can happen when operators rotate accounts but reuse session paths.
            expected_user_id = str(
                getattr(self.client, "user_id", "")
                or getattr(self.client, "user", "")
                or ""
            ).strip()
            session_user_id = str(config.get("user_id", "") or "").strip()
            if (
                expected_user_id
                and session_user_id
                and session_user_id != expected_user_id
            ):
                logger.warning(
                    "Session file user_id mismatch (expected=%s, found=%s); "
                    "ignoring session restore",
                    expected_user_id,
                    session_user_id,
                )
                matrix_session_restores_total.labels(result="failure").inc()
                return False

            # Restore session credentials.
            # restore_login() initializes nio client internals used by crypto store.
            restore_login = getattr(self.client, "restore_login", None)
            if callable(restore_login):
                restore_login(
                    config["user_id"],
                    config["device_id"],
                    config["access_token"],
                )

            # Keep explicit fields set for compatibility with tests/mocks.
            self.client.access_token = config["access_token"]
            self.client.device_id = config["device_id"]
            self.client.user_id = config["user_id"]

            logger.debug(
                f"Session loaded: user={config['user_id']}, "
                f"device={config['device_id']}, "
                f"token={self._redact_token(config['access_token'])}"
            )

            return True

        except (IOError, json.JSONDecodeError):
            logger.exception(f"Failed to restore session from {self.session_file}")
            matrix_session_restores_total.labels(result="failure").inc()
            return False

    def _save_session(self, resp: "LoginResponse") -> None:
        """Atomically save session to disk.

        Uses atomic write pattern (temp file + rename) to prevent
        corruption if process crashes during write operation.

        Args:
            resp: LoginResponse from matrix-nio containing credentials

        Raises:
            Exception: If session save fails
        """
        session_data = {
            "access_token": resp.access_token,
            "device_id": resp.device_id,
            "user_id": resp.user_id,
        }

        # Ensure parent directory exists
        self.session_file.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file, then rename
        temp_file = self.session_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w") as f:
                json.dump(session_data, f, indent=2)

            # Set restrictive permissions before rename for defense-in-depth
            os.chmod(temp_file, 0o600)

            # Atomic rename (prevents corruption if crash during write)
            temp_file.replace(self.session_file)

            logger.info(
                f"Session saved to {self.session_file} for {resp.user_id} "
                f"(device: {resp.device_id})"
            )

        except Exception:
            logger.exception(f"Failed to save session to {self.session_file}")
            if temp_file.exists():
                temp_file.unlink()
            raise

    @staticmethod
    def _redact_token(token: str) -> str:
        """Redact token for safe logging.

        Shows only first 10 characters to aid debugging while
        preventing token leakage in log files.

        Args:
            token: Access token string

        Returns:
            Redacted token (e.g., "MDAxOGxvY2...")
        """
        return f"{token[:10]}..." if len(token) > 10 else "***"
