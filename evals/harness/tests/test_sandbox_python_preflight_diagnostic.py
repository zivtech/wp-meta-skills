import copy
import inspect
import json
import os
from pathlib import Path

import pytest

import sandbox_python_preflight as preflight
import sandbox_python_preflight_diagnostic as diagnostic


IMAGE = "python@sha256:" + "a" * 64
IMAGE_ID = "sha256:" + "b" * 64
NETWORK_ID = "c" * 64
CONTAINER_ID = "d" * 64
RUN_ID = "1" * 16
USER = f"{os.getuid()}:{os.getgid()}"
NAME = "wp-proxy-preflight-" + RUN_ID
MISSING = object()
ENGINE = {
    "architecture": "amd64", "client_version": "28.0.4",
    "negotiated_api_version": "1.48", "operating_system": "linux",
    "server_version": "28.0.4",
}
LOCAL_OPTIONAL = {
    "Binds": None, "CapAdd": None, "DeviceCgroupRules": None,
    "DeviceRequests": None, "Devices": [], "Dns": None, "DnsOptions": [],
    "DnsSearch": [], "ExtraHosts": None, "GroupAdd": None, "Links": None,
    "PortBindings": {}, "VolumesFrom": None,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"


def baseline(post=False, gw=0, gw_missing=False):
    endpoint = {
        "IPAMConfig": None, "Links": None, "Aliases": None, "MacAddress": "",
        "NetworkID": NETWORK_ID if post else "", "EndpointID": "", "Gateway": "", "IPAddress": "",
        "IPPrefixLen": 0, "IPv6Gateway": "", "GlobalIPv6Address": "", "GlobalIPv6PrefixLen": 0,
        "DriverOpts": None, "DNSNames": None,
    }
    if not gw_missing: endpoint["GwPriority"] = gw
    host = {**copy.deepcopy(diagnostic.RAW_HOST_FIELDS), **copy.deepcopy(LOCAL_OPTIONAL), "SecurityOpt": ["no-new-privileges:true"]}
    config = {
        "Image": IMAGE, "User": USER, "Entrypoint": ["/usr/bin/env"],
        "Cmd": ["-i", preflight.PYTHON, "-I", "-S", "-c", preflight.PREFLIGHT_PROBE],
        "WorkingDir": "", "AttachStdin": False, "AttachStdout": True, "AttachStderr": True,
        "Tty": False, "OpenStdin": False, "StdinOnce": False, "Env": list(preflight.ENV),
    }
    state = {"Status": "exited" if post else "created", "Running": False, "ExitCode": 0, "OOMKilled": False, "Error": ""}
    return {"Image": IMAGE_ID, "Mounts": [], "Config": config, "HostConfig": host, "NetworkSettings": {"Networks": {"none": endpoint}}, "State": state}


def probe_payload():
    value = {
        "capabilities": {"os_getgid": True, "os_getuid": True, "os_kill": True}, "environment": {"LC_CTYPE": "C.UTF-8"},
        "flags": {"ignore_environment": 1, "isolated": 1, "no_site": 1, "no_user_site": 1, "safe_path": True},
        "gid": os.getgid(), "os_name": "posix", "proc_self_exe": preflight.PYTHON_EXE,
        "schema": "wp-proxy-python-preflight.v1", "signals": {"KILL": 9, "TERM": 15},
        "sys_executable": preflight.PYTHON, "sys_platform": "linux", "uid": os.getuid(),
    }
    return canonical(value)


def expected_carrier():
    profile = diagnostic._collect_optional(baseline()["HostConfig"])
    gw = {"present": True, "json_type": "integer", "value": 0}
    return {
        "schema": diagnostic.SCHEMA, "engine": ENGINE,
        "profiles": {"pre_start": profile, "post_exit": profile},
        "gw_priority": {"pre_start": gw, "post_exit": gw},
        "cleanup": {"removed": True, "name_absent": True, "id_absent": True},
    }


class Ledger:
    def __init__(self): self.events = []
    def record(self, *event): self.events.append(event)


class Scenario:
    def __init__(self, gw_phase="", gw_value=0, raw_drift="", invalid_phase="", invalid_field="", invalid_value=None, engine_drift=False, retained=False, retry=False):
        self.gw_phase = gw_phase; self.gw_value = gw_value; self.raw_drift = raw_drift
        self.invalid_phase = invalid_phase; self.invalid_field = invalid_field; self.invalid_value = invalid_value
        self.engine_drift = engine_drift; self.retained = retained; self.retry = retry
        self.raw_inspections = 0; self.engine_calls = 0; self.rm_attempts = 0
        self.filters = []; self.commands = []; self.attached = []; self.events = []
    def result(self, returncode=0, stdout="", stderr=""): return {"returncode": returncode, "stdout": stdout, "stderr": stderr}
    def control(self, command, _timeout):
        self.commands.append(command)
        if command[:4] == ["docker", "network", "inspect", "none"]:
            return self.result(stdout=json.dumps([{"Name": "none", "Driver": "null", "Scope": "local", "Id": NETWORK_ID}]))
        if command[:3] == ["docker", "version", "--format"]:
            self.engine_calls += 1; value = dict(ENGINE)
            if self.engine_drift and self.engine_calls == 2: value["server_version"] = "28.0.5"
            return self.result(stdout=canonical(value))
        if command[1] == "create": return self.result(stdout=CONTAINER_ID + "\n")
        if command[1] == "inspect":
            self.raw_inspections += 1; post = self.raw_inspections == 2; phase = "post" if post else "pre"
            missing = self.gw_phase == phase and self.gw_value is MISSING
            gw = 0 if self.gw_phase != phase else self.gw_value
            data = baseline(post, gw, missing)
            if self.raw_drift == phase: data["HostConfig"]["Memory"] = 1
            if self.invalid_phase == phase: data["HostConfig"][self.invalid_field] = self.invalid_value
            return self.result(stdout=json.dumps([data]))
        if command[1:3] == ["rm", "-f"]:
            self.rm_attempts += 1; self.events.append("remove")
            if self.retry and self.rm_attempts == 1: return self.result(7, stderr="retry")
            return self.result(stdout="removed\n")
        if command[1:3] == ["container", "ls"]:
            self.filters.append(command[6]); self.events.append(command[6])
            if self.retained and command[6].startswith("name="):
                return self.result(stdout=f'{json.dumps(CONTAINER_ID)} {json.dumps(NAME)}\n')
            return self.result()
        raise AssertionError(command)


def execute(monkeypatch, scenario):
    def start(command): scenario.attached.append(command); return object()
    monkeypatch.setattr(preflight, "start_attached", start)
    monkeypatch.setattr(preflight, "await_attached", lambda *_args: {"returncode": 0, "stdout": probe_payload(), "stderr": ""})
    monkeypatch.setattr(preflight, "cleanup_attached", lambda *_args: [])
    return diagnostic.run(scenario.control, IMAGE, IMAGE_ID, USER, RUN_ID, Ledger())


def assert_cleanup(scenario, failed=False):
    assert 1 <= scenario.rm_attempts <= 2
    expected = ["name=^/" + NAME + "$"]
    if not failed: expected.append("id=" + CONTAINER_ID)
    assert scenario.filters == expected


def test_inventory_classes_local_candidate_and_profile_cap():
    assert tuple(diagnostic.OPTIONAL_FIELDS) == (
        "Binds", "CapAdd", "DeviceCgroupRules", "DeviceRequests", "Devices", "Dns", "DnsOptions",
        "DnsSearch", "ExtraHosts", "GroupAdd", "Init", "Links", "PortBindings", "Tmpfs", "VolumesFrom",
    )
    assert diagnostic.LIST_FIELDS | diagnostic.MAP_FIELDS | diagnostic.BOOL_FIELDS == set(diagnostic.OPTIONAL_FIELDS)
    assert not (diagnostic.LIST_FIELDS & diagnostic.MAP_FIELDS or diagnostic.LIST_FIELDS & diagnostic.BOOL_FIELDS)
    profile = diagnostic._collect_optional(baseline()["HostConfig"])
    assert set(profile) == set(diagnostic.OPTIONAL_FIELDS)
    assert len(canonical(profile).encode()) <= diagnostic.PROFILE_LIMIT
    assert profile["Dns"] == {"present": True, "encoding": "null"}
    assert profile["DnsOptions"] == {"present": True, "encoding": "empty-array"}
    assert profile["PortBindings"] == {"present": True, "encoding": "empty-object"}
    assert profile["Init"] == profile["Tmpfs"] == {"present": False, "encoding": "missing"}


def safe_cases():
    cases = []
    for field in diagnostic.LIST_FIELDS: cases.extend(((field, MISSING, "missing"), (field, None, "null"), (field, [], "empty-array")))
    for field in diagnostic.MAP_FIELDS: cases.extend(((field, MISSING, "missing"), (field, None, "null"), (field, {}, "empty-object")))
    for field in diagnostic.BOOL_FIELDS: cases.extend(((field, MISSING, "missing"), (field, None, "null"), (field, False, "false")))
    return cases


@pytest.mark.parametrize("field,value,encoding", safe_cases())
def test_collector_distinguishes_every_safe_presence_and_encoding(field, value, encoding):
    host = {} if value is MISSING else {field: value}
    profile = diagnostic._collect_optional(host)
    assert profile[field] == {"present": value is not MISSING, "encoding": encoding}
    assert set(profile) == set(diagnostic.OPTIONAL_FIELDS)


def invalid_cases():
    cases = []
    for field in diagnostic.LIST_FIELDS: cases.extend((field, value) for value in (["secret-value"], {"secret-key": "secret-value"}, False, "secret-value", 1))
    for field in diagnostic.MAP_FIELDS: cases.extend((field, value) for value in ({"secret-key": "secret-value"}, ["secret-value"], False, "secret-value", 1))
    for field in diagnostic.BOOL_FIELDS: cases.extend((field, value) for value in (True, ["secret-value"], {"secret-key": "secret-value"}, "secret-value", 1))
    return cases


@pytest.mark.parametrize("field,value", invalid_cases())
def test_every_invalid_shape_is_redacted(field, value):
    with pytest.raises(RuntimeError, match="invalid-redacted") as caught:
        diagnostic._collect_optional({field: value})
    profile = json.loads(str(caught.value).split(": ", 1)[1])
    assert set(profile) == set(diagnostic.OPTIONAL_FIELDS)
    assert profile[field] == {"present": True, "encoding": "invalid-redacted"}
    assert "secret-key" not in str(caught.value) and "secret-value" not in str(caught.value)


def test_multiple_invalid_fields_still_collect_one_redacted_fifteen_field_profile():
    host = {"Dns": ["secret-value"], "Tmpfs": {"secret-key": "secret-value"}, "Init": None}
    with pytest.raises(RuntimeError, match="invalid-redacted") as caught:
        diagnostic._collect_optional(host)
    profile = json.loads(str(caught.value).split(": ", 1)[1])
    assert set(profile) == set(diagnostic.OPTIONAL_FIELDS) and len(profile) == 15
    assert profile["Dns"] == profile["Tmpfs"] == {"present": True, "encoding": "invalid-redacted"}
    assert profile["Init"] == {"present": True, "encoding": "null"}
    assert "secret-key" not in str(caught.value) and "secret-value" not in str(caught.value)


def test_clean_run_builds_exact_carrier_only_after_cleanup(monkeypatch):
    scenario = Scenario(); constructed = []
    real = diagnostic.RawHostConfigProfile
    def build(value):
        assert scenario.filters == ["name=^/" + NAME + "$", "id=" + CONTAINER_ID]
        constructed.append(value); return real(value)
    monkeypatch.setattr(diagnostic, "RawHostConfigProfile", build)
    with pytest.raises(real) as caught: execute(monkeypatch, scenario)
    assert caught.value.carrier == expected_carrier() and constructed == [expected_carrier()]
    assert caught.value.encoded == canonical(expected_carrier()).rstrip("\n")
    assert scenario.raw_inspections == 2 and scenario.engine_calls == 2
    create = next(command for command in scenario.commands if command[1] == "create")
    assert create == preflight.create_command(NAME, IMAGE, USER)
    assert all(flag not in create for flag in ("--mount", "--tmpfs", "--volume", "--secret", "-v"))
    assert scenario.attached == [["docker", "start", "-a", NAME]]
    assert all(command[1] in {"network", "version", "create", "inspect", "rm", "container"} for command in scenario.commands)
    assert_cleanup(scenario)


@pytest.mark.parametrize("phase", ["pre", "post"])
@pytest.mark.parametrize("value", [MISSING, False, "0", 1])
def test_gwpriority_missing_bool_string_or_nonzero_blocks_without_carrier(monkeypatch, phase, value):
    scenario = Scenario(gw_phase=phase, gw_value=value)
    with pytest.raises(RuntimeError, match="GwPriority drift") as caught: execute(monkeypatch, scenario)
    assert not isinstance(caught.value, diagnostic.RawHostConfigProfile)
    assert scenario.attached == ([] if phase == "pre" else [["docker", "start", "-a", NAME]])
    assert_cleanup(scenario)


@pytest.mark.parametrize("post", [False, True])
def test_none_endpoint_network_id_transition_is_exact(post):
    networks = baseline(post)["NetworkSettings"]["Networks"]
    assert diagnostic._none_network(networks, NETWORK_ID, post) == {"present": True, "json_type": "integer", "value": 0}
    networks["none"]["NetworkID"] = NETWORK_ID if not post else ""
    with pytest.raises(RuntimeError, match="state drift"): diagnostic._none_network(networks, NETWORK_ID, post)


@pytest.mark.parametrize("key", tuple(diagnostic.RAW_HOST_FIELDS))
def test_every_retained_raw_host_field_remains_exact(key):
    data = baseline(); data["HostConfig"][key] = None
    with pytest.raises(RuntimeError, match=key): diagnostic._raw_gate(data, IMAGE, IMAGE_ID, USER, NETWORK_ID)


@pytest.mark.parametrize("target", ["identity", "mounts", "config", "environment", "security", "network", "state"])
def test_other_retained_raw_surfaces_remain_exact(target):
    data = baseline()
    if target == "identity": data["Image"] = "sha256:" + "e" * 64
    elif target == "mounts": data["Mounts"] = [{"Type": "bind"}]
    elif target == "config": data["Config"]["Cmd"] = []
    elif target == "environment": data["Config"]["Env"] = []
    elif target == "security": data["HostConfig"]["SecurityOpt"] = []
    elif target == "network": data["NetworkSettings"]["Networks"] = {}
    elif target == "state": data["State"]["Status"] = "running"
    with pytest.raises(RuntimeError): diagnostic._raw_gate(data, IMAGE, IMAGE_ID, USER, NETWORK_ID)


@pytest.mark.parametrize("field", diagnostic.OPTIONAL_FIELDS)
def test_optional_fields_are_exclusively_collector_gated_in_raw_gate(field):
    data = baseline(); data["HostConfig"][field] = {"raw-secret": "raw-value"}
    security, gw = diagnostic._raw_gate(data, IMAGE, IMAGE_ID, USER, NETWORK_ID)
    assert security == ("no-new-privileges:true",) and gw["value"] == 0


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_invalid_optional_or_retained_phase_is_generic_ineligible_and_cleaned(monkeypatch, phase):
    invalid = Scenario(invalid_phase=phase, invalid_field="Dns", invalid_value=["secret-value"])
    with pytest.raises(RuntimeError, match="invalid-redacted") as caught: execute(monkeypatch, invalid)
    assert not isinstance(caught.value, diagnostic.RawHostConfigProfile) and "secret-value" not in str(caught.value)
    assert_cleanup(invalid)
    retained = Scenario(raw_drift=phase)
    with pytest.raises(RuntimeError, match="HostConfig.Memory drift"): execute(monkeypatch, retained)
    assert_cleanup(retained)


def test_engine_drift_blocks_and_cleanup_failure_never_constructs_carrier(monkeypatch):
    drift = Scenario(engine_drift=True)
    with pytest.raises(RuntimeError, match="engine tuple changed"): execute(monkeypatch, drift)
    assert_cleanup(drift)
    calls = []; monkeypatch.setattr(diagnostic, "RawHostConfigProfile", lambda value: calls.append(value))
    failed = Scenario(retained=True)
    with pytest.raises(RuntimeError, match="cleanup failed"): execute(monkeypatch, failed)
    assert calls == [] and failed.filters == ["name=^/" + NAME + "$"]


def test_schema_inventory_cleanup_facts_and_carrier_cap():
    carrier = expected_carrier(); error = diagnostic.RawHostConfigProfile(carrier)
    assert error.carrier["schema"] == "wp-proxy-hostconfig-raw-profile.v1"
    assert error.carrier["cleanup"] == {"removed": True, "name_absent": True, "id_absent": True}
    assert len(error.encoded.encode()) <= diagnostic.CARRIER_LIMIT
    broken = copy.deepcopy(carrier); broken["schema"] = "wrong"
    with pytest.raises(RuntimeError, match="carrier shape"): diagnostic.RawHostConfigProfile(broken)
    profile = copy.deepcopy(carrier["profiles"]["pre_start"]); profile.pop("Tmpfs")
    with pytest.raises(RuntimeError, match="inventory"): diagnostic._validate_profile(profile)


def test_one_retry_dual_absence_and_separate_deadline_structure(monkeypatch):
    scenario = Scenario(retry=True)
    with pytest.raises(diagnostic.RawHostConfigProfile): execute(monkeypatch, scenario)
    assert scenario.rm_attempts == 2; assert_cleanup(scenario)
    source = inspect.getsource(diagnostic.run)
    assert source.count("time.monotonic() + preflight.EXECUTION_SECONDS") == 1
    assert source.count("preflight._remove(") == 1
    assert "time.monotonic() + CLEANUP_SECONDS" in inspect.getsource(preflight._remove)


def test_emit_profile_writes_one_exact_carrier_to_each_sink(tmp_path):
    error = diagnostic.RawHostConfigProfile(expected_carrier()); logs = []; summary = tmp_path / "summary.md"
    diagnostic.emit_profile(error, summary, logs.append)
    assert logs == [error.encoded] and summary.read_text(encoding="utf-8").count(error.encoded) == 1
    with pytest.raises(TypeError): diagnostic.emit_profile(RuntimeError("generic"), summary, logs.append)
    assert logs == [error.encoded] and summary.read_text(encoding="utf-8").count(error.encoded) == 1


def test_workflow_catches_only_raw_carrier_then_blocks_native_step():
    workflow = (Path(__file__).resolve().parents[3] / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    start = workflow.index("      - name: Observe exact zero-mount preflight serialization")
    end = workflow.index("      - name: Run implemented package acquisition and endpointless boundary cases", start)
    block = workflow[start:end]
    assert block.count("except diagnostic.RawHostConfigProfile as blocked:") == 1
    assert block.count("diagnostic.emit_profile(blocked") == 1
    assert block.count("raise SystemExit(diagnostic.BLOCK_MESSAGE)") == 1
    assert diagnostic.BLOCK_MESSAGE == "AWAITING_HOSTCONFIG_PROFILE_REVIEW"
    assert "except Exception" not in block and "continue-on-error" not in block and start < end
