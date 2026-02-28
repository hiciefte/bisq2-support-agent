import asyncio

import pytest
from app.channels.coordination import InMemoryCoordinationStore


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reserve_dedup_blocks_duplicates_until_ttl_expires():
    store = InMemoryCoordinationStore()

    first = await store.reserve_dedup("matrix:$evt1", ttl_seconds=0.05)
    second = await store.reserve_dedup("matrix:$evt1", ttl_seconds=0.05)

    assert first is True
    assert second is False

    await asyncio.sleep(0.06)
    third = await store.reserve_dedup("matrix:$evt1", ttl_seconds=0.05)
    assert third is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_thread_lock_requires_release_or_expiry():
    store = InMemoryCoordinationStore()

    token1 = await store.acquire_lock("matrix:!room:server", ttl_seconds=0.2)
    token2 = await store.acquire_lock("matrix:!room:server", ttl_seconds=0.2)

    assert token1 is not None
    assert token2 is None

    await store.release_lock("matrix:!room:server", token1)
    token3 = await store.acquire_lock("matrix:!room:server", ttl_seconds=0.2)
    assert token3 is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_thread_lock_expires_without_release():
    store = InMemoryCoordinationStore()

    token1 = await store.acquire_lock("bisq2:support.support", ttl_seconds=0.05)
    assert token1 is not None

    await asyncio.sleep(0.06)
    token2 = await store.acquire_lock("bisq2:support.support", ttl_seconds=0.05)
    assert token2 is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_thread_state_ttl():
    store = InMemoryCoordinationStore()
    key = "thread:matrix:!room:server"

    await store.set_thread_state(key, {"last_event_id": "$evt1"}, ttl_seconds=0.05)
    state1 = await store.get_thread_state(key)
    assert state1 == {"last_event_id": "$evt1"}

    await asyncio.sleep(0.06)
    state2 = await store.get_thread_state(key)
    assert state2 is None
