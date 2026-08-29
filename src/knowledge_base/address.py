"""The address this service tells people to use.

Where a service listens and where it can be reached are different facts, and only the first
one is configured. Binding to every interface says nothing about which of them a colleague's
laptop will come in on, and `localhost` -- the name the startup log used to print -- is the
one answer that is right on the server and wrong for everybody else.

So the address handed out is worked out rather than assumed: the IPv4 address of the
interface the default route leaves by, which is the one a machine on the same network reaches.
It is deliberately not taken from the request that asked for it. A member reads the MCP
snippet off the status page and pastes it into a config file that then travels -- to another
machine, into a repository, into a message -- so it has to be the same address every time,
not whichever hostname that one browser happened to use.

When there is no such address the caller is told so. A service that quietly hands out a
plausible-looking address nobody can connect to costs an afternoon; one that says it does not
know costs a question.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Protocol

DEFAULT_PORT = 8080
"""The port the service listens on unless told otherwise, and the one it advertises."""

WILDCARD_HOSTS = frozenset({"0.0.0.0", "::", ""})
"""Listening addresses that name every interface, and therefore name none of them."""

_ROUTING_PROBE = ("192.0.2.1", 9)
"""An address in TEST-NET-1 (RFC 5737), which is documentation-only and never routed.

Connecting a UDP socket sends nothing: it only asks the kernel which local address it would
use to get there. Any off-link address answers that question, and one reserved for
documentation cannot be mistaken for the service reaching out to somewhere real.
"""


class NoRouteOutward(RuntimeError):
    """There is no IPv4 address this service could sensibly be reached on."""


@dataclass(frozen=True)
class Reachable:
    """An address other machines can use, whole enough to paste into a config file."""

    host: str
    port: int
    scheme: str = "http"

    def url(self, path: str = "") -> str:
        return f"{self.scheme}://{self.host}:{self.port}{path}"


class Address(Protocol):
    """Whatever can say where this service is reachable."""

    def advertised(self) -> Reachable:
        """Raises NoRouteOutward when there is no address worth handing out."""
        ...


def primary_route_ipv4() -> str:
    """The local IPv4 address of the interface the default route leaves by."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(_ROUTING_PROBE)
            return str(probe.getsockname()[0])
    except OSError as unrouted:
        raise NoRouteOutward(
            "找不到可对外提供服务的 IPv4 地址：这台机器没有默认路由，"
            "或者只有 IPv6。请用 --host 显式指定组员能连上的地址。"
        ) from unrouted


class RoutedAddress:
    """The address on whichever interface the default route leaves by."""

    def __init__(self, port: int = DEFAULT_PORT, scheme: str = "http") -> None:
        self._port = port
        self._scheme = scheme

    def advertised(self) -> Reachable:
        # Resolved on every call rather than at startup: a laptop that moved between networks
        # is still the same running service, and the address it hands out has to move with it.
        return Reachable(host=primary_route_ipv4(), port=self._port, scheme=self._scheme)


class FixedAddress:
    """An address somebody stated, repeated back unchanged."""

    def __init__(self, host: str, port: int = DEFAULT_PORT, scheme: str = "http") -> None:
        self._reachable = Reachable(host=host, port=port, scheme=scheme)

    def advertised(self) -> Reachable:
        return self._reachable


def advertised_for(host: str, port: int = DEFAULT_PORT) -> Address:
    """Which address to hand out, given what the service was told to listen on.

    A host named explicitly is the operator's own decision and is not second-guessed. Every
    interface at once is not an answer to "where are you", so that is the case the routing
    table has to settle.
    """
    return RoutedAddress(port) if host in WILDCARD_HOSTS else FixedAddress(host, port)
