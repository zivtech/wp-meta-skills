import json
import ipaddress
import os
import platform
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
import sandbox_network_policy as policy
import artifact_staging
import runtime_image_provision
import sandboxed_package_runner as runner
import step4_evidence
import workspace_lease


def inspected(name, spec, internal):
    return {
        "Id": "1" * 64,
        "Name": name,
        "Driver": "bridge",
        "Internal": internal,
        "EnableIPv6": False,
        "IPAM": {"Config": [{"Subnet": spec.subnet, "Gateway": spec.gateway}]},
        "Containers": {},
    }


def test_canonical_pools_prefix_and_slot_count_are_exact():
    assert policy.NETWORK_PREFIX == 29
    assert policy.SLOTS_PER_POOL == 524_288
    assert {key: str(value) for key, value in policy.POOLS.items()} == {
        "internal": "10.64.0.0/10",
        "egress": "10.128.0.0/10",
        "fixture": "10.192.0.0/10",
    }
    assert all(1 << (policy.NETWORK_PREFIX - pool.prefixlen) == 524_288 for pool in policy.POOLS.values())
    assert not policy.INTERNAL_POOL.overlaps(policy.EGRESS_POOL)
    assert not policy.INTERNAL_POOL.overlaps(policy.FIXTURE_POOL)
    assert not policy.EGRESS_POOL.overlaps(policy.FIXTURE_POOL)


def test_hardcoded_golden_vectors_bind_algorithm_for_every_role():
    assert policy.specification(policy.GOLDEN_IDENTITY, "internal") == policy.NetworkSpec(
        "10.76.161.240/29", "10.76.161.241", "10.76.161.242", "10.76.161.243",
    )
    assert policy.specification(policy.GOLDEN_IDENTITY, "egress") == policy.NetworkSpec(
        "10.184.154.104/29", "10.184.154.105", "10.184.154.106", "10.184.154.107",
    )
    assert policy.specification(policy.GOLDEN_IDENTITY, "fixture") == policy.NetworkSpec(
        "10.228.154.24/29", "10.228.154.25", "10.228.154.26", "10.228.154.27",
    )


def test_role_separated_specs_are_deterministic_and_collision_resistant():
    first = policy.specification(policy.GOLDEN_IDENTITY, "internal")
    assert first == policy.specification(policy.GOLDEN_IDENTITY, "internal")
    specs = {
        policy.specification(identity, pool) for pool, identities in {
            "internal": ("0123456789abcdef", "1111111111111111", "2222222222222222"),
            "egress": ("0123456789abcdef", "1111111111111111", "2222222222222222"),
            "fixture": ("0123456789ab", "111111111111", "222222222222"),
        }.items() for identity in identities
    }
    assert len(specs) == 9
    subnet = ipaddress.ip_network(first.subnet)
    assert tuple(map(ipaddress.ip_address, (first.gateway, first.package_ip, first.proxy_ip))) == (
        subnet.network_address + 1, subnet.network_address + 2, subnet.network_address + 3,
    )
    assert all(ipaddress.ip_network(spec.subnet).prefixlen == 29 for spec in specs)


def test_network_create_command_binds_explicit_ipam_and_isolation():
    spec = policy.specification(policy.GOLDEN_IDENTITY, "internal")
    command = policy.create_command("network", spec, internal=True, labels=("wp-meta-run=run-a",))
    assert command == [
        "docker", "network", "create", "--driver", "bridge",
        "--subnet", spec.subnet, "--gateway", spec.gateway,
        "--internal", "--label", "wp-meta-run=run-a", "network",
    ]
    egress = policy.create_command("egress", policy.specification(policy.GOLDEN_IDENTITY, "egress"), internal=False)
    assert egress == [
        "docker", "network", "create", "--driver", "bridge",
        "--subnet", "10.184.154.104/29", "--gateway", "10.184.154.105", "egress",
    ]


@pytest.mark.parametrize("mutation", ["name", "subnet", "gateway", "internal", "driver", "ipv6", "config"])
def test_live_inspection_rejects_ipam_or_isolation_drift(mutation):
    spec = policy.specification(policy.GOLDEN_IDENTITY, "internal")
    data = inspected("network", spec, True)
    if mutation == "name":
        data["Name"] = "other"
    elif mutation == "subnet":
        data["IPAM"]["Config"][0]["Subnet"] = policy.specification("fedcba9876543210", "internal").subnet
    elif mutation == "gateway":
        data["IPAM"]["Config"][0]["Gateway"] = policy.specification("fedcba9876543210", "internal").gateway
    elif mutation == "internal":
        data["Internal"] = False
    elif mutation == "driver":
        data["Driver"] = "overlay"
    elif mutation == "ipv6":
        data["EnableIPv6"] = True
    else:
        data["IPAM"]["Config"].append(dict(data["IPAM"]["Config"][0]))
    with pytest.raises(RuntimeError):
        policy.validate_inspection(data, "network", spec, internal=True)


