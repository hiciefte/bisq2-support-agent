from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

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


def test_failed_durable_claim_restores_prior_in_memory_state(tmp_path) -> None:
    manager = BisqSyncStateManager(str(tmp_path / "bisq-sync-state.json"))
    manager.mark_processed("already-durable")

    def fail_save(*, prune_expired: bool = True) -> set[str]:
        _ = prune_expired
        raise OSError("fixture write failure")

    manager._save_state_locked = fail_save  # type: ignore[method-assign]

    with pytest.raises(OSError, match="fixture write failure"):
        manager.claim_processed_and_save({"new-undurable-claim"})

    assert manager.processed_message_ids == {"already-durable"}
    assert manager.get_processed_ids_in_order() == ["already-durable"]


def test_durable_claim_returns_only_newly_persisted_ids(tmp_path) -> None:
    manager = BisqSyncStateManager(str(tmp_path / "bisq-sync-state.json"))
    manager.mark_processed("already-durable")
    manager.save_state()

    claimed = manager.claim_processed_and_save({"already-durable", "newly-durable"})
    repeated = manager.claim_processed_and_save({"already-durable"})

    assert claimed == {"newly-durable"}
    assert repeated == set()


def test_claim_notifies_prune_listener_after_releasing_state_lock(tmp_path) -> None:
    manager = BisqSyncStateManager(
        str(tmp_path / "bisq-sync-state.json"), retention_days=1
    )
    manager.mark_processed(
        "expired-message",
        processed_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    channel_lock = threading.Lock()
    outbound_has_channel_lock = threading.Event()
    listener_entered = threading.Event()
    listener_acquired_channel_lock: list[bool] = []

    def prune_listener(_expired_ids: set[str]) -> None:
        listener_entered.set()
        acquired = channel_lock.acquire(timeout=1)
        listener_acquired_channel_lock.append(acquired)
        if acquired:
            channel_lock.release()

    def outbound_mark() -> None:
        with channel_lock:
            outbound_has_channel_lock.set()
            assert listener_entered.wait(timeout=1)
            manager.mark_processed("outbound-message")

    manager.register_prune_listener(prune_listener)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outbound_future = executor.submit(outbound_mark)
        assert outbound_has_channel_lock.wait(timeout=1)
        claim_future = executor.submit(
            manager.claim_processed_and_save,
            {"inbound-message"},
        )
        outbound_future.result(timeout=2)
        claim_future.result(timeout=2)

    assert listener_acquired_channel_lock == [True]


def test_non_ascii_message_ids_round_trip_as_utf8(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path))
    manager.mark_processed("nachricht-λ-漢字")

    manager.save_state()

    restarted = BisqSyncStateManager(str(state_path))
    assert restarted.is_processed("nachricht-λ-漢字") is True


def test_live_save_does_not_restore_expired_processed_ids(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path), retention_days=1)
    manager.mark_processed(
        "expired-message",
        processed_at=datetime(2000, 1, 1, tzinfo=UTC),
    )

    manager.save_state()

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["processed_message_ids"] == []
    assert manager.is_processed("expired-message") is False


def test_live_save_notifies_prune_listeners_for_expired_ids(tmp_path) -> None:
    manager = BisqSyncStateManager(
        str(tmp_path / "bisq-sync-state.json"), retention_days=1
    )
    manager.mark_processed(
        "expired-message",
        processed_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    notifications: list[set[str]] = []
    manager.register_prune_listener(notifications.append)

    manager.save_state()

    assert notifications == [{"expired-message"}]


def test_failed_save_restores_ids_removed_during_retention_prune(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path), retention_days=1)
    manager.mark_processed(
        "expired-message",
        processed_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    notifications: list[set[str]] = []
    manager.register_prune_listener(notifications.append)

    def fail_replace(_self, _target):
        raise OSError("fixture replace failure")

    monkeypatch.setattr(type(state_path), "replace", fail_replace)

    with pytest.raises(OSError, match="fixture replace failure"):
        manager.save_state()

    assert manager.is_processed("expired-message") is True
    assert notifications == []


def test_failed_prune_before_restores_ids_and_later_retry_notifies(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    manager = BisqSyncStateManager(str(state_path), retention_days=36500)
    manager.mark_processed(
        "expired-message",
        processed_at=datetime.now(UTC) - timedelta(days=2),
    )
    notifications: list[set[str]] = []
    manager.register_prune_listener(notifications.append)
    path_type = type(state_path)
    original_replace = path_type.replace

    def fail_replace(_self, _target):
        raise OSError("fixture replace failure")

    monkeypatch.setattr(path_type, "replace", fail_replace)
    cutoff = datetime.now(UTC) - timedelta(days=1)

    with pytest.raises(OSError, match="fixture replace failure"):
        manager.prune_before(cutoff)

    assert manager.is_processed("expired-message") is True
    assert notifications == []

    monkeypatch.setattr(path_type, "replace", original_replace)
    assert manager.prune_before(cutoff) == 1
    assert manager.is_processed("expired-message") is False
    assert notifications == [{"expired-message"}]


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


def test_legacy_ids_without_valid_timestamps_expire_fail_closed(tmp_path) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    now = datetime.now(UTC)
    state_path.write_text(
        json.dumps(
            {
                "processed_message_ids": ["valid", "missing", "invalid"],
                "processed_message_timestamps": {
                    "valid": now.isoformat(),
                    "invalid": "not-a-timestamp",
                },
            }
        ),
        encoding="utf-8",
    )

    manager = BisqSyncStateManager(str(state_path))

    assert manager.processed_message_ids == {"valid"}
    cutoff = now - timedelta(days=1)
    assert manager.prune_before(cutoff, dry_run=True) == 2
    assert manager.prune_before(cutoff) == 2
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["processed_message_ids"] == ["valid"]


@pytest.mark.parametrize("content", ["[]", "null", '"scalar"', "42"])
def test_non_object_json_state_falls_back_to_fresh_state(tmp_path, content) -> None:
    state_path = tmp_path / "bisq-sync-state.json"
    state_path.write_text(content, encoding="utf-8")

    manager = BisqSyncStateManager(str(state_path))

    assert manager.last_sync_timestamp is None
    assert manager.processed_message_ids == set()
