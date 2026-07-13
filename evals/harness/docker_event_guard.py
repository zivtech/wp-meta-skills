"""Bounded continuous Docker event evidence for endpointless execution."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field

import runtime_image_provision as provision

TRANSPORT_LIMIT = 32768


@dataclass
class EventFollower:
    process: subprocess.Popen
    container_id: str
    events: list[dict] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    total: int = 0
    malformed: bool = False
    overflow: bool = False
    stderr_seen: bool = False
    stopped: bool = False
    gate: object = lambda: None


def _stdout_reader(follower):
    while raw := follower.process.stdout.readline(TRANSPORT_LIMIT + 1):
        with follower.lock:
            follower.total += len(raw)
            if follower.total > TRANSPORT_LIMIT:
                follower.overflow = True
                return
        try:
            event = json.loads(raw)
            if not isinstance(event, dict):
                raise ValueError("event is not an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            with follower.lock:
                follower.malformed = True
            return
        with follower.lock:
            follower.events.append(event)


def _stderr_reader(follower):
    while chunk := follower.process.stderr.read(4096):
        with follower.lock:
            follower.stderr_seen = True
            follower.total += len(chunk)
            if follower.total > TRANSPORT_LIMIT:
                follower.overflow = True
                return


def start(container_id, gate=lambda:None):
    since = f"{time.time():.9f}"
    command = ["docker", "events", "--since", since, "--format", "{{json .}}"]
    gate()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env={"PATH": "/usr/bin:/bin"})
    follower = EventFollower(process, container_id, gate=gate)
    try:
        candidates = [threading.Thread(target=_stdout_reader, args=(follower,), daemon=True), threading.Thread(target=_stderr_reader, args=(follower,), daemon=True)]
        for thread in candidates:
            try: thread.start()
            except Exception:
                if thread.ident is not None: follower.threads.append(thread)
                raise
            follower.threads.append(thread)
        gate()
    except Exception as original:
        try: _stop(follower, signal.SIGKILL)
        except Exception as cleanup: raise RuntimeError(f"Docker event follower setup failed ({original}); cleanup also failed ({cleanup})") from original
        raise
    return follower


def _health(follower):
    follower.gate()
    _transport_health(follower)
    if follower.process.poll() is not None:
        raise RuntimeError("Docker event follower exited before post-sentinel")


def _transport_health(follower):
    with follower.lock:
        malformed, overflow, stderr_seen = follower.malformed, follower.overflow, follower.stderr_seen
    if malformed or overflow or stderr_seen:
        raise RuntimeError("Docker event stream was malformed, wrote stderr, or exceeded 32 KiB")


def _snapshot(follower):
    with follower.lock:
        return tuple(follower.events)


def _wait_for(follower, predicate, detail, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _health(follower)
        if any(predicate(event) for event in _snapshot(follower)):
            return
        time.sleep(0.05)
    raise RuntimeError(detail)


def sentinel(follower, container_name, label, run=None):
    command = ["docker", "exec", container_name, "/usr/bin/env", "true", label]
    follower.gate()
    runner=run or (lambda item,timeout:provision.run_capped(item,timeout=timeout,limit=TRANSPORT_LIMIT))
    result = runner(command,10)
    follower.gate()
    if result["returncode"]:
        raise RuntimeError("Docker event sentinel exec failed")

    def witnessed(event):
        actor = event.get("Actor", {})
        return event.get("Type") == "container" and actor.get("ID") == follower.container_id and event.get("Action", "").startswith("exec_create") and label in event.get("Action", "")

    _wait_for(follower, witnessed, "Docker event sentinel was not witnessed")


def await_disconnect(follower, network_id):
    def witnessed(event):
        actor = event.get("Actor", {})
        return event.get("Type") == "network" and event.get("Action") == "disconnect" and actor.get("ID") == network_id and actor.get("Attributes", {}).get("container") == follower.container_id

    _wait_for(follower, witnessed, "exact owned package disconnect event was not witnessed")


def validate_history(events, container_id, network_id, pre_label, post_label):
    disconnect = None
    sentinels = {pre_label: None, post_label: None}
    for index, event in enumerate(events):
        actor = event.get("Actor", {}); attributes = actor.get("Attributes", {})
        if event.get("Type") == "container" and actor.get("ID") == container_id:
            for label in sentinels:
                if sentinels[label] is None and event.get("Action", "").startswith("exec_create") and label in event.get("Action", ""):
                    sentinels[label] = index
            if disconnect is not None and event.get("Action") in {"start", "restart"}:
                raise RuntimeError("package restarted after endpointless disconnect")
        package_network = event.get("Type") == "network" and attributes.get("container") == container_id
        owned_network = package_network and actor.get("ID") == network_id
        if owned_network and event.get("Action") == "disconnect" and disconnect is None:
            disconnect = index
        if package_network and event.get("Action") == "connect" and disconnect is not None:
            raise RuntimeError("package reconnected to a network after endpointless disconnect")
    if disconnect is None or any(index is None for index in sentinels.values()):
        raise RuntimeError("Docker event history lacks disconnect or sentinel evidence")
    if not sentinels[pre_label] < disconnect < sentinels[post_label]:
        raise RuntimeError("Docker event history is out of order around endpointless disconnect")


def _reap(follower, first_signal, deadline):
    failures = []
    try:
        os.killpg(follower.process.pid, first_signal)
    except OSError:
        pass
    try:
        follower.process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(follower.process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            follower.process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            failures.append(f"Docker event follower survived reap deadline: {exc}")
    return failures


def _finish_readers(follower, deadline):
    failures = []
    started = [thread for thread in follower.threads if thread.ident is not None]
    for thread in started:
        try: thread.join(max(0, deadline - time.monotonic()))
        except RuntimeError as exc: failures.append(f"Docker event follower reader join failed: {exc}")
    if any(thread.is_alive() for thread in started): failures.append("Docker event follower reader survived deadline")
    for stream in (follower.process.stdout, follower.process.stderr):
        try: stream.close()
        except Exception as exc: failures.append(f"Docker event follower stream close failed: {exc}")
    return failures


def _stop(follower, first_signal):
    if follower.stopped: return
    deadline = time.monotonic() + 5
    failures = _reap(follower, first_signal, deadline) + _finish_readers(follower, deadline)
    if failures: raise RuntimeError("; ".join(failures))
    follower.stopped = True


def finish(follower, network_id, pre_label, post_label):
    _health(follower)
    _stop(follower, signal.SIGINT)
    _transport_health(follower)
    validate_history(_snapshot(follower), follower.container_id, network_id, pre_label, post_label)


def abort(follower):
    _stop(follower, signal.SIGKILL)
