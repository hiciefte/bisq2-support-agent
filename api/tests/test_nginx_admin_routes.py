"""Tests that nginx admin whitelist covers all registered admin route prefixes.

TDD RED: These tests verify that nginx allows access to every admin route
prefix registered in the FastAPI app. Catches drift between route additions
and nginx configuration.
"""

import re
from pathlib import Path

import pytest

# Path constants
PROJECT_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = [
    PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.conf",
    PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.prod.conf",
]

# Regex that extracts the admin whitelist group from nginx config
# Matches: location ~ ^/api/admin/(faqs|feedback|...|training)(/.*)?$
NGINX_ADMIN_RE = re.compile(r"location ~ \^/api/admin/\(([^)]+)\)\(/\.\*\)\?\$")


def _get_nginx_allowed_prefixes(conf_path: Path) -> set[str]:
    """Parse nginx config and return set of allowed admin prefixes."""
    content = conf_path.read_text()
    match = NGINX_ADMIN_RE.search(content)
    assert match, f"Could not find admin whitelist regex in {conf_path.name}"
    return set(match.group(1).split("|"))


def _get_registered_admin_prefixes() -> set[str]:
    """Scan admin route files and extract their prefix segments.

    Each admin router uses prefix="/admin/<segment>" (optionally nested, e.g.
    "/admin/channels/autoresponse") or prefix="/admin"
    with routes like "/faqs", "/feedback/*".  We extract the first path
    segment after /admin/ that the frontend would call.
    """
    admin_routes_dir = PROJECT_ROOT / "api" / "app" / "routes" / "admin"
    prefix_re = re.compile(
        r'prefix\s*=\s*["\']/?admin(?:/([^"\'/]+)(?:/[^"\'/]*)*)?["\']'
    )

    prefixes: set[str] = set()
    for py_file in admin_routes_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text()
        for m in prefix_re.finditer(content):
            segment = m.group(1)
            if segment:
                prefixes.add(segment)
            else:
                # prefix="/admin" — routes define the segment themselves
                # Extract first segment from route decorators
                route_re = re.compile(r'@router\.\w+\(\s*["\']/?([^"\'/]+)')
                for rm in route_re.finditer(content):
                    prefixes.add(rm.group(1))
    return prefixes


@pytest.fixture(params=NGINX_CONFIGS, ids=lambda p: p.name)
def nginx_conf(request):
    """Parametrize tests over all nginx config files."""
    return request.param


class TestNginxAdminWhitelist:
    """Ensure nginx admin whitelist covers all registered admin routes."""

    def test_nginx_config_exists(self, nginx_conf):
        """Nginx config file must exist at expected path."""
        assert nginx_conf.exists(), f"Missing nginx config: {nginx_conf}"

    def test_nginx_has_admin_whitelist_regex(self, nginx_conf):
        """Nginx config must contain the admin whitelist regex."""
        content = nginx_conf.read_text()
        assert NGINX_ADMIN_RE.search(
            content
        ), f"Could not find admin whitelist regex in {nginx_conf.name}"

    def test_escalations_in_nginx_whitelist(self, nginx_conf):
        """escalations must be in the nginx admin whitelist.

        This was the specific bug: escalations routes returned 403 because
        they weren't in the nginx regex, falling through to internal-only block.
        """
        allowed = _get_nginx_allowed_prefixes(nginx_conf)
        assert "escalations" in allowed, (
            f"'escalations' missing from {nginx_conf.name} admin whitelist. "
            f"Found: {sorted(allowed)}"
        )

    def test_all_admin_prefixes_in_nginx(self, nginx_conf):
        """Every registered admin route prefix must appear in nginx whitelist.

        Excludes 'metrics' (internal-only by design, called from Docker
        network by scheduler container, not from frontend).
        """
        allowed = _get_nginx_allowed_prefixes(nginx_conf)
        registered = _get_registered_admin_prefixes()

        # metrics is intentionally internal-only (scheduler → api, no frontend)
        internal_only = {"metrics"}
        public_registered = registered - internal_only

        missing = public_registered - allowed
        assert not missing, (
            f"Admin route prefixes missing from {nginx_conf.name}: {sorted(missing)}. "
            f"Nginx allows: {sorted(allowed)}. "
            f"Registered: {sorted(registered)}."
        )

    def test_no_stale_nginx_entries(self, nginx_conf):
        """Nginx whitelist should not contain prefixes with no matching routes.

        Catches entries that linger after routes are removed.
        """
        allowed = _get_nginx_allowed_prefixes(nginx_conf)
        registered = _get_registered_admin_prefixes()

        stale = allowed - registered
        if stale:
            pytest.fail(
                f"Stale entries in {nginx_conf.name} "
                f"(no matching admin routes): {sorted(stale)}"
            )
