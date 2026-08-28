"""Staying alive while something slow is running.

An agent's tool call is cut off after thirty seconds of silence, but the clock is reset by
every progress report. Indexing or walking a large repository is well past thirty seconds, and
the code domain is synchronous, so the work goes to a thread and this keeps saying it is not
finished until it is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta

from fastmcp import Context

HEARTBEAT = timedelta(seconds=5)
"""Comfortably inside the thirty seconds an agent waits, without flooding its channel."""

WORKING = "上游正在处理"


async def answered[T](work: Callable[[], T], context: Context, heartbeat: timedelta) -> T:
    """Run blocking work off the event loop, reporting progress until it finishes.

    Progress is a count of heartbeats with no total: how long the upstream will take is not
    knowable, and claiming a percentage would be an invention.
    """
    task = asyncio.create_task(asyncio.to_thread(work))
    beats = 0
    while True:
        done, _ = await asyncio.wait({task}, timeout=heartbeat.total_seconds())
        if done:
            return task.result()
        beats += 1
        await context.report_progress(progress=beats, message=WORKING)
