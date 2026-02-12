"""Unit tests for Matrix SessionManager."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip entire module if matrix-nio is not installed
nio = pytest.importorskip("nio", reason="matrix-nio not installed")

from app.channels.plugins.matrix.client.session_manager import (  # noqa: E402
    MatrixAuthenticationError,
    SessionManager,
)

# Import nio classes after importorskip
from nio import AsyncClient, LoginResponse  # noqa: E402


@pytest.fixture
def temp_session_file():
    """Create temporary session file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        temp_path = f.name
    yield temp_path
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def mock_client():
    """Create mock AsyncClient."""
    client = MagicMock(spec=AsyncClient)
    client.user_id = "@test:matrix.org"
    client.homeserver = "https://matrix.org"
    client.access_token = None
    client.device_id = None
    return client


@pytest.fixture
def mock_login_response():
    """Create mock successful LoginResponse."""
    response = MagicMock(spec=LoginResponse)
    response.access_token = "test_token_123456789"
    response.device_id = "TEST_DEVICE"
    response.user_id = "@test:matrix.org"
    return response


@pytest.fixture
def session_manager(mock_client, temp_session_file):
    """Create SessionManager instance with test configuration."""
    return SessionManager(
        client=mock_client, password="test_password", session_file=temp_session_file
    )


class TestSessionManagerInit:
    """Test SessionManager initialization."""

    def test_init_success(self, mock_client, temp_session_file):
        """Test successful initialization."""
        manager = SessionManager(
            client=mock_client,
            password="test_password",
            session_file=temp_session_file,
        )

        assert manager.client == mock_client
        assert manager.password == "test_password"
        assert manager.session_file == Path(temp_session_file)

    def test_init_without_nio_available(self, mock_client, temp_session_file):
        """Test initialization fails when matrix-nio not available."""
        with patch(
            "app.channels.plugins.matrix.client.session_manager.NIO_AVAILABLE", False
        ):
            with pytest.raises(ImportError, match="matrix-nio is not installed"):
                SessionManager(
                    client=mock_client,
                    password="test_password",
                    session_file=temp_session_file,
                )


class TestSessionManagerLogin:
    """Test SessionManager login functionality."""

    @pytest.mark.asyncio
    async def test_login_fresh_success(
        self, session_manager, mock_client, mock_login_response
    ):
        """Test successful fresh login when no session file exists."""
        # Setup
        mock_client.login = AsyncMock(return_value=mock_login_response)

        # Execute
        await session_manager.login()

        # Verify
        mock_client.login.assert_called_once_with(
            "test_password", device_name="Bisq Support Bot (Shadow Mode)"
        )
        assert session_manager.session_file.exists()

        # Verify session file content
        with open(session_manager.session_file, "r") as f:
            saved_data = json.load(f)
        assert saved_data["access_token"] == mock_login_response.access_token
        assert saved_data["device_id"] == mock_login_response.device_id
        assert saved_data["user_id"] == mock_login_response.user_id

        # Verify file permissions (Unix only)
        if os.name != "nt":  # Skip on Windows
            stat_info = os.stat(session_manager.session_file)
            assert stat_info.st_mode & 0o777 == 0o600

    @pytest.mark.asyncio
    async def test_login_session_restore(self, session_manager, mock_client):
        """Test successful session restoration from existing file."""
        from nio import WhoamiResponse

        # Setup: Create existing session file
        session_data = {
            "access_token": "existing_token_123",
            "device_id": "EXISTING_DEVICE",
            "user_id": "@test:matrix.org",
        }
        with open(session_manager.session_file, "w") as f:
            json.dump(session_data, f)

        # Setup: Mock successful whoami validation
        whoami_response = MagicMock(spec=WhoamiResponse)
        whoami_response.user_id = "@test:matrix.org"
        mock_client.whoami = AsyncMock(return_value=whoami_response)

        # Execute
        await session_manager.login()

        # Verify: Should NOT call login (session restored and validated)
        assert mock_client.access_token == "existing_token_123"
        assert mock_client.device_id == "EXISTING_DEVICE"
        assert mock_client.user_id == "@test:matrix.org"
        mock_client.whoami.assert_called_once()
        mock_client.login.assert_not_called()

    @pytest.mark.asyncio
    async def test_login_failure(self, session_manager, mock_client):
        """Test login failure handling."""
        # Setup: Mock login failure
        error_response = MagicMock()
        error_response.message = "Invalid password"
        mock_client.login = AsyncMock(return_value=error_response)

        # Execute & Verify
        with pytest.raises(MatrixAuthenticationError, match="Login failed"):
            await session_manager.login()


