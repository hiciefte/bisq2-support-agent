from unittest.mock import AsyncMock


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
        assert payload["services"]["bisq2_api"]["status"] == "degraded"
