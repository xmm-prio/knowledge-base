"""Talking to codebase-memory-mcp.

The binary is an MCP server: newline-delimited JSON-RPC 2.0 on its standard streams. This
module owns that conversation and nothing else. The channel it talks over is a seam, so the
protocol can be exercised without the binary being installed -- which on a Windows workstation
it usually is not.
"""

from __future__ import annotations

import itertools
import json
import logging
from typing import Protocol

logger = logging.getLogger(__name__)

CLIENT_NAME = "knowledge-base"

PROTOCOL_VERSION = "2025-06-18"
"""The MCP revision we speak. A server that prefers another one says so and we still proceed:
every capability we use has been in the protocol since its first revision."""

DEFAULT_TIMEOUT = 600.0
"""Seconds to wait for one reply. Indexing a large repository is minutes of silence."""


class UpstreamError(RuntimeError):
    """The upstream did not give us the answer we asked for."""


class UpstreamUnavailable(UpstreamError):
    """The upstream cannot be reached at all. The supervisor restarts on this."""


class UpstreamRefused(UpstreamError):
    """The upstream ran the tool and reported failure. Restarting would not help."""


class UpstreamFailed(UpstreamError):
    """The upstream answered, but not with something this protocol allows."""


class Channel(Protocol):
    """A line-oriented duplex link to a running upstream process."""

    def send(self, line: str) -> None:
        """Write one message. Raises UpstreamUnavailable once the far end is gone."""
        ...

    def receive(self, timeout: float) -> str:
        """Read one message. Raises UpstreamUnavailable on timeout or end of stream."""
        ...

    def close(self) -> None: ...


class Session:
    """One MCP conversation, from handshake to close."""

    def __init__(self, channel: Channel, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._channel = channel
        self._timeout = timeout
        self._ids = itertools.count(1)

    def open(self) -> None:
        """Perform the handshake. Nothing else may be sent before this returns."""
        self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")

    def ping(self) -> None:
        """Ask the upstream something cheap it must be able to answer. Raises if it cannot."""
        self._request("tools/list", {})

    def call_tool(self, tool: str, arguments: dict[str, object]) -> object:
        """Run one upstream tool and return whatever payload it produced."""
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        if not isinstance(result, dict):
            raise UpstreamFailed(f"{tool} returned {type(result).__name__}, not a result object")
        if result.get("isError"):
            raise UpstreamRefused(f"{tool}: {_text(result)}")
        return _payload(result)

    def close(self) -> None:
        self._channel.close()

    def _request(self, method: str, params: dict[str, object]) -> object:
        identifier = next(self._ids)
        self._write({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
        return self._await_reply(identifier, method)

    def _notify(self, method: str) -> None:
        self._write({"jsonrpc": "2.0", "method": method})

    def _write(self, message: dict[str, object]) -> None:
        self._channel.send(json.dumps(message, ensure_ascii=False))

    def _await_reply(self, identifier: int, method: str) -> object:
        """Read until our own reply arrives.

        The upstream shares this stream with its own notifications -- progress reports during a
        long index, above all -- so anything not carrying our id is somebody else's business.
        """
        while True:
            message = self._read()
            if message.get("id") != identifier:
                continue
            if error := message.get("error"):
                raise UpstreamFailed(f"{method}: {_message_of(error)}")
            return message.get("result")

    def _read(self) -> dict[str, object]:
        line = self._channel.receive(self._timeout)
        try:
            message = json.loads(line)
        except json.JSONDecodeError as broken:
            raise UpstreamFailed(f"upstream wrote a line that is not JSON: {line!r}") from broken
        if not isinstance(message, dict):
            raise UpstreamFailed(f"upstream wrote {type(message).__name__}, not a JSON-RPC message")
        return message


def _payload(result: dict[str, object]) -> object:
    """The useful part of a tool result.

    MCP servers may answer twice over: a structured object and a human-readable rendering of it.
    Prefer the structured half, fall back to parsing the text, and hand back prose as prose.
    """
    if "structuredContent" in result:
        return result["structuredContent"]
    text = _text(result)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _text(result: dict[str, object]) -> str:
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block["text"])
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _message_of(error: object) -> str:
    return str(error["message"]) if isinstance(error, dict) and "message" in error else str(error)
