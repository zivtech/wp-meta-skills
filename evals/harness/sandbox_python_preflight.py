"""Zero-mount pinned-Python preflight for proxy control operations."""
from __future__ import annotations

import errno
import json
import math
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass


EXECUTION_SECONDS = 15
CLEANUP_SECONDS = 10
STREAM_LIMIT = 4 * 1024
PYTHON = "/usr/local/bin/python"
PYTHON_EXE = "/usr/local/bin/python3.13"
ENV = (
    "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305",
    "PYTHON_VERSION=3.13.14",
    "PYTHON_SHA256=639e43243c620a308f968213df9e00f2f8f62332f7adbaa7a7eeb9783057c690",
)

PREFLIGHT_PROBE = """import json,os,signal,sys
d={"capabilities":{"os_getgid":callable(os.getgid),"os_getuid":callable(os.getuid),"os_kill":callable(os.kill)},"environment":dict(sorted(os.environ.items())),"flags":{"ignore_environment":sys.flags.ignore_environment,"isolated":sys.flags.isolated,"no_site":sys.flags.no_site,"no_user_site":sys.flags.no_user_site,"safe_path":sys.flags.safe_path},"gid":os.getgid(),"os_name":os.name,"proc_self_exe":os.readlink("/proc/self/exe"),"schema":"wp-proxy-python-preflight.v1","signals":{"KILL":int(signal.SIGKILL),"TERM":int(signal.SIGTERM)},"sys_executable":sys.executable,"sys_platform":sys.platform,"uid":os.getuid()}
sys.stdout.write(json.dumps(d,sort_keys=True,separators=(",",":"),allow_nan=False)+"\\n")
"""

SIGNAL_HELPER = """import os,signal,sys
if len(sys.argv)!=3: raise SystemExit(64)
p,n=sys.argv[1],sys.argv[2]
if not (p.isascii() and p.isdecimal() and 1<=len(p)<=10 and p==str(int(p))): raise SystemExit(64)
i=int(p)
if not 2<=i<=2147483647: raise SystemExit(64)
m={"TERM":signal.SIGTERM,"KILL":signal.SIGKILL}
if n not in m: raise SystemExit(64)
os.kill(i,m[n])
"""


@dataclass
class AttachedTransport:
    process: subprocess.Popen
    streams: tuple[object, object]
    threads: tuple[threading.Thread, threading.Thread]
    buffers: dict[str, bytearray]
    overflow: list[str]


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("proxy interpreter preflight deadline exceeded")
    return value


def assert_image_environment(values) -> None:
    if not isinstance(values, list) or any(not isinstance(item, str) or "=" not in item for item in values):
        raise RuntimeError("pinned Python Config.Env is malformed")
    keys = [item.split("=", 1)[0] for item in values]
    folded = [key.casefold() for key in keys]
    if len(folded) != len(set(folded)):
        raise RuntimeError("pinned Python Config.Env contains duplicate keys")
    for key in folded:
        if key.startswith(("ld_", "dyld_")):
            raise RuntimeError("pinned Python Config.Env contains a loader control")
        if key.startswith("python") and key not in {"python_version", "python_sha256"}:
            raise RuntimeError("pinned Python Config.Env contains a runtime control")
    if tuple(values) != ENV:
        raise RuntimeError("pinned Python Config.Env inventory drift")


