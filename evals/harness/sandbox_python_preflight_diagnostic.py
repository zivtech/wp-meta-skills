"""Hosted-Linux diagnostic for preflight Tmpfs serialization only."""
from __future__ import annotations

import json
import os
import re
import time
from types import MappingProxyType

import sandbox_python_preflight as preflight


BLOCK_MESSAGE = "post-exit Tmpfs representation awaiting review"
VERSION_TEMPLATE = '{"api_version":{{json .Server.APIVersion}},"architecture":{{json .Server.Arch}},"server_version":{{json .Server.Version}}}'
OBSERVATION_FIELDS = {
    "phase", "present", "json_type", "entry_count", "empty",
    "api_version", "architecture", "server_version",
}
HOST_FIELDS = {
    "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
    "Privileged": False, "AutoRemove": False, "PidsLimit": 16,
    "Memory": 67108864, "MemorySwap": 67108864, "NanoCpus": 250000000,
    "Ulimits": [{"Name": "nofile", "Hard": 64, "Soft": 64}],
    "LogConfig": {"Type": "none", "Config": {}},
    "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
    "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "",
    "UTSMode": "", "UsernsMode": "", "Binds": None,
    "Devices": [], "PortBindings": {}, "ExtraHosts": None, "Links": None,
    "Dns": [], "DnsSearch": [], "DnsOptions": [], "Init": None,
    "ShmSize": 1048576,
}


class PostExitTmpfsObservation(RuntimeError):
    """Eligible sanitized representation evidence after all retained gates pass."""

    def __init__(self, observation):
        _validate_observation(observation)
        self.observation = MappingProxyType(dict(observation))
        super().__init__(BLOCK_MESSAGE)


