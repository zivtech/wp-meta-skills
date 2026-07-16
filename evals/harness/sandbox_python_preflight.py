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
from types import MappingProxyType


EXECUTION_SECONDS = 15
CLEANUP_SECONDS = 10
STREAM_LIMIT = 4 * 1024
ENGINE_LIMIT = 2 * 1024
DAEMON_ID_LIMIT = 256
ENGINE_TEMPLATE = '{"architecture":{{json .Server.Arch}},"client_version":{{json .Client.Version}},"negotiated_api_version":{{json .Client.APIVersion}},"operating_system":{{json .Server.Os}},"server_version":{{json .Server.Version}}}'
DAEMON_ID_TEMPLATE = "{{json .ID}}"
ENGINE_FIELDS = {
    "architecture", "client_version", "negotiated_api_version",
    "operating_system", "server_version",
}
OPTIONAL_HOST_FIELDS = (
    "Binds", "CapAdd", "DeviceCgroupRules", "DeviceRequests", "Devices",
    "Dns", "DnsOptions", "DnsSearch", "ExtraHosts", "GroupAdd", "Init",
    "Links", "PortBindings", "Tmpfs", "VolumesFrom",
)
OPTIONAL_LIST_FIELDS = frozenset({
    "Binds", "CapAdd", "DeviceCgroupRules", "DeviceRequests", "Devices",
    "Dns", "DnsOptions", "DnsSearch", "ExtraHosts", "GroupAdd", "Links",
    "VolumesFrom",
})
OPTIONAL_MAP_FIELDS = frozenset({"PortBindings", "Tmpfs"})
HOSTED_28_PROFILE = (
    ("Binds", True, "null"), ("CapAdd", True, "null"),
    ("DeviceCgroupRules", True, "null"), ("DeviceRequests", True, "null"),
    ("Devices", True, "empty-array"), ("Dns", True, "empty-array"),
    ("DnsOptions", True, "empty-array"), ("DnsSearch", True, "empty-array"),
    ("ExtraHosts", True, "null"), ("GroupAdd", True, "null"),
    ("Init", False, "missing"), ("Links", True, "null"),
    ("PortBindings", True, "empty-object"), ("Tmpfs", False, "missing"),
    ("VolumesFrom", True, "null"),
)
HOSTED_28_ENGINE = ("28.0.4", "28.0.4", "1.48", "linux", "amd64")
REVIEWED_HOSTCONFIG_PROFILES = MappingProxyType({
    (*HOSTED_28_ENGINE, "pre_start"): HOSTED_28_PROFILE,
    (*HOSTED_28_ENGINE, "post_exit"): HOSTED_28_PROFILE,
})
PYTHON = "/usr/local/bin/python"
PYTHON_EXE = "/usr/local/bin/python3.13"
ENV = (
    "PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "GPG_KEY=7169605F62C751356D054A26A821E680E5FA6305",
    "PYTHON_VERSION=3.13.14",
    "PYTHON_SHA256=639e43243c620a308f968213df9e00f2f8f62332f7adbaa7a7eeb9783057c690",
)


class DaemonIdentityError(RuntimeError):
    """Docker daemon identity was lost after an owned operation."""


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


def _unique_object(items):
    if len({key for key, _value in items}) != len(items):
        raise ValueError("duplicate key")
    return dict(items)


