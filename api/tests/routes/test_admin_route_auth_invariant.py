"""Application-wide authentication invariant for protected admin routes."""

import re
from collections.abc import Iterable

import pytest
from app.core.security import verify_admin_access
from app.main import app
from fastapi.routing import APIRoute


def _protected_admin_operations() -> list[tuple[APIRoute, str]]:
    operations: list[tuple[APIRoute, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/admin") or route.path.startswith("/admin/auth"):
            continue
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            operations.append((route, method))
    return operations


def _operation_id(operation: tuple[APIRoute, str]) -> str:
    route, method = operation
    return f"{method}-{route.path}"


_PROTECTED_ADMIN_OPERATIONS = _protected_admin_operations()


def test_protected_admin_operations_are_discovered() -> None:
    assert _PROTECTED_ADMIN_OPERATIONS, "No protected /admin operations discovered"


def _concrete_path(route: APIRoute) -> str:
    """Fill path placeholders with values accepted by common convertors."""

    path = route.path
    for name, convertor in route.param_convertors.items():
        convertor_name = type(convertor).__name__.lower()
        value = "1" if "int" in convertor_name or "float" in convertor_name else "test"
        path = re.sub(rf"\{{{re.escape(name)}(?::[^}}]+)?\}}", value, path)
    return path


def _dependency_calls(route: APIRoute) -> Iterable[object]:
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        yield dependency.call
        pending.extend(dependency.dependencies)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("route", "method"),
    _PROTECTED_ADMIN_OPERATIONS,
    ids=[_operation_id(operation) for operation in _PROTECTED_ADMIN_OPERATIONS],
)
def test_every_protected_admin_operation_rejects_missing_credentials(
    test_client,
    route: APIRoute,
    method: str,
) -> None:
    response = test_client.request(method, _concrete_path(route), json={})

    assert response.status_code == 401


@pytest.mark.unit
@pytest.mark.parametrize(
    ("route", "method"),
    _PROTECTED_ADMIN_OPERATIONS,
    ids=[_operation_id(operation) for operation in _PROTECTED_ADMIN_OPERATIONS],
)
def test_every_protected_admin_operation_declares_admin_dependency(
    route: APIRoute,
    method: str,
) -> None:
    del method
    assert verify_admin_access in set(_dependency_calls(route))