def test_inspect_returns_only_reviewed_addresses():
    spec = policy.specification(policy.GOLDEN_IDENTITY, "egress")
    run = lambda command, timeout: {
        "returncode": 0,
        "stdout": json.dumps([inspected(command[-1], spec, False)]),
        "stderr": "",
    }
    snapshot = policy.inspect(run, "egress", spec, internal=False)
    assert snapshot.addresses == (
        spec.gateway, spec.package_ip, spec.proxy_ip,
    )
    assert snapshot.name == "egress" and snapshot.containers == frozenset()


def test_acquisition_names_bind_both_specs_to_one_token():
    internal, egress = policy.acquisition_specifications(
        "wp-acquire-internal-0123456789abcdef", "wp-acquire-egress-0123456789abcdef",
    )
    assert internal == policy.specification("0123456789abcdef", "internal")
    assert egress == policy.specification("0123456789abcdef", "egress")
    with pytest.raises(RuntimeError, match="token drift"):
        policy.acquisition_specifications(
            "wp-acquire-internal-0123456789abcdef", "wp-acquire-egress-fedcba9876543210",
        )


@pytest.mark.parametrize("identity,pool", [
    ("0123456789abcde", "internal"), ("0123456789abcdef0", "egress"),
    ("0123456789AB", "fixture"), ("wp-dns-observe-0123456789ab", "fixture"),
    ("../0123456789abcdef", "internal"),
])
def test_identity_is_locally_bounded_by_role(identity, pool):
    with pytest.raises(ValueError, match="bounded role"):
        policy.specification(identity, pool)


def test_bounded_docker_error_scrubs_descriptor_and_controls():
    result = {"stderr": "failed /proc/123/fd/9\n" + "x" * 4096}
    detail = policy.bounded_docker_error(result)
    assert detail.startswith("failed /proc/<pid>/fd/<fd> x")
    assert len(detail) == 2048 and "\n" not in detail


def test_controlled_connect_public_subnet_is_exact_and_outside_allocator():
    assert (step4_evidence.FAKE_PUBLIC_SUBNET, step4_evidence.FAKE_PUBLIC_GATEWAY, step4_evidence.FAKE_REGISTRY_IP) == (
        "93.184.216.32/28", "93.184.216.33", "93.184.216.34",
    )
    fake = ipaddress.ip_network("93.184.216.32/28")
    assert fake.is_global and all(not fake.overlaps(pool) for pool in policy.POOLS.values())


def fake_proxy_code():
    return SimpleNamespace(lease=SimpleNamespace(root=Path("/tmp/wp-network-policy-proxy-code")))


def context_mocks(monkeypatch, cleanup):
    monkeypatch.setattr(runner, "_memory_admission", lambda _request: 8 * 1024**3)
    monkeypatch.setattr(runner, "_stage_proxy_code", lambda *_args: fake_proxy_code())
    monkeypatch.setattr(runner, "_proxy_image", lambda _arch: "python@sha256:" + "a" * 64)
    monkeypatch.setattr(runner, "_cleanup_acquisition", cleanup)
    monkeypatch.setattr(runner.daemon_control, "run", lambda _ledger,command,timeout,control,deadline=None:control(command,timeout))


def test_internal_create_collision_is_deterministic_fail_closed(monkeypatch):
    calls = []; cleaned = []
    context_mocks(monkeypatch, lambda context, *_args, **_kwargs: cleaned.append(context))
    diagnostic = "Error response from daemon: Pool overlaps with other one on this address space\n"
    monkeypatch.setattr(runner, "_control_run", lambda command, *_args: calls.append(command) or {"returncode": 1, "stdout": "", "stderr": diagnostic})
    with pytest.raises(RuntimeError, match="internal network creation failed.*Pool overlaps"):
        runner._create_acquisition_context(object(), "amd64", run_token="ffffffffffffffff")
    assert len([command for command in calls if command[:3] == ["docker", "network", "create"]]) == 1
    assert len(cleaned) == 1


