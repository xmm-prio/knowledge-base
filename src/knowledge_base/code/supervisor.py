"""Keeping codebase-memory-mcp alive and answering, for as long as the service runs.

The upstream is a child process that can crash, and the agents talking to us never reconnect
on their own. So this module owns its whole life: it silences the upstream's own watcher
before starting it, replaces a process when it dies, and -- the part that matters most on an
upgrade -- takes down the shared coordination daemon it leaves behind.

It also owns how many of those processes there are. One MCP server answers one request at a
time on one pair of pipes: two callers sharing a session would read each other's replies, and
ten agents behind one session would queue behind the slowest question anybody asked. So the
supervisor keeps several long-lived conversations, hands out one at a time, and bounds how
many callers may be waiting at once. They all share one cache directory and one coordination
daemon, which is what ADR-0007 requires of them.
"""

from __future__ import annotations

import itertools
import logging
import math
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Protocol

from knowledge_base.code.upstream import (
    REPLAYABLE_TOOLS,
    Channel,
    Session,
    UpstreamError,
    UpstreamUnavailable,
)

logger = logging.getLogger(__name__)

DEFAULT_HEALTH_INTERVAL = timedelta(seconds=30)
DEFAULT_RESTART_INTERVAL = timedelta(seconds=30)

DEFAULT_CONVERSATIONS = 4
"""How many upstream processes may be open at once. Enough that a slow graph query does not
stall the rest, few enough that a workstation is not running an index engine per agent."""

DEFAULT_CAPACITY = 20
"""How many callers may be inside the pool at once. Past this they wait their turn rather
than being refused -- but they wait in a queue with a known bound, not in unbounded threads."""

DEFAULT_QUEUE_WAIT = timedelta(minutes=10)
"""How long a caller may wait for its turn before being told the upstream is saturated. The
same order as one upstream reply, because that is what it is waiting behind."""


class Binary(Protocol):
    """The installed executable: a server to talk to, and one-shot commands to run."""

    def spawn(self) -> Channel:
        """Start it as an MCP server. Raises UpstreamUnavailable if it will not run."""
        ...

    def run(self, *arguments: str) -> None:
        """Run one command to completion, e.g. `daemon stop`."""
        ...


def _classify(failure: BaseException | None) -> str:
    """One word for what became of a call, for the log line that records it."""
    if failure is None:
        return "ok"
    if isinstance(failure, UpstreamUnavailable):
        return "unavailable"
    if isinstance(failure, UpstreamError):
        return type(failure).__name__.removeprefix("Upstream").lower()
    return "error"


