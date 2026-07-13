"""Hosted-Linux diagnostic for preflight Tmpfs serialization only."""
from __future__ import annotations

import copy
import json
import os
import re
import time

import sandbox_python_preflight as preflight


SCHEMA = "wp-proxy-python-preflight-diagnostic.v1"
VERSION_TEMPLATE = '{"api_version":{{json .Server.APIVersion}},"architecture":{{json .Server.Arch}},"server_version":{{json .Server.Version}}}'


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
    return "unknown"


def tmpfs_observation(data, daemon, phase):
    host = data.get("HostConfig")
    present = isinstance(host, dict) and "Tmpfs" in host
    value = host.get("Tmpfs") if present else object()
    observation = {
        **daemon,
        "present": present,
        "json_type": _json_type(value),
        "entry_count": len(value) if isinstance(value, dict) else None,
        "empty": value is None or (isinstance(value, (dict, list, str)) and len(value) == 0),
    }
    if isinstance(value, dict) and not value:
        observation["literal"] = {}
    if not present or (value is not None and value != {}):
        detail = json.dumps(observation, sort_keys=True, separators=(",", ":"), allow_nan=False)
        raise RuntimeError(f"diagnostic preflight {phase} Tmpfs serialization rejected: {detail}")
    return observation


def _phase_gate(data, daemon, image, image_id, user, network_id, post, security_opt=None):
    phase = "post_exit" if post else "pre_start"
    observation = tmpfs_observation(data, daemon, phase)
    normalized = copy.deepcopy(data)
    normalized["HostConfig"]["Tmpfs"] = None
    security_opt = preflight.inspect_gate(
        normalized, image, image_id, user, network_id, post, security_opt
    )
    return observation, security_opt


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
    container_id = ""; transport = None; original = None; attempted = False; observations = {}
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
        observations["pre_start"], security_opt = _phase_gate(before, daemon, image, image_id, user, network_id, False)
        preflight.remaining(deadline); transport = preflight.start_attached(["docker", "start", "-a", name])
        result = preflight.await_attached(transport, deadline)
        if result["returncode"] or result["stderr"]: raise RuntimeError("diagnostic preflight execution failed")
        preflight._canonical_json(result["stdout"], os.getuid(), os.getgid())
        after = preflight._inspect(control, name, deadline, ledger)
        post_daemon = _daemon(control, deadline, ledger)
        if post_daemon != daemon: raise RuntimeError("diagnostic Docker server observation changed")
        observations["post_exit"], _security_opt = _phase_gate(after, post_daemon, image, image_id, user, network_id, True, security_opt)
    except Exception as exc: original = exc
    try: preflight._remove(control, name, container_id, ledger, transport, attempted)
    except Exception as cleanup:
        if original is not None: raise RuntimeError(f"diagnostic preflight failed ({original}); cleanup also failed ({cleanup})") from original
        raise
    if original is not None: raise original
    return {"schema": SCHEMA, **observations}
