import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
import sandbox_network_policy as network_policy
import sandbox_resource_identity as identity
import sandboxed_package_runner as runner


def test_container_discovery_requires_exact_run_and_role_labels():
    name = "wp-package-0123456789abcdef"; target = "a" * 64
    data = {"Id": target, "Name": f"/{name}", "Config": {"Labels": {"wp-meta-run": "0123456789abcdef", "wp-meta-role": "package"}}}
    ledger = runner.ResourceLedger(); run = lambda *_args: {"returncode": 0, "stdout": json.dumps([data]), "stderr": ""}
    assert identity.discover_container(run, name, "0123456789abcdef", "package", ledger)
    assert ledger.target(name) == target and ledger.created("container", name)
    wrong = runner.ResourceLedger(); data["Config"]["Labels"]["wp-meta-role"] = "proxy"
    assert not identity.discover_container(run, name, "0123456789abcdef", "package", wrong)
    assert not wrong.targets and not wrong.events


def test_network_discovery_requires_exact_policy_and_labels():
    run_id = "0123456789abcdef"; name = f"wp-acquire-internal-{run_id}"; spec = network_policy.specification(run_id, "internal")
    data = {"Id": "b" * 64, "Name": name, "Driver": "bridge", "Internal": True, "EnableIPv6": False, "IPAM": {"Config": [{"Subnet": spec.subnet, "Gateway": spec.gateway}]}, "Containers": {}, "Labels": {"wp-meta-run": run_id, "wp-meta-role": "internal"}}
    ledger = runner.ResourceLedger(); run = lambda *_args: {"returncode": 0, "stdout": json.dumps([data]), "stderr": ""}
    assert identity.discover_network(run, name, run_id, "internal", spec, True, ledger)
    assert ledger.target(name) == "b" * 64 and ledger.created("network", name)
    data["Labels"]["wp-meta-run"] = "f" * 16; wrong = runner.ResourceLedger()
    assert not identity.discover_network(run, name, run_id, "internal", spec, True, wrong)
    assert not wrong.targets and not wrong.events


def test_resource_target_cannot_be_rebound():
    ledger = runner.ResourceLedger(); ledger.bind("resource", "a" * 64)
    with pytest.raises(RuntimeError, match="cannot be rebound"): ledger.bind("resource", "b" * 64)
    assert ledger.target("resource") == "a" * 64


def test_acquisition_context_binds_and_inspects_exact_network_ids(monkeypatch):
    run_id = "0123456789abcdef"; internal = f"wp-acquire-internal-{run_id}"; egress = f"wp-acquire-egress-{run_id}"
    targets = {internal: "a" * 64, egress: "b" * 64}; commands = []
    code = SimpleNamespace(lease=SimpleNamespace(root=Path("/tmp/proxy-code")))
    monkeypatch.setattr(runner, "_memory_admission", lambda _request: 1); monkeypatch.setattr(runner, "_stage_proxy_code", lambda *_args: code); monkeypatch.setattr(runner, "_proxy_image", lambda _arch: "image")
    monkeypatch.setattr(runner.daemon_control, "run", lambda _ledger, command, timeout, control, deadline=None: control(command, timeout))
    def control(command, *_args):
        commands.append(command)
        if command[:3] == ["docker", "network", "create"]: return {"returncode": 0, "stdout": targets[command[-1]], "stderr": ""}
        target = command[-1]; name = internal if target == targets[internal] else egress; role = "internal" if name == internal else "egress"; spec = network_policy.specification(run_id, role)
        data = {"Id": target, "Name": name, "Driver": "bridge", "Internal": role == "internal", "EnableIPv6": False, "IPAM": {"Config": [{"Subnet": spec.subnet, "Gateway": spec.gateway}]}, "Containers": {}}
        return {"returncode": 0, "stdout": json.dumps([data]), "stderr": ""}
    monkeypatch.setattr(runner, "_control_run", control)
    context = runner._create_acquisition_context(SimpleNamespace(), "amd64", run_token=run_id)
    assert context.ledger.target(internal) == targets[internal] and context.ledger.target(egress) == targets[egress]
    assert [command[-1] for command in commands if command[:3] == ["docker", "network", "inspect"]] == [targets[internal], targets[egress]]


