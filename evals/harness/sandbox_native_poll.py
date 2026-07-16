"""Bounded polling for hosted native-oracle commands."""
from __future__ import annotations

import time


def until_success(run, deadline, interval=0.05):
    attempts = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("native oracle observation deadline exceeded")
        result = run(remaining)
        attempts += 1
        if result.returncode == 0:
            return attempts
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("native oracle observation deadline exceeded")
        time.sleep(min(interval, remaining))
