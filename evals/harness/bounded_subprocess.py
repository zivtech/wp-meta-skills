"""Deadline- and output-bounded subprocess execution for harness tools."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class BoundedProcessError(RuntimeError):
    """Base class for bounded process failures."""


class BoundedProcessTimeout(BoundedProcessError):
    """The absolute process deadline elapsed."""


class BoundedProcessOverflow(BoundedProcessError):
    """A captured output stream exceeded its configured byte ceiling."""


@dataclass(frozen=True)
class BoundedCompletedProcess:
    returncode: int
    stdout: str
    stderr: str


def _terminate_process_group(proc: subprocess.Popen[bytes]) -> None:
    """Terminate the isolated process group, escalating after a short grace."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        proc.wait()
        return
    cutoff = time.monotonic() + 0.25
    while _process_group_exists(proc.pid) and time.monotonic() < cutoff:
        time.sleep(0.01)
    if _process_group_exists(proc.pid):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _append_bounded(buffer: bytearray, chunk: bytes, limit: int, stream: str) -> None:
    if len(buffer) + len(chunk) > limit:
        raise BoundedProcessOverflow(f"{stream} exceeded {limit} bytes")
    buffer.extend(chunk)


def _drain_pipes(
    proc: subprocess.Popen[bytes],
    deadline_monotonic: float,
    stdout_limit: int,
    stderr_limit: int,
) -> tuple[bytes, bytes]:
    selector = selectors.DefaultSelector()
    streams = ((proc.stdout, "stdout"), (proc.stderr, "stderr"))
    for stream, name in streams:
        if stream is not None:
            selector.register(stream, selectors.EVENT_READ, name)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    try:
        while selector.get_map():
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise BoundedProcessTimeout("process deadline elapsed")
            for key, _mask in selector.select(remaining):
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                _append_bounded(buffers[key.data], chunk, limits[key.data], key.data)
    finally:
        selector.close()
    return bytes(buffers["stdout"]), bytes(buffers["stderr"])


def _wait_until_deadline(proc: subprocess.Popen[bytes], deadline_monotonic: float) -> int:
    returncode = proc.poll()
    if returncode is not None:
        return returncode
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise BoundedProcessTimeout("process deadline elapsed")
    try:
        return proc.wait(timeout=remaining)
    except subprocess.TimeoutExpired as exc:
        raise BoundedProcessTimeout("process deadline elapsed") from exc


def run_bounded(
    command: Sequence[str],
    *,
    deadline_monotonic: float,
    stdout_limit: int,
    stderr_limit: int,
    cwd: Path | None = None,
) -> BoundedCompletedProcess:
    """Run an isolated process group with one absolute deadline and byte caps."""
    if deadline_monotonic <= time.monotonic():
        raise BoundedProcessTimeout("process deadline elapsed before launch")
    proc = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = _drain_pipes(proc, deadline_monotonic, stdout_limit, stderr_limit)
        returncode = _wait_until_deadline(proc, deadline_monotonic)
    except (BoundedProcessError, OSError):
        _terminate_process_group(proc)
        raise
    return BoundedCompletedProcess(
        returncode=returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )
