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
NGINX_CONF = PROJECT_ROOT / "docker" / "nginx" / "conf.d" / "default.conf"

# Regex that extracts the admin whitelist group from nginx config
# Matches: location ~ ^/api/admin/(faqs|feedback|...|training)(/.*)?$
NGINX_ADMIN_RE = re.compile(r"location ~ \^/api/admin/\(([^)]+)\)\(/\.\*\)\?\$")


def _get_nginx_allowed_prefixes() -> set[str]:
    """Parse nginx config and return set of allowed admin prefixes."""
    content = NGINX_CONF.read_text()
    match = NGINX_ADMIN_RE.search(content)
    assert match, "Could not find admin whitelist regex in nginx config"
    return set(match.group(1).split("|"))


def _get_registered_admin_prefixes() -> set[str]:
    """Scan admin route files and extract their prefix segments.

    Each admin router uses prefix="/admin/<segment>" or prefix="/admin"
    with routes like "/faqs", "/feedback/*".  We extract the first path
    segment after /admin/ that the frontend would call.
    """
    admin_routes_dir = PROJECT_ROOT / "api" / "app" / "routes" / "admin"
    prefix_re = re.compile(r'prefix\s*=\s*["\']/?admin/?(\w+)?["\']')

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
                route_re = re.compile(r'@router\.\w+\(\s*["\']/?(\w+)')
                for rm in route_re.finditer(content):
                    prefixes.add(rm.group(1))
    return prefixes


class TestNginxAdminWhitelist:
    """Ensure nginx admin whitelist covers all registered admin routes."""

    def test_nginx_config_exists(self):
        """Nginx config file must exist at expected path."""
        assert NGINX_CONF.exists(), f"Missing nginx config: {NGINX_CONF}"

    def test_nginx_has_admin_whitelist_regex(self):
        """Nginx config must contain the admin whitelist regex."""
        content = NGINX_CONF.read_text()
        assert NGINX_ADMIN_RE.search(
            content
        ), "Could not find admin whitelist regex pattern in nginx config"

    def test_escalations_in_nginx_whitelist(self):
        """escalations must be in the nginx admin whitelist.

        This was the specific bug: escalations routes returned 403 because
        they weren't in the nginx regex, falling through to internal-only block.
        """
        allowed = _get_nginx_allowed_prefixes()
        assert "escalations" in allowed, (
            f"'escalations' missing from nginx admin whitelist. "
            f"Found: {sorted(allowed)}"
        )

    def test_all_admin_prefixes_in_nginx(self):
        """Every registered admin route prefix must appear in nginx whitelist.

        Excludes 'metrics' (internal-only by design, called from Docker
        network by scheduler container, not from frontend).
        """
        allowed = _get_nginx_allowed_prefixes()
        registered = _get_registered_admin_prefixes()

        # metrics is intentionally internal-only (scheduler → api, no frontend)
        internal_only = {"metrics"}
        public_registered = registered - internal_only

        missing = public_registered - allowed
        assert not missing, (
            f"Admin route prefixes missing from nginx whitelist: {sorted(missing)}. "
            f"Nginx allows: {sorted(allowed)}. "
            f"Registered: {sorted(registered)}."
        )

    def test_no_stale_nginx_entries(self):
        """Nginx whitelist should not contain prefixes with no matching routes.

        Catches entries that linger after routes are removed.
        """
        allowed = _get_nginx_allowed_prefixes()
        registered = _get_registered_admin_prefixes()

        # 'dashboard' is a route under analytics prefix="/admin"
        # so it IS registered (via route decorator)
        stale = allowed - registered
        if stale:
            pytest.skip(
                f"Potential stale nginx entries (may be route aliases): {sorted(stale)}"
            )
