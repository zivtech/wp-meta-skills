import copy
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
DAEMON = {"api_version": "1.52", "architecture": "amd64", "server_version": "29.4.0"}
MISSING = object()


def baseline(tmpfs=MISSING, post=False):
    endpoint = {
        "IPAMConfig": None, "Links": None, "Aliases": None, "MacAddress": "",
        "NetworkID": NETWORK_ID if post else "", "EndpointID": "", "Gateway": "", "IPAddress": "",
        "IPPrefixLen": 0, "IPv6Gateway": "", "GlobalIPv6Address": "", "GlobalIPv6PrefixLen": 0,
        "DriverOpts": None, "DNSNames": None,
    }
    host = {
        "NetworkMode": "none", "ReadonlyRootfs": True, "CapDrop": ["ALL"], "Privileged": False,
        "AutoRemove": False, "PidsLimit": 16, "Memory": 67108864, "MemorySwap": 67108864,
        "NanoCpus": 250000000, "Ulimits": [{"Name": "nofile", "Hard": 64, "Soft": 64}],
        "LogConfig": {"Type": "none", "Config": {}}, "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
        "IpcMode": "private", "CgroupnsMode": "private", "PidMode": "", "UTSMode": "", "UsernsMode": "",
        "Binds": None, "Devices": [], "PortBindings": {}, "ExtraHosts": None, "Links": None,
        "Dns": [], "DnsSearch": [], "DnsOptions": [], "Init": None, "ShmSize": 1048576,
        "SecurityOpt": ["no-new-privileges:true"], "CapAdd": None, "GroupAdd": None,
        "DeviceRequests": None, "DeviceCgroupRules": None,
    }
    if tmpfs is not MISSING:
        host["Tmpfs"] = tmpfs
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
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def expected_observation(value):
    present = value is not MISSING
    observed = value if present else None
    empty = bool(present and (observed is None or (isinstance(observed, (dict, list, str)) and len(observed) == 0)))
    return {
        **DAEMON, "phase": "post_exit", "present": present,
        "json_type": diagnostic._json_type(observed) if present else "missing",
        "entry_count": len(observed) if isinstance(observed, dict) else None,
        "empty": empty,
    }


class Ledger:
    def __init__(self): self.events = []
    def record(self, *event): self.events.append(event)


class Scenario:
    def __init__(self, pre_tmpfs=MISSING, post_tmpfs=MISSING, drift_phase="", retry=False, retained=False):
        self.pre_tmpfs = pre_tmpfs; self.post_tmpfs = post_tmpfs; self.drift_phase = drift_phase
        self.retry = retry; self.retained = retained; self.inspections = 0; self.rm_attempts = 0
        self.filters = []; self.commands = []; self.attached = []
    def result(self, returncode=0, stdout="", stderr=""): return {"returncode": returncode, "stdout": stdout, "stderr": stderr}
    def control(self, command, _timeout):
        self.commands.append(command)
        if command[:4] == ["docker", "network", "inspect", "none"]:
            return self.result(stdout=json.dumps([{"Name": "none", "Driver": "null", "Scope": "local", "Id": NETWORK_ID}]))
        if command[:2] == ["docker", "version"]:
            return self.result(stdout=json.dumps(DAEMON, sort_keys=True, separators=(",", ":")) + "\n")
        if command[1] == "create": return self.result(stdout=CONTAINER_ID + "\n")
        if command[1] == "inspect":
            self.inspections += 1; post = self.inspections == 2
            data = baseline(self.post_tmpfs if post else self.pre_tmpfs, post)
            if self.drift_phase == ("post" if post else "pre"): data["Config"]["User"] = "999:999"
            return self.result(stdout=json.dumps([data]))
        if command[1:3] == ["rm", "-f"]:
            self.rm_attempts += 1
            if self.retry and self.rm_attempts == 1: return self.result(7, stderr="retry")
            return self.result(stdout="removed\n")
        if command[1:3] == ["container", "ls"]:
            self.filters.append(command[6])
            if self.retained and command[6].startswith("name="):
                return self.result(stdout=f'{json.dumps(CONTAINER_ID)} {json.dumps(NAME)}\n')
            return self.result()
        raise AssertionError(command)


