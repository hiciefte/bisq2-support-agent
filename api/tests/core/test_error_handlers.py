"""Security contract tests for API exception responses."""

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.core.error_handlers import base_exception_handler, http_exception_handler
from app.core.exceptions import BaseAppException, ValidationError
from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _request(path: str = "/public") -> MagicMock:
    request = MagicMock()
    request.url.path = path
    request.method = "GET"
    return request


@pytest.mark.asyncio
async def test_server_exception_detail_is_logged_but_not_returned(caplog) -> None:
    private_detail = "private-storage-location"
    exception = BaseAppException(
        detail=private_detail,
        status_code=503,
        error_code="DEPENDENCY_FAILURE",
    )

    with caplog.at_level("ERROR"):
        response = await base_exception_handler(_request(), exception)

    assert response.status_code == 503
    assert private_detail not in response.body.decode()
    assert b'"message":"An unexpected error occurred"' in response.body
    assert private_detail in caplog.text


@pytest.mark.asyncio
async def test_client_exception_detail_remains_actionable() -> None:
    exception = ValidationError("currency must be three letters", field="currency")

    response = await base_exception_handler(_request(), exception)

    assert response.status_code == 422
    assert b'"message":"currency must be three letters"' in response.body


@pytest.mark.asyncio
async def test_http_server_exception_detail_is_logged_but_not_returned(caplog) -> None:
    private_detail = "private-route-failure"
    exception = StarletteHTTPException(status_code=500, detail=private_detail)

    with caplog.at_level("ERROR"):
        response = await http_exception_handler(_request(), exception)

    assert response.status_code == 500
    assert private_detail not in response.body.decode()
    assert b'"detail":"Internal server error"' in response.body
    assert private_detail in caplog.text


@pytest.mark.asyncio
async def test_http_client_exception_detail_and_headers_remain_actionable() -> None:
    exception = HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

    response = await http_exception_handler(_request(), exception)

    assert response.status_code == 401
    assert b'"detail":"Authentication required"' in response.body
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_main_registers_handler_for_starlette_http_exceptions() -> None:
    from app.main import app

    assert app.exception_handlers[StarletteHTTPException] is http_exception_handler


def test_training_sync_failures_do_not_serialize_exception_details() -> None:
    source = (
        PROJECT_ROOT / "api" / "app" / "routes" / "admin" / "training.py"
    ).read_text(encoding="utf-8")

    error_messages: list[ast.expr] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "SyncResponse":
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        status_value = keywords.get("status")
        if isinstance(status_value, ast.Constant) and status_value.value == "error":
            error_messages.append(keywords["message"])

    assert [
        message.value for message in error_messages if isinstance(message, ast.Constant)
    ] == ["Bisq sync failed", "Matrix sync failed"]
    assert all(isinstance(message, ast.Constant) for message in error_messages)