class TestSessionFileLoading:
    """Test session file loading functionality."""

    def test_load_session_success(self, session_manager, mock_client):
        """Test successful session file loading."""
        # Setup: Create valid session file
        session_data = {
            "access_token": "test_token",
            "device_id": "TEST_DEVICE",
            "user_id": "@test:matrix.org",
        }
        with open(session_manager.session_file, "w") as f:
            json.dump(session_data, f)

        # Execute
        result = session_manager._load_session()

        # Verify
        assert result is True
        assert mock_client.access_token == "test_token"
        assert mock_client.device_id == "TEST_DEVICE"
        assert mock_client.user_id == "@test:matrix.org"

    def test_load_session_file_not_exists(self, session_manager):
        """Test session loading when file doesn't exist."""
        result = session_manager._load_session()
        assert result is False

    def test_load_session_missing_fields(self, session_manager):
        """Test session loading with missing required fields."""
        # Setup: Create incomplete session file
        incomplete_data = {"access_token": "test_token"}  # Missing device_id, user_id
        with open(session_manager.session_file, "w") as f:
            json.dump(incomplete_data, f)

        # Execute
        result = session_manager._load_session()

        # Verify
        assert result is False

    def test_load_session_invalid_json(self, session_manager):
        """Test session loading with corrupted JSON."""
        # Setup: Create invalid JSON file
        with open(session_manager.session_file, "w") as f:
            f.write("{invalid json")

        # Execute
        result = session_manager._load_session()

        # Verify
        assert result is False


class TestSessionFileSaving:
    """Test session file saving functionality."""

    def test_save_session_success(self, session_manager, mock_login_response):
        """Test successful session file saving."""
        # Execute
        session_manager._save_session(mock_login_response)

        # Verify file exists
        assert session_manager.session_file.exists()

        # Verify file content
        with open(session_manager.session_file, "r") as f:
            saved_data = json.load(f)
        assert saved_data["access_token"] == mock_login_response.access_token
        assert saved_data["device_id"] == mock_login_response.device_id
        assert saved_data["user_id"] == mock_login_response.user_id

        # Verify file permissions (Unix only)
        if os.name != "nt":  # Skip on Windows
            stat_info = os.stat(session_manager.session_file)
            assert stat_info.st_mode & 0o777 == 0o600

    def test_save_session_atomic_write(self, session_manager, mock_login_response):
        """Test atomic write behavior (temp file + rename)."""
        # Execute
        session_manager._save_session(mock_login_response)

        # Verify: Temp file should not exist (already renamed)
        temp_file = session_manager.session_file.with_suffix(".tmp")
        assert not temp_file.exists()

        # Verify: Final file exists
        assert session_manager.session_file.exists()

    def test_save_session_parent_directory_creation(self, mock_client):
        """Test parent directory creation if it doesn't exist."""
        # Setup: Use non-existent directory path
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_path = os.path.join(tmpdir, "nested", "dir", "session.json")
            manager = SessionManager(
                client=mock_client, password="test_password", session_file=nested_path
            )

            mock_response = MagicMock(spec=LoginResponse)
            mock_response.access_token = "token"
            mock_response.device_id = "device"
            mock_response.user_id = "@test:matrix.org"

            # Execute
            manager._save_session(mock_response)

            # Verify: Parent directories were created
            assert os.path.exists(nested_path)


