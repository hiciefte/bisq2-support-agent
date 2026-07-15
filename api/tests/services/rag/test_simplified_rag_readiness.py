"""Readiness checks for the live RAG reader state."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.simplified_rag_service import SimplifiedRAGService


def _ready_service() -> SimplifiedRAGService:
    service = object.__new__(SimplifiedRAGService)
    service.rag_chain = object()
    service.document_retriever = object()
    service.retriever = MagicMock()
    service._readiness_probe_task = None
    service._readiness_probe_retriever = None
    service._readiness_cached_retriever = None
    service._readiness_cached_result = False
    service._readiness_checked_at = 0.0
    return service


@pytest.mark.asyncio
async def test_readiness_uses_a_lease_for_the_live_retriever() -> None:
    service = _ready_service()
    retriever = service.retriever
    service._run_retriever_call = AsyncMock(return_value=True)

    assert await service.check_readiness() is True

    service._run_retriever_call.assert_awaited_once_with(
        retriever,
        retriever.health_check,
    )


@pytest.mark.asyncio
async def test_readiness_rejects_an_incomplete_rag_reader_state() -> None:
    service = _ready_service()
    service.rag_chain = None
    service._run_retriever_call = AsyncMock(return_value=True)

    assert await service.check_readiness() is False

    service._run_retriever_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_coalesces_concurrent_backend_probes() -> None:
    service = _ready_service()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def blocked_probe(*_args) -> bool:
        probe_started.set()
        await release_probe.wait()
        return True

    service._run_retriever_call = AsyncMock(side_effect=blocked_probe)
    checks = [asyncio.create_task(service.check_readiness()) for _ in range(20)]

    await probe_started.wait()
    await asyncio.sleep(0)
    service._run_retriever_call.assert_awaited_once()

    release_probe.set()
    assert await asyncio.gather(*checks) == [True] * 20
    service._run_retriever_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_readiness_route_timeout_does_not_spawn_another_probe() -> None:
    service = _ready_service()
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()

    async def blocked_probe(*_args) -> bool:
        probe_started.set()
        await release_probe.wait()
        return True

    service._run_retriever_call = AsyncMock(side_effect=blocked_probe)
    first_check = asyncio.create_task(service.check_readiness())
    await probe_started.wait()
    first_check.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_check

    second_check = asyncio.create_task(service.check_readiness())
    await asyncio.sleep(0)
    service._run_retriever_call.assert_awaited_once()

    release_probe.set()
    assert await second_check is True
    service._run_retriever_call.assert_awaited_once()
