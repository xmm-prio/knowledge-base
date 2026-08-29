"""A real browser pointed at a real service.

The web UI is the half of this service a person actually touches, and none of it is exercised
by asking the API the same questions in Python: what a member reports is what the page showed
them. So this harness starts the composed application behind a socket, opens the built
single-page app in Chromium, and lets a test read the screen.

Three things can be missing on a given machine -- the driver, its browser, and a build of the
frontend -- and none of them means the code is broken. Each one skips with the command that
would fix it, the way the real upstream binary already does.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from knowledge_base.code.supervisor import Binary
from service_harness import served

BUILT_FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "dist"
"""What `npm run build` leaves behind. The browser needs the real bundle, not a stub."""

PATIENCE = 15_000
"""Milliseconds to wait for something to appear on screen. A cold first paint plus one API
round trip, with room to spare on a loaded CI runner."""


def require_frontend() -> Path:
    if not (BUILT_FRONTEND / "index.html").is_file():
        pytest.skip(
            f"the web UI is not built at {BUILT_FRONTEND}: run `npm run build` in frontend/"
        )
    return BUILT_FRONTEND


def require_driver() -> Any:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright is not installed: run `pip install -e .[browser]`")
    return async_playwright


@dataclass
class Browsing:
    """A page open on a running knowledge base."""

    page: Any
    address: str
    binary: Binary | None
    """The upstream double behind the service, for a test that wants to steer its answers."""

    async def visit(self, route: str) -> None:
        """Go to one of the app's own routes. They are hash routes, so the path never moves."""
        await self.page.goto(f"{self.address}/#{route}")
        await self.page.wait_for_load_state("networkidle")


@asynccontextmanager
async def browsing(
    path: Path, binary: Binary | None = None, route: str = "/"
) -> AsyncIterator[Browsing]:
    """Start the service, open the built app in Chromium, and hand back the page."""
    frontend = require_frontend()
    async_playwright = require_driver()
    async with served(path, binary=binary, frontend=frontend) as address:
        async with async_playwright() as driver:
            try:
                browser = await driver.chromium.launch()
            except Exception as missing:  # noqa: BLE001 - an absent browser is not a defect
                pytest.skip(f"chromium is not installed for playwright: {missing}")
            try:
                page = await browser.new_page()
                page.set_default_timeout(PATIENCE)
                open_on = Browsing(page=page, address=address, binary=binary)
                await open_on.visit(route)
                yield open_on
            finally:
                await browser.close()


__all__ = ["Browsing", "browsing", "require_driver", "require_frontend"]
