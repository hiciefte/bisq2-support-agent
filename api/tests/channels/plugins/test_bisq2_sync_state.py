from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager


def test_processed_ids_keep_the_newest_entries_in_insertion_order(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path))
    manager.MAX_PROCESSED_IDS = 3

    for message_id in ("message-1", "message-2", "message-3", "message-4"):
        manager.mark_processed(message_id)
    manager.save_state()

    assert manager.processed_message_ids == {
        "message-2",
        "message-3",
        "message-4",
    }
    persisted = json.loads(state_path.read_text())
    assert persisted["processed_message_ids"] == [
        "message-2",
        "message-3",
        "message-4",
    ]

    restarted = BisqSyncStateManager(str(state_path))
    restarted.MAX_PROCESSED_IDS = 3
    restarted.mark_processed("message-5")

    assert restarted.processed_message_ids == {
        "message-3",
        "message-4",
        "message-5",
    }


def test_concurrent_saves_are_serialized_and_atomic(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path))

    def mark_and_save(index: int) -> None:
        manager.mark_processed(f"message-{index}")
        manager.save_state()

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(mark_and_save, index) for index in range(200)]
        for future in futures:
            future.result()

    manager.save_state()
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert set(persisted["processed_message_ids"]) == {
        f"message-{index}" for index in range(200)
    }
    assert list(tmp_path.glob("*.tmp*")) == []


def test_non_ascii_message_ids_round_trip_as_utf8(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path))
    manager.mark_processed("nachricht-λ-漢字")

    manager.save_state()

    restarted = BisqSyncStateManager(str(state_path))
    assert restarted.is_processed("nachricht-λ-漢字") is True


def test_invalid_utf8_state_falls_back_to_fresh_state(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    state_path.write_bytes(b'{"processed_message_ids":["\xff"]}')

    manager = BisqSyncStateManager(str(state_path))

    assert manager.last_sync_timestamp is None
    assert manager.processed_message_ids == set()


def test_invalid_timestamp_state_falls_back_to_fresh_state(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    state_path.write_text(
        '{"last_sync_timestamp":"not-a-timestamp","processed_message_ids":["m-1"]}',
        encoding="utf-8",
    )

    manager = BisqSyncStateManager(str(state_path))

    assert manager.last_sync_timestamp is None
    assert manager.processed_message_ids == set()


@pytest.mark.parametrize("content", ["[]", "null", '"scalar"', "42"])
def test_non_object_json_state_falls_back_to_fresh_state(tmp_path, content) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    state_path.write_text(content, encoding="utf-8")

    manager = BisqSyncStateManager(str(state_path))

    assert manager.last_sync_timestamp is None
    assert manager.processed_message_ids == set()
