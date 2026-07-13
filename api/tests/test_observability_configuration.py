"""Regression tests for production observability configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(relative_path: str) -> dict:
    with (REPO_ROOT / relative_path).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _alert_rules() -> dict[str, dict]:
    config = _load_yaml("docker/prometheus/alert_rules.yml")
    return {
        rule["alert"]: rule
        for group in config["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }


def test_container_alerts_use_real_cadvisor_freshness_series() -> None:
    rules = _alert_rules()
    expressions = "\n".join(
        str(rules[name]["expr"]) for name in ("ContainerDown", "ContainerUnhealthy")
    )

    assert "container_last_seen" in expressions
    assert "container_label_com_docker_compose_service" in expressions
    assert 'up{job="cadvisor", container=' not in expressions
    assert "container_health_status" not in expressions
    assert "max_over_time" in str(rules["ContainerUnhealthy"]["expr"])
    assert "[10m]" in str(rules["ContainerUnhealthy"]["expr"])


def test_feedback_alert_uses_exported_percentage_metric() -> None:
    rule = _alert_rules()["LowUserSatisfaction"]

    assert str(rule["expr"]).strip() == "bisq_feedback_helpful_rate < 60"
    assert "{{ $value }}%" in rule["annotations"]["description"]


def test_alertmanager_routes_notifications_outside_the_api_container() -> None:
    config = _load_yaml("docker/alertmanager/alertmanager.yml")
    urls = [
        webhook["url"]
        for receiver in config["receivers"]
        for webhook in receiver.get("webhook_configs", [])
    ]

    assert urls
    assert all(url == "http://matrix-alert-relay:8000/alerts" for url in urls)
    assert all("http://api:" not in url for url in urls)


def test_every_compose_service_has_a_healthcheck() -> None:
    services = _load_yaml("docker/docker-compose.yml")["services"]
    missing = sorted(
        name for name, service in services.items() if "healthcheck" not in service
    )

    assert missing == []


def test_matrix_alert_relay_uses_existing_password_lane_and_isolated_state() -> None:
    services = _load_yaml("docker/docker-compose.yml")["services"]
    relay = services["matrix-alert-relay"]
    environment = "\n".join(relay["environment"])

    assert "MATRIX_HOMESERVER_URL=${MATRIX_HOMESERVER_URL:-}" in environment
    assert "MATRIX_ALERT_USER=${MATRIX_ALERT_USER:-}" in environment
    assert "MATRIX_ALERT_PASSWORD=${MATRIX_ALERT_PASSWORD:-}" in environment
    assert "MATRIX_ALERT_ROOM=${MATRIX_ALERT_ROOM:-}" in environment
    assert "matrix-alert-relay-data:/data" in relay["volumes"]
    assert "../api/app:/app/app" not in relay["volumes"]
    assert "api:" not in " ".join(relay.get("depends_on", []))


def test_grafana_has_secure_legacy_upgrade_fallbacks() -> None:
    compose = (REPO_ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")

    assert (
        "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-${ADMIN_API_KEY:-}}"
        in compose
    )
    assert (
        "GRAFANA_DATASOURCE_API_KEY=${GRAFANA_DATASOURCE_API_KEY:-${ADMIN_API_KEY:-}}"
        in compose
    )


def test_scheduler_healthcheck_requires_process_and_fresh_heartbeat() -> None:
    scheduler = _load_yaml("docker/docker-compose.yml")["services"]["scheduler"]
    health_command = " ".join(scheduler["healthcheck"]["test"])

    assert "pidof crond" in health_command
    assert "scheduler-heartbeat" in health_command
    assert "touch /tmp/scheduler-heartbeat" in scheduler["command"]


def test_deploy_health_timeout_is_fail_closed() -> None:
    deploy_script = (REPO_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")
    timeout_block = deploy_script.split(
        "if [ $ELAPSED_TIME -ge $MAX_WAIT ]; then", maxsplit=1
    )[1].split("fi", maxsplit=1)[0]

    assert "exit 1" in timeout_block
