"""Evidence-only raw optional HostConfig and GwPriority profile collector."""
from __future__ import annotations

import json
import os
import re
import time

import sandbox_python_preflight as preflight


SCHEMA = "wp-proxy-hostconfig-raw-profile.v1"
BLOCK_MESSAGE = "AWAITING_HOSTCONFIG_PROFILE_REVIEW"
PROFILE_LIMIT = 2048
CARRIER_LIMIT = 4096
ENGINE_TEMPLATE = '{"architecture":{{json .Server.Arch}},"client_version":{{json .Client.Version}},"negotiated_api_version":{{json .Client.APIVersion}},"operating_system":{{json .Server.Os}},"server_version":{{json .Server.Version}}}'
ENGINE_FIELDS = {"architecture", "client_version", "negotiated_api_version", "operating_system", "server_version"}
OPTIONAL_FIELDS = (
    "Binds", "CapAdd", "DeviceCgroupRules", "DeviceRequests", "Devices",
    "Dns", "DnsOptions", "DnsSearch", "ExtraHosts", "GroupAdd", "Init",
    "Links", "PortBindings", "Tmpfs", "VolumesFrom",
)
LIST_FIELDS = {
    "Binds", "CapAdd", "DeviceCgroupRules", "DeviceRequests", "Devices",
    "Dns", "DnsOptions", "DnsSearch", "ExtraHosts", "GroupAdd", "Links",
    "VolumesFrom",
}
MAP_FIELDS = {"PortBindings", "Tmpfs"}
BOOL_FIELDS = {"Init"}
RAW_HOST_FIELDS = {
    "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"],
    "Privileged": False, "AutoRemove": False, "PidsLimit": 16,
    "Memory": 67108864, "MemorySwap": 67108864, "NanoCpus": 250000000,
    "Ulimits": [{"Name": "nofile", "Hard": 64, "Soft": 64}],
    "LogConfig": {"Type": "none", "Config": {}},
    "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
    "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "",
    "UTSMode": "", "UsernsMode": "", "ShmSize": 1048576,
}


class RawHostConfigProfile(RuntimeError):
    """Eligible evidence constructed only after ordinary cleanup succeeds."""

    def __init__(self, carrier):
        _validate_carrier(carrier)
        self._encoded = _canonical(carrier)
        if len(self._encoded.encode("utf-8")) > CARRIER_LIMIT:
            raise RuntimeError("diagnostic raw profile carrier limit exceeded")
        super().__init__(BLOCK_MESSAGE)

    @property
    def carrier(self):
        return json.loads(self._encoded)

    @property
    def encoded(self):
        return self._encoded


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _encoding(field, present, value):
    if not present: return "missing"
    if value is None: return "null"
    if field in LIST_FIELDS and isinstance(value, list) and not value: return "empty-array"
    if field in MAP_FIELDS and isinstance(value, dict) and not value: return "empty-object"
    if field in BOOL_FIELDS and value is False: return "false"
    return "invalid-redacted"


def _collect_optional(host):
    if not isinstance(host, dict): raise RuntimeError("diagnostic HostConfig object drift")
    profile = {}
    for field in OPTIONAL_FIELDS:
        present = field in host; value = host.get(field) if present else _MISSING
        profile[field] = {"present": present, "encoding": _encoding(field, present, value)}
    encoded = _canonical(profile)
    if len(encoded.encode("utf-8")) > PROFILE_LIMIT:
        raise RuntimeError("diagnostic optional HostConfig profile limit exceeded")
    if any(record["encoding"] == "invalid-redacted" for record in profile.values()):
        raise RuntimeError("diagnostic optional HostConfig invalid: " + encoded)
    _validate_profile(profile)
    return profile


def _validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != set(OPTIONAL_FIELDS):
        raise RuntimeError("diagnostic optional HostConfig inventory drift")
    for field in OPTIONAL_FIELDS:
        record = profile[field]
        if not isinstance(record, dict) or set(record) != {"present", "encoding"} or type(record["present"]) is not bool:
            raise RuntimeError("diagnostic optional HostConfig record drift")
        allowed = {"missing", "null"}
        if field in LIST_FIELDS: allowed.add("empty-array")
        if field in MAP_FIELDS: allowed.add("empty-object")
        if field in BOOL_FIELDS: allowed.add("false")
        if record["encoding"] not in allowed or record["present"] != (record["encoding"] != "missing"):
            raise RuntimeError("diagnostic optional HostConfig encoding drift")


def _unique(items):
    if len({key for key, _value in items}) != len(items): raise ValueError("duplicate key")
    return dict(items)