def _strict_engine(payload):
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > ENGINE_LIMIT:
        raise RuntimeError("preflight Docker engine tuple limit exceeded")
    if not payload.endswith("\n") or payload.count("\n") != 1:
        raise RuntimeError("preflight Docker engine tuple framing drift")
    try:
        value = json.loads(
            payload, object_pairs_hook=_unique_object,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("preflight Docker engine tuple is not strict JSON") from exc
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    valid = isinstance(value, dict) and set(value) == ENGINE_FIELDS and payload == canonical
    if not valid:
        raise RuntimeError("preflight Docker engine tuple shape drift")
    strings = all(type(value[key]) is str for key in ENGINE_FIELDS)
    versions = all(re.fullmatch(r"[0-9A-Za-z._+\-]{1,64}", value[key]) for key in ("client_version", "server_version")) if strings else False
    api = strings and re.fullmatch(r"[0-9.]{1,16}", value["negotiated_api_version"])
    platform = strings and re.fullmatch(r"[0-9A-Za-z._+\-]{1,32}", value["architecture"]) and value["operating_system"] == "linux"
    if not (strings and versions and api and platform):
        raise RuntimeError("preflight Docker engine tuple value drift")
    return (
        value["client_version"], value["server_version"],
        value["negotiated_api_version"], value["operating_system"],
        value["architecture"],
    )


def _engine(control, deadline, ledger):
    command = ["docker", "version", "--format", ENGINE_TEMPLATE]
    result = _control(control, command, deadline, ledger, "engine-tuple")
    stderr = result.get("stderr")
    bounded = isinstance(stderr, str) and len(stderr.encode("utf-8")) <= ENGINE_LIMIT
    if result.get("returncode") != 0 or not bounded or stderr:
        raise RuntimeError("preflight Docker engine tuple command failed")
    return _strict_engine(result.get("stdout"))


def _strict_daemon_id(payload):
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > DAEMON_ID_LIMIT:
        raise RuntimeError("preflight Docker daemon identity limit exceeded")
    if not payload.endswith("\n") or payload.count("\n") != 1:
        raise RuntimeError("preflight Docker daemon identity framing drift")
    try:
        value = json.loads(payload, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("preflight Docker daemon identity is not strict JSON") from exc
    canonical = json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n"
    if type(value) is not str or payload != canonical or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z:._\-]{7,127}", value):
        raise RuntimeError("preflight Docker daemon identity value drift")
    return value


def _daemon_id(control, deadline, ledger, state="daemon-identity"):
    command = ["docker", "info", "--format", DAEMON_ID_TEMPLATE]
    result = _control(control, command, deadline, ledger, state)
    stderr = result.get("stderr")
    bounded = isinstance(stderr, str) and len(stderr.encode("utf-8")) <= DAEMON_ID_LIMIT
    if result.get("returncode") != 0 or not bounded or stderr:
        raise RuntimeError("preflight Docker daemon identity command failed")
    return _strict_daemon_id(result.get("stdout"))


def _require_daemon(control, expected, deadline, ledger, state):
    try:
        observed = _daemon_id(control, deadline, ledger, state)
    except Exception as exc:
        raise DaemonIdentityError("Docker daemon identity unavailable; cleanup unverified") from exc
    if observed != expected:
        raise DaemonIdentityError("Docker daemon identity changed; cleanup unverified")


def _cleanup_control(control, command, deadline, ledger, daemon_id, state, cap=None):
    _require_daemon(control, daemon_id, deadline, ledger, f"{state}-daemon-before")
    timeout = remaining(deadline)
    result = control(command, min(cap, timeout) if cap is not None else timeout)
    _require_daemon(control, daemon_id, deadline, ledger, f"{state}-daemon-after")
    return result


def _reviewed_profiles(engine):
    try:
        before = REVIEWED_HOSTCONFIG_PROFILES[(*engine, "pre_start")]
        after = REVIEWED_HOSTCONFIG_PROFILES[(*engine, "post_exit")]
    except KeyError as exc:
        raise RuntimeError("preflight Docker engine tuple is not reviewed") from exc
    return _validate_reviewed_profile(before), _validate_reviewed_profile(after)


def _validate_reviewed_profile(profile):
    if type(profile) is not tuple or len(profile) != len(OPTIONAL_HOST_FIELDS):
        raise RuntimeError("preflight reviewed HostConfig profile shape drift")
    for record, field in zip(profile, OPTIONAL_HOST_FIELDS):
        if type(record) is not tuple or len(record) != 3:
            raise RuntimeError("preflight reviewed HostConfig profile record drift")
        name, present, encoding = record
        allowed = {"missing", "null"}
        if field in OPTIONAL_LIST_FIELDS:
            allowed.add("empty-array")
        if field in OPTIONAL_MAP_FIELDS:
            allowed.add("empty-object")
        if field == "Init":
            allowed.add("false")
        valid = name == field and type(present) is bool and encoding in allowed
        if not valid or present != (encoding != "missing"):
            raise RuntimeError("preflight reviewed HostConfig profile record drift")
    return profile


def _optional_encoding(field, present, value):
    if not present:
        return "missing"
    if value is None:
        return "null"
    if field in OPTIONAL_LIST_FIELDS and type(value) is list and not value:
        return "empty-array"
    if field in OPTIONAL_MAP_FIELDS and type(value) is dict and not value:
        return "empty-object"
    if field == "Init" and value is False:
        return "false"
    return "invalid-redacted"


def _assert_optional_profile(host, expected, phase):
    if not isinstance(host, dict):
        raise RuntimeError(f"preflight {phase} HostConfig object drift")
    for field, expected_present, expected_encoding in expected:
        present = field in host
        encoding = _optional_encoding(field, present, host.get(field))
        if (present, encoding) != (expected_present, expected_encoding):
            observed = f"present={str(present).lower()} encoding={encoding}"
            raise RuntimeError(f"preflight {phase} HostConfig.{field} {observed} drift")


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
        "GlobalIPv6Address": "", "GlobalIPv6PrefixLen": 0, "DriverOpts": None,
        "DNSNames": None, "GwPriority": 0,
    }
    endpoint = value.get("none") if isinstance(value, dict) else None
    if not isinstance(endpoint, dict) or type(endpoint.get("GwPriority")) is not int:
        raise RuntimeError("preflight none-network GwPriority drift")
    if value != {"none": expected}:
        raise RuntimeError("preflight none-network state drift")


