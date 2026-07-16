#!/usr/bin/env python3
"""Emit a bounded local measurement packet for FD-rooted artifact staging."""
from __future__ import annotations

import argparse
import json
import math
import signal
import tempfile
import time
import tracemalloc
from pathlib import Path

import artifact_staging
import workspace_lease

MAX_WATCHDOG_SEC=180


def _timeout(_signum, _frame):
    raise TimeoutError("artifact staging measurement exceeded watchdog")


def _write_fixture(root: Path, payload_bytes: int, entries: int) -> None:
    root.mkdir()
    chunk = b"x" * min(payload_bytes, 1024 * 1024)
    with (root / "payload.bin").open("wb") as handle:
        remaining = payload_bytes
        while remaining:
            part = chunk[:remaining]
            handle.write(part)
            remaining -= len(part)
    for index in range(1, entries):
        (root / f"entry-{index:04d}.txt").write_text("x", encoding="utf-8")


def _validate_bounds(payload_bytes: int, entries: int, watchdog_sec: int) -> None:
    if payload_bytes < 1 or entries < 1 or watchdog_sec < 1:
        raise ValueError("measurement bounds must be positive")
    if payload_bytes > artifact_staging.MAX_FILE_BYTES or payload_bytes+entries-1 > artifact_staging.MAX_TOTAL_BYTES:
        raise ValueError("measurement bytes exceed staging limits")
    if entries > artifact_staging.MAX_ENTRIES or watchdog_sec > MAX_WATCHDOG_SEC:
        raise ValueError("measurement entries or watchdog exceed reviewed limits")


def _measure_operation(payload_bytes: int, entries: int):
    staged=scan_stage=None
    with tempfile.TemporaryDirectory(prefix="wp-artifact-measure-") as temporary:
        root = Path(temporary).resolve()
        _write_fixture(root / "source", payload_bytes, entries)
        try:
            staged = artifact_staging.stage_tree(root / "source", root / "leases")
            with artifact_staging.hold_staged_tree(staged) as held:
                snapshot=artifact_staging.snapshot_held_tree(held)
            scan_stage=artifact_staging._stage_scan_handoff_snapshot(snapshot,root/"scan-leases")
            with artifact_staging.hold_staged_tree(scan_stage) as held_scan:
                handoff_entries=held_scan.proof.entries
        finally:
            try:
                if scan_stage is not None: workspace_lease.cleanup(scan_stage.lease)
            finally:
                if staged is not None: workspace_lease.cleanup(staged.lease)
    return len(snapshot),handoff_entries


def measure(payload_bytes: int, entries: int, watchdog_sec: int) -> dict:
    _validate_bounds(payload_bytes,entries,watchdog_sec)
    previous=signal.signal(signal.SIGALRM,_timeout); started=time.monotonic(); tracing=False
    try:
        signal.setitimer(signal.ITIMER_REAL,watchdog_sec); tracemalloc.start(); tracing=True
        snapshot_entries,handoff_entries=_measure_operation(payload_bytes,entries)
        elapsed=time.monotonic()-started; _current,peak=tracemalloc.get_traced_memory()
    finally:
        if tracing: tracemalloc.stop()
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)
    metrics = {"elapsed_sec": elapsed, "peak_bytes": peak}
    if not all(math.isfinite(value) and value >= 0 for value in metrics.values()):
        raise RuntimeError("measurement produced non-finite metrics")
    return {
        "status": "pass",
        "payload_bytes": payload_bytes,
        "entries": entries,
        "snapshot_entries": snapshot_entries,
        "scan_handoff_entries": handoff_entries,
        "watchdog_sec": watchdog_sec,
        **metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--entries", type=int, default=2000)
    parser.add_argument("--watchdog-sec", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(measure(args.bytes, args.entries, args.watchdog_sec), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
