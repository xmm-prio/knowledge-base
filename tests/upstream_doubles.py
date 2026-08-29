"""Test doubles for the code domain's upstream.

The binary only exists on the deployment target, so everything below the channel is faked and
everything above it -- the JSON-RPC framing, the handshake, the tool results -- is real.

These doubles hold several conversations at once, because that is what the gateway does. A
double that answers the instant it is asked can never show whether two callers got each
other's replies: by the time the second question is asked the first is already over. So a
reply passes through a `Gate`, and a held gate is what turns "twenty questions are in flight
and none of them has been answered yet" into a state a test can look at.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from tests.upstream_schema import refusal, unknown_arguments

from knowledge_base.code.upstream import Channel, UpstreamUnavailable

VIOLATIONS: list[str] = []
"""Calls that named an argument the real upstream does not have, from every double in the
running test. Emptied and asserted on by an autouse fixture; see conftest."""

SCOPED_ARGS: dict[str, object] = {"project": "somewhere"}
"""The least a read tool will accept. Tests about the plumbing -- framing, pooling, crashes --
still have to make a call the upstream would run, or they are testing the refusal instead."""

PATIENCE = 5.0
"""Seconds a faked exchange may block for. Past this a test is wedged, not slow, and saying
so beats inheriting the ten-minute deadline the real upstream is given."""


class Gate:
    """A hold on replies, and a count of who is waiting behind it.

    Open by default, so a channel nobody is holding behaves like the immediate one it
    replaced. Closed, every reply queues up and `waiting` says how many.
    """

    def __init__(self) -> None:
        self._open = threading.Event()
        self._open.set()
        self._changed = threading.Condition()
        self._waiting = 0

    @property
    def waiting(self) -> int:
        """How many requests are being held right now."""
        with self._changed:
            return self._waiting

    def hold(self) -> None:
        self._open.clear()

    def release(self) -> None:
        self._open.set()

    def wait_for(self, requests: int, timeout: float = PATIENCE) -> None:
        """Block until that many requests are held at once."""
        deadline = time.monotonic() + timeout
        with self._changed:
            while self._waiting < requests:
                if not self._changed.wait(max(0.0, deadline - time.monotonic())):
                    raise AssertionError(
                        f"only {self._waiting} of {requests} requests reached the upstream"
                    )

    def pass_through(self, alive: Callable[[], bool]) -> None:
        """Let one request past, once the test has stopped holding it.

        A channel that dies while its request is held lets it go too: a crash has to reach
        the caller as a failure, not as a wait that never ends.
        """
        if self._open.is_set():
            return
        with self._changed:
            self._waiting += 1
            self._changed.notify_all()
        try:
            deadline = time.monotonic() + PATIENCE
            while not self._open.is_set() and alive():
                if time.monotonic() > deadline:
                    raise AssertionError("a held request was never released")
                self._open.wait(0.01)
        finally:
            with self._changed:
                self._waiting -= 1
                self._changed.notify_all()


class FakeChannel:
    """An upstream MCP server answering over an in-process link instead of a pipe.

    Replies are queued rather than handed back, so a reader waits for its own answer exactly
    as it waits on a pipe. Swap `gate` for one of your own to hold this conversation while
    the others carry on.
    """

    def __init__(
        self,
        results: dict[str, object] | None = None,
        name: str = "upstream",
        gate: Gate | None = None,
        patience: float = PATIENCE,
        strict: bool = True,
    ) -> None:
        self.results = results if results is not None else {}
        self.name = name
        self.gate = gate if gate is not None else Gate()
        self.strict = strict
        """Whether to hold callers to the real tool contract. Off only for tests about the
        protocol itself, which call tools the upstream does not have."""
        self.sent: list[dict[str, object]] = []
        self.noise: list[dict[str, object]] = []
        self.closed = False
        self.delay = 0.0
        """Seconds to spend on each reply, for an upstream that is slow rather than held."""

        self._patience = patience
        self._replies: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()

    def send(self, line: str) -> None:
        if self.closed:
            raise UpstreamUnavailable("the upstream is gone")
        message = json.loads(line)
        with self._lock:
            self.sent.append(message)
        if "id" not in message:
            return
        if message.get("method") == "tools/call":
            # Only the work is held. A handshake and a health probe are plumbing, and a test
            # holding those would be holding the pool together rather than holding it up.
            self.gate.pass_through(lambda: not self.closed)
        if self.delay:
            time.sleep(self.delay)
        if self.closed:
            raise UpstreamUnavailable("the upstream is gone")
        with self._lock:
            noise, self.noise = self.noise, []
        for extra in noise:
            self._replies.put(json.dumps(extra))
        self._replies.put(
            json.dumps({"jsonrpc": "2.0", "id": message["id"]} | self._reply(message))
        )

    def receive(self, timeout: float) -> str:
        try:
            line = self._replies.get(timeout=min(timeout, self._patience))
        except queue.Empty:
            raise UpstreamUnavailable(f"the upstream said nothing for {timeout:g}s") from None
        if line is None:
            raise UpstreamUnavailable("the upstream closed its output")
        return line

    def close(self) -> None:
        self.closed = True
        # Whoever is waiting for a reply has to be told, or they wait out the whole deadline.
        self._replies.put(None)

    def die(self) -> None:
        """What a crashed binary looks like from this side."""
        self.close()

    def methods(self) -> list[str]:
        with self._lock:
            return [str(message["method"]) for message in self.sent]

    def tools_called(self) -> list[str]:
        """The upstream tools asked for on this conversation, in order."""
        with self._lock:
            return [
                str(message["params"]["name"])  # type: ignore[index]
                for message in self.sent
                if message.get("method") == "tools/call"
            ]

    def _reply(self, message: dict[str, object]) -> dict[str, object]:
        params = message.get("params")
        if message["method"] != "tools/call" or not isinstance(params, dict):
            return {"result": {}}
        tool = str(params["name"])
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        if self.strict and (refused := refusal(tool, arguments)) is not None:
            return {"result": {"isError": True, "content": [{"type": "text", "text": refused}]}}
        if self.strict:
            VIOLATIONS.extend(
                f"{tool} has no argument {name!r}" for name in unknown_arguments(tool, arguments)
            )
        canned = self.results.get(tool)
        if callable(canned):
            # An answer computed from the question is how a test tells replies apart when
            # several are in flight at once.
            canned = canned(arguments)
        return canned if isinstance(canned, dict) else {"result": {"content": []}}


class FakeBinary:
    """The installed executable, without the executable.

    Every conversation it hands out shares one gate, so a test can hold the whole upstream
    at once and see how much the gateway managed to send before it filled up.
    """

    def __init__(
        self,
        results: dict[str, object] | None = None,
        patience: float = PATIENCE,
        strict: bool = True,
    ) -> None:
        self.results = results or {}
        self.strict = strict
        self.channels: list[FakeChannel] = []
        self.actions: list[str] = []
        self.refuses_to_spawn = False
        self.gate = Gate()
        self._patience = patience
        self._lock = threading.Lock()

    def spawn(self) -> Channel:
        with self._lock:
            self.actions.append("spawn")
            refusing = self.refuses_to_spawn
            index = len(self.channels) + 1
        if refusing:
            raise UpstreamUnavailable("the binary is not installed")
        channel = FakeChannel(
            self.results,
            name=f"upstream-{index}",
            gate=self.gate,
            patience=self._patience,
            strict=self.strict,
        )
        with self._lock:
            self.channels.append(channel)
        return channel

    def run(self, *arguments: str) -> None:
        with self._lock:
            self.actions.append(" ".join(arguments))

    @property
    def channel(self) -> FakeChannel:
        """The channel most recently handed out."""
        return self.channels[-1]

    @property
    def live(self) -> list[FakeChannel]:
        """The conversations that have not been closed or killed."""
        return [one for one in self.channels if not one.closed]

    def hold(self) -> None:
        """Stop answering, on every conversation at once."""
        self.gate.hold()

    def release(self) -> None:
        self.gate.release()

    def wait_for(self, requests: int, timeout: float = PATIENCE) -> None:
        """Block until that many requests are held across all conversations."""
        self.gate.wait_for(requests, timeout)


def tool_result(payload: object) -> dict[str, object]:
    """What an MCP server returns for a successful tool call."""
    return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


class StubUpstream:
    """The supervised binary as the code domain sees it: canned answers, no protocol.

    It keeps its own list of indexed projects and answers `list_projects` from it, spelled
    the way the binary spells one. Tests say which repositories are indexed by putting them
    there; nobody writes a project name by hand, because the whole point is that the name is
    the upstream's to derive and not ours to predict.
    """

    def __init__(self, answers: dict[str, object] | None = None) -> None:
        self.answers = answers or {}
        self.failing: set[str] = set()
        self.raising: dict[str, Exception] = {}
        """Failures of a stated kind, for tests about how a failure is classified."""

        self.indexed: list[Path] = []
        self.unknown_to: set[str] = set()
        """Projects that refuse everything, for a symbol only one repository has heard of."""

        self.calls: list[tuple[str, dict[str, object]]] = []

    def indexes(self, location: Path) -> str:
        """Have the upstream claim this directory, and say what it now calls it."""
        self.indexed.append(location)
        return derived_name(location)

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        self.calls.append((tool, arguments))
        if (stated := self.raising.get(tool)) is not None:
            raise stated
        if tool in self.failing:
            raise RuntimeError(f"{tool} refused")
        if arguments.get("project") in self.unknown_to:
            raise RuntimeError(f"{arguments['project']} knows nothing about that")
        answer = self.answers.get(tool)
        if isinstance(answer, Exception):
            raise answer
        if answer is not None:
            return answer
        return self._listing() if tool == "list_projects" else {}

    def arguments_for(self, tool: str) -> list[dict[str, object]]:
        return [arguments for name, arguments in self.calls if name == tool]

    def _listing(self) -> dict[str, object]:
        projects = [
            {"name": derived_name(location), "root_path": str(location)}
            for location in self.indexed
        ]
        return {
            "projects": projects,
            "total": len(projects),
            "offset": 0,
            "limit": 100,
            "returned": len(projects),
            "has_more": False,
        }


def derived_name(location: Path) -> str:
    """The name the upstream gives a repository indexed from this path.

    It flattens the whole path rather than taking its last component, which is why a gateway
    that assumes the directory name gets a refusal: `/home/mdc/kb/codebase/ge` is indexed as
    `home-mdc-kb-codebase-ge`.
    """
    return re.sub(r"[^A-Za-z0-9]+", "-", str(location)).strip("-").lower()


def project_listing(codebase: Path, *repos: str) -> dict[str, object]:
    """A `list_projects` answer covering these repositories, spelled the upstream's way."""
    projects = [
        {"name": derived_name(codebase / repo), "root_path": str(codebase / repo)} for repo in repos
    ]
    return tool_result(
        {
            "projects": projects,
            "total": len(projects),
            "offset": 0,
            "limit": 100,
            "returned": len(projects),
            "has_more": False,
        }
    )


def echo(payload: Callable[[dict[str, object]], object]) -> Callable[[dict[str, object]], object]:
    """A canned answer computed from the arguments it was asked with.

    Distinct answers are the only way to catch a reply reaching the wrong caller.
    """
    return lambda arguments: tool_result(payload(arguments))
