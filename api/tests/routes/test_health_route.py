import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.routes import health as health_routes


def _set_disabled_optional_integrations(test_client, test_settings) -> None:
    test_settings.MATRIX_SYNC_ENABLED = False
    test_settings.BISQ2_CHANNEL_ENABLED = False
    test_settings.ENABLE_BISQ_MCP_INTEGRATION = False
    test_settings.AUTONOMOUS_DELIVERY_ENABLED = False
    test_client.app.state.settings = test_settings
    test_client.app.state.matrix_channel = None
    test_client.app.state.bisq_mcp_service = None
    test_client.app.state.channel_launch_control_service = SimpleNamespace(
        check_readiness=lambda: True
    )


def _ready_rag_service(*, vector_ready: bool = True):
    return SimpleNamespace(
        rag_chain=object(),
        document_retriever=object(),
        retriever=object(),
        check_readiness=AsyncMock(return_value=vector_ready),
    )


def _scoped_bisq_runtime(scope, *, reaction_listening: bool = True):
    bisq_api = SimpleNamespace(_test_scope=scope)
    reaction_handler = SimpleNamespace(
        _test_scope=scope,
        is_listening=reaction_listening,
    )
    dependencies = {
        "bisq2_api": bisq_api,
        "bisq2_reaction_handler": reaction_handler,
    }
    return (
        bisq_api,
        reaction_handler,
        SimpleNamespace(resolve_optional=dependencies.get),
    )


