"""Structural checks for the two-layer LLM request ceiling."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NGINX_HTTP_CONFIG = PROJECT_ROOT / "docker" / "nginx" / "nginx.conf"
PRODUCTION_SITE_CONFIG = (
    PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.prod.conf"
)
PRODUCTION_ROUTES_CONFIG = (
    PROJECT_ROOT
    / "docker"
    / "nginx"
    / "conf.d"
    / "snippets"
    / "application-routes.prod.conf"
)
ROUTE_CONFIGS = [
    PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.conf",
    PRODUCTION_ROUTES_CONFIG,
]


def _location_block(content: str, declaration: str) -> str:
    start = content.index(declaration)
    depth = 0
    for index in range(start, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    raise AssertionError(f"unterminated location block: {declaration}")


def test_nginx_declares_address_keyed_llm_zone() -> None:
    content = NGINX_HTTP_CONFIG.read_text(encoding="utf-8")
    assert "limit_req_zone $binary_remote_addr zone=llm_addr:" in content


def test_production_server_includes_the_tested_route_configuration() -> None:
    content = PRODUCTION_SITE_CONFIG.read_text(encoding="utf-8")

    assert "include /etc/nginx/conf.d/snippets/application-routes.prod.conf;" in content


@pytest.mark.parametrize("config_path", ROUTE_CONFIGS, ids=lambda path: path.name)
@pytest.mark.parametrize(
    ("declaration", "rewrite"),
    [
        (
            'location ~ "^/api/chat/query/?$" {',
            "rewrite ^/api/chat/query/?$ /chat/query break;",
        ),
        (
            'location ~ "^/api/chat/query/stream/?$" {',
            "rewrite ^/api/chat/query/stream/?$ /chat/query/stream break;",
        ),
    ],
)
def test_chat_endpoints_apply_session_and_address_limits(
    config_path: Path, declaration: str, rewrite: str
) -> None:
    block = _location_block(config_path.read_text(encoding="utf-8"), declaration)
    assert "limit_req zone=api " in block
    assert "limit_req zone=llm_addr " in block
    assert rewrite in block


@pytest.mark.parametrize("config_path", ROUTE_CONFIGS, ids=lambda path: path.name)
def test_synchronous_chat_query_has_llm_sized_proxy_timeouts(
    config_path: Path,
) -> None:
    declaration = 'location ~ "^/api/chat/query/?$" {'
    block = _location_block(config_path.read_text(encoding="utf-8"), declaration)

    assert "proxy_read_timeout 10m;" in block
    assert "proxy_send_timeout 10m;" in block
