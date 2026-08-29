"""Tests for the address this service hands out.

The address is copied out of a status page into a config file that then travels, so the two
things worth pinning down are that it never depends on who is asking, and that a machine
which has no such address says so instead of inventing one.
"""

from __future__ import annotations

import ipaddress

import pytest

from knowledge_base.address import (
    DEFAULT_PORT,
    FixedAddress,
    NoRouteOutward,
    Reachable,
    RoutedAddress,
    advertised_for,
    primary_route_ipv4,
)


class TestWhatItResolves:
    def test_it_finds_an_ipv4_address_of_this_machine(self) -> None:
        """A routable address, which on a developer's machine is whatever the LAN gave it."""
        found = primary_route_ipv4()

        assert ipaddress.ip_address(found).version == 4

    def test_it_is_not_the_loopback_answer(self) -> None:
        """`localhost` is correct on the server and wrong for everyone the page is written for."""
        assert not ipaddress.ip_address(primary_route_ipv4()).is_loopback

    def test_a_stated_host_is_repeated_back_unchanged(self) -> None:
        """An operator who named an address knows something the routing table does not."""
        assert FixedAddress("kb.internal", 9000).advertised() == Reachable("kb.internal", 9000)


class TestWhichResolverToUse:
    def test_listening_on_every_interface_is_answered_by_the_routing_table(self) -> None:
        assert isinstance(advertised_for("0.0.0.0", DEFAULT_PORT), RoutedAddress)
        assert isinstance(advertised_for("::", DEFAULT_PORT), RoutedAddress)

    def test_a_host_the_operator_named_is_taken_at_its_word(self) -> None:
        assert advertised_for("kb.internal", 9000).advertised().host == "kb.internal"


class TestTheUrlItBuilds:
    def test_it_carries_the_port_because_a_colleague_has_to_type_one(self) -> None:
        assert Reachable("10.0.0.5", 8080).url("/mcp") == "http://10.0.0.5:8080/mcp"

    def test_the_base_address_is_the_url_without_a_path(self) -> None:
        assert Reachable("10.0.0.5", 8080).url() == "http://10.0.0.5:8080"


class TestWhenThereIsNoAddress:
    def test_it_says_so_rather_than_handing_out_something_plausible(self, monkeypatch) -> None:
        """A machine with no default route exists -- an isolated build agent is one."""

        def unrouted(*_arguments: object, **_keywords: object) -> None:
            raise OSError("Network is unreachable")

        monkeypatch.setattr("socket.socket.connect", unrouted)

        with pytest.raises(NoRouteOutward, match="--host"):
            primary_route_ipv4()