class TestTokenValidation:
    """Test token validation against homeserver."""

    @pytest.mark.asyncio
    async def test_validate_token_success(self, session_manager, mock_client):
        """Test successful token validation with whoami endpoint."""
        from nio import WhoamiResponse

        # Setup: Create session file with valid token
        session_data = {
            "access_token": "valid_token",
            "device_id": "VALID_DEVICE",
            "user_id": "@test:matrix.org",
        }
        with open(session_manager.session_file, "w") as f:
            json.dump(session_data, f)

        # Load the session first to set access_token on client
        session_manager._load_session()

        # Setup: Mock successful whoami response with proper spec
        whoami_response = MagicMock(spec=WhoamiResponse)
        whoami_response.user_id = "@test:matrix.org"
        mock_client.whoami = AsyncMock(return_value=whoami_response)

        # Execute
        result = await session_manager._validate_token()

        # Verify
        assert result is True
        mock_client.whoami.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_token_expired(self, session_manager, mock_client):
        """Test token validation fails with M_UNKNOWN_TOKEN error."""
        # Setup: Create session file
        session_data = {
            "access_token": "expired_token",
            "device_id": "OLD_DEVICE",
            "user_id": "@test:matrix.org",
        }
        with open(session_manager.session_file, "w") as f:
            json.dump(session_data, f)

        # Load the session first
        session_manager._load_session()

        # Setup: Mock M_UNKNOWN_TOKEN error response
        from nio import WhoamiError

        error_response = MagicMock(spec=WhoamiError)
        error_response.message = "M_UNKNOWN_TOKEN: Token is not active"
        mock_client.whoami = AsyncMock(return_value=error_response)

        # Execute
        result = await session_manager._validate_token()

        # Verify
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_token_no_access_token(self, session_manager, mock_client):
        """Test token validation fails when no access token is set."""
        # Setup: No access token
        mock_client.access_token = None

        # Execute
        result = await session_manager._validate_token()

        # Verify
        assert result is False

    @pytest.mark.asyncio
    async def test_login_validates_restored_session(
        self, session_manager, mock_client, mock_login_response
    ):
        """Test that login validates restored sessions before accepting them."""
        # Setup: Create session file
        session_data = {
            "access_token": "expired_token",
            "device_id": "OLD_DEVICE",
            "user_id": "@test:matrix.org",
        }
        with open(session_manager.session_file, "w") as f:
            json.dump(session_data, f)

        # Setup: Mock token validation failure (expired token)
        from nio import WhoamiError

        error_response = MagicMock(spec=WhoamiError)
        error_response.message = "M_UNKNOWN_TOKEN"
        mock_client.whoami = AsyncMock(return_value=error_response)

        # Setup: Mock successful fresh login
        mock_client.login = AsyncMock(return_value=mock_login_response)

        # Execute
        await session_manager.login()

        # Verify: whoami was called to validate, then fresh login happened
        mock_client.whoami.assert_called_once()
        mock_client.login.assert_called_once_with(
            "test_password", device_name="Bisq Support Bot (Shadow Mode)"
        )

    @pytest.mark.asyncio
    async def test_login_accepts_valid_restored_session(
        self, session_manager, mock_client
    ):
        """Test that login accepts restored sessions with valid tokens."""
        from nio import WhoamiResponse

        # Setup: Create session file
        session_data = {
            "access_token": "valid_token",
            "device_id": "VALID_DEVICE",
            "user_id": "@test:matrix.org",
        }
        with open(session_manager.session_file, "w") as f:
            json.dump(session_data, f)

        # Setup: Mock successful whoami validation with proper spec
        whoami_response = MagicMock(spec=WhoamiResponse)
        whoami_response.user_id = "@test:matrix.org"
        mock_client.whoami = AsyncMock(return_value=whoami_response)

        # Execute
        await session_manager.login()

        # Verify: whoami was called, no fresh login needed
        mock_client.whoami.assert_called_once()
        assert not hasattr(mock_client, "login") or not mock_client.login.called


class TestTokenRedaction:
    """Test token redaction for safe logging."""

    def test_redact_token_long(self, session_manager):
        """Test redaction of long token."""
        token = "MDAxOGxvY2F0aW9uIG1hdHJpeC5vcmc"
        redacted = session_manager._redact_token(token)
        assert redacted == "MDAxOGxvY2..."  # First 10 chars + "..."
        assert len(redacted) == 13  # 10 chars + "..."

    def test_redact_token_short(self, session_manager):
        """Test redaction of short token."""
        token = "short"
        redacted = session_manager._redact_token(token)
        assert redacted == "***"