def request():
    staged = SimpleNamespace(root=Path("/tmp/input"))
    return SimpleNamespace(staged=staged, user="501:20", workspace_bytes=1024, workspace_inodes=100, pids=16, memory="64m", cpus="1", environment=(), image="node@sha256:" + "c" * 64, timeout=30)


def test_package_uses_created_id_immediately_for_inspect_and_start(monkeypatch):
    name = "wp-package-0123456789abcdef"; target = "d" * 64; ledger = runner.ResourceLedger(); commands = []; gates = []
    monkeypatch.setattr(runner.sandbox_none_network, "require_daemon", lambda *_args: None); monkeypatch.setattr(runner, "_reprove_artifact", lambda *_args: None)
    monkeypatch.setattr(runner, "_configured_mount_gate", lambda value, *_args: gates.append(value))
    monkeypatch.setattr(runner, "_run", lambda command, *_args, **_kwargs: commands.append(command) or {"returncode": 0, "stdout": target if command[1] == "create" else "", "stderr": ""})
    runner._create_started_container(request(), name, SimpleNamespace(source="/tmp/input"), None, ledger, "daemon")
    assert gates == [target] and ["docker", "start", target] in commands


def test_proxy_uses_bound_container_and_network_ids_immediately(monkeypatch):
    run_id = "0123456789abcdef"; proxy = f"wp-acquire-proxy-{run_id}"; ledger = runner.ResourceLedger(); commands = []
    ledger.bind("internal", "a" * 64); ledger.bind("egress", "b" * 64)
    code = SimpleNamespace(source="/tmp/proxy.py"); context = runner.AcquisitionContext("internal", "egress", proxy, "nonce", "10.0.0.2", "10.0.0.3", "10.0.0.1", "image", code, 1, ledger)
    profile = runner.dependency_egress_proxy.ACQUISITION_PROFILES["block-scripts-32.4.1-smoke"]
    monkeypatch.setattr(runner, "_reprove_proxy", lambda *_args: None); monkeypatch.setattr(runner, "_configured_proxy_mount_gate", lambda item: None); monkeypatch.setattr(runner, "_live_proxy_source_gate", lambda *_args: None)
    monkeypatch.setattr(runner, "_inspect_proxy", lambda *_args: "c" * 64); monkeypatch.setattr(runner, "_wait_proxy", lambda *_args: None)
    monkeypatch.setattr(runner.daemon_control, "run", lambda _ledger, command, timeout, control, deadline=None: control(command, timeout))
    monkeypatch.setattr(runner, "_control_run", lambda command, *_args: commands.append(command) or {"returncode": 0, "stdout": "c" * 64 if command[1] == "create" else "", "stderr": ""})
    monkeypatch.setattr(runner.proxy_supervisor, "launch", lambda *_args, **_kwargs: SimpleNamespace(lifecycle_deadline=time.monotonic() + 30))
    observed = runner._start_proxy(context, "package", SimpleNamespace(user="501:20", timeout=30), profile)
    assert observed.proxy_target == "c" * 64
    assert ["docker", "start", "c" * 64] in commands and ["docker", "network", "connect", "b" * 64, "c" * 64] in commands
    create = next(command for command in commands if command[1] == "create"); assert create[create.index("--network") + 1] == "a" * 64


