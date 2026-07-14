"""Hermetic contract tests for the sole staged WordPress runtime path."""
from __future__ import annotations

import inspect
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import artifact_staging
import isolated_runtime_contract as runtime_contract
import run_wordpress_runtime_smoke as smoke
import runtime_artifact_pipeline
import wp_env_network_guard as guard
import wp_runtime_provisioning
import wp_runtime_export
import wp_runtime_inspection
import wp_runtime_oracles
import wp_runtime_topology as topology
from wp_runtime_types import RuntimeRequest, RuntimeResult
from wp_runtime_evidence import RuntimeDeadline


def _synthesized(tmp_path, slug="safe-plugin", adversarial=False):
    source = tmp_path / "source"
    source.mkdir()
    fixture_root = HARNESS / "tests/fixtures"
    body = "<?php\n/** Plugin Name: Safe */\n"
    if adversarial:
        body = (fixture_root / "adversarial-runtime-plugin.php").read_text(encoding="utf-8")
    (source / "plugin.php").write_text(body, encoding="utf-8")
    if adversarial:
        generated_js = fixture_root / "adversarial-runtime-plugin.js"
        (source / "wp-runtime-adversarial.js").write_bytes(generated_js.read_bytes())
    staged = artifact_staging.stage_tree(source, tmp_path / "input-parent")
    synthesized = runtime_artifact_pipeline.synthesize_plugin_runtime(staged, slug, tmp_path / "runtime-parent")
    digest = artifact_staging.digest_manifest_tree(staged.manifest)
    return staged, synthesized, digest


def _cleanup(staged, synthesized):
    runtime_artifact_pipeline.cleanup_component("synthesized_runtime", synthesized.staged)
    artifact_staging.cleanup_staged_tree(staged)


def _request(synthesized, digest, parent):
    return RuntimeRequest(synthesized.staged, synthesized.plugin_slug, "evidence-123", digest, digest, 60, parent)


