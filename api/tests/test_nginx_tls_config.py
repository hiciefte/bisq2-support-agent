"""Regression tests for optional production nginx TLS activation."""

import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NGINX_ROOT = PROJECT_ROOT / "docker" / "nginx"
TLS_ENTRYPOINT = NGINX_ROOT / "docker-entrypoint.d" / "40-enable-tls.sh"
NGINX_HTTP_CONFIG = NGINX_ROOT / "nginx.conf"
LOCAL_SITE_CONFIG = NGINX_ROOT / "conf.d" / "default.conf"
PRODUCTION_SITE_CONFIG = NGINX_ROOT / "conf.d" / "default.prod.conf"
PRODUCTION_ROUTES = NGINX_ROOT / "conf.d" / "snippets" / "application-routes.prod.conf"
TRANSPORT_SECURITY = NGINX_ROOT / "conf.d" / "snippets" / "transport-security.conf"


def _run_tls_entrypoint(
    tmp_path: Path,
    *,
    certificate: bool = False,
    private_key: bool = False,
    redirect_http: str = "false",
) -> subprocess.CompletedProcess[str]:
    tls_dir = tmp_path / "tls"
    runtime_dir = tmp_path / "runtime"
    tls_dir.mkdir()
    runtime_dir.mkdir()

    certificate_path = tls_dir / "certificate.pem"
    private_key_path = tls_dir / "private-key.pem"
    if certificate:
        certificate_path.write_text("test certificate\n", encoding="utf-8")
    if private_key:
        private_key_path.write_text("test private key\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "NGINX_TLS_CERTIFICATE": str(certificate_path),
            "NGINX_TLS_PRIVATE_KEY": str(private_key_path),
            "NGINX_TLS_REDIRECT_HTTP": redirect_http,
            "NGINX_TLS_RUNTIME_DIR": str(runtime_dir),
        }
    )
    return subprocess.run(
        ["/bin/sh", str(TLS_ENTRYPOINT)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def _generated_runtime_config(tmp_path: Path) -> str:
    return (tmp_path / "runtime" / "tls.conf").read_text(encoding="utf-8")


def test_production_routes_are_shared_by_http_and_generated_tls() -> None:
    site_config = PRODUCTION_SITE_CONFIG.read_text(encoding="utf-8")
    routes = PRODUCTION_ROUTES.read_text(encoding="utf-8")

    assert "include /etc/nginx/conf.d/snippets/application-routes.prod.conf;" in (
        site_config
    )
    assert 'location ~ "^/api/chat/query/?$" {' in routes
    assert "location /api/ {" in routes
    assert "location / {" in routes


def test_nginx_loads_generated_runtime_configuration() -> None:
    nginx_config = NGINX_HTTP_CONFIG.read_text(encoding="utf-8")

    assert "include /etc/nginx/runtime/*.conf;" in nginx_config


def test_no_certificates_keep_tls_and_redirect_disabled(tmp_path: Path) -> None:
    result = _run_tls_entrypoint(tmp_path)

    assert result.returncode == 0, result.stderr
    generated = _generated_runtime_config(tmp_path)
    assert "listen 443 ssl;" not in generated
    assert "server {" not in generated
    assert "http 1;" not in generated


@pytest.mark.parametrize(
    ("certificate", "private_key"),
    [(True, False), (False, True)],
)
def test_partial_certificate_pair_fails_closed(
    tmp_path: Path, certificate: bool, private_key: bool
) -> None:
    result = _run_tls_entrypoint(
        tmp_path,
        certificate=certificate,
        private_key=private_key,
    )

    assert result.returncode != 0
    assert "partial TLS configuration" in result.stderr
    assert str(tmp_path) not in result.stderr


def test_complete_certificate_pair_generates_tls_server(tmp_path: Path) -> None:
    result = _run_tls_entrypoint(
        tmp_path,
        certificate=True,
        private_key=True,
    )

    assert result.returncode == 0, result.stderr
    generated = _generated_runtime_config(tmp_path)
    assert "server {" in generated
    assert "listen 443 ssl;" in generated
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in generated
    assert "ssl_session_tickets off;" in generated
    assert "application-routes.prod.conf" in generated
    assert 'set $strict_transport_security "max-age=31536000";' in generated
    assert "http 1;" not in generated


def test_http_redirect_requires_explicit_enablement(tmp_path: Path) -> None:
    result = _run_tls_entrypoint(
        tmp_path,
        certificate=True,
        private_key=True,
        redirect_http="true",
    )

    assert result.returncode == 0, result.stderr
    generated = _generated_runtime_config(tmp_path)
    assert "http 1;" in generated
    assert "return 308 https://$host$request_uri;" in (
        PRODUCTION_SITE_CONFIG.read_text(encoding="utf-8")
    )


def test_http_redirect_without_certificates_fails_closed(tmp_path: Path) -> None:
    result = _run_tls_entrypoint(tmp_path, redirect_http="true")

    assert result.returncode != 0
    assert "HTTP redirection requires a complete TLS certificate pair" in (
        result.stderr
    )
    assert str(tmp_path) not in result.stderr


def test_hsts_is_suppressed_for_http_and_enabled_for_https(tmp_path: Path) -> None:
    result = _run_tls_entrypoint(
        tmp_path,
        certificate=True,
        private_key=True,
    )

    assert result.returncode == 0, result.stderr
    local_config = LOCAL_SITE_CONFIG.read_text(encoding="utf-8")
    site_config = PRODUCTION_SITE_CONFIG.read_text(encoding="utf-8")
    generated = _generated_runtime_config(tmp_path)
    transport_security = TRANSPORT_SECURITY.read_text(encoding="utf-8")
    assert 'set $strict_transport_security "";' in local_config
    assert 'set $strict_transport_security "";' in site_config
    assert 'set $strict_transport_security "max-age=31536000";' in generated
    assert (
        "add_header Strict-Transport-Security $strict_transport_security always;"
        in transport_security
    )


@pytest.mark.parametrize(
    "snippet_name",
    [
        "security-headers-api.conf",
        "security-headers-grafana.conf",
        "security-headers-web.conf",
    ],
)
def test_security_header_snippets_include_transport_security(
    snippet_name: str,
) -> None:
    snippet = (NGINX_ROOT / "conf.d" / "snippets" / snippet_name).read_text(
        encoding="utf-8"
    )

    assert "include /etc/nginx/conf.d/snippets/transport-security.conf;" in snippet
