import subprocess
import sys
import threading
from pathlib import Path

import pytest


HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
import docker_event_guard as guard


@pytest.mark.parametrize("failure,index", [("constructor", 1), ("constructor", 2), ("start", 1), ("start", 2)])
def test_partial_event_follower_setup_reaps_process_and_closes_pipes(monkeypatch, failure, index):
    real_popen = guard.subprocess.Popen; real_thread = guard.threading.Thread
    processes = []; threads = []; calls = 0

    def popen(*_args, **_kwargs):
        process = real_popen(["/bin/sh", "-c", "sleep 30"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        processes.append(process); return process

    def construct(*args, **kwargs):
        nonlocal calls
        calls += 1
        if failure == "constructor" and calls == index: raise RuntimeError(f"constructor {index} failed")
        thread = real_thread(*args, **kwargs); threads.append(thread)
        if failure == "start" and calls == index: thread.start = lambda: (_ for _ in ()).throw(RuntimeError(f"start {index} failed"))
        return thread

    monkeypatch.setattr(guard.subprocess, "Popen", popen); monkeypatch.setattr(guard.threading, "Thread", construct)
    with pytest.raises(RuntimeError, match=f"{failure} {index} failed"):
        guard.start("a" * 64)
    assert len(processes) == 1 and processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed
    assert all(not thread.is_alive() for thread in threads)


def test_abort_ignores_never_started_reader_but_reaps_and_closes(monkeypatch):
    process = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    follower = guard.EventFollower(process, "a" * 64, threads=[threading.Thread(target=lambda: None)])
    guard.abort(follower)
    assert follower.stopped and process.poll() is not None
    assert process.stdout.closed and process.stderr.closed
