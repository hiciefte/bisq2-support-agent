"""Least-privilege contracts for API-backed scheduler jobs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.config import get_settings
from app.routes import scheduler
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def scheduler_client(test_settings, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        test_settings,
        "SCHEDULER_API_TOKEN",
        "test-scheduler-token-with-sufficient-length",
    )

    app = FastAPI()
    app.include_router(scheduler.router)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.state.rag_service = MagicMock()
    app.state.rag_service.rebuild_live_index = AsyncMock(return_value=True)
    app.state.unified_pipeline_service = SimpleNamespace(
        repository=SimpleNamespace(db_path="test-unified-training.db")
    )
    return TestClient(app)


def _scheduler_headers() -> dict[str, str]:
    return {"X-Scheduler-Token": "test-scheduler-token-with-sufficient-length"}


@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({}, 401),
        ({"X-Scheduler-Token": "wrong-token"}, 403),
        ({"X-API-Key": "test-admin-key-with-sufficient-length-24chars"}, 401),
    ],
)
def test_scheduler_routes_reject_non_scheduler_credentials(
    scheduler_client: TestClient,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    response = scheduler_client.post(
        "/internal/scheduler/process-feedback",
        headers=headers,
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize("configured_token", ["", "too-short"])
def test_scheduler_routes_fail_closed_when_token_is_not_securely_configured(
    scheduler_client: TestClient,
    test_settings,
    monkeypatch,
    configured_token: str,
) -> None:
    monkeypatch.setattr(test_settings, "SCHEDULER_API_TOKEN", configured_token)

    response = scheduler_client.post(
        "/internal/scheduler/process-feedback",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 503


def test_process_feedback_runs_only_the_feedback_task(
    scheduler_client: TestClient,
    monkeypatch,
) -> None:
    process_feedback = AsyncMock(return_value={"entries_processed": 7})
    monkeypatch.setattr(scheduler, "process_feedback_task", process_feedback)

    response = scheduler_client.post(
        "/internal/scheduler/process-feedback",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "entries_processed": 7,
    }
    process_feedback.assert_awaited_once_with()


def test_update_wiki_rebuilds_the_live_rag_index(
    scheduler_client: TestClient,
    monkeypatch,
) -> None:
    events: list[str] = []

    async def update_wiki() -> dict[str, int]:
        events.append("wiki")
        return {"pages_processed": 12}

    async def rebuild(*, force_rebuild: bool) -> bool:
        assert force_rebuild is True
        events.append("rebuild")
        return True

    monkeypatch.setattr(scheduler, "update_wiki_task", update_wiki)
    scheduler_client.app.state.rag_service.rebuild_live_index = rebuild

    response = scheduler_client.post(
        "/internal/scheduler/update-wiki",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "pages_processed": 12,
    }
    assert events == ["wiki", "rebuild"]


def test_update_wiki_reports_an_incomplete_rebuild_as_failure(
    scheduler_client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "update_wiki_task",
        AsyncMock(return_value={"pages_processed": 12}),
    )
    scheduler_client.app.state.rag_service.rebuild_live_index = AsyncMock(
        return_value=False
    )

    response = scheduler_client.post(
        "/internal/scheduler/update-wiki",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Scheduled task failed"}


def test_reconciliation_uses_the_live_training_repository(
    scheduler_client: TestClient,
    test_settings,
    monkeypatch,
) -> None:
    reconcile = MagicMock(return_value={"matched": 3, "updated": 2})
    monkeypatch.setattr(scheduler, "run_reconciliation", reconcile)

    response = scheduler_client.post(
        "/internal/scheduler/reconcile-llm-wiki-coverage",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "result": {"matched": 3, "updated": 2},
    }
    reconcile.assert_called_once_with(
        settings=test_settings,
        db_path="test-unified-training.db",
        apply=True,
    )


@pytest.mark.parametrize(
    ("source", "handler_name"),
    [
        ("bisq", "trigger_bisq_sync"),
        ("matrix", "trigger_matrix_sync"),
    ],
)
def test_training_sync_uses_only_the_selected_source_handler(
    scheduler_client: TestClient,
    monkeypatch,
    source: str,
    handler_name: str,
) -> None:
    selected_handler = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            processed=4,
            message=None,
        )
    )
    other_handler_name = (
        "trigger_matrix_sync" if source == "bisq" else "trigger_bisq_sync"
    )
    other_handler = AsyncMock()
    monkeypatch.setattr(scheduler, handler_name, selected_handler)
    monkeypatch.setattr(scheduler, other_handler_name, other_handler)

    response = scheduler_client.post(
        f"/internal/scheduler/training-sync/{source}",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "processed": 4,
        "message": None,
    }
    selected_handler.assert_awaited_once()
    other_handler.assert_not_awaited()


def test_task_failures_log_details_but_return_generic_errors(
    scheduler_client: TestClient,
    monkeypatch,
    caplog,
) -> None:
    private_detail = "private scheduler failure detail"
    monkeypatch.setattr(
        scheduler,
        "process_feedback_task",
        AsyncMock(side_effect=RuntimeError(private_detail)),
    )

    with caplog.at_level("ERROR"):
        response = scheduler_client.post(
            "/internal/scheduler/process-feedback",
            headers=_scheduler_headers(),
        )

    assert response.status_code == 500
    assert private_detail not in response.text
    assert response.json() == {"detail": "Scheduled task failed"}
    assert private_detail in caplog.text


def test_sync_error_payload_is_not_reported_as_success(
    scheduler_client: TestClient,
    monkeypatch,
) -> None:
    private_detail = "private upstream failure"
    monkeypatch.setattr(
        scheduler,
        "trigger_bisq_sync",
        AsyncMock(
            return_value=SimpleNamespace(
                status="error",
                processed=None,
                message=private_detail,
            )
        ),
    )

    response = scheduler_client.post(
        "/internal/scheduler/training-sync/bisq",
        headers=_scheduler_headers(),
    )

    assert response.status_code == 500
    assert private_detail not in response.text
