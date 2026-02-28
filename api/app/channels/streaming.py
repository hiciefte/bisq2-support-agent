"""Streaming delivery helpers with safe channel fallbacks."""

from __future__ import annotations

import copy
import inspect
from collections.abc import AsyncIterable, Iterable
from typing import Any

_STREAM_ATTRS = ("stream", "answer_stream", "stream_chunks")
_MISSING = object()


def _resolve_stream(response: Any) -> Any | None:
    for attr in _STREAM_ATTRS:
        static_value = inspect.getattr_static(response, attr, _MISSING)
        if static_value is _MISSING:
            continue
        candidate = getattr(response, attr, None)
        if candidate is not None:
            return candidate
    return None


async def _aiter_chunks(stream: Any) -> AsyncIterable[str]:
    if isinstance(stream, AsyncIterable):
        async for chunk in stream:
            if chunk is None:
                continue
            yield str(chunk)
        return

    if isinstance(stream, Iterable):
        for chunk in stream:
            if chunk is None:
                continue
            yield str(chunk)


def _clone_with_answer(response: Any, answer: str) -> Any:
    if hasattr(response, "model_copy") and callable(response.model_copy):
        return response.model_copy(update={"answer": answer})

    cloned = copy.copy(response)
    setattr(cloned, "answer", answer)
    return cloned


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def deliver_native_stream(channel: Any, target: str, response: Any) -> bool:
    sender = getattr(channel, "send_streaming_message", None)
    if not callable(sender):
        return False
    result = sender(target, response)
    return bool(await _await_if_needed(result))


async def deliver_buffered_stream(channel: Any, target: str, response: Any) -> bool:
    stream = _resolve_stream(response)
    if stream is None:
        result = channel.send_message(target, response)
        return bool(await _await_if_needed(result))

    chunks: list[str] = []
    async for piece in _aiter_chunks(stream):
        if piece:
            chunks.append(piece)

    buffered_answer = "".join(chunks).strip()
    final_answer = buffered_answer or str(getattr(response, "answer", "") or "")
    final_response = _clone_with_answer(response, final_answer)
    result = channel.send_message(target, final_response)
    return bool(await _await_if_needed(result))