def test_facade_preserves_identity_manifest_and_cleanup(monkeypatch, tmp_path):
    staged, synthesized, digest = _synthesized(tmp_path)
    runtime = wp_runtime_provisioning.ProvisionedRuntime(
        {"wordpress": "sha256:" + "1" * 64, "database": "sha256:" + "2" * 64,
         "browser": "sha256:" + "3" * 64},
        {"wordpress": "33:33", "database": "999:999", "browser": "1000:1000"},
        ("a", "b", "c"), {"pins": True},
    )
    monkeypatch.setattr(guard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(guard.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(guard.wp_runtime_provisioning, "provision_runtime", lambda _work, _deadline: runtime)
    monkeypatch.setattr(guard.wp_runtime_provisioning, "cleanup_images",
                        lambda _runtime, _deadline: {"component": "runtime_images", "state": "removed", "error": None})
    runtime_export = SimpleNamespace(image="sha256:" + "4" * 64, digest="f" * 64)
    monkeypatch.setattr(guard.wp_runtime_export, "materialize_export",
                        lambda _held, _work, _slug, _runtime, _deadline, _project: runtime_export)
    monkeypatch.setattr(guard.wp_runtime_export, "seal_export",
                        lambda _export, _runtime, _deadline: {"state": "sealed"})
    monkeypatch.setattr(guard.wp_runtime_export, "release_export",
                        lambda _export, _runtime, _deadline: {
                            "component": "runtime_export", "state": "released", "error": None,
                        })
    monkeypatch.setattr(guard.wp_runtime_lifecycle, "execute_runtime",
                        lambda *_args: {"status": "pass", "reason": None,
                                       "checks": (
                                           {"id": "wp_cli_activation", "status": "pass"},
                                           {"id": "plugin_check", "status": "pass"},
                                           {"id": "container_browser", "status": "pass"},
                                       ),
                                       "inspection": {"live": True},
                                       "cleanup": {"component": "compose", "state": "removed"}})
    monkeypatch.setattr(guard.artifact_staging,"snapshot_held_tree",
                        lambda *_args: pytest.fail("runtime must not reload the held artifact"))
    try:
        result = guard.run_staged_runtime(_request(synthesized, digest, tmp_path / "result-parent"))
        assert result.status == "pass" and result.evidence_id == "evidence-123", result
        assert result.input_artifact_digest == digest
        assert result.post_command_manifest_digest == artifact_staging.manifest_sha256(synthesized.staged.manifest)
        assert result.cleanup["workspace"]["state"] == "removed"
    finally:
        _cleanup(staged, synthesized)


def test_facade_rejects_wrong_role_forgery_digest_slug_and_evidence(tmp_path):
    staged, synthesized, digest = _synthesized(tmp_path)
    request = _request(synthesized, digest, tmp_path / "result-parent")
    forged = artifact_staging.StagedTree(
        synthesized.staged.lease, synthesized.staged.root, synthesized.staged.manifest,
        artifact_staging.StageRole.SYNTHESIZED_RUNTIME,
    )
    cases = (
        replace(request, staged=staged), replace(request, staged=forged),
        replace(request, expected_input_artifact_digest="0" * 64),
        replace(request, plugin_slug="../escape"), replace(request, evidence_id=""),
    )
    try:
        for invalid in cases:
            with pytest.raises(ValueError):
                guard.run_staged_runtime(invalid)
    finally:
        _cleanup(staged, synthesized)


def test_missing_linux_or_docker_blocks_without_provisioning(monkeypatch, tmp_path):
    staged, synthesized, digest = _synthesized(tmp_path)
    calls = []
    monkeypatch.setattr(guard.wp_runtime_provisioning, "provision_runtime", lambda _work: calls.append(True))
    try:
        monkeypatch.setattr(guard.platform, "system", lambda: "Darwin")
        assert guard.run_staged_runtime(_request(synthesized, digest, tmp_path / "one")).status == "blocked"
        monkeypatch.setattr(guard.platform, "system", lambda: "Linux")
        monkeypatch.setattr(guard.shutil, "which", lambda _name: None)
        assert guard.run_staged_runtime(_request(synthesized, digest, tmp_path / "two")).status == "blocked"
        assert calls == []
    finally:
        _cleanup(staged, synthesized)


def test_topology_uses_exact_artifact_image_and_has_zero_mounts():
    images = {name: "sha256:" + str(index) * 64 for index, name in enumerate(("database", "wordpress", "browser"), 1)}
    identities = {"database": "999:999", "wordpress": "33:33", "browser": "1000:1000"}
    artifact_image="sha256:"+"4"*64
    spec = topology.build_compose(images, identities, artifact_image)
    assert topology.validate_compose(spec, artifact_image)
    assert all("volumes" not in service for service in spec["services"].values())
    assert spec["services"]["wordpress"]["image"]==artifact_image
    assert spec["services"]["cli"]["image"]==artifact_image
    assert all(service["logging"] == {"driver": "none"} for service in spec["services"].values())
    mutated = json.loads(json.dumps(spec))
    mutated["services"]["wordpress"]["ports"] = ["8080:8080"]
    with pytest.raises(ValueError, match="field"):
        topology.validate_compose(mutated, artifact_image)


def test_normalized_database_accepts_explicit_null_command_and_entrypoint():
    image="sha256:"+"1"*64; identity="999:999"
    spec=topology.build_compose(
        {"database":image,"wordpress":"sha256:"+"2"*64,"browser":"sha256:"+"3"*64},
        {"database":identity,"wordpress":"33:33","browser":"1000:1000"},
        "sha256:"+"4"*64,
    )
    expected=spec["services"]["database"]
    normalized={**expected,"command":None,"entrypoint":None,"mem_limit":"536870912",
                "memswap_limit":"536870912","cpus":0.5,"shm_size":"16777216",
                "networks":{"backend":None}}
    wp_runtime_inspection._normalized_service(
        "database",normalized,image,identity,expected,
    )


def test_runtime_export_tar_is_capability_derived_deterministic_and_bounded(tmp_path):
    staged, synthesized, _digest = _synthesized(tmp_path)
    try:
        with artifact_staging.hold_staged_tree(synthesized.staged) as held:
            one=io.BytesIO(); manifest=artifact_staging.write_held_tar(held,one)
        with artifact_staging.hold_staged_tree(synthesized.staged) as held:
            two=io.BytesIO(); artifact_staging.write_held_tar(held,two)
        assert one.getvalue()==two.getvalue()
        assert len(one.getvalue())<=artifact_staging.MAX_ARCHIVE_STREAM_BYTES
        with tarfile.open(fileobj=io.BytesIO(one.getvalue()),mode="r:") as archive:
            names=archive.getnames()
            assert f"{synthesized.plugin_slug}/plugin.php" in names
            assert archive.extractfile(f"{synthesized.plugin_slug}/plugin.php").read().startswith(b"<?php")
        assert manifest==synthesized.staged.manifest
    finally:
        _cleanup(staged, synthesized)


def test_artifact_image_handoff_never_starts_seed_and_cleans_seed(monkeypatch,tmp_path):
    staged,synthesized,_digest=_synthesized(tmp_path); calls=[]; removed=set()
    base="sha256:"+"1"*64; derived="sha256:"+"4"*64
    runtime=wp_runtime_provisioning.ProvisionedRuntime(
        {"wordpress":base,"database":"sha256:"+"2"*64,"browser":"sha256:"+"3"*64},
        {"wordpress":"33:33","database":"999:999","browser":"1000:1000"},(),{},
    )
    seed_id="5"*64
    config={"User":"www-data","Entrypoint":["/usr/local/bin/wp-sandbox-entrypoint"],
            "AttachStderr":False,"AttachStdout":False,"Hostname":"","Image":"","Labels":None}
    seed_config={**config,"AttachStderr":True,"AttachStdout":True,"Hostname":seed_id[:12],
                 "Image":base,"Labels":{}}
    seed_profile={"Id":seed_id,"Image":base,"State":{"Status":"created","Running":False},"Mounts":[],
        "HostConfig":{"NetworkMode":"none","CapDrop":["ALL"],"SecurityOpt":["no-new-privileges:true"],"ReadonlyRootfs":False},
        "Config":seed_config}
    def fake(command,_deadline,_cap=120,_limit=131072,allow_failure=False,stdin=None):
        calls.append(command)
        if command[1:3]==["image","inspect"]:
            image=command[-1]; return {"returncode":0,"stdout":json.dumps([{"Id":derived if image.endswith(derived[-12:]) or image.startswith("wp-isolated-artifact:") else base,"Config":config}]),"stderr":""}
        if command[1]=="inspect":
            if command[-1] in removed: return {"returncode":1,"stdout":"","stderr":"Error: No such object"}
            return {"returncode":0,"stdout":json.dumps([seed_profile]),"stderr":""}
        if command[1]=="commit": return {"returncode":0,"stdout":derived,"stderr":""}
        if command[1]=="rm": removed.add(command[-1])
        if command[1]=="cp":
            with tarfile.open(fileobj=stdin,mode="r:") as archive:
                assert f"{synthesized.plugin_slug}/plugin.php" in archive.getnames()
        return {"returncode":0,"stdout":"seed-id" if command[1]=="create" else "","stderr":""}
    monkeypatch.setattr(wp_runtime_export,"_run",fake)
    try:
        with artifact_staging.hold_staged_tree(synthesized.staged) as held:
            export=wp_runtime_export.materialize_export(
                held,tmp_path,synthesized.plugin_slug,runtime,RuntimeDeadline.start(300),"wpisolatedtest",
            )
        assert export.image==derived and export.evidence["seed_started"] is False
        assert not any(command[1] in {"start","run","exec"} for command in calls)
        create=next(command for command in calls if command[1]=="create")
        assert "none" in create and "ALL" in create and "no-new-privileges:true" in create
        assert "--read-only" not in create and "--label" not in create
        final=topology.build_compose(runtime.images,runtime.identities,derived)
        assert final["services"]["wordpress"]["read_only"] is True
        assert final["services"]["cli"]["read_only"] is True
    finally: _cleanup(staged,synthesized)


def test_artifact_cleanup_uses_bounded_formatted_absence_probes(monkeypatch):
    commands=[]
    def fake(command,*_args,**_kwargs):
        commands.append(command)
        is_inspect=command[1]=="inspect" or command[1:3]==["image","inspect"]
        if is_inspect and "--format" not in command:
            raise RuntimeError("full inspect overflow")
        kind = "image" if command[1:3] == ["image", "inspect"] else "container"
        detail = f"Error: No such {kind}" if is_inspect else ""
        return {"returncode":1 if is_inspect else 0,"stdout":"","stderr":detail}
    monkeypatch.setattr(wp_runtime_export,"_run",fake)
    deadline=RuntimeDeadline.start(60)
    assert wp_runtime_export._remove_seed("seed",deadline)
    assert wp_runtime_export._remove_image("image",deadline)
    assert commands[0][1:3]==["rm","-f"] and "--format" in commands[1]
    assert commands[2][1:4]==["image","rm","-f"] and "--format" in commands[3]


def test_artifact_image_config_drift_diagnostic_names_keys_not_values():
    base = {"User": "www-data", "Hostname": "", "Env": ["SECRET=value"]}
    derived = {"User": "www-data", "Hostname": "container-id", "Env": ["SECRET=changed"]}
    assert wp_runtime_export._config_drift_keys(base, derived) == ("Env", "Hostname")


def test_artifact_image_config_accepts_only_observed_passive_commit_serialization():
    image="sha256:"+"a"*64; seed_id="b"*64
    base={"AttachStderr":False,"AttachStdout":False,"Hostname":"","Image":"",
          "Labels":None,"User":"www-data","Env":["SAFE=value"]}
    seed={**base,"AttachStderr":True,"AttachStdout":True,"Hostname":seed_id[:12],
          "Image":image,"Labels":{}}
    derived={**seed}
    wp_runtime_export._validate_committed_config(base,seed,derived,seed_id,image)
    for key,value in (("Env",["SECRET=changed"]),("Labels",{"surprise":"true"}),
                      ("Hostname","unrelated"),("Image","sha256:"+"c"*64),
                      ("AttachStdout","true")):
        changed={**derived,key:value}
        with pytest.raises(RuntimeError,match="metadata drift field"):
            wp_runtime_export._validate_committed_config(base,seed,changed,seed_id,image)


def test_artifact_cleanup_reports_seed_and_image_failures(monkeypatch):
    monkeypatch.setattr(wp_runtime_export,"_remove_seed",lambda *_args:(_ for _ in ()).throw(RuntimeError("overflow")))
    monkeypatch.setattr(wp_runtime_export,"_remove_image",lambda *_args:False)
    errors=wp_runtime_export._cleanup_failed("seed","image",RuntimeDeadline.start(60))
    assert errors==["seed container cleanup RuntimeError","derived image retained"]
    failure=wp_runtime_export.RuntimeExportCleanupError(RuntimeError("primary"),errors,"seed","image")
    assert failure.cleanup["state"]=="retained"
    assert failure.cleanup["resources"]=={"seed_container":"seed","derived_image":"image"}


def test_artifact_cleanup_does_not_treat_daemon_failure_as_absence(monkeypatch):
    monkeypatch.setattr(wp_runtime_export, "_run", lambda command, *_args, **_kwargs: {
        "returncode": 1 if "inspect" in command else 0,
        "stdout": "", "stderr": "Cannot connect to the Docker daemon",
    })
    with pytest.raises(RuntimeError, match="absence could not be proved"):
        wp_runtime_export._remove_seed("seed", RuntimeDeadline.start(60))


def test_named_canary_cleanup_does_not_treat_daemon_failure_as_absence(monkeypatch):
    monkeypatch.setattr(wp_runtime_oracles, "_cleanup_raw", lambda command, *_args: {
        "returncode": 1 if "inspect" in command else 0,
        "stdout": "", "stderr": "Cannot connect to the Docker daemon",
    })
    with pytest.raises(RuntimeError, match="absence could not be proved"):
        wp_runtime_oracles._remove_named_canary("canary", RuntimeDeadline.start(60))


def test_named_canary_inspection_excludes_the_one_off_from_reference(monkeypatch):
    inspected = {"Id": "one-off", "HostConfig": {}, "Config": {}}
    reference = {
        "Id": "long-lived", "Image": "sha256:reference",
        "Config": {"User": "33:33"},
        "HostConfig": {"Tmpfs": {"/tmp": "size=1"}},
    }
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if command[:3] == ["docker", "inspect", "one-off"]:
            return {"returncode": 0, "stdout": json.dumps([inspected]), "stderr": ""}
        if command[-4:] == ["ps", "-q", "--all", "cli"]:
            return {"returncode": 0, "stdout": "one-off\nlong-lived\n", "stderr": ""}
        if command[:3] == ["docker", "inspect", "long-lived"]:
            return {"returncode": 0, "stdout": json.dumps([reference]), "stderr": ""}
        return {"returncode": 0, "stdout": "Seccomp:\t2\n", "stderr": ""}

    monkeypatch.setattr(wp_runtime_inspection, "_run", run)
    monkeypatch.setattr(wp_runtime_inspection, "_validate_live",
        lambda service, actual, image, identity, expected, running: {
            "service": service, "image": image, "identity": identity,
            "expected": expected, "running": running, "actual": actual["Id"],
        })
    evidence = wp_runtime_inspection.inspect_named_canary(
        ["docker", "compose"], "cli", "one-off", RuntimeDeadline.start(60),
    )
    assert evidence["profile_source"] == "long-lived"
    assert evidence["actual"] == "one-off" and evidence["image"] == "sha256:reference"
    assert ["docker", "inspect", "long-lived"] in calls


def _oracle_fake_run(command, commands, digest, canaries, denial_keys):
    commands.append(command)
    if "/opt/wp-runtime/browser-policy.js" in command:
        evidence = {
            "profile": runtime_contract.ADVERSARIAL_PROFILE, "canaries": canaries,
            "generated_denials": {
                context: {name: True for name in denial_keys}
                for context in ("frontend", "editor")
            },
            "generated_navigation_denials": [
                "/generated-navigation-editor", "/generated-navigation-frontend",
            ],
        }
        return {"returncode": 0, "stdout": json.dumps(evidence) + "\n", "stderr": ""}
    if any("RecursiveDirectoryIterator" in item for item in command):
        return {"returncode": 0, "stdout": digest + "\n", "stderr": ""}
    if any("wp_runtime_adversarial_route_canary" in item for item in command):
        return {"returncode": 0, "stdout": "generated-route-canary\n", "stderr": ""}
    if any("wp_runtime_adversarial_database" in item for item in command):
        evidence = {"created": True, "inserted": 4, "quota_inserts": 3,
                    "failed": True, "error": "disk full error 28", "recovered": True}
        return {"returncode": 0, "stdout": json.dumps(evidence) + "\n", "stderr": ""}
    if any("/proc/mounts" in item for item in command):
        return {"returncode": 0, "stdout": "tmpfs|rw,nosuid,nodev,noexec\n1\n1\n33:33:700\n33\n33\n", "stderr": ""}
    if command[:3] == ["docker", "network", "inspect"]:
        return {"returncode": 0, "stdout": '[{"Gateway":"172.30.0.1"}]\n', "stderr": ""}
    if command[:3] == ["docker", "inspect", "--format"]:
        stdout = "none|\n" if "LogConfig" in command[3] else (
            '{"project_application":{"Gateway":"172.30.0.1","IPAddress":"172.30.0.2"}}\n'
        )
        return {"returncode": 0, "stdout": stdout, "stderr": ""}
    if "ps" in command and "-q" in command:
        return {"returncode": 0, "stdout": "container-id\n", "stderr": ""}
    if any("wp_runtime_adversarial_php_canary" in item for item in command):
        return {"returncode": 0, "stdout": "generated-php-canary\n", "stderr": ""}
    if "/sys/fs/cgroup/cpu.max" in command:
        return {"returncode": 0, "stdout": "50000 100000\n", "stderr": ""}
    if command[:2] == ["docker", "wait"]:
        return {"returncode": 0, "stdout": "137\n", "stderr": ""}
    return {"returncode": 0, "stdout": "", "stderr": ""}


def test_named_runtime_oracle_bundle_covers_peer_and_resource_boundaries(monkeypatch):
    commands=[]; digest="a"*64
    canaries={name:True for name in {"same_origin","generated_frontend_js","generated_editor_js",
        "external_http","external_navigation","websocket","webrtc","service_worker","download","popup"}}
    denial_keys={"loopback","rfc1918","metadata","public_ip","public_dns","database_peer",
        "host_gateway","websocket","webrtc","service_worker","external_navigation","download","popup"}
    run = lambda command, _deadline, _cap: _oracle_fake_run(
        command, commands, digest, canaries, denial_keys,
    )
    monkeypatch.setattr(wp_runtime_oracles,"_run",run)
    monkeypatch.setattr(wp_runtime_oracles,"_expect_exit_code",
        lambda _command,_deadline,_cap,check_id,expected:{"id":check_id,"status":"pass",
            "required":True,"returncode":expected})
    monkeypatch.setattr(wp_runtime_oracles,"_expect_output_ceiling",
        lambda _command,_deadline,check_id,stream:{"id":check_id,"status":"pass",
            "required":True,"stream":stream})
    counters={}
    def counter(_base,service,filename,key,_deadline):
        name=(service,filename,key); counters[name]=counters.get(name,-1)+1; return counters[name]
    monkeypatch.setattr(wp_runtime_oracles,"_cgroup_counter",counter)
    monkeypatch.setattr(wp_runtime_oracles,"_oom_evidence",lambda *_args:"true 137 536870912 536870912")
    monkeypatch.setattr(wp_runtime_oracles.inspection,"inspect_named_canary",
        lambda *_args:{"profile":"exact"})
    monkeypatch.setattr(wp_runtime_oracles,"_remove_named_canary",lambda *_args:None)
    checks=wp_runtime_oracles.run_oracles(
        ["docker","compose","-p","test-project","-f","compose.json"],"safe-plugin",300,
                                           runtime_contract.ADVERSARIAL_REQUESTED_ORACLES,digest)
    ids={item["id"] for item in checks}
    expected=set(runtime_contract.REQUIRED_CHECKS_BY_PROFILE[runtime_contract.ADVERSARIAL_PROFILE])
    assert ids==expected and tuple(item["id"] for item in checks)==tuple(
        runtime_contract.REQUIRED_CHECKS_BY_PROFILE[runtime_contract.ADVERSARIAL_PROFILE]
    )
    assert any("wordpress" in command and "php" in command for command in commands)
    assert any(any("database" in item for item in command) for command in commands if "browser" in command)
    tmpfs_checks={item["id"]:item for item in checks if item["id"] in {
        "runtime_storage_ceiling","runtime_inode_ceiling",
    }}
    expected_paths={f"{service}:{path}" for service,path in wp_runtime_oracles.MUTABLE_PATHS}
    assert all(set(item["paths"])==expected_paths and item["recovery"]=="verified"
               for item in tmpfs_checks.values())
    assert "172.17.0.1" not in Path(wp_runtime_oracles.__file__).read_text(encoding="utf-8")


def test_one_off_output_is_inspected_before_generated_code(monkeypatch):
    events = []
    monkeypatch.setattr(wp_runtime_oracles, "_run",
        lambda *_args, **_kwargs: events.append("start") or {"returncode":0,"stdout":"id\n","stderr":""})
    monkeypatch.setattr(wp_runtime_oracles.inspection, "inspect_named_canary",
        lambda *_args: events.append("inspect") or {"profile":"exact"})
    monkeypatch.setattr(wp_runtime_oracles, "_expect_output_ceiling",
        lambda *_args: events.append("generated") or {"id":"output","status":"pass"})
    monkeypatch.setattr(wp_runtime_oracles, "_remove_named_canary",
        lambda *_args: events.append("cleanup"))
    result = wp_runtime_oracles._named_output_ceiling(
        ["docker","compose"], "cli", ["wp","eval","generated();"],
        RuntimeDeadline.start(60), "output", "stdout", "named-canary",
    )
    assert result["sandbox_profile"] == {"profile":"exact"}
    assert events == ["start", "inspect", "generated", "cleanup"]


def test_retained_synthesized_runtime_blocks_top_level_pass():
    receipt = runtime_artifact_pipeline.CleanupReceipt(
        "synthesized_runtime", "retained", True, True, "/recovery", None, "/resource",
    )
    result = smoke._attach_runtime_input_evidence(
        {"status":"pass", "pass":True, "_artifact_retention_receipts":[receipt]},
        None, None, None, None,
    )
    assert result["status"] == "blocked" and result["pass"] is False
    assert "synthesized_runtime remains retained" in result["artifact_execution_cleanup_error"]


def test_output_ceiling_does_not_pass_when_transport_cleanup_failed(monkeypatch):
    monkeypatch.setattr(wp_runtime_oracles,"_raw",
        lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError(
            "stdout output limit exceeded; cleanup also failed")))
    with pytest.raises(RuntimeError,match="cleanup"):
        wp_runtime_oracles._expect_output_ceiling(
            ["command"],RuntimeDeadline.start(60),"output","stdout",
        )


def test_oracle_failure_preserves_completed_checks():
    completed = {"id": "first", "status": "pass", "required": True}
    with pytest.raises(wp_runtime_oracles.OracleFailure) as raised:
        wp_runtime_oracles._run_steps((
            ("first", lambda: (completed,)),
            ("second", lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
        ))
    assert raised.value.step == "second"
    assert raised.value.checks == (completed,)


def test_database_canary_uses_bounded_raw_connection():
    source = Path(__file__).read_text(encoding="utf-8")
    assert "new mysqli(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)" in source
    assert "SET STATEMENT max_statement_time=5" in source
    assert "REPEAT('x', 8388608)" in source
    entrypoint = Path(HARNESS / "runtime-images/database/entrypoint.sh").read_text()
    assert "chmod 0700 /var/lib/mysql" in entrypoint


def test_inode_canary_catches_expected_enospc():
    script = wp_runtime_oracles._tmpfs_script("inodes")
    assert "touch $d/$i 2>/dev/null ||" in script
    assert ": > $d/$i" not in script


def test_php_output_canary_targets_process_stderr():
    source = Path(__file__).read_text(encoding="utf-8")
    assert "fwrite(STDERR, $payload)" in source


def test_plain_permalink_rest_canary_is_query_bounded():
    browser = Path(HARNESS / "runtime-images/browser/browser-policy.js").read_text()
    gateway = Path(HARNESS / "runtime-images/browser/gateway-policy.js").read_text()
    expected = "url.searchParams.size === 1"
    assert expected in browser and expected in gateway
    assert "rest_route" in browser and "rest_route" in gateway
    assert "/wp-json/wp-runtime-canary/v1/" not in browser + gateway


def test_daemon_log_stress_script_is_valid_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is unavailable")
    result = subprocess.run(
        [node, "-e", "new Function(process.argv[1])",
         wp_runtime_oracles._daemon_log_stress_script()],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_output_ceiling_requires_the_exact_named_stream(monkeypatch):
    monkeypatch.setattr(wp_runtime_oracles,"_raw",
        lambda *_args,**_kwargs:(_ for _ in ()).throw(RuntimeError("stdout output limit exceeded")))
    with pytest.raises(RuntimeError,match="stdout"):
        wp_runtime_oracles._expect_output_ceiling(
            ["command"],RuntimeDeadline.start(60),"stderr-check","stderr",
        )


def test_output_ceiling_reports_short_result(monkeypatch):
    monkeypatch.setattr(wp_runtime_oracles,"_raw",lambda *_args,**_kwargs:{
        "returncode":41,"stdout":"short","stderr":"HTTP canary failed",
    })
    with pytest.raises(RuntimeError,match="rc=41: HTTP canary failedshort"):
        wp_runtime_oracles._expect_output_ceiling(
            ["command"],RuntimeDeadline.start(60),"http","stdout",
        )


def test_memory_ceiling_requires_the_exact_oom_exit(monkeypatch):
    monkeypatch.setattr(wp_runtime_oracles,"_raw",
        lambda *_args,**_kwargs:{"returncode":1,"stdout":"","stderr":"failed for another reason"})
    with pytest.raises(RuntimeError,match="expected causal exit 137"):
        wp_runtime_oracles._expect_exit_code(
            ["command"],RuntimeDeadline.start(60),10,"memory",137,
        )


def test_standard_browser_profile_does_not_require_fixture_markers(monkeypatch):
    common={name:True for name in {"same_origin","external_http","external_navigation",
        "websocket","webrtc","service_worker","download","popup"}}
    monkeypatch.setattr(wp_runtime_oracles,"_run",lambda *_args:{"returncode":0,
        "stdout":json.dumps({"profile":runtime_contract.STANDARD_PROFILE,"canaries":common})+"\n",
        "stderr":""})
    checks=wp_runtime_oracles._browser_policy(
        ["docker","compose"],RuntimeDeadline.start(60),runtime_contract.STANDARD_PROFILE,
        "safe-plugin",
    )
    assert tuple(item["id"] for item in checks)==("container_browser",)
    assert "generated_frontend_js" not in checks[0]["canaries"]
    source=Path(HARNESS/"runtime-images/browser/browser-policy.js").read_text(encoding="utf-8")
    assert "gateway-frontend:8081" in source and "profile === 'adversarial-test'" in source


def test_provisioning_api_cannot_receive_an_artifact():
    parameters = tuple(inspect.signature(wp_runtime_provisioning.provision_runtime).parameters)
    assert parameters == ("work", "deadline")
    assert "artifact" not in parameters and "staged" not in parameters
    source = Path(wp_runtime_provisioning.__file__).read_text(encoding="utf-8")
    assert "npx" not in source and ":latest" not in source


def test_smoke_dispatch_never_reaches_legacy_host_runtime(monkeypatch, tmp_path):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.php").write_text("<?php\n/** Plugin Name: Isolated */\n", encoding="utf-8")
    digest = artifact_staging.digest_regular_tree(source)
    observed = []

    def isolated(request):
        observed.append(request)
        return RuntimeResult("pass", request.evidence_id, request.input_artifact_digest,
                             artifact_staging.manifest_sha256(request.staged.manifest),
                             ({"id": "wp_cli_activation", "status": "pass", "required": True, "duration_sec": 0.1},
                              {"id": "plugin_check", "status": "pass", "required": True, "duration_sec": 0.1},
                              {"id": "container_browser", "status": "pass", "required": True, "duration_sec": 0.1}))

    monkeypatch.setattr(smoke.wp_env_network_guard, "run_staged_runtime", isolated)
    monkeypatch.setattr(smoke, "run_command", lambda *_args, **_kwargs: pytest.fail("legacy host runtime called"))
    result = smoke.run_smoke(timeout_sec=60, workdir=tmp_path / "work", artifact_path=source,
                             expected_artifact_digest=digest, evidence_id="plan008-evidence")
    assert result["status"] == "pass" and result["sandbox_posture"]["host_fallback"] is False
    assert result["sandbox_posture"]["generated_execution"]["php"] == "pass"
    assert result["sandbox_posture"]["generated_execution"]["browser"] == "pass"
    assert len(observed) == 1 and observed[0].staged.role is artifact_staging.StageRole.SYNTHESIZED_RUNTIME


def test_nonpass_block_build_stops_before_runtime(monkeypatch, tmp_path):
    source = tmp_path / "block"
    source.mkdir()
    (source / "block.json").write_text(
        '{"name":"acme/card","title":"Card","category":"widgets"}', encoding="utf-8"
    )
    digest = artifact_staging.digest_regular_tree(source)
    failed = runtime_artifact_pipeline.BuildResult("fail", "build failed", ("npm", "run", "build"), None)
    monkeypatch.setattr(runtime_artifact_pipeline, "build_block", lambda *_args: failed)
    monkeypatch.setattr(
        smoke.wp_env_network_guard, "run_staged_runtime",
        lambda _request: pytest.fail("runtime must not start after a non-pass build"),
    )
    result = smoke.run_smoke(
        timeout_sec=60, workdir=tmp_path / "work", artifact_path=source,
        artifact_kind="block", block_build_smoke=True,
        expected_artifact_digest=digest, evidence_id="plan008-evidence",
    )
    assert result["status"] == "fail" and result["pass"] is False
    assert result["artifact_kind"] == "block" and result["block_build_smoke_status"] == "fail"


def test_requested_phpunit_gate_can_pass_with_isolated_runtime(monkeypatch, tmp_path):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.php").write_text("<?php\n/** Plugin Name: Isolated */\n", encoding="utf-8")
    digest = artifact_staging.digest_regular_tree(source)

    checks = (
        {"id": "wp_cli_activation", "status": "pass", "required": True, "duration_sec": 0.1},
        {"id": "plugin_check", "status": "pass", "required": True, "duration_sec": 0.1},
        {"id": "container_browser", "status": "pass", "required": True, "duration_sec": 0.1},
    )

    def isolated(request):
        return RuntimeResult(
            "pass", request.evidence_id, request.input_artifact_digest,
            artifact_staging.manifest_sha256(request.staged.manifest), checks,
        )

    monkeypatch.setattr(smoke.wp_env_network_guard, "run_staged_runtime", isolated)
    monkeypatch.setattr(
        smoke.validate_wordpress_artifact, "validate_staged_artifact",
        lambda *_args, **_kwargs: {
            "status": "pass", "pass": True,
            "checks": [{"id": "phpunit", "status": "pass", "required": True}],
            "_artifact_retention_receipts": [],
        },
    )
    result = smoke.run_smoke(
        timeout_sec=60, workdir=tmp_path / "work", artifact_path=source,
        phpunit_smoke=True, expected_artifact_digest=digest, evidence_id="plan008-evidence",
    )
    assert result["status"] == "pass" and result["phpunit_smoke_status"] == "pass"
    assert result["phpunit_gate"]["checks"][0]["id"] == "phpunit"
    assert result["sandbox_posture"]["generated_execution"]["phpunit"] == "pass"


def test_isolated_full_profile_combines_trusted_wpcs_and_plugin_check(monkeypatch, tmp_path):
    source = tmp_path / "plugin"; source.mkdir()
    (source / "plugin.php").write_text("<?php\n/** Plugin Name: Isolated */\n", encoding="utf-8")
    digest = artifact_staging.digest_regular_tree(source)
    checks = (
        {"id": "wp_cli_activation", "status": "pass", "required": True, "duration_sec": 0.1},
        {"id": "plugin_check", "status": "pass", "required": True, "duration_sec": 0.1},
        {"id": "container_browser", "status": "pass", "required": True, "duration_sec": 0.1},
    )
    def isolated(request):
        return RuntimeResult(
            "pass", request.evidence_id, request.input_artifact_digest,
            artifact_staging.manifest_sha256(request.staged.manifest), checks,
        )
    def validate(_kind, _staged, args, **_kwargs):
        assert args.require_tool == ["wpcs"]
        return {"status": "pass", "pass": True, "checks": [
            {"id": "phpcs_wpcs", "status": "pass", "required": True},
        ], "_artifact_retention_receipts": []}
    monkeypatch.setattr(smoke.wp_security_gate, "resolve_toolchain",
        lambda _root: (SimpleNamespace(), None))
    monkeypatch.setattr(smoke.validate_wordpress_artifact, "validate_staged_artifact", validate)
    monkeypatch.setattr(smoke.wp_env_network_guard, "run_staged_runtime", isolated)
    result = smoke.run_smoke(
        timeout_sec=60, workdir=tmp_path / "work", artifact_path=source,
        provision_full_profile=True, strict_full_profile=True,
        expected_artifact_digest=digest, evidence_id="plan008-evidence",
    )
    assert result["status"] == "pass"
    assert result["full_plugin_runtime_profile"]["status"] == "pass"
    assert [item["id"] for item in result["full_plugin_runtime_profile"]["checks"]] == [
        "phpcs_wpcs", "plugin_check", "wp_env_smoke",
    ]


def test_smoke_without_plan008_identity_blocks_without_host_fallback(monkeypatch, tmp_path):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.php").write_text("<?php\n/** Plugin Name: Isolated */\n", encoding="utf-8")
    monkeypatch.setattr(smoke, "run_command", lambda *_args, **_kwargs: pytest.fail("legacy host runtime called"))
    result = smoke.run_smoke(timeout_sec=60, workdir=tmp_path / "work", artifact_path=source)
    assert result["status"] == "blocked" and result["sandbox_posture"]["host_fallback"] is False


def test_smoke_blocks_a_malformed_runtime_result(monkeypatch, tmp_path):
    source = tmp_path / "plugin"
    source.mkdir()
    (source / "plugin.php").write_text("<?php\n/** Plugin Name: Isolated */\n", encoding="utf-8")
    digest = artifact_staging.digest_regular_tree(source)
    monkeypatch.setattr(smoke.wp_env_network_guard, "run_staged_runtime", lambda _request: {})
    result = smoke.run_smoke(
        timeout_sec=60, workdir=tmp_path / "work", artifact_path=source,
        expected_artifact_digest=digest, evidence_id="plan008-evidence",
    )
    assert result["status"] == "blocked" and result["pass"] is False
    assert "invalid result" in result["reason"]


@pytest.fixture(scope="module")
def live_runtime_result(tmp_path_factory):
    if platform.system() != "Linux" or shutil.which("docker") is None:
        pytest.skip("real staged runtime requires Linux Docker")
    tmp_path=tmp_path_factory.mktemp("isolated-runtime")
    staged, synthesized, digest = _synthesized(tmp_path,adversarial=True)
    try:
        request=replace(_request(synthesized,digest,tmp_path/"live-result"),timeout_sec=1800,
            requested_oracles=runtime_contract.ADVERSARIAL_REQUESTED_ORACLES)
        yield guard.run_staged_runtime(request)
    finally:
        _cleanup(staged, synthesized)


@pytest.mark.docker_boundary
def test_real_generated_plugin_uses_internal_runtime(live_runtime_result):
    assert live_runtime_result.status == "pass", live_runtime_result.reason


@pytest.mark.docker_boundary
def test_real_runtime_exercises_named_hostile_canaries(live_runtime_result):
    expected=set(runtime_contract.REQUIRED_CHECKS_BY_PROFILE[runtime_contract.ADVERSARIAL_PROFILE])
    checks={item["id"]:item["status"] for item in live_runtime_result.checks}
    assert expected<=set(checks) and all(checks[name]=="pass" for name in expected)


@pytest.mark.docker_boundary
def test_real_runtime_is_mount_free_and_cleanup_converges(live_runtime_result):
    created=live_runtime_result.inspection["created"]["services"]
    assert all(not service["mounts"] for service in created.values())
    assert all(item["state"] not in {"retained","unknown"} for item in live_runtime_result.cleanup.values())