def test_boundary_capability_probe_uses_exact_created_id(monkeypatch):
    req = request(); name = "wp-package-0123456789abcdef"; target = "d" * 64; network = "e" * 64; ledger = runner.ResourceLedger(); ledger.bind(name, target); ledger.bind("internal", network)
    context = SimpleNamespace(internal="internal", package_ip="10.0.0.2", ledger=ledger); capability = SimpleNamespace(source="/tmp/input", device=4, inode=5)
    work = "size=1024,nr_inodes=100,mode=0700,uid=501,gid=20,exec,nosuid,nodev"; temporary = "size=67108864,nr_inodes=4096,mode=0700,uid=501,gid=20,noexec,nosuid,nodev"
    host = {"NetworkMode": network, "ReadonlyRootfs": True, "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "", "UTSMode": "", "UsernsMode": "", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}, "PidsLimit": 16, "Memory": 64 * 1024**2, "MemorySwap": 64 * 1024**2, "NanoCpus": 1_000_000_000, "SecurityOpt": ["no-new-privileges"], "Binds": [], "Privileged": False, "Devices": [], "PortBindings": {}, "ExtraHosts": [], "Dns": ["127.0.0.1"], "DnsSearch": [], "Ulimits": [{"Name": "nofile", "Hard": 1024, "Soft": 1024}], "LogConfig": {"Type": "none"}, "Tmpfs": {"/workspace": work, "/tmp": temporary, "/home/sandbox": temporary, "/cache": temporary}}
    data = {"Id": target, "Image": "sha256:" + "f" * 64, "Config": {"User": req.user, "Entrypoint": ["sleep"], "Cmd": ["infinity"], "Env": []}, "HostConfig": host, "Mounts": [{"Type": "bind", "Destination": "/input", "RW": False, "Propagation": "rprivate", "Source": capability.source}], "NetworkSettings": {"Networks": {"internal": {"IPAddress": context.package_ip}}}}
    commands = []
    def run(command, *_args, **_kwargs):
        commands.append(command)
        if command[:2] == ["docker", "inspect"]: return {"returncode": 0, "stdout": json.dumps([data]), "stderr": ""}
        if command[:3] == ["docker", "image", "inspect"]: return {"returncode": 0, "stdout": data["Image"], "stderr": ""}
        return {"returncode": 0, "stdout": "4:5", "stderr": ""}
    monkeypatch.setattr(runner, "_run", run)
    assert runner._inspect_boundary(name, req, capability, context, ledger=ledger, target=target) == target
    assert ["docker", "exec", target, "stat", "-c", "%d:%i", "/input"] in commands


def test_nonzero_package_create_never_authorizes_cleanup(monkeypatch):
    name = "wp-package-0123456789abcdef"; ledger = runner.ResourceLedger(); calls = []
    monkeypatch.setattr(runner.sandbox_none_network, "require_daemon", lambda *_args: None); monkeypatch.setattr(runner, "_reprove_artifact", lambda *_args: None)
    monkeypatch.setattr(runner, "_run", lambda *_args, **_kwargs: {"returncode": 1, "stdout": "", "stderr": "collision"})
    with pytest.raises(RuntimeError, match="container creation failed"):
        runner._create_started_container(request(), name, SimpleNamespace(source="/tmp/input"), None, ledger, "daemon")
    monkeypatch.setattr(runner.provision, "run_capped", lambda command, **_kwargs: calls.append(command))
    runner._cleanup_package_result(runner._blocked(request(), name, "failed"), name, ledger, time.monotonic())
    assert calls == [] and not ledger.targets and not ledger.created("container", name)


def test_lost_package_create_recovers_only_exact_labeled_identity(monkeypatch):
    name = "wp-package-0123456789abcdef"; target = "e" * 64; ledger = runner.ResourceLedger()
    payload = [{"Id": target, "Name": f"/{name}", "Config": {"Labels": {"wp-meta-run": "0123456789abcdef", "wp-meta-role": "package"}}}]
    monkeypatch.setattr(runner.sandbox_none_network, "require_daemon", lambda *_args: None); monkeypatch.setattr(runner, "_reprove_artifact", lambda *_args: None)
    monkeypatch.setattr(runner, "_run", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("lost create response")))
    monkeypatch.setattr(runner.daemon_control, "run", lambda _ledger, command, _timeout, _control, _deadline=None: {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})
    with pytest.raises(TimeoutError, match="lost create response"):
        runner._create_started_container(request(), name, SimpleNamespace(source="/tmp/input"), None, ledger, "daemon")
    assert ledger.target(name) == target and ledger.created("container", name)


