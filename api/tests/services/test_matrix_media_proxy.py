"""Tests for the Matrix media proxy fetcher."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from app.services.matrix_media_proxy import (
    MediaProxyError,
    fetch_matrix_media,
    validate_segment,
)


@dataclass
class _FakeResponse:
    status_code: int
    content: bytes = b""
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def get(self, url: str, *, headers: dict[str, str], timeout: float):
        self.calls.append((url, dict(headers)))
        if not self._responses:
            raise RuntimeError("no more fake responses")
        return self._responses.pop(0)


@pytest.mark.parametrize(
    "value",
    ["matrix.org", "abc123", "AB_xy.zw-1", "matrix.example:8448", "ABCDEFG12345"],
)
def test_validate_segment_accepts_safe_values(value: str) -> None:
    assert validate_segment(value, field="x") == value


@pytest.mark.parametrize(
    "value",
    ["", "../etc/passwd", "foo/bar", "foo bar", "foo\x00bar", "foo?bar"],
)
def test_validate_segment_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(MediaProxyError):
        validate_segment(value, field="x")


@pytest.mark.asyncio
async def test_fetch_uses_authenticated_endpoint_when_token_present() -> None:
    client = _FakeClient(
        [_FakeResponse(200, b"PNGDATA", {"Content-Type": "image/png"})]
    )
    payload = await fetch_matrix_media(
        homeserver_url="https://matrix.org",
        access_token="syt_xxx",
        server_name="matrix.org",
        media_id="abc123",
        http_client=client,
    )
    assert payload.content == b"PNGDATA"
    assert payload.content_type == "image/png"
    url, headers = client.calls[0]
    assert "/client/v1/media/download/matrix.org/abc123" in url
    assert headers["Authorization"] == "Bearer syt_xxx"


@pytest.mark.asyncio
async def test_fetch_falls_back_to_legacy_v3_when_no_token() -> None:
    client = _FakeClient([_FakeResponse(200, b"JPG", {"Content-Type": "image/jpeg"})])
    payload = await fetch_matrix_media(
        homeserver_url="https://matrix.org",
        access_token=None,
        server_name="matrix.org",
        media_id="abc",
        http_client=client,
    )
    assert payload.content_type == "image/jpeg"
    assert "/_matrix/media/v3/download/matrix.org/abc" in client.calls[0][0]


@pytest.mark.asyncio
async def test_fetch_falls_back_to_v3_when_v1_fails() -> None:
    client = _FakeClient(
        [
            _FakeResponse(401),
            _FakeResponse(200, b"OK", {"Content-Type": "image/png"}),
        ]
    )
    payload = await fetch_matrix_media(
        homeserver_url="https://matrix.org",
        access_token="syt_xxx",
        server_name="matrix.org",
        media_id="abc",
        http_client=client,
    )
    assert payload.content == b"OK"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_fetch_raises_404_when_all_attempts_404() -> None:
    client = _FakeClient([_FakeResponse(404), _FakeResponse(404)])
    with pytest.raises(MediaProxyError) as excinfo:
        await fetch_matrix_media(
            homeserver_url="https://matrix.org",
            access_token="syt_xxx",
            server_name="matrix.org",
            media_id="missing",
            http_client=client,
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_fetch_rejects_invalid_server_name() -> None:
    client = _FakeClient([])
    with pytest.raises(MediaProxyError) as excinfo:
        await fetch_matrix_media(
            homeserver_url="https://matrix.org",
            access_token=None,
            server_name="../etc",
            media_id="abc",
            http_client=client,
        )
    assert excinfo.value.status_code == 400
    assert client.calls == []


@pytest.mark.asyncio
async def test_fetch_rejects_oversized_content() -> None:
    big = b"x" * (3 * 1024 * 1024)
    client = _FakeClient([_FakeResponse(200, big, {"Content-Type": "image/png"})])
    with pytest.raises(MediaProxyError) as excinfo:
        await fetch_matrix_media(
            homeserver_url="https://matrix.org",
            access_token=None,
            server_name="matrix.org",
            media_id="abc",
            http_client=client,
        )
    assert excinfo.value.status_code == 413


@pytest.mark.asyncio
async def test_fetch_503_when_homeserver_missing() -> None:
    client = _FakeClient([])
    with pytest.raises(MediaProxyError) as excinfo:
        await fetch_matrix_media(
            homeserver_url="",
            access_token=None,
            server_name="matrix.org",
            media_id="abc",
            http_client=client,
        )
    assert excinfo.value.status_code == 503