def _host_gate(host, expected_profile, phase, security_opt):
    exact = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
        "Privileged": False, "AutoRemove": False, "PidsLimit": 16,
        "Memory": 67108864, "MemorySwap": 67108864, "NanoCpus": 250000000,
        "Ulimits": [{"Name": "nofile", "Hard": 64, "Soft": 64}],
        "LogConfig": {"Type": "none", "Config": {}},
        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "",
        "UTSMode": "", "UsernsMode": "", "ShmSize": 1048576,
    }
    for key, expected in exact.items():
        if key not in host or host[key] != expected:
            raise RuntimeError(f"preflight HostConfig.{key} drift")
    _assert_optional_profile(host, expected_profile, phase)
    if "SecurityOpt" not in host:
        raise RuntimeError("preflight no-new-privileges drift")
    observed = host["SecurityOpt"]
    if security_opt is None:
        if observed not in (["no-new-privileges"], ["no-new-privileges:true"]):
            raise RuntimeError("preflight no-new-privileges drift")
        security_opt = tuple(observed)
    elif tuple(observed or ()) != security_opt:
        raise RuntimeError("preflight no-new-privileges serialization drift")
    return security_opt


def inspect_gate(data, image, image_id, user, network_id, host_profile, post=False, security_opt=None):
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
    phase = "post_exit" if post else "pre_start"
    security_opt = _host_gate(data.get("HostConfig") or {}, host_profile, phase, security_opt)
    _none_network((data.get("NetworkSettings") or {}).get("Networks"), network_id, post)
    state = data.get("State") or {}
    expected_state={"Status":"exited" if post else "created","Running":False,"ExitCode":0,"OOMKilled":False,"Error":""}
    if any(key not in state or state[key]!=expected for key,expected in expected_state.items()):
        raise RuntimeError("preflight stopped-state drift" if post else "preflight pre-start state drift")
    return security_opt


def _inspect(control, name, deadline, ledger, daemon_id=""):
    if daemon_id:
        _require_daemon(control, daemon_id, deadline, ledger, "inspect-daemon-before")
    result = _control(control, ["docker", "inspect", name], deadline, ledger, "inspect")
    if daemon_id:
        _require_daemon(control, daemon_id, deadline, ledger, "inspect-daemon-after")
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


