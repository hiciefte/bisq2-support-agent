"""Security boundary tests for the isolated Alertmanager relay."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from secrets import compare_digest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from app.core.config import Settings, get_settings
from app.routes.alertmanager import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_AUTH_VALUE = "unit-test-auth-value"
AUTHORIZATION_HEADER = {"Authorization": f"Bearer {TEST_AUTH_VALUE}"}
PAYLOAD = {
    "receiver": "test-receiver",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "BoundaryTest", "severity": "warning"},
            "annotations": {"summary": "Boundary test alert"},
        }
    ],
}


@pytest.fixture
def relay_route() -> tuple[TestClient, MagicMock]:
    """Mount the shared relay router with isolated settings and Matrix service."""
    test_app = FastAPI()
    test_app.include_router(router)

    service = MagicMock()
    service.is_configured.return_value = True
    service.send_alert_message = AsyncMock(return_value=True)
    test_app.state.matrix_alert_service = service

    settings = Settings(
        _env_file=None,
        ALERTMANAGER_WEBHOOK_SECRET=TEST_AUTH_VALUE,
    )
    test_app.dependency_overrides[get_settings] = lambda: settings

    return TestClient(test_app), service


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer invalid"},
    ],
)
def test_alert_webhook_rejects_missing_or_invalid_secret(
    relay_route: tuple[TestClient, MagicMock], headers: dict[str, str]
) -> None:
    client, service = relay_route

    response = client.post("/alerts", headers=headers, json=PAYLOAD)

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_alertmanager_credentials"}
    service.send_alert_message.assert_not_awaited()


def test_alert_webhook_fails_closed_when_secret_is_not_configured(
    relay_route: tuple[TestClient, MagicMock],
) -> None:
    client, service = relay_route
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        ALERTMANAGER_WEBHOOK_SECRET="",
    )

    response = client.post("/alerts", headers=AUTHORIZATION_HEADER, json=PAYLOAD)

    assert response.status_code == 503
    assert response.json() == {"detail": "alertmanager_webhook_not_configured"}
    service.send_alert_message.assert_not_awaited()


def test_alert_webhook_uses_constant_time_secret_comparison(
    relay_route: tuple[TestClient, MagicMock],
) -> None:
    client, service = relay_route
    comparison_module = sys.modules["secrets"]

    with patch.object(
        comparison_module,
        "compare_digest",
        wraps=compare_digest,
    ) as compare:
        response = client.post("/alerts", headers=AUTHORIZATION_HEADER, json=PAYLOAD)

    assert response.status_code == 200
    compare.assert_called_once_with(
        AUTHORIZATION_HEADER["Authorization"],
        f"Bearer {TEST_AUTH_VALUE}",
    )
    service.send_alert_message.assert_awaited_once()


def test_main_api_does_not_import_or_mount_alertmanager_routes() -> None:
    main_source = (PROJECT_ROOT / "api" / "app" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_source)

    imported_modules: set[str] = set()
    mounted_routers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_modules.update(f"{module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
            and node.args
        ):
            mounted_routers.append(ast.unparse(node.args[0]))

    assert not any(
        module == "app.routes.alertmanager"
        or module.startswith("app.routes.alertmanager.")
        for module in imported_modules
    )
    assert not any("alertmanager" in router.lower() for router in mounted_routers)


def test_alertmanager_webhooks_load_bearer_secret_from_file() -> None:
    config_path = PROJECT_ROOT / "docker" / "alertmanager" / "alertmanager.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    webhook_configs = [
        webhook
        for receiver in config["receivers"]
        for webhook in receiver.get("webhook_configs", [])
    ]

    assert webhook_configs
    for webhook in webhook_configs:
        authorization = webhook["http_config"]["authorization"]
        assert authorization == {
            "type": "Bearer",
            "credentials_file": (
                "/run/bisq-secrets/alertmanager/alertmanager_webhook_secret"
            ),
        }
        assert "credentials" not in authorization
