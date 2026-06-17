"""Tests for admin reporting routes."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.routes.admin.reports import get_support_reporting_service, router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client(report_payload: dict) -> tuple[TestClient, MagicMock]:
    service = MagicMock()
    service.build_support_work_report.return_value = report_payload
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_support_reporting_service] = lambda: service

    from app.core.security import verify_admin_access

    app.dependency_overrides[verify_admin_access] = lambda: None
    return TestClient(app), service


def test_get_support_work_report_forwards_period_filters() -> None:
    report_payload = {
        "period": {
            "start_date": "2026-06-01",
            "end_date": "2026-06-16",
            "period_label": "Cycle 62",
            "reviewer": "support-admin",
        },
        "summary": {
            "total_reviews": 1,
            "approved": 1,
            "rejected": 0,
            "pages_touched": 1,
            "new_pages": 0,
            "existing_page_updates": 1,
        },
        "reviewers": [],
        "pages": [],
        "items": [],
        "future_sections": [],
        "report_markdown": "# Support admin work report",
    }
    client, service = _build_client(report_payload)

    response = client.get(
        "/admin/reports/support-work"
        "?start_date=2026-06-01"
        "&end_date=2026-06-16"
        "&reviewer=support-admin"
        "&period_label=Cycle%2062"
    )

    assert response.status_code == 200
    assert response.json()["summary"]["total_reviews"] == 1
    service.build_support_work_report.assert_called_once_with(
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 16),
        reviewer="support-admin",
        period_label="Cycle 62",
    )


def test_get_support_work_report_returns_400_for_invalid_period() -> None:
    client, service = _build_client({})
    service.build_support_work_report.side_effect = ValueError(
        "start_date must be on or before end_date"
    )

    response = client.get(
        "/admin/reports/support-work?start_date=2026-06-16&end_date=2026-06-01"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "start_date must be on or before end_date"
