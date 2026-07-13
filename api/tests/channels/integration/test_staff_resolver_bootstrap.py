"""Integration coverage for channel-scoped staff resolver bootstrap wiring."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.channels.bootstrapper import ChannelBootstrapper
from app.channels.plugins.bisq2.client.api import Bisq2API
from app.channels.plugins.matrix.client.connection_manager import ConnectionManager
from app.channels.staff import (
    resolve_channel_staff_resolver,
    staff_resolver_service_key,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "setup_order",
    [
        pytest.param(["bisq2", "matrix"], id="bisq2-then-matrix"),
        pytest.param(["matrix", "bisq2"], id="matrix-then-bisq2"),
    ],
)
def test_dual_channel_bootstrap_keeps_staff_resolvers_isolated(tmp_path, setup_order):
    """Real channel dependency setup must not clobber either staff resolver."""
    matrix_staff_id = "@matrix-staff:example.invalid"
    bisq2_staff_id = "bisq2-staff-profile"
    settings = SimpleNamespace(
        DATA_DIR=str(tmp_path),
        CHANNEL_PLUGINS=[
            "app.channels.plugins.bisq2.channel",
            "app.channels.plugins.matrix.channel",
        ],
        ENVIRONMENT="testing",
        REACTOR_IDENTITY_SALT="staff-resolver-bootstrap-test",
        REACTION_NEGATIVE_STABILIZATION_SECONDS=0.0,
        REACTION_FEEDBACK_FOLLOWUP_TTL_SECONDS=60.0,
        BISQ_API_URL="http://127.0.0.1:8090",
        BISQ2_STAFF_PROFILE_IDS=[bisq2_staff_id],
        BISQ2_CHATOPS_CHANNEL_IDS=[],
        BISQ2_CHATOPS_ENABLED=False,
        TRUSTED_STAFF_IDS=[matrix_staff_id],
        SUPPORT_AGENT_NICKNAMES=[],
        MATRIX_HOMESERVER_URL="https://example.invalid",
        MATRIX_SYNC_USER_RESOLVED="@support-bot:example.invalid",
        MATRIX_SYNC_USER="@support-bot:example.invalid",
        MATRIX_SYNC_PASSWORD_RESOLVED="test-password",
        MATRIX_SYNC_PASSWORD="test-password",
        MATRIX_SYNC_ROOMS=["!support:example.invalid"],
        MATRIX_SYNC_SESSION_PATH=str(tmp_path / "matrix_session.json"),
        MATRIX_STAFF_ROOM="",
        MATRIX_ALERT_ROOM="",
        MATRIX_CHATOPS_ROOM_IDS=[],
        MATRIX_CHATOPS_ENABLED=False,
    )
    bootstrapper = ChannelBootstrapper(settings, MagicMock())
    bootstrapper._get_enabled_channels = MagicMock(return_value=setup_order)

    result = bootstrapper.bootstrap()

    assert result.errors == []
    assert result.loaded == setup_order
    assert isinstance(result.runtime.resolve("bisq2_api"), Bisq2API)
    assert isinstance(
        result.runtime.resolve("matrix_connection_manager"), ConnectionManager
    )

    bisq2_resolver = resolve_channel_staff_resolver(result.runtime, "bisq2")
    matrix_resolver = resolve_channel_staff_resolver(result.runtime, "matrix")

    assert bisq2_resolver is result.runtime.resolve(staff_resolver_service_key("bisq2"))
    assert matrix_resolver is result.runtime.resolve(
        staff_resolver_service_key("matrix")
    )
    assert bisq2_resolver is not matrix_resolver
    assert bisq2_resolver.is_staff(bisq2_staff_id)
    assert matrix_resolver.is_staff(matrix_staff_id)
    assert not bisq2_resolver.is_staff(matrix_staff_id)
    assert not matrix_resolver.is_staff(bisq2_staff_id)
    assert result.runtime.resolve_optional("staff_resolver") is None