def test_unlabeled_lost_create_never_authorizes_name_cleanup(monkeypatch):
    name = "wp-package-0123456789abcdef"; ledger = runner.ResourceLedger(); removals = []
    payload = [{"Id": "f" * 64, "Name": f"/{name}", "Config": {"Labels": {}}}]
    monkeypatch.setattr(runner.sandbox_none_network, "require_daemon", lambda *_args: None); monkeypatch.setattr(runner, "_reprove_artifact", lambda *_args: None)
    monkeypatch.setattr(runner, "_run", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("lost create response")))
    monkeypatch.setattr(runner.daemon_control, "run", lambda _ledger, command, _timeout, _control, _deadline=None: {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})
    with pytest.raises(TimeoutError): runner._create_started_container(request(), name, SimpleNamespace(source="/tmp/input"), None, ledger, "daemon")
    monkeypatch.setattr(runner.provision, "run_capped", lambda command, **_kwargs: removals.append(command))
    runner._cleanup_package_result(runner._blocked(request(), name, "failed"), name, ledger, time.monotonic())
    assert removals == [] and not ledger.targets and not ledger.created("container", name)


def acquisition_context():
    ledger = runner.ResourceLedger(); names = {"proxy": "proxy", "package": "package", "internal": "internal", "egress": "egress"}
    targets = {name: character * 64 for (name, character) in zip(names.values(), "abcd")}
    for kind, name in (("container", "proxy"), ("container", "package"), ("network", "internal"), ("network", "egress")):
        ledger.record(kind, name, "created"); ledger.bind(name, targets[name])
    code = SimpleNamespace(lease=SimpleNamespace(root=Path("/tmp/proxy-code")))
    context = runner.AcquisitionContext("internal", "egress", "proxy", "nonce", "10.0.0.2", "10.0.0.3", "10.0.0.1", "image", code, 1, ledger)
    return context, targets


@pytest.mark.parametrize("operation", ["detach", "cleanup"])
def test_acquisition_detach_and_cleanup_use_only_bound_ids(monkeypatch, operation):
    context, targets = acquisition_context()
    commands = []; monkeypatch.setattr(runner, "_remove_retry", lambda command, *_args: commands.append(command)); monkeypatch.setattr(runner, "_release_proxy_code", lambda *_args: None)
    if operation == "cleanup": runner._cleanup_acquisition(context, "package", force=True)
    else: runner._detach_acquisition(context, "package", SimpleNamespace())
    forced = ["-f"] if operation == "cleanup" else []
    proxy = ["docker", "rm"] + forced + [targets["proxy"]]; disconnect = ["docker", "network", "disconnect"] + forced + [targets["internal"], targets["package"]]
    assert commands == [proxy, disconnect, ["docker", "network", "rm", targets["egress"]], ["docker", "network", "rm", targets["internal"]]]


@pytest.mark.parametrize("failed_network", ["egress", "internal"])
@pytest.mark.parametrize("retry_succeeds", [True, False])
def test_normal_detach_network_remove_failure_is_retried_or_retained(monkeypatch, failed_network, retry_succeeds):
    context, targets = acquisition_context(); phase = ["detach"]; commands = []
    def remove(command, *_args):
        commands.append(command)
        if command == ["docker", "network", "rm", targets[failed_network]] and (phase[0] == "detach" or not retry_succeeds): raise RuntimeError("network remove failed")
    monkeypatch.setattr(runner, "_remove_retry", remove); monkeypatch.setattr(runner, "_release_proxy_code", lambda *_args: None)
    with pytest.raises(RuntimeError, match="network remove failed"): runner._detach_acquisition(context, "package", SimpleNamespace())
    phase[0] = "cleanup"
    if retry_succeeds: runner._cleanup_acquisition(context, "package", force=True)
    else:
        with pytest.raises(RuntimeError) as stopped: runner._cleanup_acquisition(context, "package", force=True)
        assert targets[failed_network] in str(stopped.value)
    state = [event.state for event in context.ledger.events if event.kind == "network" and event.name == failed_network][-1]
    assert state == ("removed" if retry_succeeds else "retained")
