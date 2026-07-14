"""Fail-closed contracts for the human-run Tor rollback workflow."""

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SCRIPT = PROJECT_ROOT / "scripts" / "rollback-tor.sh"


def test_tor_rollback_requires_explicit_tls_selection_before_mutation() -> None:
    script = ROLLBACK_SCRIPT.read_text(encoding="utf-8")

    validation_call = "if ! require_clearnet_tls_selection; then"
    first_mutation = 'mkdir -p "$BACKUP_DIR"'

    assert validation_call in script
    assert script.index(validation_call) < script.index(first_mutation)
    assert '!= "docker-compose.tls.yml"' in script
    assert "config --quiet" in script
    assert "run --rm --no-deps nginx nginx -T" in script.replace("\\\n", " ")
    assert "listen[[:space:]]+443[[:space:]]+ssl" in script
    assert "docs/runbooks/public-access.md" in script


def test_tor_rollback_requires_secure_tls_runtime_settings() -> None:
    script = ROLLBACK_SCRIPT.read_text(encoding="utf-8")

    for setting in (
        "NGINX_HTTP_BIND_ADDRESS",
        "NGINX_HTTPS_BIND_ADDRESS",
        "NGINX_TLS_CERTIFICATE_DIR",
        "NGINX_TLS_CERTIFICATE_FILENAME",
        "NGINX_TLS_PRIVATE_KEY_FILENAME",
        "NGINX_TLS_REDIRECT_HTTP",
        "COOKIE_SECURE",
    ):
        assert setting in script

    assert 'grep -q "listen 443 ssl"' in script


def test_tor_rollback_rejects_invalid_certificate_before_docker_preflight(
    tmp_path: Path,
) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (docker_dir / "docker-compose.tls.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )

    certificate_dir = tmp_path / "tls"
    certificate_dir.mkdir()
    (certificate_dir / "certificate.pem").write_text(
        "not a certificate\n", encoding="utf-8"
    )
    (certificate_dir / "private-key.pem").write_text(
        "not a private key\n", encoding="utf-8"
    )
    (docker_dir / ".env").write_text(
        "\n".join(
            (
                "NGINX_HTTP_BIND_ADDRESS=127.0.0.1",
                "NGINX_HTTPS_BIND_ADDRESS=127.0.0.1",
                f"NGINX_TLS_CERTIFICATE_DIR={certificate_dir}",
                "NGINX_TLS_CERTIFICATE_FILENAME=certificate.pem",
                "NGINX_TLS_PRIVATE_KEY_FILENAME=private-key.pem",
                "NGINX_TLS_REDIRECT_HTTP=true",
                "COOKIE_SECURE=true",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fakebin / "docker"
    fake_docker.write_text(
        "#!/bin/bash\n" f'printf \'%s\\n\' "$*" >> "{docker_log}"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
            export PATH="{fakebin}:$PATH"
            source "{ROLLBACK_SCRIPT}"
            DOCKER_DIR="{docker_dir}"
            COMPOSE_FILE=docker-compose.yml
            BISQ_SUPPORT_COMPOSE_OVERRIDE_FILE=docker-compose.tls.yml
            require_clearnet_tls_selection
            """,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "not valid X.509 material" in result.stdout
    assert not docker_log.exists()
