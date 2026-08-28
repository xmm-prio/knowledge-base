"""Tests for the single write queue.

Every write to the knowledge base is funnelled through here, in submission order, one at a
time. Reads do not go through it at all.
"""

import asyncio

import pytest

from knowledge_base.writes import WriteQueue


class TestWriteQueue:
    async def test_a_write_gives_its_result_back_to_whoever_submitted_it(self) -> None:
        async with WriteQueue() as queue:
            assert await queue.submit(lambda: "learnings/ascendc/对齐.md") == (
                "learnings/ascendc/对齐.md"
            )

    async def test_a_failing_write_raises_to_its_own_caller(self) -> None:
        def boom() -> str:
            raise ValueError("no learning there")

        async with WriteQueue() as queue:
            with pytest.raises(ValueError, match="no learning there"):
                await queue.submit(boom)

    async def test_one_write_failing_does_not_stop_the_next(self) -> None:
        """A rejected distillation is routine; it must not take the queue down with it."""

        def boom() -> str:
            raise ValueError("no learning there")

        async with WriteQueue() as queue:
            with pytest.raises(ValueError):
                await queue.submit(boom)

            assert await queue.submit(lambda: "还活着") == "还活着"

    async def test_concurrent_writes_run_in_the_order_they_were_submitted(self) -> None:
        order: list[int] = []

        async with WriteQueue() as queue:
            await asyncio.gather(*(queue.submit(lambda n=n: order.append(n)) for n in range(20)))

        assert order == list(range(20))

    async def test_a_write_submitted_before_the_queue_runs_is_still_carried_out(self) -> None:
        order: list[str] = []
        queue = WriteQueue()
        submitted = asyncio.ensure_future(queue.submit(lambda: order.append("沉淀")))

        async with queue:
            await submitted

        assert order == ["沉淀"]