def _container_rows(control, deadline, filter_value, ledger, daemon_id=""):
    command = [
        "docker", "container", "ls", "-a", "--no-trunc", "--filter", filter_value,
        "--format", "{{json .ID}} {{json .Names}}",
    ]
    if daemon_id:
        result = _cleanup_control(control, command, deadline, ledger, daemon_id, "absence-list")
    else:
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


def _prove_absent(control, name, container_id, deadline, ledger, daemon_id="", record_evidence=True):
    rows = _container_rows(control, deadline, f"name=^/{name}$", ledger, daemon_id)
    if any(row_name != name for _row_id, row_name in rows) or len(rows) > 1:
        raise RuntimeError("preflight exact-name absence listing is malformed")
    if rows:
        raise RuntimeError(f"retained {name}")
    if not container_id:
        if daemon_id:
            _require_daemon(control, daemon_id, deadline, ledger, "absence-final-daemon")
        if record_evidence:
            ledger.record("preflight", name, "absent")
        return
    rows = _container_rows(control, deadline, f"id={container_id}", ledger, daemon_id)
    if any(row_id != container_id for row_id, _row_name in rows) or len(rows) > 1:
        raise RuntimeError("preflight exact-ID absence listing is malformed")
    if rows:
        raise RuntimeError(f"retained {container_id}")
    if daemon_id:
        _require_daemon(control, daemon_id, deadline, ledger, "absence-final-daemon")
    if record_evidence:
        ledger.record("preflight", name, "absent")
        ledger.record("preflight", container_id, "absent")


def _discover_container_id(control, name, deadline, ledger, daemon_id):
    try:
        if daemon_id:
            result = _cleanup_control(control, ["docker", "inspect", name], deadline, ledger, daemon_id, "discover", 2)
        else:
            result = control(["docker", "inspect", name], min(2, remaining(deadline)))
    except DaemonIdentityError:
        raise
    except Exception:
        return ""
    if result.get("returncode") != 0:
        return ""
    try:
        values = json.loads(result.get("stdout", ""))
    except json.JSONDecodeError:
        return ""
    valid = isinstance(values, list) and len(values) == 1 and values[0].get("Name") == f"/{name}"
    candidate = values[0].get("Id", "") if valid else ""
    if re.fullmatch(r"[0-9a-f]{64}", candidate):
        ledger.record("preflight", name, "id-authenticated")
        return candidate
    return ""


def _remove_attempts(control, name, deadline, ledger, daemon_id):
    for attempt in range(2):
        if deadline <= time.monotonic():
            return ["container removal deadline"]
        try:
            command = ["docker", "rm", "-f", name]
            if daemon_id:
                result = _cleanup_control(control, command, deadline, ledger, daemon_id, f"remove-{attempt + 1}")
            else:
                result = control(command, remaining(deadline))
        except DaemonIdentityError:
            raise
        except Exception:
            ledger.record("preflight", name, f"remove-{attempt + 1}-raised")
            continue
        state = "ok" if result["returncode"] == 0 else "failed"
        ledger.record("preflight", name, f"remove-{attempt + 1}-{state}")
        if result["returncode"] == 0:
            break
    return []


def _remove(control, name, container_id, ledger, transport, attempted=True, daemon_id="", identity_tainted=False):
    deadline = time.monotonic() + CLEANUP_SECONDS
    failures = cleanup_attached(transport, deadline)
    try:
        if attempted and daemon_id:
            _require_daemon(control, daemon_id, deadline, ledger, "cleanup-entry-daemon")
        if attempted and not container_id and deadline > time.monotonic():
            container_id = _discover_container_id(control, name, deadline, ledger, daemon_id)
        if attempted:
            failures.extend(_remove_attempts(control, name, deadline, ledger, daemon_id))
        _prove_absent(control, name, container_id, deadline, ledger, daemon_id, not identity_tainted)
    except Exception as exc:
        failures.append(str(exc))
    if identity_tainted:
        failures.append("Docker daemon identity was previously unverified")
    if failures:
        recovery = f"verify original Docker daemon, then docker rm -f {name}"
        raise RuntimeError(f"preflight cleanup failed: {', '.join(failures)}; possible retained resource; recovery: {recovery}")