def _daemon(control, deadline, ledger):
    result = preflight._control(
        control,
        ["docker", "version", "--format", VERSION_TEMPLATE],
        deadline,
        ledger,
        "daemon-version",
    )
    try:
        value = json.loads(result["stdout"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("diagnostic Docker server observation is malformed") from exc
    if result["returncode"] or not isinstance(value, dict) or set(value) != {"api_version", "architecture", "server_version"}:
        raise RuntimeError("diagnostic Docker server observation failed")
    valid = (
        isinstance(value["api_version"], str)
        and re.fullmatch(r"[0-9.]{1,16}", value["api_version"])
        and value["architecture"] in {"amd64", "arm64"}
        and isinstance(value["server_version"], str)
        and re.fullmatch(r"[0-9A-Za-z._+\-]{1,64}", value["server_version"])
    )
    if not valid:
        raise RuntimeError("diagnostic Docker server observation drift")
    return value


def _json_type(value):
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, dict): return "object"
    if isinstance(value, list): return "array"
    if isinstance(value, str): return "string"
    if isinstance(value, (int, float)): return "number"
    raise RuntimeError("diagnostic post-exit Tmpfs JSON type drift")


def _tmpfs_observation(data, daemon):
    host = data["HostConfig"]
    present = "Tmpfs" in host
    value = host.get("Tmpfs") if present else None
    json_type = _json_type(value) if present else "missing"
    empty = bool(
        present
        and (value is None or (isinstance(value, (dict, list, str)) and len(value) == 0))
    )
    return {
        **daemon,
        "phase": "post_exit",
        "present": present,
        "json_type": json_type,
        "entry_count": len(value) if isinstance(value, dict) else None,
        "empty": empty,
    }


def _validate_observation(value):
    if not isinstance(value, dict) or set(value) != OBSERVATION_FIELDS:
        raise RuntimeError("diagnostic observation shape drift")
    if value["phase"] != "post_exit" or type(value["present"]) is not bool or type(value["empty"]) is not bool:
        raise RuntimeError("diagnostic observation phase or boolean drift")
    valid_daemon = (
        isinstance(value["api_version"], str)
        and re.fullmatch(r"[0-9.]{1,16}", value["api_version"])
        and value["architecture"] in {"amd64", "arm64"}
        and isinstance(value["server_version"], str)
        and re.fullmatch(r"[0-9A-Za-z._+\-]{1,64}", value["server_version"])
    )
    if not valid_daemon:
        raise RuntimeError("diagnostic observation daemon drift")
    kind = value["json_type"]; count = value["entry_count"]
    if not value["present"]:
        if kind != "missing" or count is not None or value["empty"]:
            raise RuntimeError("diagnostic absent observation drift")
        return
    if kind not in {"null", "boolean", "object", "array", "string", "number"}:
        raise RuntimeError("diagnostic observation JSON type drift")
    if kind == "object":
        if type(count) is not int or count < 0 or value["empty"] != (count == 0):
            raise RuntimeError("diagnostic object observation drift")
    elif count is not None:
        raise RuntimeError("diagnostic non-object entry count drift")
    if kind == "null" and not value["empty"]:
        raise RuntimeError("diagnostic null observation drift")
    if kind in {"boolean", "number"} and value["empty"]:
        raise RuntimeError("diagnostic scalar observation drift")


def emit_observation(error, summary_path, log=print):
    if type(error) is not PostExitTmpfsObservation:
        raise TypeError("only an exact post-exit Tmpfs observation is eligible")
    observation = dict(error.observation)
    _validate_observation(observation)
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"), allow_nan=False)
    log(encoded)
    with open(os.fspath(summary_path), "a", encoding="utf-8") as summary:
        summary.write("## Post-exit Tmpfs representation\n\n```json\n" + encoded + "\n```\n")


def _retained_host_gate(host, security_opt):
    if not isinstance(host, dict):
        raise RuntimeError("preflight HostConfig drift")
    for key, expected in HOST_FIELDS.items():
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


def _retained_inspect_gate(data, image, image_id, user, network_id, post=False, security_opt=None):
    if data.get("Image") != image_id or data.get("Mounts") != []:
        raise RuntimeError("preflight image identity or zero-mount drift")
    config = data.get("Config") or {}
    exact = {
        "Image": image, "User": user, "Entrypoint": ["/usr/bin/env"],
        "Cmd": ["-i", preflight.PYTHON, "-I", "-S", "-c", preflight.PREFLIGHT_PROBE],
        "WorkingDir": "", "AttachStdin": False, "AttachStdout": True,
        "AttachStderr": True, "Tty": False, "OpenStdin": False, "StdinOnce": False,
    }
    for key, expected in exact.items():
        if key not in config or config[key] != expected:
            raise RuntimeError(f"preflight Config.{key} drift")
    preflight.assert_image_environment(config.get("Env"))
    security_opt = _retained_host_gate(data.get("HostConfig"), security_opt)
    preflight._none_network((data.get("NetworkSettings") or {}).get("Networks"), network_id, post)
    state = data.get("State") or {}
    expected_state = {"Status": "exited" if post else "created", "Running": False, "ExitCode": 0, "OOMKilled": False, "Error": ""}
    if any(key not in state or state[key] != expected for key, expected in expected_state.items()):
        raise RuntimeError("preflight stopped-state drift" if post else "preflight pre-start state drift")
    return security_opt


def _pre_start_tmpfs_gate(data):
    host = data.get("HostConfig")
    if not isinstance(host, dict):
        raise RuntimeError("diagnostic pre-start HostConfig drift")
    if "Tmpfs" in host:
        raise RuntimeError("diagnostic pre-start HostConfig.Tmpfs must be absent")


def _validate(user, run_id):
    if os.getuid() == 0 or user.startswith("0:"):
        raise RuntimeError("diagnostic proxy interpreter preflight forbids root")
    if user != f"{os.getuid()}:{os.getgid()}" or not re.fullmatch(r"[1-9][0-9]*:[0-9]+", user):
        raise RuntimeError("diagnostic proxy interpreter preflight user drift")
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        raise ValueError("invalid diagnostic proxy interpreter preflight run ID")


def run(control, image, image_id, user, run_id, ledger):
    _validate(user, run_id)
    name = f"wp-proxy-preflight-{run_id}"
    deadline = time.monotonic() + preflight.EXECUTION_SECONDS
    container_id = ""; transport = None; original = None; attempted = False; evidence = None
    try:
        network_id = preflight._network_id(control, deadline, ledger)
        daemon = _daemon(control, deadline, ledger)
        ledger.record("container", name, "attempted"); attempted = True
        created = preflight._control(control, preflight.create_command(name, image, user), deadline, ledger, "create")
        candidate = created["stdout"].strip()
        if re.fullmatch(r"[0-9a-f]{64}", candidate): container_id = candidate
        if created["returncode"] or not container_id: raise RuntimeError("diagnostic preflight creation failed")
        ledger.record("container", name, "created")
        before = preflight._inspect(control, name, deadline, ledger)
        _pre_start_tmpfs_gate(before)
        security_opt = _retained_inspect_gate(before, image, image_id, user, network_id)
        preflight.remaining(deadline); transport = preflight.start_attached(["docker", "start", "-a", name])
        result = preflight.await_attached(transport, deadline)
        if result["returncode"] or result["stderr"]: raise RuntimeError("diagnostic preflight execution failed")
        preflight._canonical_json(result["stdout"], os.getuid(), os.getgid())
        after = preflight._inspect(control, name, deadline, ledger)
        post_daemon = _daemon(control, deadline, ledger)
        if post_daemon != daemon: raise RuntimeError("diagnostic Docker server observation changed")
        _retained_inspect_gate(after, image, image_id, user, network_id, True, security_opt)
        evidence = PostExitTmpfsObservation(_tmpfs_observation(after, post_daemon))
        original = evidence
    except Exception as exc:
        original = exc
    try:
        preflight._remove(control, name, container_id, ledger, transport, attempted)
    except Exception as cleanup:
        if evidence is not None:
            raise RuntimeError(f"diagnostic post-exit block; cleanup also failed ({cleanup})") from original
        if original is not None:
            raise RuntimeError(f"diagnostic preflight failed ({original}); cleanup also failed ({cleanup})") from original
        raise
    if original is None:
        raise RuntimeError("diagnostic preflight completed without a post-exit observation")
    raise original
