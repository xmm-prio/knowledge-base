"""Tests for the real child process underneath the code domain.

The upstream binary is a Linux/macOS/Windows executable that development machines often do not
have, so these drive the pipe plumbing with a Python child instead. The one test that needs
codebase-memory-mcp itself is marked and skipped when it is not installed.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from knowledge_base.code.process import CbmBinary, PipeChannel, upstream_environment
from knowledge_base.code.upstream import Session, UpstreamUnavailable
from knowledge_base.layout import KnowledgeBaseRoot


def child(script: str) -> PipeChannel:
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    return PipeChannel(process)


ECHO = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line)\n    sys.stdout.flush()\n"
SILENT = "import sys\nsys.stdin.read()\n"
IMMEDIATE_EXIT = "pass"


class TestPipeChannel:
    def test_a_line_written_comes_back_from_the_child(self) -> None:
        channel = child(ECHO)

        channel.send('{"hello": true}')

        assert channel.receive(timeout=10) == '{"hello": true}'
        channel.close()

    def test_a_child_that_says_nothing_times_out_rather_than_hanging_forever(self) -> None:
        """A wedged upstream must surface as a failure the supervisor can act on."""
        channel = child(SILENT)

        with pytest.raises(UpstreamUnavailable):
            channel.receive(timeout=0.05)
        channel.close()

    def test_a_child_that_exited_is_reported_as_unavailable(self) -> None:
        channel = child(IMMEDIATE_EXIT)

        with pytest.raises(UpstreamUnavailable):
            channel.receive(timeout=10)
        channel.close()

    def test_closing_it_ends_the_child(self) -> None:
        channel = child(SILENT)

        channel.close()

        assert channel.returncode is not None


class TestUpstreamEnvironment:
    def test_the_upstream_keeps_its_index_inside_the_knowledge_base(self, tmp_path: Path) -> None:
        """Its default is a directory in the user's home, which no backup of the root captures."""
        root = KnowledgeBaseRoot(tmp_path)

        assert upstream_environment(root)["CBM_CACHE_DIR"] == str(tmp_path / ".knowledge-base/cbm")

    def test_the_upstream_may_only_index_inside_the_codebase_directory(
        self, tmp_path: Path
    ) -> None:
        """Callers name a repo, but the request travels far; this is the backstop."""
        root = KnowledgeBaseRoot(tmp_path)

        assert upstream_environment(root)["CBM_ALLOWED_ROOT"] == str(tmp_path / "codebase")


class TestCbmBinary:
    def test_it_knows_when_it_is_not_installed(self, tmp_path: Path) -> None:
        """Windows workstations have no build of it, and the service still has to boot."""
        root = KnowledgeBaseRoot(tmp_path)

        assert CbmBinary(root, executable="no-such-binary-anywhere").installed is False


@pytest.mark.upstream_binary
class TestAgainstTheRealBinary:
    def test_it_answers_a_tool_call_over_stdio(self, tmp_path: Path) -> None:
        """The whole point of the seam is that this is the only test that needs the binary."""
        root = KnowledgeBaseRoot(tmp_path)
        root.initialize()
        binary = CbmBinary(root)
        if not binary.installed:
            pytest.skip("codebase-memory-mcp is not installed")

        session = Session(binary.spawn())
        try:
            session.open()
            assert session.call_tool("list_projects", {}) is not None
        finally:
            session.close()
            binary.run("daemon", "stop")

    def test_the_watcher_switch_is_a_key_the_upstream_actually_has(self, tmp_path: Path) -> None:
        """`CbmBinary.run` swallows failures, so a renamed key would disable nothing and say so
        only in a log line. This is the only place that can notice."""
        root = KnowledgeBaseRoot(tmp_path)
        root.initialize()
        binary = CbmBinary(root)
        if not binary.installed:
            pytest.skip("codebase-memory-mcp is not installed")

        finished = subprocess.run(
            ["codebase-memory-mcp", "config", "set", "auto_watch", "false"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=upstream_environment(root),
            cwd=root.path,
        )

        assert finished.returncode == 0, finished.stdout + finished.stderr