def _canonical_json(payload: str, uid: int, gid: int) -> dict:
    raw = payload.encode("utf-8")
    if len(raw) > 2048 or not payload.endswith("\n") or payload.count("\n") != 1:
        raise RuntimeError("proxy interpreter preflight output framing drift")
    def unique(items):
        if len({key for key, _item in items}) != len(items):
            raise ValueError("duplicate key")
        return dict(items)
    try:
        value = json.loads(
            payload,
            object_pairs_hook=unique,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("proxy interpreter preflight output is not strict JSON") from exc
    expected = {
        "capabilities": {"os_getgid": True, "os_getuid": True, "os_kill": True},
        "environment": {"LC_CTYPE": "C.UTF-8"},
        "flags": {"ignore_environment": 1, "isolated": 1, "no_site": 1, "no_user_site": 1, "safe_path": True},
        "gid": gid,
        "os_name": "posix",
        "proc_self_exe": PYTHON_EXE,
        "schema": "wp-proxy-python-preflight.v1",
        "signals": {"KILL": 9, "TERM": 15},
        "sys_executable": PYTHON,
        "sys_platform": "linux",
        "uid": uid,
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    if value != expected or not _same_types(value, expected) or payload != canonical:
        raise RuntimeError("proxy interpreter preflight schema or canonical encoding drift")
    return value


def _same_types(value, expected):
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(_same_types(value[key], expected[key]) for key in expected)
    return True


def _drain(stream, name, buffers, overflow, limit):
    try:
        while chunk := stream.read(1024):
            room = max(0, limit - len(buffers[name]))
            buffers[name].extend(chunk[:room])
            if len(chunk) > room and name not in overflow: overflow.append(name)
    except OSError: pass


def start_attached(command, limit=STREAM_LIMIT) -> AttachedTransport:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    streams = (process.stdout, process.stderr)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = []
    threads = []
    try:
        for stream, name in zip(streams, ("stdout", "stderr")):
            thread = threading.Thread(target=_drain, args=(stream, name, buffers, overflow, limit), daemon=True)
            threads.append(thread)
            thread.start()
    except Exception as original:
        partial = AttachedTransport(process, streams, tuple(threads), buffers, overflow)
        try: failures = cleanup_attached(partial, time.monotonic() + CLEANUP_SECONDS)
        except Exception as cleanup:
            raise RuntimeError(f"preflight transport start failed ({original}); cleanup also raised ({cleanup})") from original
        if failures:
            raise RuntimeError(f"preflight transport start failed ({original}); cleanup also failed ({', '.join(failures)})") from original
        raise
    return AttachedTransport(process, streams, tuple(threads), buffers, overflow)


def _thread_states(threads, failures):
    states=[]
    for index,thread in enumerate(threads):
        try: states.append(thread.is_alive())
        except Exception as exc:
            failures.append(f"drain {index} liveness {type(exc).__name__}"); states.append(True)
    return states


def _close_join(transport: AttachedTransport, deadline: float) -> list[str]:
    failures = []; raw_closed=set(); states=_thread_states(transport.threads,failures); live=any(states)
    for index,stream in enumerate(transport.streams):
        try:
            if live and hasattr(stream,"fileno"): os.close(stream.fileno()); raw_closed.add(index)
        except Exception as exc: failures.append(f"pipe {index} raw close {type(exc).__name__}")
    for index,thread in enumerate(transport.threads):
        if not states[index]: continue
        available = max(0, deadline - time.monotonic())
        if available:
            try: thread.join(available)
            except Exception as exc: failures.append(f"drain {index} join {type(exc).__name__}")
    if any(_thread_states(transport.threads,failures)): return failures+["drain thread"]
    for index,stream in enumerate(transport.streams):
        try: stream.close()
        except OSError as exc:
            if not (index in raw_closed and exc.errno==errno.EBADF and getattr(stream,"closed",False)):
                failures.append(f"pipe {index} buffered close {type(exc).__name__}")
        except Exception as exc: failures.append(f"pipe {index} buffered close {type(exc).__name__}")
        if not getattr(stream,"closed",False): failures.append(f"pipe {index} buffered wrapper open")
    return failures


def await_attached(transport: AttachedTransport, deadline: float) -> dict[str, object]:
    while transport.process.poll() is None:
        if transport.overflow:
            raise RuntimeError(f"preflight {transport.overflow[0]} exceeded output limit")
        available = remaining(deadline)
        try:
            transport.process.wait(timeout=min(0.05, available))
        except subprocess.TimeoutExpired:
            pass
    for thread in transport.threads:
        thread.join(remaining(deadline))
        if thread.is_alive():
            raise RuntimeError("preflight output drain survived execution deadline")
    if transport.overflow:
        raise RuntimeError(f"preflight {transport.overflow[0]} exceeded output limit")
    for stream in transport.streams:
        stream.close()
    return {
        "returncode": transport.process.returncode,
        "stdout": bytes(transport.buffers["stdout"]).decode("utf-8", "strict"),
        "stderr": bytes(transport.buffers["stderr"]).decode("utf-8", "strict"),
    }


def cleanup_attached(transport: AttachedTransport | None, deadline: float) -> list[str]:
    if transport is None:
        return []
    process = transport.process; failures=[]
    try: group_alive = _group_alive(process.pid)
    except OSError as exc:
        failures.append(f"host process group probe {type(exc).__name__}"); group_alive=True
    if group_alive:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        available = max(0, deadline - time.monotonic())
        grace = min(deadline, time.monotonic() + min(2, available / 2))
        if process.poll() is None and grace > time.monotonic():
            try:
                process.wait(timeout=grace - time.monotonic())
            except subprocess.TimeoutExpired:
                pass
        try: group_alive = _wait_group(process.pid, grace)
        except OSError as exc:
            failures.append(f"host process group TERM probe {type(exc).__name__}"); group_alive=True
    if group_alive:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        available = max(0, deadline - time.monotonic())
        if process.poll() is None and available:
            try:
                process.wait(timeout=available)
            except subprocess.TimeoutExpired:
                pass
        try: group_alive = _wait_group(process.pid, deadline)
        except OSError as exc:
            failures.append(f"host process group KILL probe {type(exc).__name__}"); group_alive=True
    if process.poll() is None or group_alive: failures.append("host process group")
    failures.extend(_close_join(transport, deadline))
    return failures


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_group(pid: int, deadline: float) -> bool:
    while _group_alive(pid) and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    return _group_alive(pid)


def _control(control, command, deadline, ledger, state):
    try:
        result = control(command, remaining(deadline))
    except Exception:
        ledger.record("preflight", command[1], f"{state}-raised")
        raise
    ledger.record("preflight", command[1], f"{state}-{'ok' if result['returncode'] == 0 else 'failed'}")
    return result


def _network_id(control, deadline, ledger) -> str:
    result = _control(control, ["docker", "network", "inspect", "none"], deadline, ledger, "network-inspect")
    try:
        values = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("none network inspection is malformed") from exc
    if result["returncode"] or not isinstance(values, list) or len(values) != 1:
        raise RuntimeError("none network inspection failed")
    value = values[0]
    if value.get("Name") != "none" or value.get("Driver") != "null" or value.get("Scope") != "local" or not re.fullmatch(r"[0-9a-f]{64}", value.get("Id", "")):
        raise RuntimeError("none network identity drift")
    return value["Id"]


def create_command(name: str, image: str, user: str) -> list[str]:
    return [
        "docker", "create", "--pull=never", "--name", name, "--network", "none",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", user, "--pids-limit", "16", "--memory", "67108864",
        "--memory-swap", "67108864", "--cpus", "0.25", "--ulimit", "nofile=64:64",
        "--log-driver", "none", "--restart", "no", "--shm-size", "1m",
        "--entrypoint", "/usr/bin/env", image, "-i", PYTHON, "-I", "-S", "-c", PREFLIGHT_PROBE,
    ]


def _none_network(value, network_id, post):
    expected = {
        "IPAMConfig": None, "Links": None, "Aliases": None, "MacAddress": "",
        "NetworkID": network_id if post else "", "EndpointID": "", "Gateway": "",
        "IPAddress": "", "IPPrefixLen": 0, "IPv6Gateway": "",
        "GlobalIPv6Address": "", "GlobalIPv6PrefixLen": 0, "DriverOpts": None, "DNSNames": None,
    }
    if value != {"none": expected}:
        raise RuntimeError("preflight none-network state drift")


def _host_gate(host, security_opt):
    exact = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
        "Privileged": False, "AutoRemove": False, "PidsLimit": 16,
        "Memory": 67108864, "MemorySwap": 67108864, "NanoCpus": 250000000,
        "Ulimits": [{"Name": "nofile", "Hard": 64, "Soft": 64}],
        "LogConfig": {"Type": "none", "Config": {}},
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "",
        "UTSMode": "", "UsernsMode": "", "Binds": None, "Tmpfs": None,
        "Devices": [], "PortBindings": {}, "ExtraHosts": None, "Links": None,
        "Dns": [], "DnsSearch": [], "DnsOptions": [], "Init": None, "ShmSize": 1048576,
    }
    for key, expected in exact.items():
        if key not in host or host[key] != expected:
            raise RuntimeError(f"preflight HostConfig.{key} drift")
    if "SecurityOpt" not in host:
        raise RuntimeError("preflight no-new-privileges drift")
    observed = host["SecurityOpt"]
    if security_opt is None:
        if observed not in (["no-new-privileges"], ["no-new-privileges:true"]):
            raise RuntimeError("preflight no-new-privileges drift")
        security_opt = tuple(observed)
    elif tuple(observed or ()) != security_opt:
        raise RuntimeError("preflight no-new-privileges serialization drift")
    if any(key not in host or host[key] not in (None, []) for key in ("CapAdd", "GroupAdd")):
        raise RuntimeError("preflight added privilege drift")
    if any(key not in host or host[key] is not None for key in ("DeviceRequests", "DeviceCgroupRules")):
        raise RuntimeError("preflight device surface drift")
    return security_opt


def inspect_gate(data, image, image_id, user, network_id, post=False, security_opt=None):
    if data.get("Image") != image_id or data.get("Mounts") != []:
        raise RuntimeError("preflight image identity or zero-mount drift")
    config = data.get("Config") or {}
    exact = {
        "Image": image, "User": user, "Entrypoint": ["/usr/bin/env"],
        "Cmd": ["-i", PYTHON, "-I", "-S", "-c", PREFLIGHT_PROBE],
        "WorkingDir": "", "AttachStdin": False, "AttachStdout": True,
        "AttachStderr": True, "Tty": False, "OpenStdin": False, "StdinOnce": False,
    }
    for key, expected in exact.items():
        if key not in config or config[key] != expected:
            raise RuntimeError(f"preflight Config.{key} drift")
    assert_image_environment(config.get("Env"))
    security_opt = _host_gate(data.get("HostConfig") or {}, security_opt)
    _none_network((data.get("NetworkSettings") or {}).get("Networks"), network_id, post)
    state = data.get("State") or {}
    expected_state={"Status":"exited" if post else "created","Running":False,"ExitCode":0,"OOMKilled":False,"Error":""}
    if any(key not in state or state[key]!=expected for key,expected in expected_state.items()):
        raise RuntimeError("preflight stopped-state drift" if post else "preflight pre-start state drift")
    return security_opt


def _inspect(control, name, deadline, ledger):
    result = _control(control, ["docker", "inspect", name], deadline, ledger, "inspect")
    try:
        values = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("preflight container inspection is malformed") from exc
    if result["returncode"] or not isinstance(values, list) or len(values) != 1:
        raise RuntimeError("preflight container inspection failed")
    return values[0]


def _parse_container_row(line: str) -> tuple[str, str]:
    parts = line.split(" ")
    if len(parts) != 2:
        raise RuntimeError("preflight absence listing is malformed")
    try:
        container_id, name = (json.loads(part) for part in parts)
    except json.JSONDecodeError as exc:
        raise RuntimeError("preflight absence listing is malformed") from exc
    if not isinstance(container_id, str) or not re.fullmatch(r"[0-9a-f]{64}", container_id) or not isinstance(name, str):
        raise RuntimeError("preflight absence listing is malformed")
    if parts != [json.dumps(container_id), json.dumps(name)]:
        raise RuntimeError("preflight absence listing is noncanonical")
    return container_id, name


def _container_rows(control, deadline, filter_value, ledger):
    command = [
        "docker", "container", "ls", "-a", "--no-trunc", "--filter", filter_value,
        "--format", "{{json .ID}} {{json .Names}}",
    ]
    result = control(command, remaining(deadline))
    ledger.record("preflight", filter_value, "absence-list-ok" if result["returncode"] == 0 else "absence-list-failed")
    if result["returncode"] != 0:
        raise RuntimeError("preflight absence listing failed")
    if result.get("stderr"):
        raise RuntimeError("preflight absence listing emitted stderr")
    payload = result.get("stdout", "")
    if not isinstance(payload, str) or (payload and not payload.endswith("\n")):
        raise RuntimeError("preflight absence listing framing is malformed")
    lines = payload.splitlines()
    return tuple(_parse_container_row(line) for line in lines)


def _prove_absent(control, name, container_id, deadline, ledger):
    rows = _container_rows(control, deadline, f"name=^/{name}$", ledger)
    if any(row_name != name for _row_id, row_name in rows) or len(rows) > 1:
        raise RuntimeError("preflight exact-name absence listing is malformed")
    if rows:
        raise RuntimeError(f"retained {name}")
    ledger.record("preflight", name, "absent")
    if not container_id:
        return
    rows = _container_rows(control, deadline, f"id={container_id}", ledger)
    if any(row_id != container_id for row_id, _row_name in rows) or len(rows) > 1:
        raise RuntimeError("preflight exact-ID absence listing is malformed")
    if rows:
        raise RuntimeError(f"retained {container_id}")
    ledger.record("preflight", container_id, "absent")


def _remove(control, name, container_id, ledger, transport, attempted=True):
    deadline = time.monotonic() + CLEANUP_SECONDS
    failures = cleanup_attached(transport, deadline)
    if attempted and not container_id and deadline>time.monotonic():
        try: discovery=control(["docker","inspect",name],min(2, deadline-time.monotonic()))
        except Exception: discovery={"returncode":1,"stdout":""}
        if discovery["returncode"]==0:
            try: values=json.loads(discovery["stdout"])
            except json.JSONDecodeError: values=[]
            if isinstance(values,list) and len(values)==1 and values[0].get("Name")==f"/{name}" and re.fullmatch(r"[0-9a-f]{64}",values[0].get("Id","")):
                container_id=values[0]["Id"]; ledger.record("preflight",name,"id-authenticated")
    if attempted:
        for attempt in range(2):
            available = deadline - time.monotonic()
            if available <= 0:
                failures.append("container removal deadline")
                break
            try:
                result = control(["docker", "rm", "-f", name], available)
            except Exception as exc:
                ledger.record("preflight", name, f"remove-{attempt + 1}-raised")
                continue
            ledger.record("preflight", name, f"remove-{attempt + 1}-{'ok' if result['returncode'] == 0 else 'failed'}")
            if result["returncode"] == 0:
                break
    try:
        _prove_absent(control, name, container_id, deadline, ledger)
    except Exception as exc:
        failures.append(str(exc))
    if failures:
        raise RuntimeError(f"preflight cleanup failed: {', '.join(failures)}; recovery: docker rm -f {name}")


def run(control, image, image_id, user, run_id, ledger):
    if os.getuid() == 0 or user.startswith("0:"):
        raise RuntimeError("proxy interpreter preflight forbids root")
    if user != f"{os.getuid()}:{os.getgid()}" or not re.fullmatch(r"[1-9][0-9]*:[0-9]+", user):
        raise RuntimeError("proxy interpreter preflight user drift")
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise ValueError("invalid proxy interpreter preflight run ID")
    name = f"wp-proxy-preflight-{run_id}"
    deadline = time.monotonic() + EXECUTION_SECONDS
    started = time.monotonic(); container_id = ""; transport = None; original = None; create_attempted=False
    try:
        network_id = _network_id(control, deadline, ledger)
        ledger.record("container",name,"attempted"); create_attempted=True
        created = _control(control, create_command(name, image, user), deadline, ledger, "create")
        candidate = created["stdout"].strip()
        if re.fullmatch(r"[0-9a-f]{64}",candidate): container_id=candidate
        if created["returncode"] or not container_id:
            raise RuntimeError("proxy interpreter preflight creation failed")
        ledger.record("container", name, "created")
        before = _inspect(control, name, deadline, ledger)
        security_opt = inspect_gate(before, image, image_id, user, network_id)
        try:
            remaining(deadline)
            transport = start_attached(["docker", "start", "-a", name])
        except Exception:
            ledger.record("preflight", name, "start-raised")
            raise
        ledger.record("preflight", name, "start-ok")
        result = await_attached(transport, deadline)
        ledger.record("preflight", name, "exit-ok" if result["returncode"] == 0 else "exit-failed")
        if result["returncode"] or result["stderr"]:
            raise RuntimeError("proxy interpreter preflight execution failed")
        _canonical_json(result["stdout"], os.getuid(), os.getgid())
        after = _inspect(control, name, deadline, ledger)
        inspect_gate(after, image, image_id, user, network_id, True, security_opt)
    except Exception as exc:
        original = exc
    try:
        _remove(control, name, container_id, ledger, transport,create_attempted)
        if create_attempted: ledger.record("container", name, "removed")
    except Exception as cleanup:
        ledger.record("preflight", name, f"duration={time.monotonic() - started:.6f}")
        if original is not None:
            raise RuntimeError(f"preflight failed ({original}); cleanup also failed ({cleanup})") from original
        raise
    ledger.record("preflight", name, f"duration={time.monotonic() - started:.6f}")
    if original is not None:
        raise original
    return {"name": name, "container_id": container_id, "duration": time.monotonic() - started}