def _strict_engine(payload):
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > PROFILE_LIMIT:
        raise RuntimeError("diagnostic Docker engine tuple limit exceeded")
    if not payload.endswith("\n") or payload.count("\n") != 1:
        raise RuntimeError("diagnostic Docker engine tuple framing drift")
    try:
        value = json.loads(payload, object_pairs_hook=_unique, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("diagnostic Docker engine tuple is not strict JSON") from exc
    if payload != _canonical(value) + "\n": raise RuntimeError("diagnostic Docker engine tuple is not canonical JSON")
    if not isinstance(value, dict) or set(value) != ENGINE_FIELDS:
        raise RuntimeError("diagnostic Docker engine tuple shape drift")
    valid = (
        value["architecture"] in {"amd64", "arm64"} and value["operating_system"] == "linux"
        and isinstance(value["negotiated_api_version"], str)
        and re.fullmatch(r"[0-9.]{1,16}", value["negotiated_api_version"])
        and all(isinstance(value[key], str) and re.fullmatch(r"[0-9A-Za-z._+\-]{1,64}", value[key]) for key in ("client_version", "server_version"))
    )
    if not valid: raise RuntimeError("diagnostic Docker engine tuple value drift")
    return value


def _engine(control, deadline, ledger):
    command = ["docker", "version", "--format", ENGINE_TEMPLATE]
    result = preflight._control(control, command, deadline, ledger, "engine-tuple")
    stdout = result.get("stdout"); stderr = result.get("stderr")
    bounded = isinstance(stderr, str) and len(stderr.encode("utf-8")) <= PROFILE_LIMIT
    if result.get("returncode") != 0 or not bounded or stderr:
        raise RuntimeError("diagnostic Docker engine tuple command failed")
    return _strict_engine(stdout)


def _raw_host_gate(host, security_opt):
    if not isinstance(host, dict): raise RuntimeError("preflight HostConfig drift")
    for key, expected in RAW_HOST_FIELDS.items():
        if key not in host or host[key] != expected:
            raise RuntimeError(f"preflight HostConfig.{key} drift")
    if "SecurityOpt" not in host: raise RuntimeError("preflight no-new-privileges drift")
    observed = host["SecurityOpt"]
    if security_opt is None:
        if observed not in (["no-new-privileges"], ["no-new-privileges:true"]):
            raise RuntimeError("preflight no-new-privileges drift")
        security_opt = tuple(observed)
    elif tuple(observed or ()) != security_opt:
        raise RuntimeError("preflight no-new-privileges serialization drift")
    return security_opt


def _none_network(value, network_id, post):
    expected_endpoint = {
        "IPAMConfig": None, "Links": None, "Aliases": None, "MacAddress": "",
        "NetworkID": network_id if post else "", "EndpointID": "", "Gateway": "",
        "IPAddress": "", "IPPrefixLen": 0, "IPv6Gateway": "", "GlobalIPv6Address": "",
        "GlobalIPv6PrefixLen": 0, "DriverOpts": None, "DNSNames": None, "GwPriority": 0,
    }
    if not isinstance(value, dict) or not isinstance(value.get("none"), dict):
        raise RuntimeError("diagnostic none-network state drift")
    endpoint = value["none"]
    if "GwPriority" not in endpoint or type(endpoint["GwPriority"]) is not int or endpoint["GwPriority"] != 0:
        raise RuntimeError("diagnostic none-network GwPriority drift")
    if value != {"none": expected_endpoint}: raise RuntimeError("diagnostic none-network state drift")
    return {"present": True, "json_type": "integer", "value": 0}


def _raw_gate(data, image, image_id, user, network_id, post=False, security_opt=None):
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
        if key not in config or config[key] != expected: raise RuntimeError(f"preflight Config.{key} drift")
    preflight.assert_image_environment(config.get("Env"))
    security_opt = _raw_host_gate(data.get("HostConfig"), security_opt)
    gw = _none_network((data.get("NetworkSettings") or {}).get("Networks"), network_id, post)
    state = data.get("State") or {}
    expected_state = {"Status": "exited" if post else "created", "Running": False, "ExitCode": 0, "OOMKilled": False, "Error": ""}
    if any(key not in state or state[key] != expected for key, expected in expected_state.items()):
        raise RuntimeError("preflight stopped-state drift" if post else "preflight pre-start state drift")
    return security_opt, gw


def _validate_carrier(value):
    expected_keys = {"schema", "engine", "profiles", "gw_priority", "cleanup"}
    if not isinstance(value, dict) or set(value) != expected_keys or value["schema"] != SCHEMA:
        raise RuntimeError("diagnostic raw profile carrier shape drift")
    _strict_engine(_canonical(value["engine"]) + "\n")
    if not isinstance(value["profiles"], dict) or set(value["profiles"]) != {"pre_start", "post_exit"}:
        raise RuntimeError("diagnostic raw profile phase inventory drift")
    for phase in ("pre_start", "post_exit"):
        _validate_profile(value["profiles"][phase])
        if value["gw_priority"].get(phase) != {"present": True, "json_type": "integer", "value": 0}:
            raise RuntimeError("diagnostic raw profile GwPriority fact drift")
    if set(value["gw_priority"]) != {"pre_start", "post_exit"}:
        raise RuntimeError("diagnostic raw profile GwPriority inventory drift")
    if value["cleanup"] != {"removed": True, "name_absent": True, "id_absent": True}:
        raise RuntimeError("diagnostic raw profile cleanup fact drift")


def emit_profile(error, summary_path, log=print):
    if type(error) is not RawHostConfigProfile:
        raise TypeError("only an exact raw HostConfig profile is eligible")
    log(error.encoded)
    with open(os.fspath(summary_path), "a", encoding="utf-8") as summary:
        summary.write("## Raw HostConfig profile\n\n```json\n" + error.encoded + "\n```\n")


def _validate(user, run_id):
    if os.getuid() == 0 or user.startswith("0:"): raise RuntimeError("diagnostic proxy interpreter preflight forbids root")
    if user != f"{os.getuid()}:{os.getgid()}" or not re.fullmatch(r"[1-9][0-9]*:[0-9]+", user):
        raise RuntimeError("diagnostic proxy interpreter preflight user drift")
    if not re.fullmatch(r"[0-9a-f]{16}", run_id): raise ValueError("invalid diagnostic proxy interpreter preflight run ID")


def run(control, image, image_id, user, run_id, ledger):
    _validate(user, run_id); name = f"wp-proxy-preflight-{run_id}"
    deadline = time.monotonic() + preflight.EXECUTION_SECONDS
    container_id = ""; daemon_id = ""; transport = None
    original = None; attempted = False; identity_tainted = False; candidate = None
    try:
        daemon_id = preflight._daemon_id(control, deadline, ledger)
        network_id = preflight._network_id(control, deadline, ledger)
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-network-daemon-after")
        engine = _engine(control, deadline, ledger)
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-engine-daemon-after")
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-create-daemon-before")
        ledger.record("container", name, "attempted"); attempted = True
        created = preflight._control(control, preflight.create_command(name, image, user), deadline, ledger, "create")
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-create-daemon-after")
        possible = created["stdout"].strip()
        if re.fullmatch(r"[0-9a-f]{64}", possible): container_id = possible
        if created["returncode"] or not container_id: raise RuntimeError("diagnostic preflight creation failed")
        ledger.record("container", name, "created"); before = preflight._inspect(control, name, deadline, ledger, daemon_id)
        security_opt, pre_gw = _raw_gate(before, image, image_id, user, network_id)
        profiles = {"pre_start": _collect_optional(before["HostConfig"])}
        preflight.remaining(deadline); preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-start-daemon-before")
        transport = preflight.start_attached(["docker", "start", "-a", name])
        result = preflight.await_attached(transport, deadline)
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-start-daemon-after")
        if result["returncode"] or result["stderr"]: raise RuntimeError("diagnostic preflight execution failed")
        preflight._canonical_json(result["stdout"], os.getuid(), os.getgid()); after = preflight._inspect(control, name, deadline, ledger, daemon_id)
        _security, post_gw = _raw_gate(after, image, image_id, user, network_id, True, security_opt)
        profiles["post_exit"] = _collect_optional(after["HostConfig"])
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-post-engine-daemon-before")
        post_engine = _engine(control, deadline, ledger)
        if post_engine != engine: raise RuntimeError("diagnostic Docker engine tuple changed")
        preflight._require_daemon(control, daemon_id, deadline, ledger, "diagnostic-post-exit-daemon")
        candidate = {"engine": engine, "profiles": profiles, "gw_priority": {"pre_start": pre_gw, "post_exit": post_gw}}
    except Exception as exc:
        original = exc; identity_tainted = attempted and isinstance(exc, preflight.DaemonIdentityError)
    try: preflight._remove(control, name, container_id, ledger, transport, attempted, daemon_id, identity_tainted)
    except Exception as cleanup:
        if original is not None: raise RuntimeError(f"diagnostic preflight failed ({original}); cleanup also failed ({cleanup})") from original
        raise
    if original is not None: raise original
    if candidate is None: raise RuntimeError("diagnostic raw profile candidate unavailable")
    carrier = {"schema": SCHEMA, **candidate, "cleanup": {"removed": True, "name_absent": True, "id_absent": True}}
    raise RawHostConfigProfile(carrier)


_MISSING = object()