def _validate_request(user, run_id):
    if os.getuid() == 0 or user.startswith("0:"):
        raise RuntimeError("proxy interpreter preflight forbids root")
    if user != f"{os.getuid()}:{os.getgid()}" or not re.fullmatch(r"[1-9][0-9]*:[0-9]+", user):
        raise RuntimeError("proxy interpreter preflight user drift")
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise ValueError("invalid proxy interpreter preflight run ID")
    return f"wp-proxy-preflight-{run_id}"


def _admission(control, deadline, ledger):
    daemon_id = _daemon_id(control, deadline, ledger)
    network_id = _network_id(control, deadline, ledger)
    _require_daemon(control, daemon_id, deadline, ledger, "network-daemon-after")
    engine = _engine(control, deadline, ledger)
    _require_daemon(control, daemon_id, deadline, ledger, "engine-daemon-after")
    before_profile, after_profile = _reviewed_profiles(engine)
    _require_daemon(control, daemon_id, deadline, ledger, "create-daemon-before")
    return daemon_id, network_id, engine, before_profile, after_profile


def run(control, image, image_id, user, run_id, ledger):
    name = _validate_request(user, run_id); deadline = time.monotonic() + EXECUTION_SECONDS
    started=time.monotonic(); container_id=daemon_id=""; transport=original=None; create_attempted=identity_tainted=False
    try:
        daemon_id, network_id, engine, before_profile, after_profile = _admission(control, deadline, ledger)
        ledger.record("container",name,"attempted"); create_attempted=True
        created = _control(control, create_command(name, image, user), deadline, ledger, "create")
        _require_daemon(control, daemon_id, deadline, ledger, "create-daemon-after")
        candidate = created["stdout"].strip()
        if re.fullmatch(r"[0-9a-f]{64}",candidate): container_id=candidate
        if created["returncode"] or not container_id:
            raise RuntimeError("proxy interpreter preflight creation failed")
        ledger.record("container", name, "created")
        before = _inspect(control, name, deadline, ledger, daemon_id)
        security_opt = inspect_gate(before, image, image_id, user, network_id, before_profile)
        try:
            remaining(deadline)
            _require_daemon(control, daemon_id, deadline, ledger, "start-daemon-before")
            transport = start_attached(["docker", "start", "-a", name])
        except Exception:
            ledger.record("preflight", name, "start-raised")
            raise
        ledger.record("preflight", name, "start-ok")
        result = await_attached(transport, deadline)
        _require_daemon(control, daemon_id, deadline, ledger, "start-daemon-after")
        ledger.record("preflight", name, "exit-ok" if result["returncode"] == 0 else "exit-failed")
        if result["returncode"] or result["stderr"]:
            raise RuntimeError("proxy interpreter preflight execution failed")
        _canonical_json(result["stdout"], os.getuid(), os.getgid())
        after = _inspect(control, name, deadline, ledger, daemon_id)
        _require_daemon(control, daemon_id, deadline, ledger, "post-engine-daemon-before")
        post_engine = _engine(control, deadline, ledger)
        if post_engine != engine:
            raise RuntimeError("preflight Docker engine tuple changed")
        _require_daemon(control, daemon_id, deadline, ledger, "post-exit-daemon")
        inspect_gate(after, image, image_id, user, network_id, after_profile, True, security_opt)
    except Exception as exc:
        original = exc; identity_tainted = create_attempted and isinstance(exc, DaemonIdentityError)
    try:
        _remove(control, name, container_id, ledger, transport,create_attempted,daemon_id,identity_tainted)
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
