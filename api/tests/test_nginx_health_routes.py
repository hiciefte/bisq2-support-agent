"""Regression tests for nginx API health routing."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = [
    PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.conf",
    PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.prod.conf",
]


def _location_block(conf_path: Path, marker: str) -> str:
    """Return the body of a simple nginx location block."""
    content = conf_path.read_text()
    start = content.find(marker)
    assert start != -1, f"Could not find {marker!r} in {conf_path.name}"

    body_start = start + len(marker)
    body_end = content.find("\n    }", body_start)
    assert body_end != -1, f"Could not find end of {marker!r} in {conf_path.name}"
    return content[body_start:body_end]


@pytest.fixture(params=NGINX_CONFIGS, ids=lambda p: p.name)
def nginx_conf(request):
    """Parametrize tests over all nginx config files."""
    return request.param


class TestNginxHealthRoutes:
    """Ensure health routing matches frontend and operational expectations."""

    def test_api_health_proxy_is_publicly_routed(self, nginx_conf):
        """The web proxy health path must reach FastAPI, not nginx 403."""
        block = _location_block(nginx_conf, "location ~ ^/api/health(/ready|/live)?$ {")

        assert "deny all;" not in block
        assert "allow 127.0.0.1;" not in block
        assert "allow 172.16.0.0/12;" not in block
        assert "rewrite ^/api/health(/ready|/live)?$ /health$1 break;" in block
        assert "proxy_pass http://api:8000;" in block
        assert "proxy_pass http://api:8000/health$1;" not in block

    def test_api_metrics_remains_internal_only(self, nginx_conf):
        """Prometheus metrics should stay restricted even though health is public."""
        block = _location_block(nginx_conf, "location /api/metrics {")

        assert "allow 127.0.0.1;" in block
        assert "allow 172.16.0.0/12;" in block
        assert "deny all;" in block
