"""Exact transport tests for deadline- and output-bounded tool processes."""

import sys
import time
from pathlib import Path

import pytest

import bounded_subprocess


def _child_writer_script(marker: Path, *, stream: str, delay: float) -> str:
    child = (
        "import pathlib,signal,time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        f"time.sleep({delay!r});"
        f"pathlib.Path({str(marker)!r}).write_text('escaped')"
    )
    return (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable, '-c', {child!r}]);"
        "time.sleep(0.1);"
        f"sys.{stream}.write('x' * 65536);sys.{stream}.flush();"
        "time.sleep(5)"
    )


def _assert_marker_stays_absent(marker: Path, wait_seconds: float) -> None:
    cutoff = time.monotonic() + wait_seconds
    while time.monotonic() < cutoff and not marker.exists():
        time.sleep(0.02)
    assert not marker.exists(), "descendant escaped process-group termination"


def test_run_bounded_captures_stdout_and_stderr():
    script = "import sys;print('out');print('err', file=sys.stderr)"
    result = bounded_subprocess.run_bounded(
        [sys.executable, "-c", script],
        deadline_monotonic=time.monotonic() + 2,
        stdout_limit=1024,
        stderr_limit=1024,
    )

    assert result.returncode == 0
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_run_bounded_overflow_kills_the_process_group(tmp_path, stream):
    marker = tmp_path / f"{stream}-escaped"
    script = _child_writer_script(marker, stream=stream, delay=0.4)

    with pytest.raises(bounded_subprocess.BoundedProcessOverflow, match=stream):
        bounded_subprocess.run_bounded(
            [sys.executable, "-c", script],
            deadline_monotonic=time.monotonic() + 2,
            stdout_limit=128,
            stderr_limit=128,
        )

    _assert_marker_stays_absent(marker, 0.6)


def test_run_bounded_timeout_kills_the_process_group(tmp_path):
    marker = tmp_path / "timeout-escaped"
    script = _child_writer_script(marker, stream="stdout", delay=0.5)

    with pytest.raises(bounded_subprocess.BoundedProcessTimeout, match="deadline"):
        bounded_subprocess.run_bounded(
            [sys.executable, "-c", script],
            deadline_monotonic=time.monotonic() + 0.1,
            stdout_limit=128 * 1024,
            stderr_limit=1024,
        )

    _assert_marker_stays_absent(marker, 0.7)
