import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.routes import health as health_routes


def _set_disabled_optional_integrations(test_client, test_settings) -> None:
    test_settings.MATRIX_SYNC_ENABLED = False
    test_settings.BISQ2_CHANNEL_ENABLED = False
    test_settings.ENABLE_BISQ_MCP_INTEGRATION = False
    test_client.app.state.settings = test_settings
    test_client.app.state.matrix_channel = None
    test_client.app.state.bisq_mcp_service = None


def _ready_rag_service(*, vector_ready: bool = True):
    return SimpleNamespace(
        rag_chain=object(),
        document_retriever=object(),
        retriever=object(),
        check_readiness=AsyncMock(return_value=vector_ready),
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
                "matrix": {"status": "disabled", "required": False},
                "bisq2_api": {"status": "disabled", "required": False},
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
                "matrix": {"status": "disabled", "required": False},
                "bisq2_api": {"status": "disabled", "required": False},
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

    def test_readiness_accepts_healthy_enabled_integrations(
        self, test_client, test_settings
    ):
        _set_disabled_optional_integrations(test_client, test_settings)
        test_settings.MATRIX_SYNC_ENABLED = True
        test_settings.BISQ2_CHANNEL_ENABLED = True
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

        response = test_client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["components"]["matrix"]["status"] == "ready"
        assert response.json()["components"]["bisq2_api"]["status"] == "ready"

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
        test_client.app.state.rag_service = MagicMock(
            side_effect=AssertionError("liveness inspected RAG")
        )

        response = test_client.get("/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}