def test_egress_create_diagnostic_survives_cleanup_wrapper(monkeypatch):
    calls = []
    def cleanup(_context, *_args, **_kwargs):
        raise RuntimeError("cleanup retained exact run-owned network")
    context_mocks(monkeypatch, cleanup)
    internal = policy.specification("eeeeeeeeeeeeeeee", "internal")
    internal_name = "wp-acquire-internal-eeeeeeeeeeeeeeee"
    def control(command, *_args):
        calls.append(command)
        if command[:3] == ["docker", "network", "inspect"]:
            return {"returncode": 0, "stdout": json.dumps([inspected(internal_name, internal, True)]), "stderr": ""}
        if command[-1] == "wp-acquire-egress-eeeeeeeeeeeeeeee":
            return {"returncode": 1, "stdout": "", "stderr": "Error response from daemon:\tegress bridge allocation failed\n"}
        return {"returncode": 0, "stdout": "1" * 64, "stderr": ""}
    monkeypatch.setattr(runner, "_control_run", control)
    with pytest.raises(RuntimeError, match="egress network creation failed: Error response from daemon: egress bridge allocation failed.*cleanup also failed.*retained exact"):
        runner._create_acquisition_context(object(), "amd64", run_token="eeeeeeeeeeeeeeee")
    assert len([command for command in calls if command[:3] == ["docker", "network", "create"]]) == 2


def test_inspect_daemon_diagnostic_survives_sanitization_and_cleanup(monkeypatch):
    cleaned = []
    context_mocks(monkeypatch, lambda context, *_args, **_kwargs: cleaned.append(context))
    def control(command, *_args):
        if command[:3] == ["docker", "network", "inspect"]:
            return {"returncode": 1, "stdout": "", "stderr": "Error response from daemon:\nnetwork /proc/421/fd/7 not found\n"}
        return {"returncode": 0, "stdout": "1" * 64, "stderr": ""}
    monkeypatch.setattr(runner, "_control_run", control)
    with pytest.raises(RuntimeError, match=r"sandbox network inspection failed: Error response from daemon: network /proc/<pid>/fd/<fd> not found"):
        runner._create_acquisition_context(object(), "amd64", run_token="dddddddddddddddd")
    assert len(cleaned) == 1


def staged_request(tmp_path):
    source = tmp_path / "source"; source.mkdir(); (source / "input.txt").write_text("safe")
    tree = artifact_staging.stage_tree(source, tmp_path / "leases")
    item = runtime_image_provision.inventory()["images"]["node"]
    image = f"node@{runtime_image_provision.platform_digest(item, platform.machine())}"
    return tree, runner.SandboxRequest(tree, image, ("node", "-e", "process.exit(0)"), acquisition="block-scripts-32.4.1-smoke")


def test_ipam_diagnostic_reaches_final_sandbox_evidence(tmp_path, monkeypatch):
    tree, request = staged_request(tmp_path); cleaned = []
    profile = runner.dependency_egress_proxy.ACQUISITION_PROFILES[request.acquisition]
    monkeypatch.setattr(runner, "_validate_acquisition", lambda *_args: profile)
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    context_mocks(monkeypatch, lambda context, *_args, **_kwargs: cleaned.append(context))
    monkeypatch.setattr(runner, "_control_run", lambda *_args: {"returncode": 1, "stdout": "", "stderr": "Error response from daemon: Pool overlaps with exact CI subnet\n"})
    def live(req, _name, _capability, _profile, ledger):
        try:
            runner._create_acquisition_context(req, "amd64", ledger, "cccccccccccccccc")
        except Exception as exc:
            raise runner.SandboxBoundaryError(f"{type(exc).__name__}: {exc}", {}, {}, runner._resource_events(ledger)) from exc
    monkeypatch.setattr(runner, "_run_live", live)
    try:
        result = runner.run_sandbox(request); evidence = json.loads(result.detail)
        assert result.status == "blocked" and "Pool overlaps with exact CI subnet" in evidence["errors"][0]
        assert len(cleaned) == 1 and evidence["outcome"] == "blocked"
    finally:
        workspace_lease.cleanup(tree.lease)


