"""Tests for the background heartbeat.

The debounced auto-commit only reaches git if something calls it on a timer. This is that
timer, and it has to survive whatever the action throws at it.
"""

from datetime import timedelta

from conftest import ManualSleep
from knowledge_base.scheduling import Heartbeat

EVERY_FIVE_SECONDS = timedelta(seconds=5)


class TestHeartbeat:
    async def test_it_acts_once_per_interval(self) -> None:
        beats: list[int] = []
        sleep = ManualSleep()

        async def beat() -> None:
            beats.append(len(beats))

        heartbeat = Heartbeat(EVERY_FIVE_SECONDS, beat, sleep=sleep)
        await heartbeat.start()
        await sleep.tick()
        await sleep.tick()
        await heartbeat.stop()

        assert beats == [0, 1]

    async def test_it_waits_the_interval_it_was_given(self) -> None:
        sleep = ManualSleep()

        async def beat() -> None:
            return None

        heartbeat = Heartbeat(EVERY_FIVE_SECONDS, beat, sleep=sleep)
        await heartbeat.start()
        await sleep.tick()
        await heartbeat.stop()

        assert sleep.intervals[:1] == [5.0]

    async def test_a_failing_action_does_not_stop_the_heartbeat(self) -> None:
        """One unwritable commit must not silently end auto-commit for the whole process."""
        beats: list[int] = []
        sleep = ManualSleep()

        async def beat() -> None:
            beats.append(len(beats))
            raise RuntimeError("git is unhappy")

        heartbeat = Heartbeat(EVERY_FIVE_SECONDS, beat, sleep=sleep)
        await heartbeat.start()
        await sleep.tick()
        await sleep.tick()
        await heartbeat.stop()

        assert beats == [0, 1]

    async def test_stopping_it_ends_the_beating(self) -> None:
        beats: list[int] = []
        sleep = ManualSleep()

        async def beat() -> None:
            beats.append(len(beats))

        heartbeat = Heartbeat(EVERY_FIVE_SECONDS, beat, sleep=sleep)
        await heartbeat.start()
        await sleep.tick()
        await heartbeat.stop()
        await heartbeat.stop()

        assert beats == [0]
