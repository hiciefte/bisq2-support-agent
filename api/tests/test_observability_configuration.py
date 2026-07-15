"""Regression tests for production observability configuration."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

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


def test_every_long_running_compose_service_has_a_healthcheck() -> None:
    services = _load_yaml("docker/docker-compose.yml")["services"]
    one_shots = {
        name for name, service in services.items() if service.get("restart") == "no"
    }
    missing = sorted(
        name
        for name, service in services.items()
        if name not in one_shots and "healthcheck" not in service
    )

    assert one_shots == {"alertmanager-secret-init", "scheduler-secret-init"}
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
    assert "/scripts/scheduler-heartbeat.sh" in scheduler["command"]


def test_api_compose_healthchecks_consume_truthful_readiness() -> None:
    for compose_path in (
        "docker/docker-compose.yml",
        "docker/docker-compose.local.yml",
    ):
        api = _load_yaml(compose_path)["services"]["api"]
        command = " ".join(api["healthcheck"]["test"])

        assert "/health/ready" in command
        assert "-f" in command
        assert "--max-time 5" in command


def test_critical_services_have_functional_prometheus_probes() -> None:
    prometheus = _load_yaml("docker/prometheus/prometheus.yml")
    scrape_configs = {
        config["job_name"]: config for config in prometheus["scrape_configs"]
    }
    probed_services = {
        static_config["labels"]["service"]
        for static_config in scrape_configs["critical-service-probes"]["static_configs"]
    }

    assert probed_services == {
        "api",
        "web",
        "nginx",
        "qdrant",
        "bisq2-api",
        "matrix-alert-relay",
    }
    assert scrape_configs["blackbox-exporter"]["static_configs"] == [
        {"targets": ["blackbox-exporter:9115"]}
    ]

    docker_utils = (REPO_ROOT / "scripts/lib/docker-utils.sh").read_text(
        encoding="utf-8"
    )
    assert '"blackbox-exporter"' in docker_utils
    assert "compose_service_is_listed" in docker_utils


def test_critical_service_and_scheduler_alerts_fail_on_missing_metrics() -> None:
    rules = _alert_rules()
    failed_probe = str(rules["CriticalServiceProbeFailed"]["expr"])
    missing_probe = str(rules["CriticalServiceProbeMissing"]["expr"])
    scheduler_heartbeat = str(rules["SchedulerHeartbeatStale"]["expr"])

    assert 'probe_success{job="critical-service-probes"} == 0' in failed_probe
    assert "absent(" in missing_probe
    for service in (
        "api",
        "web",
        "nginx",
        "qdrant",
        "bisq2-api",
        "matrix-alert-relay",
    ):
        assert f'service="{service}"' in missing_probe
    assert "absent(scheduler_heartbeat_timestamp_seconds)" in scheduler_heartbeat
    assert "scheduler_heartbeat_timestamp_seconds == 0" in scheduler_heartbeat


def test_scheduler_exports_fresh_heartbeat_metric(tmp_path: Path) -> None:
    services = _load_yaml("docker/docker-compose.yml")["services"]
    scheduler = services["scheduler"]
    node_exporter = services["node-exporter"]

    assert (
        "./scripts/scheduler-heartbeat.sh:/scripts/scheduler-heartbeat.sh:ro"
        in scheduler["volumes"]
    )
    assert "/scripts/scheduler-heartbeat.sh" in scheduler["command"]
    assert (
        "scheduler-metrics:/var/lib/node_exporter/textfile_collector"
        in scheduler["volumes"]
    )
    assert (
        "scheduler-metrics:/var/lib/node_exporter/textfile_collector:ro"
        in node_exporter["volumes"]
    )
    assert any(
        "--collector.textfile.directory=/var/lib/node_exporter/textfile_collector"
        == argument
        for argument in node_exporter["command"]
    )

    metrics_dir = tmp_path / "metrics"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "docker/scripts/scheduler-heartbeat.sh")],
        env={**os.environ, "SCHEDULER_METRICS_DIR": str(metrics_dir)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    metric = (metrics_dir / "scheduler-heartbeat.prom").read_text(encoding="utf-8")
    value = int(metric.strip().splitlines()[-1].split()[-1])
    assert "# TYPE scheduler_heartbeat_timestamp_seconds gauge" in metric
    assert abs(time.time() - value) < 10


def test_alert_delivery_drill_uses_a_dedicated_verified_receiver() -> None:
    alertmanager = _load_yaml("docker/alertmanager/alertmanager.yml")
    alertmanager_service = _load_yaml("docker/docker-compose.yml")["services"][
        "alertmanager"
    ]
    drill_route = next(
        route
        for route in alertmanager["route"]["routes"]
        if route.get("match", {}).get("alertname") == "AlertDeliveryDrill"
    )
    receiver = next(
        receiver
        for receiver in alertmanager["receivers"]
        if receiver["name"] == drill_route["receiver"]
    )
    script = (REPO_ROOT / "scripts/drill-alert-delivery.sh").read_text(encoding="utf-8")

    assert drill_route["group_wait"] == "0s"
    assert receiver["webhook_configs"]
    assert alertmanager_service["image"] == "prom/alertmanager:v0.27.0"
    assert (
        "--enable-feature=receiver-name-in-metrics" in alertmanager_service["command"]
    )
    assert "alertmanager_notifications_total" in script
    assert "alertmanager_notifications_failed_total" in script
    assert "AlertDeliveryDrill" in script
    assert "api/v2/alerts" in script
    assert "resolve_drill_alert" in script
    assert "MATRIX_ALERT_PASSWORD" not in script


def test_alert_delivery_drill_confirms_receiver_success(tmp_path: Path) -> None:
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    state_file = tmp_path / "notification-state"
    state_file.write_text("0\n", encoding="utf-8")
    call_log = tmp_path / "docker-calls"
    docker = fakebin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        'printf \'%s\\n\' "$*" >> "$DRILL_TEST_CALL_LOG"\n'
        'case "$*" in\n'
        '  info|"compose version") exit 0 ;;\n'
        '  *"/metrics"*)\n'
        '    state=$(cat "$DRILL_TEST_STATE")\n'
        "    printf '%s\\n' \\\n"
        '      "alertmanager_notifications_total{integration=\\"webhook\\",receiver=\\"matrix-drill\\"} $state" \\\n'
        '      "alertmanager_notifications_failed_total{integration=\\"webhook\\",receiver=\\"matrix-drill\\"} 0"\n'
        "    exit 0\n"
        "    ;;\n"
        '  *"api/v2/alerts"*)\n'
        '    if [[ "$*" != *"endsAt"* ]]; then\n'
        "      printf '1\\n' > \"$DRILL_TEST_STATE\"\n"
        "    fi\n"
        "    exit 0\n"
        "    ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}",
        "DRILL_TEST_CALL_LOG": str(call_log),
        "DRILL_TEST_STATE": str(state_file),
        "DRILL_TIMEOUT_SECONDS": "10",
    }

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/drill-alert-delivery.sh"), "--yes"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "confirmed delivery" in result.stdout
    assert call_log.read_text(encoding="utf-8").count("api/v2/alerts") == 2


def test_monitoring_validator_checks_every_changed_configuration() -> None:
    script = (REPO_ROOT / "scripts/validate-monitoring-config.sh").read_text(
        encoding="utf-8"
    )

    assert "check config /etc/prometheus/prometheus.yml" in script
    assert "check rules /etc/prometheus/alert_rules.yml" in script
    assert "--config.check" in script
    assert "check-config /etc/alertmanager/alertmanager.yml" in script


def test_every_alert_runbook_reference_resolves_to_a_repository_file() -> None:
    rules = _alert_rules()

    references = [
        rule["annotations"]["runbook_url"]
        for rule in rules.values()
        if "runbook_url" in rule.get("annotations", {})
    ]

    assert references
    for reference in references:
        parsed_path = urlparse(reference).path
        if "/blob/main/" in parsed_path:
            relative_path = parsed_path.split("/blob/main/", maxsplit=1)[1]
        else:
            relative_path = parsed_path.lstrip("/")
        assert (REPO_ROOT / relative_path).is_file(), reference


def test_deploy_health_timeout_is_fail_closed() -> None:
    deploy_script = (REPO_ROOT / "scripts/deploy.sh").read_text(encoding="utf-8")
    docker_utils = (REPO_ROOT / "scripts/lib/docker-utils.sh").read_text(
        encoding="utf-8"
    )
    deploy_health_call = deploy_script.split(
        "if ! wait_for_compose_health", maxsplit=1
    )[1].split("fi", maxsplit=1)[0]
    timeout_block = docker_utils.split(
        'log_error "Docker services did not become healthy', maxsplit=1
    )[1].split("\n}", maxsplit=1)[0]

    assert "scheduler-secret-init" in deploy_health_call
    assert "alertmanager-secret-init" in deploy_health_call
    assert "exit 1" in deploy_health_call
    assert "logs --tail=50" in timeout_block
    assert "return 1" in timeout_block
