"""Trial authentication preserves the existing Matrix device and encryption store."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.channels.plugins.matrix.channel import MatrixChannel
from app.channels.plugins.matrix.client.session_manager import (
    MatrixAuthenticationError,
    SessionManager,
)
from nio import AsyncClient, WhoamiError, WhoamiResponse

from tests.channels.plugins.test_matrix_staff_context_boundary import setup_boundary

pytestmark = pytest.mark.unit


@pytest.fixture
def identity(tmp_path):
    client = MagicMock(spec=AsyncClient)
    client.user_id = "@bot:example.invalid"
    client.store_path = str(tmp_path / "store")
    Path(client.store_path).mkdir()
    database = Path(client.store_path) / "@bot:example.invalid_EXISTING.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute(
            "CREATE TABLE accounts (user_id TEXT, device_id TEXT, account BLOB)"
        )
        conn.execute(
            "INSERT INTO accounts VALUES (?,?,?)",
            (client.user_id, "EXISTING", b"synthetic-pickle"),
        )
        conn.commit()
    session = tmp_path / "session.json"
    session.write_text(
        json.dumps(
            {
                "user_id": client.user_id,
                "device_id": "EXISTING",
                "access_token": "synthetic-token",
            }
        )
    )
    client.whoami = AsyncMock(
        return_value=WhoamiResponse(
            user_id=client.user_id,
            device_id="EXISTING",
            is_guest=False,
        )
    )
    client.login = AsyncMock()
    manager = SessionManager(
        client, "synthetic-password", str(session), restore_only=True
    )
    return manager, client, database


@pytest.mark.asyncio
async def test_exact_existing_identity_restores_without_login_or_rewrite(identity):
    manager, client, database = identity
    before = (manager.session_file.read_bytes(), database.read_bytes())
    await manager.login()
    client.restore_login.assert_called_once_with(
        "@bot:example.invalid",
        "EXISTING",
        "synthetic-token",
    )
    client.login.assert_not_awaited()
    assert before == (manager.session_file.read_bytes(), database.read_bytes())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "missing_session",
        "invalid_session",
        "wrong_user",
        "missing_store",
        "empty_store",
        "wrong_device_store",
        "missing_account",
        "wrong_account_device",
    ],
)
async def test_invalid_existing_identity_never_creates_replacement(identity, failure):
    manager, client, database = identity
    if failure == "missing_session":
        manager.session_file.unlink()
    elif failure == "invalid_session":
        manager.session_file.write_text("{}")
    elif failure == "wrong_user":
        data = json.loads(manager.session_file.read_text())
        data["user_id"] = "@other:example.invalid"
        manager.session_file.write_text(json.dumps(data))
    elif failure == "missing_store":
        database.unlink()
    elif failure == "empty_store":
        database.write_bytes(b"")
    elif failure == "wrong_device_store":
        database.rename(database.with_name("@bot:example.invalid_OTHER.db"))
    else:
        with closing(sqlite3.connect(database)) as conn:
            if failure == "missing_account":
                conn.execute("DELETE FROM accounts")
            else:
                conn.execute("UPDATE accounts SET device_id='OTHER'")
            conn.commit()
    before = (
        manager.session_file.read_bytes() if manager.session_file.exists() else None
    )
    with pytest.raises(MatrixAuthenticationError):
        await manager.login()
    client.login.assert_not_awaited()
    client.restore_login.assert_not_called()
    client.whoami.assert_not_awaited()
    assert (
        manager.session_file.read_bytes() if manager.session_file.exists() else None
    ) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["timeout", "revoked", "unknown", "wrong_user", "wrong_device", "no_device"],
)
async def test_validation_failure_preserves_session_and_never_logs_in(
    identity, failure
):
    manager, client, database = identity
    if failure == "timeout":
        client.whoami.side_effect = TimeoutError("synthetic timeout")
    elif failure == "revoked":
        client.whoami.return_value = WhoamiError("revoked", "M_UNKNOWN_TOKEN")
    elif failure == "unknown":
        client.whoami.return_value = object()
    else:
        client.whoami.return_value = WhoamiResponse(
            user_id=(
                "@other:example.invalid" if failure == "wrong_user" else client.user_id
            ),
            device_id={"wrong_device": "OTHER", "no_device": None}.get(
                failure, "EXISTING"
            ),
            is_guest=False,
        )
    before = (manager.session_file.read_bytes(), database.read_bytes())
    with pytest.raises(MatrixAuthenticationError):
        await manager.login()
    client.login.assert_not_awaited()
    assert before == (manager.session_file.read_bytes(), database.read_bytes())
    assert client.device_id == "EXISTING"
    assert client.access_token == "synthetic-token"


@pytest.mark.asyncio
async def test_missing_trial_runtime_cannot_send(tmp_path):
    _, runtime, client, channel = setup_boundary(tmp_path)
    runtime.settings.MATRIX_CONTEXT_TRIAL_ID = "trial"
    result = await channel.send_staff_context(
        "Synthetic", transaction_id="context-1-root"
    )
    assert result.error == "context_trial_runtime_unavailable"
    client.room_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_deadline_checked_after_waiting_for_transport_lock(tmp_path):
    _, runtime, client, channel = setup_boundary(tmp_path)
    guard = MagicMock()
    guard.check_trial_delivery = AsyncMock(return_value=None)
    runtime.register("matrix_context_runtime", guard)
    async with channel._session_lifecycle_lock:
        task = asyncio.create_task(
            channel.send_staff_context(
                "Synthetic",
                transaction_id="context-1-root",
            )
        )
        await asyncio.sleep(0)
        guard.check_trial_delivery.assert_not_awaited()
        guard.check_trial_delivery.return_value = "context_trial_expired"
    result = await task
    assert result.error == "context_trial_expired"
    guard.check_trial_delivery.assert_awaited_once_with("context-1-root")
    client.room_send.assert_not_awaited()


def test_trial_bootstrap_refuses_to_create_missing_encryption_store(
    tmp_path, monkeypatch
):
    _, runtime, _, _ = setup_boundary(tmp_path)
    settings = runtime.settings
    settings.MATRIX_SYNC_USER = "@bot:example.invalid"
    settings.MATRIX_SYNC_PASSWORD = "synthetic"
    settings.MATRIX_SYNC_SESSION_PATH = str(tmp_path / "session.json")
    settings.MATRIX_CONTEXT_TRIAL_ID = "trial"
    client_constructor = MagicMock()
    monkeypatch.setattr("nio.AsyncClient", client_constructor)
    monkeypatch.setattr("nio.crypto.ENCRYPTION_ENABLED", True)
    with pytest.raises(RuntimeError, match="existing encryption store"):
        MatrixChannel.setup_dependencies(runtime, settings)
    assert not (tmp_path / "session_store").exists()
    client_constructor.assert_not_called()
