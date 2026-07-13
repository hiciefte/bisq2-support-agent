"""Concurrency invariants for FAQ index rebuild/update coordination."""

import asyncio

import pytest
from app.services.rag.faq_index_sync import AsyncSharedExclusiveGate


@pytest.mark.asyncio
async def test_waiting_writer_blocks_new_shared_entries() -> None:
    gate = AsyncSharedExclusiveGate()
    release_reader = asyncio.Event()
    writer_entered = asyncio.Event()
    release_writer = asyncio.Event()
    second_reader_entered = asyncio.Event()

    async def first_reader() -> None:
        async with gate.shared():
            await release_reader.wait()

    async def writer() -> None:
        async with gate.exclusive():
            writer_entered.set()
            await release_writer.wait()

    async def second_reader() -> None:
        async with gate.shared():
            second_reader_entered.set()

    first_task = asyncio.create_task(first_reader())
    await asyncio.sleep(0)
    writer_task = asyncio.create_task(writer())
    while gate.waiting_writers == 0:
        await asyncio.sleep(0)
    second_task = asyncio.create_task(second_reader())
    await asyncio.sleep(0)

    assert second_reader_entered.is_set() is False
    release_reader.set()
    await asyncio.wait_for(writer_entered.wait(), timeout=1)
    assert second_reader_entered.is_set() is False
    release_writer.set()
    await asyncio.gather(first_task, writer_task, second_task)
    assert second_reader_entered.is_set() is True


@pytest.mark.asyncio
async def test_cancelled_writer_does_not_strand_shared_entries() -> None:
    gate = AsyncSharedExclusiveGate()
    release_reader = asyncio.Event()
    next_reader_entered = asyncio.Event()

    async def holding_reader() -> None:
        async with gate.shared():
            await release_reader.wait()

    async def waiting_writer() -> None:
        async with gate.exclusive():
            raise AssertionError("cancelled writer unexpectedly entered")

    async def next_reader() -> None:
        async with gate.shared():
            next_reader_entered.set()

    first_task = asyncio.create_task(holding_reader())
    await asyncio.sleep(0)
    writer_task = asyncio.create_task(waiting_writer())
    while gate.waiting_writers == 0:
        await asyncio.sleep(0)

    writer_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await writer_task

    second_task = asyncio.create_task(next_reader())
    await asyncio.wait_for(next_reader_entered.wait(), timeout=1)
    release_reader.set()
    await asyncio.gather(first_task, second_task)
