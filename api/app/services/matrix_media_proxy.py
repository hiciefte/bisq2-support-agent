"""Proxy that downloads Matrix media via the local homeserver.

Used by the admin security UI to render avatars referenced by ``mxc://``
URIs in trust-monitor evidence. Centralized so credentials never leave
the backend.

The Matrix spec moved authenticated media to
``/_matrix/client/v1/media/download/{server}/{mediaId}`` (MSC3916, June
2024). matrix.org now requires it. We try v1 first and fall back to the
legacy unauthenticated v3 endpoint for old/self-hosted servers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

# Avatars are tiny — cap at 2 MB to defend against pathological responses.
_MAX_BYTES = 2 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 8.0
_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._\-:]+$")


class MediaProxyError(Exception):
    """Raised when upstream media cannot be retrieved."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MediaPayload:
    content: bytes
    content_type: str


class _AsyncHttpClient(Protocol):
    async def get(self, url: str, *, headers: dict[str, str], timeout: float): ...


def validate_segment(value: str, *, field: str) -> str:
    """Reject anything that could escape the URL path."""
    if not value or not _SAFE_SEGMENT_RE.match(value):
        raise MediaProxyError(
            f"Invalid {field}",
            status_code=400,
        )
    return value


def _strip_trailing_slash(url: str) -> str:
    return url.rstrip("/")


async def fetch_matrix_media(
    *,
    homeserver_url: str,
    access_token: str | None,
    server_name: str,
    media_id: str,
    http_client: _AsyncHttpClient,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> MediaPayload:
    """Fetch media from the homeserver, trying authenticated then legacy endpoints."""
    if not homeserver_url:
        raise MediaProxyError("Matrix homeserver not configured", status_code=503)

    server = validate_segment(server_name, field="server name")
    media = validate_segment(media_id, field="media id")
    base = _strip_trailing_slash(homeserver_url)

    attempts: list[tuple[str, dict[str, str]]] = []
    if access_token:
        attempts.append(
            (
                f"{base}/_matrix/client/v1/media/download/{server}/{media}",
                {"Authorization": f"Bearer {access_token}"},
            )
        )
    attempts.append(
        (
            f"{base}/_matrix/media/v3/download/{server}/{media}",
            {},
        )
    )

    last_status: int | None = None
    for url, headers in attempts:
        try:
            response = await http_client.get(
                url, headers=headers, timeout=timeout_seconds
            )
        except Exception as exc:  # network errors, timeouts
            logger.debug("Matrix media fetch failed for %s: %s", url, exc)
            last_status = 504
            continue

        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(response, "status", None)
        if status == 200:
            content = getattr(response, "content", None)
            if content is None and hasattr(response, "read"):
                content = await response.read()
            if not isinstance(content, (bytes, bytearray)):
                raise MediaProxyError("Upstream returned non-bytes body")
            if len(content) > _MAX_BYTES:
                raise MediaProxyError("Media too large", status_code=413)
            content_type = "application/octet-stream"
            headers_obj = getattr(response, "headers", None)
            if headers_obj is not None:
                ct = headers_obj.get("content-type") or headers_obj.get("Content-Type")
                if ct:
                    content_type = ct.split(";", 1)[0].strip()
            return MediaPayload(content=bytes(content), content_type=content_type)
        last_status = status

    if last_status == 404:
        raise MediaProxyError("Media not found", status_code=404)
    raise MediaProxyError(f"Upstream returned status {last_status}", status_code=502)
