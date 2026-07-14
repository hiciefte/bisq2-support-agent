"""Static contracts for production Compose security boundaries."""

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = PROJECT_ROOT / "docker" / "docker-compose.yml"
TLS_COMPOSE_PATH = PROJECT_ROOT / "docker" / "docker-compose.tls.yml"
ENV_EXAMPLE_PATH = PROJECT_ROOT / "docker" / ".env.example"
RUN_LOCAL_PATH = PROJECT_ROOT / "run-local.sh"
SECRET_RUNBOOK_PATH = PROJECT_ROOT / "docs" / "runbooks" / "public-boundary-secrets.md"


def _load_compose(path: Path = COMPOSE_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _environment(service: dict[str, Any]) -> list[str]:
    environment = service.get("environment", [])
    assert isinstance(environment, list)
    return environment


def test_scheduler_has_only_its_scoped_api_credential() -> None:
    scheduler = _load_compose()["services"]["scheduler"]
    serialized = yaml.safe_dump(scheduler)
    mounted_sources = {str(volume).split(":", 1)[0] for volume in scheduler["volumes"]}

    assert "SCHEDULER_API_TOKEN=" not in serialized
    assert ". /scripts/lib/scheduler-api.sh" in scheduler["command"]
    assert "ADMIN_API_KEY" not in serialized
    assert "docker.sock" not in serialized
    assert "docker-cli" not in serialized
    assert "docker-compose" not in serialized
    assert "./scripts" not in mounted_sources
    assert "./scripts/maintenance" not in serialized
    assert {
        "./scripts/lib",
        "./scripts/bisq-readiness-check.sh",
        "./scripts/poll-matrix.sh",
        "./scripts/process-feedback.sh",
        "./scripts/rag-health-check.sh",
        "./scripts/reconcile-llm-wiki-coverage.sh",
        "./scripts/update-wiki.sh",
    } <= mounted_sources


def test_scheduler_external_heartbeat_has_no_embedded_destination() -> None:
    scheduler = _load_compose()["services"]["scheduler"]
    healthcheck_entry = next(
        item for item in _environment(scheduler) if item.startswith("HEALTHCHECK_URL=")
    )

    assert healthcheck_entry == "HEALTHCHECK_URL=${HEALTHCHECK_URL:-}"
    assert "hc-ping" not in yaml.safe_dump(scheduler)


def test_scoped_secrets_reach_only_the_services_that_need_them() -> None:
    services = _load_compose()["services"]
    expected_consumers = {
        "scheduler-api-secret": {
            "scheduler-secret-init",
            "api",
            "scheduler",
        },
        "alertmanager-webhook-secret": {
            "alertmanager-secret-init",
            "alertmanager",
            "matrix-alert-relay",
        },
    }

    for volume_name, expected_services in expected_consumers.items():
        actual_services = {
            service_name
            for service_name, service in services.items()
            if any(volume_name in str(volume) for volume in service.get("volumes", []))
        }
        assert actual_services == expected_services

    assert "SCHEDULER_API_TOKEN=" not in yaml.safe_dump(services)
    assert "ALERTMANAGER_WEBHOOK_SECRET=" not in yaml.safe_dump(services)


def test_secret_initializers_are_hardened_and_gate_consumers() -> None:
    services = _load_compose()["services"]

    for initializer_name in ("scheduler-secret-init", "alertmanager-secret-init"):
        initializer = services[initializer_name]
        assert initializer["network_mode"] == "none"
        assert initializer["read_only"] is True
        assert initializer["restart"] == "no"
        assert initializer["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in initializer["security_opt"]
        assert initializer["pids_limit"] == 32

    assert services["api"]["depends_on"]["scheduler-secret-init"]["condition"] == (
        "service_completed_successfully"
    )
    assert (
        services["scheduler"]["depends_on"]["scheduler-secret-init"]["condition"]
        == "service_completed_successfully"
    )
    assert (
        services["matrix-alert-relay"]["depends_on"]["alertmanager-secret-init"][
            "condition"
        ]
        == "service_completed_successfully"
    )
    assert (
        services["alertmanager"]["depends_on"]["alertmanager-secret-init"]["condition"]
        == "service_completed_successfully"
    )


def test_alertmanager_reads_the_isolated_secret_file_directly() -> None:
    alertmanager = _load_compose()["services"]["alertmanager"]

    assert "entrypoint" not in alertmanager
    assert "environment" not in alertmanager
    assert "./alertmanager:/etc/alertmanager:ro" in alertmanager["volumes"]
    assert (
        "alertmanager-webhook-secret:/run/bisq-secrets/alertmanager:ro"
        in alertmanager["volumes"]
    )


def test_relay_uses_api_built_image_and_alertmanager_waits_for_it() -> None:
    services = _load_compose()["services"]
    api = services["api"]
    relay = services["matrix-alert-relay"]

    assert api["image"] == relay["image"]
    assert "build" in api
    assert "build" not in relay
    assert relay["pull_policy"] == "never"
    assert (
        services["alertmanager"]["depends_on"]["matrix-alert-relay"]["condition"]
        == "service_healthy"
    )


def test_alert_lane_configuration_is_absent_from_main_api() -> None:
    services = _load_compose()["services"]
    api_environment = "\n".join(_environment(services["api"]))
    relay_environment = "\n".join(_environment(services["matrix-alert-relay"]))

    for setting in (
        "MATRIX_ALERT_USER",
        "MATRIX_ALERT_PASSWORD",
        "MATRIX_ALERT_ROOM",
        "MATRIX_ALERT_SESSION_FILE",
    ):
        assert setting not in api_environment
        assert setting in relay_environment


def test_base_nginx_requires_an_operator_selected_http_bind() -> None:
    nginx = _load_compose()["services"]["nginx"]
    serialized = yaml.safe_dump(nginx)

    assert any("NGINX_HTTP_BIND_ADDRESS" in port for port in nginx["ports"])
    assert "40-enable-tls.sh" in serialized
    assert "/etc/nginx/runtime" in serialized
    assert "/etc/nginx/runtime" in nginx["tmpfs"]


def test_tls_override_requires_certificate_and_https_bind_inputs() -> None:
    nginx = _load_compose(TLS_COMPOSE_PATH)["services"]["nginx"]
    serialized = yaml.safe_dump(nginx)

    assert "NGINX_HTTPS_BIND_ADDRESS" in serialized
    assert "NGINX_TLS_CERTIFICATE_DIR" in serialized
    assert "NGINX_TLS_CERTIFICATE" in serialized
    assert "NGINX_TLS_PRIVATE_KEY" in serialized
    assert ":/etc/nginx/tls:ro" in serialized


def test_environment_example_does_not_store_compose_runtime_secrets() -> None:
    example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "ALERTMANAGER_WEBHOOK_SECRET=" not in example
    assert "SCHEDULER_API_TOKEN=" not in example
    assert "HEALTHCHECK_URL=\n" in example
    assert "hc-ping" not in example
    assert "NGINX_HTTP_BIND_ADDRESS=" in example
    assert "NGINX_HTTPS_BIND_ADDRESS=" in example
    assert "NGINX_TLS_CERTIFICATE_DIR=" in example
    assert "NGINX_TLS_CERTIFICATE_FILENAME=" in example
    assert "NGINX_TLS_PRIVATE_KEY_FILENAME=" in example
    assert "NGINX_TLS_REDIRECT_HTTP=false" in example


def test_local_stack_uses_compose_secret_initializers() -> None:
    run_local = RUN_LOCAL_PATH.read_text(encoding="utf-8")

    assert "SCHEDULER_API_TOKEN" not in run_local
    assert "ALERTMANAGER_WEBHOOK_SECRET" not in run_local


def test_runtime_secret_runbook_covers_volume_rotation_and_recovery() -> None:
    runbook = SECRET_RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "docker compose down -v" in runbook
    assert "implicit rotation" in runbook
    assert "disaster-recovery inventory" in runbook
    assert "human-run production steps" in runbook
