"""Test doubles for the code domain's upstream.

The binary only exists on the deployment target, so everything below the channel is faked and
everything above it -- the JSON-RPC framing, the handshake, the tool results -- is real.
"""

import json

from knowledge_base.code.upstream import Channel, UpstreamUnavailable


class FakeChannel:
    """An upstream MCP server answering over an in-process link instead of a pipe."""

    def __init__(self, results: dict[str, object] | None = None) -> None:
        self.results = results or {}
        self.sent: list[dict[str, object]] = []
        self.pending: list[str] = []
        self.noise: list[dict[str, object]] = []
        self.closed = False

    def send(self, line: str) -> None:
        if self.closed:
            raise UpstreamUnavailable("the upstream is gone")
        message = json.loads(line)
        self.sent.append(message)
        if "id" not in message:
            return
        self.pending += [json.dumps(extra) for extra in self.noise]
        self.noise = []
        self.pending.append(
            json.dumps({"jsonrpc": "2.0", "id": message["id"]} | self._reply(message))
        )

    def receive(self, timeout: float) -> str:
        if not self.pending:
            raise UpstreamUnavailable("nothing to read")
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True

    def die(self) -> None:
        """What a crashed binary looks like from this side."""
        self.closed = True

    def methods(self) -> list[str]:
        return [str(message["method"]) for message in self.sent]

    def _reply(self, message: dict[str, object]) -> dict[str, object]:
        params = message.get("params")
        if message["method"] != "tools/call" or not isinstance(params, dict):
            return {"result": {}}
        canned = self.results.get(str(params["name"]))
        return canned if isinstance(canned, dict) else {"result": {"content": []}}


class FakeBinary:
    """The installed executable, without the executable."""

    def __init__(self, results: dict[str, object] | None = None) -> None:
        self.results = results or {}
        self.channels: list[FakeChannel] = []
        self.actions: list[str] = []
        self.refuses_to_spawn = False

    def spawn(self) -> Channel:
        self.actions.append("spawn")
        if self.refuses_to_spawn:
            raise UpstreamUnavailable("the binary is not installed")
        channel = FakeChannel(self.results)
        self.channels.append(channel)
        return channel

    def run(self, *arguments: str) -> None:
        self.actions.append(" ".join(arguments))

    @property
    def channel(self) -> FakeChannel:
        """The channel currently in use."""
        return self.channels[-1]


def tool_result(payload: object) -> dict[str, object]:
    """What an MCP server returns for a successful tool call."""
    return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