def proxy_gate_fixture(tmp_path):
    token = "0123456789abcdef"; internal_spec = policy.specification(token, "internal")
    egress_spec = policy.specification(token, "egress"); path = tmp_path / "proxy.py"; path.write_text("safe")
    path.chmod(0o400); descriptor = os.open(path, os.O_RDONLY); opened = os.fstat(descriptor); digest = "a" * 64
    code = SimpleNamespace(file_fd=descriptor, source=str(path.absolute()), sha256=digest)
    request = SimpleNamespace(user="1001:1001", acquisition="block-scripts-32.4.1-smoke")
    context = runner.AcquisitionContext(f"wp-acquire-internal-{token}", f"wp-acquire-egress-{token}", "proxy", "nonce", internal_spec.package_ip, internal_spec.proxy_ip, internal_spec.gateway, "python@sha256:" + "b" * 64, code, 8 * 1024**3, runner.ResourceLedger())
    context.ledger.bind(context.internal, "4" * 64); context.ledger.bind(context.egress, "5" * 64)
    proxy_id = "2" * 64; package_id = "3" * 64
    temporary = "size=16777216,nr_inodes=1024,mode=0700,uid=1001,gid=1001,noexec,nosuid,nodev"
    host = {"ReadonlyRootfs": True, "CapDrop": ["ALL"], "PidsLimit": 64, "Memory": runner.PROXY_MEMORY_BYTES, "MemorySwap": runner.PROXY_MEMORY_BYTES, "NanoCpus": 1_000_000_000, "NetworkMode": context.ledger.target(context.internal), "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}, "CapAdd": None, "PidMode": "", "IpcMode": "", "UTSMode": "", "UsernsMode": "", "SecurityOpt": ["no-new-privileges"], "Privileged": False, "PortBindings": {}, "Binds": [], "Dns": [], "ExtraHosts": [], "Devices": [], "Ulimits": [{"Name": "nofile", "Hard": 1024, "Soft": 1024}], "LogConfig": {"Type": "none"}, "Tmpfs": {"/tmp": temporary}}
    proxy = {"Id": proxy_id, "Image": "sha256:" + "c" * 64, "HostConfig": host, "Config": {"User": request.user, "Entrypoint": ["sleep"], "Cmd": ["infinity"], "Env": list(runner.python_preflight.ENV)}, "Mounts": [{"Type": "bind", "Destination": "/proxy.py", "RW": False, "Propagation": "rprivate", "Source": code.source}], "NetworkSettings": {"Networks": {context.internal: {"IPAddress": context.proxy_ip}, context.egress: {"IPAddress": egress_spec.package_ip}}}}
    package = {"Id": package_id, "NetworkSettings": {"Networks": {context.internal: {"IPAddress": context.package_ip}}}}
    proof = f"{opened.st_dev}:{opened.st_ino}:400\n{digest}\n"
    return context, request, proxy, package, proof, internal_spec, egress_spec, descriptor


@pytest.mark.parametrize("drift", [False, True])
def test_proxy_gate_uses_one_snapshot_per_network_and_rejects_peer_drift(tmp_path, monkeypatch, drift):
    context, request, proxy, package, proof, internal_spec, egress_spec, descriptor = proxy_gate_fixture(tmp_path); calls = []
    def control(command, *_args):
        if command[:2] == ["docker", "inspect"]: return {"returncode": 0, "stdout": json.dumps([proxy, package]), "stderr": ""}
        if command[:3] == ["docker", "image", "inspect"]: return {"returncode": 0, "stdout": proxy["Image"] + "\n", "stderr": ""}
        if command[:2] == ["docker", "exec"]: return {"returncode": 0, "stdout": proof, "stderr": ""}
        raise AssertionError(command)
    def snapshot(_run, name, spec, *, internal, target=None):
        calls.append(name); peers = {proxy["Id"], package["Id"]} if internal else {proxy["Id"]}
        if drift and internal: peers.remove(package["Id"])
        return policy.NetworkSnapshot(name, ("4" if internal else "5") * 64, internal, spec, frozenset(peers))
    monkeypatch.setattr(runner, "_control_run", control); monkeypatch.setattr(runner.sandbox_network_policy, "inspect", snapshot)
    monkeypatch.setattr(runner.daemon_control, "run", lambda _ledger,command,timeout,control,deadline=None:control(command,timeout))
    try:
        if drift:
            with pytest.raises(RuntimeError, match="peer membership drift"): runner._inspect_proxy(context, "package", request)
        else: assert runner._inspect_proxy(context, "package", request)==proxy["Id"]
        assert calls == [context.internal, context.egress]
    finally: os.close(descriptor)