class TestHealthRoute:
    def test_health_exposes_bisq_readiness_details(self, test_client):
        mock_bisq_service = AsyncMock()
        mock_bisq_service.enabled = True
        mock_bisq_service.health_check.return_value = {
            "enabled": True,
            "readiness": {"status": "degraded"},
        }
        test_client.app.state.bisq_mcp_service = mock_bisq_service
        test_client.app.state.rag_service = object()

        response = test_client.get("/health")

        assert response.status_code == 200
        payload = response.json()
        assert payload["mcp_enabled"] is True
        assert payload["services"]["bisq2_api"]["status"] == "degraded"

    def test_health_exposes_disabled_mcp_flag(self, test_client):
        mock_bisq_service = AsyncMock()
        mock_bisq_service.enabled = False
        mock_bisq_service.health_check.return_value = {
            "enabled": False,
            "readiness": {"status": "disabled"},
        }
        test_client.app.state.bisq_mcp_service = mock_bisq_service
        test_client.app.state.rag_service = object()

        response = test_client.get("/health")

        assert response.status_code == 200
        payload = response.json()
        assert payload["mcp_enabled"] is False
        assert payload["services"]["bisq2_api"]["status"] == "disabled"

    def test_readiness_reports_required_components_ready(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        rag_service = _ready_rag_service()
        test_client.app.state.rag_service = rag_service

        response = test_client.get("/health/ready")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "components": {
                "rag": {"status": "ready", "required": True},
                "vector_store": {"status": "ready", "required": True},
                "channel_launch_control": {"status": "ready", "required": False},
                "matrix": {"status": "disabled", "required": False},
                "bisq2_api": {"status": "disabled", "required": False},
                "bisq2_test_scope": {
                    "status": "disabled",
                    "required": False,
                    "channel_count": 0,
                    "sender_profile_count": 0,
                },
            },
        }
        rag_service.check_readiness.assert_awaited_once_with()

    def test_readiness_returns_component_breakdown_when_rag_is_missing(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_client.app.state.rag_service = None

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json() == {
            "status": "degraded",
            "components": {
                "rag": {"status": "unavailable", "required": True},
                "vector_store": {"status": "unavailable", "required": True},
                "channel_launch_control": {"status": "ready", "required": False},
                "matrix": {"status": "disabled", "required": False},
                "bisq2_api": {"status": "disabled", "required": False},
                "bisq2_test_scope": {
                    "status": "disabled",
                    "required": False,
                    "channel_count": 0,
                    "sender_profile_count": 0,
                },
            },
        }

    def test_readiness_returns_503_when_vector_store_is_unreachable(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_client.app.state.rag_service = _ready_rag_service(vector_ready=False)

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["components"]["rag"]["status"] == "ready"
        assert response.json()["components"]["vector_store"]["status"] == "unavailable"

    def test_readiness_keeps_manual_ui_available_when_launch_control_is_unavailable(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.channel_launch_control_service = None

        response = test_client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["components"]["channel_launch_control"] == {
            "status": "unavailable",
            "required": False,
        }

    def test_readiness_returns_503_when_permitted_launch_control_is_unavailable(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.AUTONOMOUS_DELIVERY_ENABLED = True
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.channel_launch_control_service = None

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["components"]["channel_launch_control"] == {
            "status": "unavailable",
            "required": True,
        }

    def test_readiness_hides_launch_control_exception_details(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.AUTONOMOUS_DELIVERY_ENABLED = True
        private_detail = "private launch-control storage failure"
        test_client.app.state.rag_service = _ready_rag_service()
        launch_control = MagicMock()
        launch_control.check_readiness.side_effect = RuntimeError(private_detail)
        test_client.app.state.channel_launch_control_service = launch_control

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert private_detail not in response.text
        assert response.json()["components"]["channel_launch_control"]["status"] == (
            "unavailable"
        )

    def test_readiness_requires_an_enabled_matrix_session(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.MATRIX_SYNC_ENABLED = True
        connection_manager = MagicMock()
        connection_manager.health_check.return_value = False
        runtime = MagicMock()
        runtime.resolve_optional.return_value = connection_manager
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.matrix_channel = SimpleNamespace(
            runtime=runtime,
            is_connected=True,
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["matrix"] == {
            "status": "unavailable",
            "required": True,
        }
        connection_manager.health_check.assert_called_once_with()

    @pytest.mark.parametrize(
        "enabled_flag",
        ["ENABLE_BISQ_MCP_INTEGRATION", "BISQ2_CHANNEL_ENABLED"],
    )
    def test_readiness_requires_an_enabled_bisq_integration(
        self, test_client, test_settings, enabled_flag
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        setattr(test_settings, enabled_flag, True)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": False,
            "readiness": {"status": "degraded"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_api"] == {
            "status": "unavailable",
            "required": True,
        }
        bisq_service.health_check.assert_awaited_once_with()

    @pytest.mark.parametrize(
        ("api_available", "readiness_status", "expected_http", "expected_status"),
        [
            (True, "healthy", 200, "ready"),
            (False, "degraded", 503, "unavailable"),
        ],
    )
    def test_scoped_training_requires_bisq_export_when_channel_is_disabled(
        self,
        test_client,
        test_settings,
        api_available,
        readiness_status,
        expected_http,
        expected_status,
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-training"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-training"]
        test_settings.BISQ2_STAFF_PROFILE_IDS = []
        test_settings.BISQ2_CHATOPS_CHANNEL_IDS = []
        test_settings.BISQ2_STAFF_NOTIFICATION_TARGET = ""
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": api_available,
            "readiness": {"status": readiness_status},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service

        response = test_client.get("/health/ready")

        assert response.status_code == expected_http
        assert response.json()["components"]["bisq2_api"] == {
            "status": expected_status,
            "required": True,
        }
        assert response.json()["components"]["bisq2_test_scope"] == {
            "status": "ready",
            "required": True,
            "channel_count": 1,
            "sender_profile_count": 1,
        }
        bisq_service.health_check.assert_awaited_once_with()

    def test_readiness_accepts_healthy_enabled_integrations(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.MATRIX_SYNC_ENABLED = True
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["support.fixture"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile.fixture"]
        connection_manager = MagicMock()
        connection_manager.health_check.return_value = True
        runtime = MagicMock()
        runtime.resolve_optional.return_value = connection_manager
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.matrix_channel = SimpleNamespace(
            runtime=runtime,
            is_connected=True,
        )
        test_client.app.state.bisq_mcp_service = bisq_service
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        _, _, bisq_runtime = _scoped_bisq_runtime(scope)
        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=True,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["components"]["matrix"]["status"] == "ready"
        assert response.json()["components"]["bisq2_api"]["status"] == "ready"
        assert response.json()["components"]["bisq2_test_scope"] == {
            "status": "ready",
            "required": True,
            "channel_count": 1,
            "sender_profile_count": 1,
        }
        assert "support.fixture" not in response.text
        assert "profile.fixture" not in response.text

    def test_readiness_rejects_enabled_bisq_channel_without_allowlist(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ""
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ""
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"] == {
            "status": "unavailable",
            "required": True,
            "channel_count": 0,
            "sender_profile_count": 0,
        }

    def test_readiness_rejects_active_bisq_scope_mismatch(
        self, test_client, test_settings
    ):
        from app.channels.plugins.bisq2.test_scope import Bisq2TestScope

        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        configured_scope = health_routes.resolve_bisq2_test_scope(test_settings)
        mismatched_scope = Bisq2TestScope(
            allowed_channel_ids=frozenset({"channel-configured"}),
            allowed_sender_profile_ids=frozenset({"profile-stale"}),
        )
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        _, reaction_handler, bisq_runtime = _scoped_bisq_runtime(configured_scope)
        mismatched_api = SimpleNamespace(_test_scope=mismatched_scope)
        bisq_runtime = SimpleNamespace(
            resolve_optional={
                "bisq2_api": mismatched_api,
                "bisq2_reaction_handler": reaction_handler,
            }.get
        )
        bisq_channel = SimpleNamespace(
            _test_scope=configured_scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=True,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"]["status"] == (
            "unavailable"
        )
        assert "profile-stale" not in response.text

    def test_readiness_rejects_inactive_registered_bisq_reaction_listener(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        _, _, bisq_runtime = _scoped_bisq_runtime(
            scope,
            reaction_listening=False,
        )
        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=True,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"]["status"] == (
            "unavailable"
        )

    def test_readiness_rejects_noncurrent_bisq_websocket_subscriptions(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        _, _, bisq_runtime = _scoped_bisq_runtime(scope)
        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=False,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"]["status"] == (
            "unavailable"
        )

    def test_readiness_requires_registered_bisq_reaction_handler(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        bisq_api = SimpleNamespace(_test_scope=scope)
        bisq_runtime = SimpleNamespace(
            resolve_optional=lambda name: bisq_api if name == "bisq2_api" else None
        )
        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=True,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"]["status"] == (
            "unavailable"
        )

    def test_bisq_scope_readiness_log_hides_dependency_exception(
        self, test_client, test_settings, caplog
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        sensitive_values = ("private-endpoint", "sentinel-secret", "profile-configured")
        sensitive_detail = " ".join(sensitive_values)

        def fail_resolution(_name):
            raise RuntimeError(sensitive_detail)

        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=True,
            runtime=SimpleNamespace(resolve_optional=fail_resolution),
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        with caplog.at_level(logging.WARNING):
            response = test_client.get("/health/ready")

        assert response.status_code == 503
        for sensitive_value in sensitive_values:
            assert sensitive_value not in caplog.text

    @pytest.mark.parametrize(
        (
            "rebaseline_complete",
            "persistence_capable",
            "persistence_healthy",
        ),
        [(False, True, True), (True, False, True), (True, True, False)],
    )
    def test_readiness_rejects_unsafe_bisq_scope_state(
        self,
        test_client,
        test_settings,
        rebaseline_complete,
        persistence_capable,
        persistence_healthy,
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        _, _, bisq_runtime = _scoped_bisq_runtime(scope)
        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=rebaseline_complete,
            test_scope_persistence_capable=persistence_capable,
            test_scope_persistence_healthy=persistence_healthy,
            test_scope_websocket_ready=True,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"]["status"] == (
            "unavailable"
        )

    def test_readiness_requires_chatops_adapter_when_bisq_chatops_is_enabled(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.BISQ2_CHANNEL_ENABLED = True
        test_settings.BISQ2_ALLOWED_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_ALLOWED_SENDER_PROFILE_IDS = ["profile-configured"]
        test_settings.BISQ2_CHATOPS_ENABLED = True
        test_settings.BISQ2_CHATOPS_CHANNEL_IDS = ["channel-configured"]
        test_settings.BISQ2_STAFF_PROFILE_IDS = ["profile-configured"]
        scope = health_routes.resolve_bisq2_test_scope(test_settings)
        bisq_service = AsyncMock()
        bisq_service.health_check.return_value = {
            "api_available": True,
            "readiness": {"status": "healthy"},
        }
        test_client.app.state.rag_service = _ready_rag_service()
        test_client.app.state.bisq_mcp_service = bisq_service
        _, _, bisq_runtime = _scoped_bisq_runtime(scope)
        bisq_channel = SimpleNamespace(
            _test_scope=scope,
            is_connected=True,
            test_scope_rebaseline_complete=True,
            test_scope_persistence_capable=True,
            test_scope_persistence_healthy=True,
            test_scope_websocket_ready=True,
            runtime=bisq_runtime,
        )
        test_client.app.state.channel_registry = SimpleNamespace(
            get=lambda channel_id: bisq_channel if channel_id == "bisq2" else None
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["bisq2_test_scope"]["status"] == (
            "unavailable"
        )

    def test_readiness_hides_dependency_exception_details(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        private_detail = "private vector backend failure"
        rag_service = _ready_rag_service()
        rag_service.check_readiness.side_effect = RuntimeError(private_detail)
        test_client.app.state.rag_service = rag_service

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert private_detail not in response.text
        assert response.json()["components"]["vector_store"]["status"] == "unavailable"

    def test_readiness_times_out_slow_dependencies(
        self, test_client, test_settings, monkeypatch
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        rag_service = _ready_rag_service()

        async def slow_readiness() -> bool:
            await asyncio.sleep(1)
            return True

        rag_service.check_readiness = slow_readiness
        test_client.app.state.rag_service = rag_service
        monkeypatch.setattr(
            health_routes,
            "READINESS_DEPENDENCY_TIMEOUT_SECONDS",
            0.01,
        )

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["components"]["vector_store"]["status"] == "unavailable"

    def test_liveness_remains_independent_of_dependencies(self, test_client):
        class DependencyTrap:
            def __bool__(self):
                raise AssertionError("liveness inspected RAG")

            def __getattr__(self, name):
                raise AssertionError(f"liveness inspected RAG attribute {name}")

        test_client.app.state.rag_service = DependencyTrap()

        response = test_client.get("/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}
