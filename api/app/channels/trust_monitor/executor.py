"""Dedicated worker pool for synchronous trust-monitor operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")

# Trust-monitor ingestion can synchronously wait for an async Matrix delivery to
# finish. Keeping those bounded waits off asyncio's default executor prevents an
# alert burst from starving unrelated ``asyncio.to_thread`` work process-wide.
_TRUST_MONITOR_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="trust-monitor",
)


async def run_in_trust_monitor_executor(
    function: Callable[_P, _T],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> _T:
    """Run one synchronous trust-monitor operation in its isolated worker pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _TRUST_MONITOR_EXECUTOR,
        partial(function, *args, **kwargs),
    )