class Conversation:
    """One long-lived upstream session, and the lifecycle of the process behind it.

    A lane of its own, in both directions: only one caller holds it at a time, so replies
    cannot be crossed, and a process that dies is replaced without disturbing the others. It
    throttles its own restarts, so a binary that crashes on startup cannot spin.
    """

    def __init__(
        self,
        name: str,
        binary: Binary,
        clock: Callable[[], float],
        restart_interval: float,
    ) -> None:
        self.name = name
        self._binary = binary
        self._clock = clock
        self._restart_interval = restart_interval
        self._session: Session | None = None
        self._restarted_at = -math.inf
        self._requests = itertools.count(1)

    @property
    def open(self) -> bool:
        return self._session is not None

    def start(self) -> None:
        """Open it now, so a binary that will not run is discovered before anyone asks."""
        self._session = self._spawn()

    def request_id(self) -> str:
        """A name for one exchange, unique within this conversation."""
        return f"{self.name}#{next(self._requests)}"

    def call(self, tool: str, arguments: dict[str, object]) -> object:
        """Run one upstream tool, reopening the process first if it has died.

        A drop before the call was sent costs nothing to retry. A drop after it was sent is
        only safe to retry for a question -- see `REPLAYABLE_TOOLS` -- so anything that
        changes the upstream's index is handed back as a failure the caller can act on.
        """
        session = self._session or self._replacement()
        try:
            return session.call_tool(tool, arguments)
        except UpstreamUnavailable as gone:
            self._session = None
            logger.warning("%s: the upstream went away during %s: %s", self.name, tool, gone)
            if tool not in REPLAYABLE_TOOLS:
                raise UpstreamUnavailable(
                    f"{tool} was cut off when the upstream went away, and it changes the index, "
                    f"so it was not sent again. Ask again once the upstream is back: {gone}"
                ) from gone
        return self._replacement().call_tool(tool, arguments)

    def ping(self) -> bool:
        """Confirm this conversation still answers, replacing the process if it does not."""
        session = self._session
        if session is not None:
            try:
                session.ping()
            except UpstreamUnavailable as gone:
                self._session = None
                logger.warning("%s failed its health check: %s", self.name, gone)
            else:
                return True
        try:
            self._replacement()
        except UpstreamUnavailable:
            return False
        return True

    def close(self) -> None:
        if self._session is None:
            return
        self._session.close()
        self._session = None

    def _replacement(self) -> Session:
        """Start a fresh process, unless the last replacement was too recent to be worth it.

        The interval is measured between restarts, not since the process started: one that ran
        all day and then died deserves an immediate replacement, one that dies on startup does
        not deserve a spin loop.
        """
        if self._clock() - self._restarted_at < self._restart_interval:
            raise UpstreamUnavailable("the upstream is crashing faster than it can be restarted")
        self._restarted_at = self._clock()
        self._session = self._spawn()
        return self._session

    def _spawn(self) -> Session:
        session = Session(self._binary.spawn())
        session.open()
        logger.info("%s: upstream started", self.name)
        return session