def execute(monkeypatch, scenario):
    def start(command):
        scenario.attached.append(command)
        return object()
    monkeypatch.setattr(preflight, "start_attached", start)
    monkeypatch.setattr(preflight, "await_attached", lambda *_args: {"returncode": 0, "stdout": probe_payload(), "stderr": ""})
    monkeypatch.setattr(preflight, "cleanup_attached", lambda *_args: [])
    return diagnostic.run(scenario.control, IMAGE, IMAGE_ID, USER, RUN_ID, Ledger())


def assert_cleanup(scenario, failed=False):
    assert 1 <= scenario.rm_attempts <= 2
    expected = ["name=^/" + NAME + "$"]
    if not failed: expected.append("id=" + CONTAINER_ID)
    assert scenario.filters == expected


def test_clean_profile_raises_only_sanitized_carrier_after_probe_and_cleanup(monkeypatch):
    scenario = Scenario(post_tmpfs={})
    with pytest.raises(diagnostic.PostExitTmpfsObservation) as caught:
        execute(monkeypatch, scenario)
    assert dict(caught.value.observation) == expected_observation({})
    assert str(caught.value) == diagnostic.BLOCK_MESSAGE
    encoded = json.dumps(dict(caught.value.observation), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert not any(value in encoded for value in ("HostConfig", "Config", "environment", IMAGE, IMAGE_ID, "/usr/local"))
    create = next(command for command in scenario.commands if command[1] == "create")
    assert create == preflight.create_command(NAME, IMAGE, USER)
    assert "--mount" not in create and "--tmpfs" not in create
    assert scenario.attached == [["docker", "start", "-a", NAME]]
    assert all(command[:2] in (["docker", "network"], ["docker", "version"], ["docker", "create"], ["docker", "inspect"], ["docker", "rm"], ["docker", "container"]) for command in scenario.commands)
    assert_cleanup(scenario)


@pytest.mark.parametrize("value", [MISSING, None, {}, {"/secret/path": "secret-value"}, [], ["secret-value"], "secret-value", False, 7])
def test_post_exit_carrier_covers_only_bounded_representation_shape(monkeypatch, value):
    scenario = Scenario(post_tmpfs=value)
    with pytest.raises(diagnostic.PostExitTmpfsObservation) as caught:
        execute(monkeypatch, scenario)
    observation = dict(caught.value.observation)
    assert observation == expected_observation(value)
    encoded = json.dumps(observation, sort_keys=True, separators=(",", ":"))
    assert len(encoded) < 256 and "/secret/path" not in encoded and "secret-value" not in encoded
    assert set(observation) == diagnostic.OBSERVATION_FIELDS
    assert_cleanup(scenario)


@pytest.mark.parametrize("value", [None, {}, {"/tmp": "size=1"}, [], [1], "", "wrong", False, 0])
def test_pre_start_accepts_only_missing_tmpfs_key(monkeypatch, value):
    scenario = Scenario(pre_tmpfs=value)
    with pytest.raises(RuntimeError, match="HostConfig.Tmpfs must be absent") as caught:
        execute(monkeypatch, scenario)
    assert not isinstance(caught.value, diagnostic.PostExitTmpfsObservation)
    assert scenario.attached == []
    assert_cleanup(scenario)


@pytest.mark.parametrize("phase", ["pre", "post"])
def test_retained_field_drift_creates_no_eligible_observation(monkeypatch, phase):
    scenario = Scenario(post_tmpfs={}, drift_phase=phase)
    monkeypatch.setattr(diagnostic, "_tmpfs_observation", lambda *_args: pytest.fail("ineligible observation constructed"))
    with pytest.raises(RuntimeError, match="Config.User drift") as caught:
        execute(monkeypatch, scenario)
    assert not isinstance(caught.value, diagnostic.PostExitTmpfsObservation)
    assert_cleanup(scenario)


def drift(data, target):
    if target == "identity": data["Image"] = "sha256:" + "e" * 64
    elif target == "mounts": data["Mounts"] = [{"Type": "bind"}]
    elif target == "config": data["Config"]["Cmd"] = []
    elif target == "environment": data["Config"]["Env"] = []
    elif target == "host": data["HostConfig"]["Memory"] = 1
    elif target == "security": data["HostConfig"]["SecurityOpt"] = []
    elif target == "privilege": data["HostConfig"]["CapAdd"] = ["NET_ADMIN"]
    elif target == "device": data["HostConfig"]["DeviceRequests"] = []
    elif target == "network": data["NetworkSettings"]["Networks"] = {}
    elif target == "state": data["State"]["ExitCode"] = 1
    return data


@pytest.mark.parametrize("target", ["identity", "mounts", "config", "environment", "host", "security", "privilege", "device", "network", "state"])
def test_post_exit_retains_each_exact_gate_surface(target):
    data = drift(copy.deepcopy(baseline({}, post=True)), target)
    with pytest.raises(RuntimeError):
        diagnostic._retained_inspect_gate(data, IMAGE, IMAGE_ID, USER, NETWORK_ID, True, ("no-new-privileges:true",))


def test_cleanup_success_reraises_the_exact_carrier_instance(monkeypatch):
    carrier = diagnostic.PostExitTmpfsObservation(expected_observation({}))
    monkeypatch.setattr(diagnostic, "PostExitTmpfsObservation", lambda _observation: carrier)
    scenario = Scenario(post_tmpfs={})
    with pytest.raises(type(carrier)) as caught:
        execute(monkeypatch, scenario)
    assert caught.value is carrier
    assert_cleanup(scenario)


def test_cleanup_failure_is_additive_but_not_eligible_evidence(monkeypatch):
    scenario = Scenario(post_tmpfs={"/private": "secret"}, retained=True)
    with pytest.raises(RuntimeError, match="post-exit block; cleanup also failed") as caught:
        execute(monkeypatch, scenario)
    assert type(caught.value) is RuntimeError
    assert isinstance(caught.value.__cause__, diagnostic.PostExitTmpfsObservation)
    assert "json_type" not in str(caught.value) and "/private" not in str(caught.value)
    assert_cleanup(scenario, failed=True)


def test_ordinary_cleanup_uses_one_retry_and_dual_absence_proof(monkeypatch):
    scenario = Scenario(post_tmpfs=MISSING, retry=True)
    with pytest.raises(diagnostic.PostExitTmpfsObservation):
        execute(monkeypatch, scenario)
    assert scenario.rm_attempts == 2
    assert_cleanup(scenario)


def test_emit_observation_writes_one_canonical_object_to_each_sink(tmp_path):
    error = diagnostic.PostExitTmpfsObservation(expected_observation(MISSING))
    logs = []; summary = tmp_path / "summary.md"
    diagnostic.emit_observation(error, summary, logs.append)
    encoded = json.dumps(dict(error.observation), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert logs == [encoded]
    assert summary.read_text(encoding="utf-8").count(encoded) == 1
    with pytest.raises(TypeError): diagnostic.emit_observation(RuntimeError("generic"), summary, logs.append)
    assert logs == [encoded] and summary.read_text(encoding="utf-8").count(encoded) == 1


def test_workflow_catches_only_carrier_then_blocks_the_later_native_step():
    workflow = (Path(__file__).resolve().parents[3] / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    start = workflow.index("      - name: Observe exact zero-mount preflight serialization")
    end = workflow.index("      - name: Run implemented package acquisition and endpointless boundary cases", start)
    block = workflow[start:end]
    assert block.count("except diagnostic.PostExitTmpfsObservation as blocked:") == 1
    assert block.count("diagnostic.emit_observation(blocked") == 1
    assert block.count("raise SystemExit(diagnostic.BLOCK_MESSAGE)") == 1
    assert "except Exception" not in block and "continue-on-error" not in block
    assert start < end
