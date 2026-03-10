"""Real Matrix E2E for staff thread commands in encrypted rooms.

Runs two scenarios against a live local API + live Matrix rooms:
- trusted staff replies in thread with ``/send <edited reply>``
- trusted staff replies in thread with ``/dismiss``

This script uses ``matrix-nio`` with encryption enabled so the staff/user
messages follow the same encrypted path as real Element clients.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nio import AsyncClient, AsyncClientConfig

from app.channels.plugins.matrix.client.session_manager import SessionManager


DEFAULT_HOMESERVER = "https://matrix.org"
DEFAULT_ADMIN_API_BASE = "http://localhost:8000"
DEFAULT_STORE_ROOT = Path("/tmp/matrix-thread-command-e2e")
HTTP_TIMEOUT_SECONDS = 30
STATUS_TIMEOUT_SECONDS = 60
ESCALATION_TIMEOUT_SECONDS = 120
NOTICE_TIMEOUT_SECONDS = 90
ROOM_EVENT_TIMEOUT_SECONDS = 25


class E2EError(RuntimeError):
    """Raised when the live Matrix E2E cannot proceed."""


@dataclass
class MatrixActor:
    user_id: str
    password: str
    client: AsyncClient
    session_file: Path
    store_dir: Path

    @property
    def access_token(self) -> str:
        return str(getattr(self.client, "access_token", "") or "")


@dataclass
class ScenarioResult:
    name: str
    escalation_id: int | None
    passed: bool
    detail: str


def _env_required(name: str) -> str:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        raise E2EError(f"Missing required environment variable: {name}")
    return value


def _http_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = HTTP_TIMEOUT_SECONDS,
    retries: int = 3,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode()
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else {}
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            ConnectionError,
        ) as exc:
            last_error = exc
        except Exception as exc:  # pragma: no cover - live-network defensive branch
            last_error = exc
        if attempt + 1 < retries:
            time.sleep(1.5)
    raise E2EError(f"HTTP {method} {url} failed: {last_error}") from last_error


def _matrix_room_messages(
    access_token: str,
    room_id: str,
    *,
    limit: int = 120,
) -> list[dict[str, Any]]:
    room_encoded = urllib.parse.quote(room_id, safe="")
    url = f"{DEFAULT_HOMESERVER}/_matrix/client/v3/rooms/{room_encoded}/messages?dir=b&limit={limit}"
    data = _http_json(
        "GET",
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return list(data.get("chunk", []) or [])


def _matrix_room_event(
    access_token: str,
    room_id: str,
    event_id: str,
) -> dict[str, Any]:
    room_encoded = urllib.parse.quote(room_id, safe="")
    event_encoded = urllib.parse.quote(event_id, safe="")
    url = f"{DEFAULT_HOMESERVER}/_matrix/client/v3/rooms/{room_encoded}/event/{event_encoded}"
    return _http_json(
        "GET",
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )


def _admin_get_escalation(api_base: str, api_key: str, escalation_id: int) -> dict[str, Any]:
    return _http_json(
        "GET",
        f"{api_base}/admin/escalations/{escalation_id}",
        headers={"X-API-KEY": api_key},
    )


def _admin_search_escalation(
    api_base: str,
    api_key: str,
    marker: str,
) -> dict[str, Any] | None:
    query = urllib.parse.quote(marker)
    data = _http_json(
        "GET",
        f"{api_base}/admin/escalations?search={query}&limit=5",
        headers={"X-API-KEY": api_key},
    )
    total = int(data.get("total", 0) or 0)
    if total <= 0:
        return None
    return data["escalations"][0]


async def _create_actor(
    *,
    homeserver: str,
    user_id: str,
    password: str,
    root: Path,
) -> MatrixActor:
    localpart = user_id.replace("@", "").replace(":", "_")
    store_dir = root / f"{localpart}_store"
    session_file = root / f"{localpart}_session.json"
    store_dir.mkdir(parents=True, exist_ok=True)
    client = AsyncClient(
        homeserver,
        user_id,
        store_path=str(store_dir),
        config=AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=True,
        ),
    )
    session_manager = SessionManager(
        client=client,
        password=password,
        session_file=str(session_file),
    )
    await session_manager.login()
    await client.sync(timeout=3000, full_state=True)
    await client.sync(timeout=3000)
    return MatrixActor(
        user_id=user_id,
        password=password,
        client=client,
        session_file=session_file,
        store_dir=store_dir,
    )


async def _join_if_needed(actor: MatrixActor, room_id: str) -> None:
    if room_id in getattr(actor.client, "rooms", {}):
        return
    join = getattr(actor.client, "join", None)
    if not callable(join):
        return
    await join(room_id)
    await actor.client.sync(timeout=2000, full_state=True)


async def _send_encrypted_message(
    actor: MatrixActor,
    room_id: str,
    body: str,
    *,
    reply_to_event_id: str | None = None,
) -> tuple[str, int]:
    await _join_if_needed(actor, room_id)
    content: dict[str, Any] = {
        "msgtype": "m.text",
        "body": body,
    }
    if reply_to_event_id:
        content["m.relates_to"] = {
            "m.in_reply_to": {"event_id": reply_to_event_id},
        }
    response = await actor.client.room_send(
        room_id=room_id,
        message_type="m.room.message",
        content=content,
        ignore_unverified_devices=True,
    )
    event_id = str(getattr(response, "event_id", "") or "").strip()
    if not event_id:
        raise E2EError(f"Failed sending Matrix message as {actor.user_id}: {response}")
    event_payload = _matrix_room_event(actor.access_token, room_id, event_id)
    server_ts = int(event_payload.get("origin_server_ts", 0) or 0)
    if server_ts <= 0:
        server_ts = int(time.time() * 1000)
    return event_id, server_ts


def _recent_sender_events(
    access_token: str,
    room_id: str,
    *,
    sender: str,
    since_ts_ms: int,
) -> list[tuple[str, int, str]]:
    events: list[tuple[str, int, str]] = []
    for event in _matrix_room_messages(access_token, room_id):
        event_id = str(event.get("event_id", "") or "").strip()
        event_sender = str(event.get("sender", "") or "").strip()
        event_type = str(event.get("type", "") or "").strip()
        timestamp = int(event.get("origin_server_ts", 0) or 0)
        if not event_id or event_sender != sender or timestamp < since_ts_ms:
            continue
        if event_type not in {"m.room.encrypted", "m.room.message"}:
            continue
        events.append((event_id, timestamp, event_type))
    return events


def _wait_for_escalation(api_base: str, api_key: str, marker: str) -> dict[str, Any]:
    deadline = time.time() + ESCALATION_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            escalation = _admin_search_escalation(api_base, api_key, marker)
        except E2EError:
            time.sleep(2)
            continue
        if escalation is not None:
            return escalation
        time.sleep(2)
    raise E2EError(f"Timed out waiting for escalation for marker={marker}")


def _wait_for_status(
    api_base: str,
    api_key: str,
    escalation_id: int,
    expected_statuses: set[str],
) -> dict[str, Any] | None:
    deadline = time.time() + STATUS_TIMEOUT_SECONDS
    while time.time() < deadline:
        try:
            escalation = _admin_get_escalation(api_base, api_key, escalation_id)
        except E2EError:
            time.sleep(2)
            continue
        status = str(escalation.get("status", "") or "").lower()
        if status in expected_statuses:
            return escalation
        time.sleep(2)
    return None


def _wait_for_sender_event(
    access_token: str,
    room_id: str,
    *,
    sender: str,
    since_ts_ms: int,
    timeout_seconds: int,
) -> tuple[str, int, str] | None:
    seen: set[str] = set()
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for event in _recent_sender_events(
            access_token,
            room_id,
            sender=sender,
            since_ts_ms=since_ts_ms,
        ):
            if event[0] in seen:
                continue
            return event
        seen.update(event_id for event_id, _, _ in _recent_sender_events(
            access_token,
            room_id,
            sender=sender,
            since_ts_ms=since_ts_ms,
        ))
        time.sleep(2)
    return None


async def _run_scenario(
    *,
    name: str,
    command_text: str,
    expect_statuses: set[str],
    expect_staff_answer: bool,
    expect_user_room_reply: bool,
    user_actor: MatrixActor,
    staff_actor: MatrixActor,
    bot_user_id: str,
    sync_room: str,
    staff_room: str,
    api_base: str,
    api_key: str,
) -> ScenarioResult:
    marker = f"MATRIX-THREAD-E2E::{name}::{int(time.time())}"
    question = f"where is my money? {marker}"
    print(f"\n--- scenario={name} marker={marker}")

    _, user_sent_ts = await _send_encrypted_message(user_actor, sync_room, question)
    print("user question sent")

    escalation = _wait_for_escalation(api_base, api_key, marker)
    escalation_id = int(escalation["id"])
    print(f"escalation created id={escalation_id}")

    staff_notice = _wait_for_sender_event(
        staff_actor.access_token,
        staff_room,
        sender=bot_user_id,
        since_ts_ms=user_sent_ts,
        timeout_seconds=NOTICE_TIMEOUT_SECONDS,
    )
    if staff_notice is None:
        return ScenarioResult(name, escalation_id, False, "staff notice event not found")

    staff_notice_event_id, _, _ = staff_notice
    print(f"staff notice event={staff_notice_event_id}")

    _, command_sent_ts = await _send_encrypted_message(
        staff_actor,
        staff_room,
        command_text,
        reply_to_event_id=staff_notice_event_id,
    )
    print(f"staff command sent command={command_text!r}")

    updated = _wait_for_status(api_base, api_key, escalation_id, expect_statuses)
    if updated is None:
        final = _admin_get_escalation(api_base, api_key, escalation_id)
        return ScenarioResult(
            name,
            escalation_id,
            False,
            f"status did not reach {sorted(expect_statuses)} final_status={final.get('status')}",
        )

    status = str(updated.get("status", "") or "").lower()
    has_staff_answer = bool(str(updated.get("staff_answer", "") or "").strip())
    if has_staff_answer != expect_staff_answer:
        return ScenarioResult(
            name,
            escalation_id,
            False,
            f"staff_answer mismatch status={status} has_staff_answer={has_staff_answer}",
        )

    user_room_reply = _wait_for_sender_event(
        user_actor.access_token,
        sync_room,
        sender=bot_user_id,
        since_ts_ms=command_sent_ts,
        timeout_seconds=ROOM_EVENT_TIMEOUT_SECONDS,
    )
    if expect_user_room_reply and user_room_reply is None:
        return ScenarioResult(
            name,
            escalation_id,
            False,
            f"status={status} but no user-room reply detected",
        )
    if not expect_user_room_reply and user_room_reply is not None:
        return ScenarioResult(
            name,
            escalation_id,
            False,
            f"status={status} but unexpected user-room reply detected",
        )

    return ScenarioResult(
        name,
        escalation_id,
        True,
        f"status={status} user_room_reply={bool(user_room_reply)}",
    )


async def _async_main(args: argparse.Namespace) -> int:
    homeserver = args.homeserver
    api_base = args.api_base.rstrip("/")
    api_key = args.api_key
    root = args.store_root.expanduser().resolve()

    if args.clean and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    user_actor = await _create_actor(
        homeserver=homeserver,
        user_id=args.user_id,
        password=args.user_password,
        root=root,
    )
    staff_actor = await _create_actor(
        homeserver=homeserver,
        user_id=args.staff_id,
        password=args.staff_password,
        root=root,
    )

    try:
        results = [
            await _run_scenario(
                name="thread_send_edited",
                command_text="/send Edited answer from Matrix thread command test.",
                expect_statuses={"responded", "closed"},
                expect_staff_answer=True,
                expect_user_room_reply=True,
                user_actor=user_actor,
                staff_actor=staff_actor,
                bot_user_id=args.bot_user_id,
                sync_room=args.sync_room,
                staff_room=args.staff_room,
                api_base=api_base,
                api_key=api_key,
            ),
            await _run_scenario(
                name="thread_dismiss",
                command_text="/dismiss",
                expect_statuses={"closed"},
                expect_staff_answer=False,
                expect_user_room_reply=False,
                user_actor=user_actor,
                staff_actor=staff_actor,
                bot_user_id=args.bot_user_id,
                sync_room=args.sync_room,
                staff_room=args.staff_room,
                api_base=api_base,
                api_key=api_key,
            ),
        ]
    finally:
        await user_actor.client.close()
        await staff_actor.client.close()

    print("\n=== MATRIX THREAD COMMAND E2E SUMMARY ===")
    failures = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(
            f"{status} scenario={result.name} escalation_id={result.escalation_id} detail={result.detail}"
        )
        if not result.passed:
            failures += 1
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--homeserver",
        default=os.getenv("MATRIX_HOMESERVER_URL", DEFAULT_HOMESERVER),
    )
    parser.add_argument(
        "--api-base",
        default=os.getenv("MATRIX_E2E_ADMIN_API_BASE", DEFAULT_ADMIN_API_BASE),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MATRIX_E2E_ADMIN_API_KEY", os.getenv("ADMIN_API_KEY", "")),
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("MATRIX_E2E_USER_ID", ""),
    )
    parser.add_argument(
        "--user-password",
        default=os.getenv("MATRIX_E2E_USER_PASSWORD", ""),
    )
    parser.add_argument(
        "--staff-id",
        default=os.getenv("MATRIX_E2E_STAFF_ID", os.getenv("MATRIX_ALERT_USER", "")),
    )
    parser.add_argument(
        "--staff-password",
        default=os.getenv("MATRIX_E2E_STAFF_PASSWORD", os.getenv("MATRIX_ALERT_PASSWORD", "")),
    )
    parser.add_argument(
        "--bot-user-id",
        default=os.getenv("MATRIX_E2E_BOT_USER_ID", os.getenv("MATRIX_SYNC_USER", "")),
    )
    parser.add_argument(
        "--sync-room",
        default=os.getenv("MATRIX_E2E_SYNC_ROOM", ""),
    )
    parser.add_argument(
        "--staff-room",
        default=os.getenv("MATRIX_E2E_STAFF_ROOM", os.getenv("MATRIX_STAFF_ROOM", "")),
    )
    parser.add_argument(
        "--store-root",
        type=Path,
        default=Path(os.getenv("MATRIX_E2E_STORE_ROOT", str(DEFAULT_STORE_ROOT))),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove local matrix-nio store/session files before the run.",
    )
    args = parser.parse_args()

    if not str(args.api_key or "").strip():
        raise E2EError("Missing admin API key (--api-key or MATRIX_E2E_ADMIN_API_KEY)")
    args.user_id = args.user_id or _env_required("MATRIX_E2E_USER_ID")
    args.user_password = args.user_password or _env_required("MATRIX_E2E_USER_PASSWORD")
    args.staff_id = args.staff_id or _env_required("MATRIX_E2E_STAFF_ID")
    args.staff_password = args.staff_password or _env_required("MATRIX_E2E_STAFF_PASSWORD")
    args.bot_user_id = args.bot_user_id or _env_required("MATRIX_E2E_BOT_USER_ID")
    args.sync_room = args.sync_room or _env_required("MATRIX_E2E_SYNC_ROOM")
    args.staff_room = args.staff_room or _env_required("MATRIX_E2E_STAFF_ROOM")
    return args


def main() -> int:
    args = parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
