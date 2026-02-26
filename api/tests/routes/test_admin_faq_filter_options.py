"""Tests for FAQ filter option admin endpoint."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_faq_routes_module():
    module_path = (
        Path(__file__).resolve().parents[2] / "app" / "routes" / "admin" / "faqs.py"
    )
    module_name = "test_admin_faq_filter_options_module"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repository = getattr(getattr(module, "faq_service", None), "repository", None)
    if repository is not None and hasattr(repository, "close"):
        repository.close()
    return module


def _build_test_app(module) -> FastAPI:
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.verify_admin_access] = lambda: None
    return app


def test_filter_options_returns_trimmed_deduplicated_values():
    module = _load_faq_routes_module()
    module.faq_service = SimpleNamespace(
        get_all_faqs=lambda: [
            SimpleNamespace(category=" General ", source="Manual"),
            SimpleNamespace(category="Technical", source=" Seed "),
            SimpleNamespace(category="general", source="Manual"),
            SimpleNamespace(category="", source=""),
            SimpleNamespace(category=None, source=None),
        ]
    )
    client = TestClient(_build_test_app(module))

    response = client.get("/admin/faqs/filter-options")
    assert response.status_code == 200
    payload = response.json()
    assert payload["categories"] == ["General", "Technical"]
    assert payload["sources"] == ["Manual", "Seed"]


def test_filter_options_returns_500_when_service_fails():
    module = _load_faq_routes_module()
    faq_service = MagicMock()
    faq_service.get_all_faqs.side_effect = RuntimeError("db unavailable")
    module.faq_service = faq_service
    client = TestClient(_build_test_app(module))

    response = client.get("/admin/faqs/filter-options")
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to fetch FAQ filter options"
