"""Regression tests for production-only internal API boundaries."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROUTES = (
    PROJECT_ROOT
    / "docker"
    / "nginx"
    / "conf.d"
    / "snippets"
    / "application-routes.prod.conf"
)


def _location_block(config: str, declaration: str) -> str:
    start = config.index(declaration)
    opening_brace = config.index("{", start)
    depth = 0
    for index in range(opening_brace, len(config)):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[start : index + 1]
    raise AssertionError(f"Unclosed nginx block: {declaration}")


def test_public_alertmanager_paths_return_not_found() -> None:
    config = PRODUCTION_ROUTES.read_text(encoding="utf-8")

    exact = _location_block(config, "location = /api/alertmanager {")
    nested = _location_block(config, "location ^~ /api/alertmanager/ {")

    assert "return 404;" in exact
    assert "return 404;" in nested
    assert "proxy_pass" not in exact
    assert "proxy_pass" not in nested


def test_public_internal_scheduler_paths_return_not_found() -> None:
    config = PRODUCTION_ROUTES.read_text(encoding="utf-8")

    exact = _location_block(config, "location = /api/internal {")
    nested = _location_block(config, "location ^~ /api/internal/ {")

    assert "return 404;" in exact
    assert "return 404;" in nested
    assert "proxy_pass" not in exact
    assert "proxy_pass" not in nested