class Supervisor:
    """Several supervised upstream conversations, and the only way to reach any of them."""

    def __init__(
        self,
        binary: Binary,
        clock: Callable[[], float] = time.monotonic,
        health_interval: timedelta = DEFAULT_HEALTH_INTERVAL,
        restart_interval: timedelta = DEFAULT_RESTART_INTERVAL,
        conversations: int = DEFAULT_CONVERSATIONS,
        capacity: int = DEFAULT_CAPACITY,
        queue_wait: timedelta = DEFAULT_QUEUE_WAIT,
    ) -> None:
        self._binary = binary
        self._clock = clock
        self._health_interval = health_interval.total_seconds()
        self._restart_interval = restart_interval.total_seconds()
        self._most = max(1, conversations)
        self._queue_wait = queue_wait.total_seconds()
        self._admission = threading.BoundedSemaphore(max(self._most, capacity))
        self._idle: queue.Queue[Conversation] = queue.Queue()
        self._all: list[Conversation] = []
        self._lock = threading.Lock()
        self._in_flight = 0
        self._started = False
        self._probed = 0.0

    @property
    def running(self) -> bool:
        return self._started

    @property
    def conversations(self) -> int:
        """How many upstream processes are open. Grows with load, up to the configured most."""
        with self._lock:
            return len(self._all)

    @property
    def in_flight(self) -> int:
        """How many callers are inside the pool, being answered or waiting their turn."""
        with self._lock:
            return self._in_flight

    def start(self) -> None:
        """Prepare the upstream and open the first conversation.

        One, not all of them: a binary that will not run has to be found out at boot, and
        everything past the first is a cost only a second concurrent caller justifies.
        """
        self._quiet_the_watcher()
        first = self._new_conversation()
        first.start()
        self._idle.put(first)
        self._started = True

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        """Run one upstream tool on whichever conversation is free."""
        if not self._started:
            raise UpstreamUnavailable("the upstream has not been started")
        with self._admitted():
            conversation = self._checkout(timeout=self._queue_wait)
            if conversation is None:
                raise UpstreamUnavailable(
                    f"every upstream conversation was busy for {self._queue_wait:g}s"
                )
            request = conversation.request_id()
            started = self._clock()
            failure: BaseException | None = None
            try:
                return conversation.call(tool, arguments)
            except BaseException as raised:
                failure = raised
                raise
            finally:
                self._return(conversation)
                logger.info(
                    "upstream call request=%s tool=%s outcome=%s elapsed_ms=%d in_flight=%d",
                    request,
                    tool,
                    _classify(failure),
                    (self._clock() - started) * 1000,
                    self._in_flight,
                )

    def check_health(self) -> bool:
        """Confirm the upstream still answers, replacing a dead process if it does not.

        Meant for a timer that ticks faster than the probe interval; extra calls are free.
        Only an idle conversation is probed, because a busy one is mid-exchange and a ping
        sent down it would be read as that exchange's reply. Everything being busy is not a
        reason to doubt the upstream -- it is what an upstream that answers looks like.
        """
        if not self._started:
            return False
        if self._clock() - self._probed < self._health_interval:
            return True
        self._probed = self._clock()
        conversation = self._checkout(timeout=0.0, grow=False)
        if conversation is None:
            return True
        try:
            return conversation.ping()
        finally:
            self._return(conversation)

    def stop(self) -> None:
        """Close every conversation and take the shared daemon down with them.

        The upstream keeps one coordination daemon per account and refuses to admit a process
        of a different version, so a daemon left running turns the next upgrade into a boot
        failure. Nothing about our own process exiting removes it.
        """
        if not self._started:
            return
        self._started = False
        with self._lock:
            closing, self._all = self._all, []
        for conversation in closing:
            conversation.close()
        self._drain()
        self._binary.run("daemon", "stop")

    @contextmanager
    def _admitted(self) -> Iterator[None]:
        """Hold one of the pool's places for the duration of one call.

        Waiting to be admitted and waiting for a conversation are one wait to the caller and
        two things to the service: the first bounds how many callers exist at all, the second
        decides which of them is being answered. Saturation is reported as such rather than
        absorbed into an unbounded pile of waiting threads.
        """
        if not self._admission.acquire(timeout=self._queue_wait):
            raise UpstreamUnavailable(
                f"too many code requests are already waiting for the upstream "
                f"({self._queue_wait:g}s)"
            )
        with self._lock:
            self._in_flight += 1
        try:
            yield
        finally:
            with self._lock:
                self._in_flight -= 1
            self._admission.release()

    def _checkout(self, timeout: float, grow: bool = True) -> Conversation | None:
        """Take a free conversation, opening another one if the pool may still grow."""
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            pass
        if grow:
            with self._lock:
                if len(self._all) < self._most:
                    return self._new_conversation(locked=True)
        if timeout <= 0:
            return None
        try:
            return self._idle.get(timeout=timeout)
        except queue.Empty:
            return None

    def _return(self, conversation: Conversation) -> None:
        with self._lock:
            if conversation not in self._all:
                # It was closed while it was out; it does not go back into rotation.
                conversation.close()
                return
        self._idle.put(conversation)

    def _new_conversation(self, locked: bool = False) -> Conversation:
        conversation = Conversation(
            name=f"upstream-{len(self._all) + 1}",
            binary=self._binary,
            clock=self._clock,
            restart_interval=self._restart_interval,
        )
        if locked:
            self._all.append(conversation)
            return conversation
        with self._lock:
            self._all.append(conversation)
        return conversation

    def _drain(self) -> None:
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                return

    def _quiet_the_watcher(self) -> None:
        """Turn off the upstream's own file watcher, and make the setting take effect.

        We decide when a repository is reindexed. The upstream reads this setting once, when
        its daemon starts, so a daemon left over from an earlier run has to go first.

        The key is `auto_watch`. Upstream rejects unknown keys with a non-zero exit rather
        than a failure we can catch, so a wrong name here disables nothing and says so only
        in a log line nobody reads.
        """
        self._binary.run("config", "set", "auto_watch", "false")
        self._binary.run("daemon", "stop")
