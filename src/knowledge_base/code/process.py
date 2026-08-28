"""The upstream binary as an actual child process.

Everything platform-specific about running codebase-memory-mcp lives here, and nothing above
this module knows it is a process at all. That is deliberate: the binary is built for the
deployment target, and the rest of the code domain has to be testable without it.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import shutil
import subprocess
import threading

from knowledge_base.code.upstream import Channel, UpstreamUnavailable
from knowledge_base.layout import KnowledgeBaseRoot

logger = logging.getLogger(__name__)

EXECUTABLE = "codebase-memory-mcp"

COMMAND_TIMEOUT = 120.0
"""Seconds a one-shot command may take. `daemon stop` waits for other sessions to leave."""

SHUTDOWN_GRACE = 10.0
"""Seconds to let the process finish on its own after its input closes."""


def upstream_environment(root: KnowledgeBaseRoot) -> dict[str, str]:
    """The environment every invocation of the upstream runs in.

    Both variables move the upstream inside the knowledge base: its index belongs with the
    root it describes, and it has no business indexing anything but the repositories under
    `codebase/`, whatever path a caller manages to smuggle through.
    """
    return os.environ | {
        "CBM_CACHE_DIR": str(root.runtime_dir / "cbm"),
        "CBM_ALLOWED_ROOT": str(root.codebase_dir),
    }


class PipeChannel:
    """A line-oriented link to a child process over its standard streams.

    Reading runs on its own thread. A blocking read on a pipe cannot be given a deadline
    portably, and a wedged upstream that blocks the whole service is worse than a slow one.
    """

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        if process.stderr is not None:
            threading.Thread(target=self._drain_stderr, daemon=True).start()

    @property
    def returncode(self) -> int | None:
        return self._process.poll()

    def send(self, line: str) -> None:
        if self._process.stdin is None or self.returncode is not None:
            raise UpstreamUnavailable(f"the upstream exited with {self.returncode}")
        try:
            self._process.stdin.write(line + "\n")
            self._process.stdin.flush()
        except OSError as broken:
            raise UpstreamUnavailable(f"writing to the upstream failed: {broken}") from broken

    def receive(self, timeout: float) -> str:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise UpstreamUnavailable(f"the upstream said nothing for {timeout:g}s") from None
        if line is None:
            raise UpstreamUnavailable(f"the upstream closed its output ({self.returncode})")
        return line

    def close(self) -> None:
        """Close its input and let it leave; kill it only if it will not.

        An MCP server exits when its standard input closes, which is the only shutdown this
        upstream documents.
        """
        if self._process.stdin is not None:
            with contextlib.suppress(OSError):
                self._process.stdin.close()
        try:
            self._process.wait(timeout=SHUTDOWN_GRACE)
        except subprocess.TimeoutExpired:
            logger.warning("upstream did not exit on its own; killing it")
            self._process.kill()
            self._process.wait()

    def _pump(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            stripped = line.strip()
            if stripped:
                self._lines.put(stripped)
        self._lines.put(None)

    def _drain_stderr(self) -> None:
        """Log what the upstream complains about, and keep its error pipe from filling up."""
        assert self._process.stderr is not None
        for line in self._process.stderr:
            if stripped := line.strip():
                logger.info("upstream: %s", stripped)


class CbmBinary:
    """The installed codebase-memory-mcp executable."""

    def __init__(self, root: KnowledgeBaseRoot, executable: str = EXECUTABLE) -> None:
        self._root = root
        self._executable = executable

    @property
    def installed(self) -> bool:
        """Whether the executable can be found. It is built per platform and often absent."""
        return shutil.which(self._executable) is not None

    def spawn(self) -> Channel:
        """Start it as an MCP server on its standard streams."""
        self._prepare_cache()
        try:
            process = subprocess.Popen(
                [self._executable],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=upstream_environment(self._root),
                cwd=self._root.path,
            )
        except OSError as missing:
            raise UpstreamUnavailable(f"cannot run {self._executable}: {missing}") from missing
        return PipeChannel(process)

    def run(self, *arguments: str) -> None:
        """Run one command to completion. Its failure is logged, never raised.

        Every caller is housekeeping -- silencing the watcher, stopping the shared daemon --
        and none of it is worth refusing to start or refusing to shut down over.
        """
        self._prepare_cache()
        try:
            finished = subprocess.run(
                [self._executable, *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=COMMAND_TIMEOUT,
                env=upstream_environment(self._root),
                cwd=self._root.path,
            )
        except (OSError, subprocess.SubprocessError) as failure:
            logger.warning("%s %s did not run: %s", self._executable, " ".join(arguments), failure)
            return
        if finished.returncode != 0:
            logger.warning(
                "%s %s exited with %d: %s",
                self._executable,
                " ".join(arguments),
                finished.returncode,
                finished.stderr.strip(),
            )

    def _prepare_cache(self) -> None:
        (self._root.runtime_dir / "cbm").mkdir(parents=True, exist_ok=True)
