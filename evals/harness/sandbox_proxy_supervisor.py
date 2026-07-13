"""Supervise the proxy workload separately from the trusted sleep PID 1."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass

import sandbox_python_preflight as python_preflight

STREAM_LIMIT = 32 * 1024
POLL_SECONDS = 0.1
SETUP_CLEANUP_SECONDS = 2


@dataclass
class ProxySupervisor:
    container: str
    nonce: str
    pid: int
    argv: tuple[str, ...]
    executable: str
    process: subprocess.Popen
    threads: tuple[threading.Thread, threading.Thread]
    streams: tuple[object, object]
    buffers: dict[str, bytearray]
    overflow: list[str]
    lifecycle_deadline: float
    user: str
    termination: tuple[str, ...] = ()
    identity_valid: bool = True


@dataclass(frozen=True)
class ControlRecord:
    value: dict
    device: int
    inode: int


@dataclass(frozen=True)
class StatusRecord:
    value: dict
    device: int
    inode: int

    def __getitem__(self, key):
        return self.value[key]


class StaleRecord(RuntimeError):
    pass


def _timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("proxy lifecycle deadline exceeded")
    return min(2.0, remaining)


def _canonical_json(payload: str, limit: int) -> dict:
    if len(payload.encode("utf-8")) > limit:
        raise RuntimeError("proxy control record exceeds byte limit")
    if not payload.endswith("\n"):
        raise EOFError("proxy control record is incomplete")
    def unique(items):
        if len({key for key, _item in items}) != len(items):
            raise ValueError("duplicate key")
        return dict(items)
    try: value = json.loads(payload, object_pairs_hook=unique)
    except (ValueError,json.JSONDecodeError) as exc: raise RuntimeError("proxy control record contains duplicate or invalid fields") from exc
    if not isinstance(value, dict): raise RuntimeError("proxy control record is not an object")
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
    if payload != canonical:
        raise RuntimeError("proxy control record is not canonical")
    return value


def _actual_enoent(result, path):
    messages={f"stat: cannot statx '{path}': No such file or directory",f"cat: {path}: No such file or directory"}
    return result["returncode"]==1 and result.get("stderr","").strip() in messages


def _read_file(control, container, path, deadline, limit):
    metadata = control(["docker", "exec", "--", container, "stat", "-c", "%d:%i:%a:%u:%g:%h:%s", path], _timeout(deadline))
    if metadata["returncode"]:
        if _actual_enoent(metadata,path): return None
        raise RuntimeError("proxy control metadata read failed")
    fields = metadata["stdout"].strip().split(":")
    if len(fields) != 7 or fields[2:6] != ["600", str(os.getuid()), str(os.getgid()), "1"] or not all(item.isdigit() for item in (fields[0],fields[1],fields[6])):
        raise RuntimeError("proxy control file identity drift")
    if int(fields[6]) > limit:
        raise RuntimeError("proxy control file size drift")
    result = control(["docker", "exec", "--", container, "cat", path], _timeout(deadline))
    if result["returncode"]:
        if _actual_enoent(result,path): return None
        raise RuntimeError("proxy control content read failed")
    return ControlRecord(_canonical_json(result["stdout"], limit),int(fields[0]),int(fields[1]))


def _wait_file(control, container, path, deadline, limit, polls, validator):
    cadence = time.monotonic()
    for attempt in range(polls):
        if time.monotonic() >= deadline:
            raise TimeoutError("proxy control readiness deadline exceeded")
        try:
            value = _read_file(control, container, path, deadline, limit)
            if value is not None: return validator(value)
        except (EOFError,StaleRecord):
            value = None
        target = cadence + (attempt + 1) * POLL_SECONDS
        delay = min(target, deadline) - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    raise TimeoutError("proxy control record did not become ready")


def _pid_record(record, nonce):
    value=record.value
    if set(value) != {"nonce", "pid"} or value["nonce"] != nonce or not isinstance(value["pid"], int) or isinstance(value["pid"], bool) or value["pid"] <= 0:
        raise RuntimeError("proxy PID record is invalid")
    return value["pid"]


def _status_record(record, nonce):
    value=record.value
    expected = {"nonce", "accepted", "active", "completed", "rejected", "client_bytes", "upstream_bytes"}
    if set(value) != expected or value["nonce"] != nonce:
        raise RuntimeError("proxy status record is invalid")
    if any(not isinstance(value[key], int) or isinstance(value[key], bool) or value[key] < 0 for key in expected - {"nonce"}):
        raise RuntimeError("proxy status counters are invalid")
    return StatusRecord(value,record.device,record.inode)


def _drain(stream, name, buffers, overflow):
    try:
        while chunk := stream.read(8192):
            if len(buffers[name]) + len(chunk) > STREAM_LIMIT:
                overflow.append(name)
                continue
            buffers[name].extend(chunk)
    except OSError: pass


def _process_evidence(control, container, pid, argv, executable, deadline):
    script = "import json,os,sys; p=sys.argv[1]; s=open('/proc/'+p+'/status').read().splitlines(); f=lambda k:next(x.split()[1:] for x in s if x.startswith(k+':')); print(json.dumps({'uid':f('Uid'),'gid':f('Gid'),'exe':os.readlink('/proc/'+p+'/exe'),'argv':open('/proc/'+p+'/cmdline','rb').read().rstrip(b'\\0').decode().split('\\0')},separators=(',',':'),sort_keys=True))"
    result = control(["docker", "exec", "--", container, "/usr/bin/env", "-i", "/usr/local/bin/python", "-I", "-S", "-c", script, str(pid)], _timeout(deadline))
    if result["returncode"]:
        raise RuntimeError("proxy /proc evidence unavailable")
    value = json.loads(result["stdout"])
    ids = [str(os.getuid())] * 4
    if value != {"uid": ids, "gid": [str(os.getgid())] * 4, "exe": executable, "argv": list(argv)}:
        raise RuntimeError("proxy /proc identity drift")


def _inventory_diagnostic(lines):
    sample=[]
    for line in lines[:8]:
        command=line[1] if len(line)==2 else ""
        encoded=command.encode("utf-8","replace")
        sample.append({"argv_bytes":len(encoded),"argv_sha256":hashlib.sha256(encoded).hexdigest(),"pid_decimal":bool(line and line[0].isascii() and line[0].isdecimal())})
    return json.dumps({"count":len(lines),"sample":sample},sort_keys=True,separators=(",",":"))


def _top_gate(control, container, argv, deadline):
    result = control(["docker", "top", container, "-eo", "pid,args"], _timeout(deadline))
    lines = [line.split(None, 1) for line in result["stdout"].splitlines()[1:] if line.strip()]
    commands = [line[1] for line in lines if len(line) == 2]
    if result["returncode"] or commands != ["sleep infinity", " ".join(argv)]:
        raise RuntimeError(f"proxy process inventory drift: {_inventory_diagnostic(lines)}")


def _top_no_helper_gate(control, container, argv, deadline):
    result = control(["docker", "top", container, "-eo", "pid,args"], _timeout(deadline))
    lines = [line.split(None, 1) for line in result["stdout"].splitlines()[1:] if line.strip()]
    commands = [line[1] for line in lines if len(line) == 2]
    if result["returncode"] or commands not in (["sleep infinity"], ["sleep infinity", " ".join(argv)]):
        raise RuntimeError(f"proxy control helper survived or process inventory drifted: {_inventory_diagnostic(lines)}")


def launch(container, nonce, argv, user, control, timeout, gate=lambda:None):
    deadline = time.monotonic() + timeout
    if tuple(argv[:3]) != ("/usr/bin/env", "-i", "/usr/local/bin/python") or tuple(argv[3:6]) != ("-I", "-S", "-B"):
        raise RuntimeError("proxy launch argv is not the reviewed isolated Python command")
    executable = python_preflight.PYTHON_EXE
    process_argv = tuple(argv[2:])
    command = ["docker", "exec", "--user", user, "--", container, *argv]
    gate()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env={"PATH": "/usr/bin:/bin"})
    buffers = {"stdout": bytearray(), "stderr": bytearray()}; overflow = []; streams = (process.stdout, process.stderr); threads=[]
    supervisor = ProxySupervisor(container, nonce, 0, process_argv, executable, process, (), streams, buffers, overflow, deadline, user)
    try:
        gate()
        for stream,name in zip(streams,("stdout","stderr")):
            thread=threading.Thread(target=_drain,args=(stream,name,buffers,overflow),daemon=True)
            threads.append(thread); supervisor.threads=tuple(threads); thread.start()
    except Exception as original:
        try: _finish_transport(supervisor,time.monotonic()+SETUP_CLEANUP_SECONDS)
        except Exception as cleanup:
            raise RuntimeError(f"proxy launch setup failed ({original}); teardown also failed ({cleanup})") from original
        raise
    try:
        supervisor.pid = _wait_file(control, container, "/tmp/proxy.pid.json", deadline, 512, 50, lambda value: _pid_record(value, nonce))
        _process_evidence(control, container, supervisor.pid, supervisor.argv, executable, deadline)
        _top_gate(control, container, supervisor.argv, deadline)
        _wait_file(control, container, "/tmp/status.json", deadline, 8192, 50, lambda value: _status_record(value, nonce))
        check(supervisor)
        return supervisor
    except Exception as original:
        try:
            if supervisor.pid > 0: abort(supervisor, control, gate)
            else: _finish_transport(supervisor, time.monotonic() + 20)
        except Exception as cleanup:
            raise RuntimeError(f"proxy launch failed ({original}); teardown also failed ({cleanup})") from original
        raise


def check(supervisor):
    if supervisor.overflow:
        raise RuntimeError(f"proxy {supervisor.overflow[0]} exceeded output limit")
    if supervisor.process.poll() is not None:
        raise RuntimeError(f"proxy workload exited early with {supervisor.process.returncode}")


def process_gate(supervisor, control):
    check(supervisor)
    _process_evidence(control, supervisor.container, supervisor.pid, supervisor.argv, supervisor.executable, supervisor.lifecycle_deadline)
    _top_gate(control, supervisor.container, supervisor.argv, supervisor.lifecycle_deadline)


def read_status(supervisor, control, polls=1, deadline=None):
    boundary = deadline or supervisor.lifecycle_deadline
    return _wait_file(control, supervisor.container, "/tmp/status.json", boundary, 8192, polls, lambda record: _status_record(record, supervisor.nonce))


def _mark(supervisor,event):
    if event not in supervisor.termination: supervisor.termination=supervisor.termination+(event,)


def mark_whole_container(supervisor):
    _mark(supervisor,"whole-container-cleanup")


def _signal_inside(supervisor, control, signal_name, deadline, gate=lambda:None):
    if not supervisor.identity_valid: raise RuntimeError("authenticated proxy PID identity was previously lost")
    try:
        _process_evidence(control, supervisor.container, supervisor.pid, supervisor.argv, supervisor.executable, deadline)
        _top_gate(control, supervisor.container, supervisor.argv, deadline)
    except Exception:
        supervisor.identity_valid=False; _mark(supervisor,"pid-identity-loss"); raise
    if signal_name=="KILL": _mark(supervisor,"authenticated-kill")
    command = ["docker", "exec", "--user", supervisor.user, "--", supervisor.container, "/usr/bin/env", "-i", "/usr/local/bin/python", "-I", "-S", "-c", python_preflight.SIGNAL_HELPER, str(supervisor.pid), signal_name]
    gate()
    transport = python_preflight.start_attached(command, limit=8192)
    try:
        gate()
        result = python_preflight.await_attached(transport, min(deadline, time.monotonic() + 2))
        gate()
    except Exception as exc:
        failures = python_preflight.cleanup_attached(transport, deadline)
        suffix = f"; control cleanup retained {', '.join(failures)}" if failures else ""
        try: gate()
        except Exception as identity: raise identity from exc
        raise RuntimeError(f"authenticated proxy {signal_name} failed: {exc}{suffix}") from exc
    if result["returncode"] or result["stdout"] or result["stderr"]:
        raise RuntimeError(f"authenticated proxy {signal_name} failed")
    _top_no_helper_gate(control, supervisor.container, supervisor.argv, deadline)


def _group_alive(pid):
    try: os.killpg(pid,0); return True
    except ProcessLookupError: return False
    except PermissionError: return True


def _wait_group(pid,deadline):
    while _group_alive(pid) and time.monotonic()<deadline: time.sleep(min(0.05,max(0,deadline-time.monotonic())))
    return _group_alive(pid)


def _bounded_wait(process,deadline):
    if process.poll() is None and deadline>time.monotonic():
        try: process.wait(timeout=deadline-time.monotonic())
        except subprocess.TimeoutExpired: pass


def _host_reap(supervisor, deadline):
    remaining=max(0,deadline-time.monotonic()); grace=min(deadline,time.monotonic()+min(5,remaining/2))
    _bounded_wait(supervisor.process,grace)
    if _group_alive(supervisor.process.pid):
        _mark(supervisor,"host-term");
        try: os.killpg(supervisor.process.pid,signal.SIGTERM)
        except OSError: pass
        remaining=max(0,deadline-time.monotonic()); grace=min(deadline,time.monotonic()+min(5,remaining/2))
        _bounded_wait(supervisor.process,grace); _wait_group(supervisor.process.pid,grace)
    if _group_alive(supervisor.process.pid):
        _mark(supervisor,"host-kill")
        try: os.killpg(supervisor.process.pid,signal.SIGKILL)
        except OSError: pass
        _bounded_wait(supervisor.process,deadline)
        _wait_group(supervisor.process.pid,deadline)
    _bounded_wait(supervisor.process,deadline)


def _thread_states(threads,failures):
    states=[]
    for index,thread in enumerate(threads):
        try: states.append(thread.is_alive())
        except Exception as exc:
            failures.append(f"drain {index} liveness {type(exc).__name__}"); states.append(True)
    return states


def _finish_streams(supervisor,deadline):
    failures=[]; raw_closed=set(); states=_thread_states(supervisor.threads,failures); live=any(states)
    for index,stream in enumerate(supervisor.streams):
        try:
            if live and hasattr(stream,"fileno"): os.close(stream.fileno()); raw_closed.add(index)
        except Exception as exc: failures.append(f"pipe {index} raw close {type(exc).__name__}")
    for index,thread in enumerate(supervisor.threads):
        if not states[index]: continue
        remaining=max(0,deadline-time.monotonic()); share=0.9*remaining/(len(supervisor.threads)-index)
        try: thread.join(share)
        except Exception as exc: failures.append(f"drain {index} join {type(exc).__name__}")
    if any(_thread_states(supervisor.threads,failures)): return failures+["surviving drain"]
    for index,stream in enumerate(supervisor.streams):
        try: stream.close()
        except OSError as exc:
            if not (index in raw_closed and exc.errno==errno.EBADF and getattr(stream,"closed",False)):
                failures.append(f"pipe {index} buffered close {type(exc).__name__}")
        except Exception as exc: failures.append(f"pipe {index} buffered close {type(exc).__name__}")
        if not getattr(stream,"closed",False): failures.append(f"pipe {index} buffered wrapper open")
    return failures


def _finish_transport(supervisor, deadline):
    _host_reap(supervisor, deadline); failures=_finish_streams(supervisor,deadline)
    if supervisor.process.poll() is None or _group_alive(supervisor.process.pid): failures.append("surviving process group")
    if failures: raise RuntimeError(f"proxy host transport survived teardown deadline: {', '.join(failures)}")


def reap_host(supervisor):
    _finish_transport(supervisor,time.monotonic()+20)


def _container_reap(supervisor, control, deadline, gate=lambda:None):
    remaining = deadline - time.monotonic()
    grace = min(deadline, time.monotonic() + min(5, max(0, remaining) / 2))
    if supervisor.process.poll() is None and grace > time.monotonic():
        try: supervisor.process.wait(timeout=grace - time.monotonic())
        except subprocess.TimeoutExpired: pass
    if supervisor.process.poll() is None:
        _signal_inside(supervisor, control, "KILL", deadline, gate)


def stop(supervisor, control, gate=lambda:None):
    deadline = time.monotonic() + 20
    before=read_status(supervisor,control,1,deadline)
    _signal_inside(supervisor, control, "TERM", deadline, gate)
    _container_reap(supervisor, control, deadline, gate)
    _finish_transport(supervisor, deadline)
    if supervisor.overflow or supervisor.process.returncode != 0:
        raise RuntimeError("proxy workload did not exit cleanly")
    def fresh(record):
        status=_status_record(record,supervisor.nonce)
        if (status.device,status.inode)==(before.device,before.inode): raise StaleRecord("proxy final status is not fresh")
        if status["active"]!=0: raise RuntimeError("proxy final status retained active tunnels")
        return status
    final_status=_wait_file(control,supervisor.container,"/tmp/status.json",deadline,8192,100,fresh)
    if supervisor.termination: raise RuntimeError(f"proxy termination required escalation: {', '.join(supervisor.termination)}")
    return final_status


def abort(supervisor, control, gate=lambda:None):
    deadline = time.monotonic() + 20
    failure = None
    if supervisor.process.poll() is None:
        try: _signal_inside(supervisor, control, "TERM", deadline, gate)
        except Exception as exc: failure = exc
        try: _container_reap(supervisor, control, deadline, gate)
        except Exception as exc: failure = failure or exc
    try: _finish_transport(supervisor, deadline)
    except Exception as exc:
        if failure: raise RuntimeError(f"proxy in-container teardown failed ({failure}); host teardown also failed ({exc})") from exc
        raise
    if failure: raise RuntimeError(f"proxy in-container teardown failed: {failure}")
