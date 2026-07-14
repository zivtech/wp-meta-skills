"""Canonical bind, proxy source, and copy-boundary regression tests."""
import dataclasses, inspect, json, os, platform, subprocess, sys, threading, time
from pathlib import Path

import pytest

HARNESS=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HARNESS))
import artifact_staging
import materialize_wordpress_executor_packet as materializer
import runtime_image_provision
import sandboxed_package_runner as runner
import workspace_lease


def staged(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"input.txt").write_text("safe")
    return artifact_staging.stage_tree(source,tmp_path/"leases")


def request(tree,**changes):
    item=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(item,platform.machine())}"
    return dataclasses.replace(runner.SandboxRequest(tree,image,("node","-e","process.exit(0)")),**changes)


def docker_ready():
    if platform.system()!="Linux": return False
    try: return subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode==0
    except (FileNotFoundError,subprocess.TimeoutExpired): return False


def docker_request(tree,script,**changes):
    item=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(item,platform.machine())}"
    return dataclasses.replace(runner.SandboxRequest(tree,image,("node","-e",script)),**changes)


def approved_npm_tree(tmp_path):
    packet=HARNESS.parent/"suites/wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md"
    source=tmp_path/"approved-source"; result=materializer.materialize_packet("block",packet.read_text(),source)
    assert result["pass"]
    return artifact_staging.stage_tree(source,tmp_path/"approved-leases")


def assert_complete_resource_cleanup(result):
    evidence=json.loads(result.detail); latest={}
    for event in evidence.get("resource_events",[]): latest[(event["kind"],event["name"])]=event["state"]
    assert not {state for state in latest.values()}&{"attempted","created","attached","retained"},latest
    assert subprocess.run(["docker","inspect",result.container_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode!=0


def test_runtime_identity_binds_request_and_runner_resource_limits(tmp_path):
    tree=staged(tmp_path); req=request(tree,memory="1g",workspace_bytes=1200*1024**2)
    identity=runner.DetachedIdentity("1"*64,"started","network","daemon","2"*64,"sha256:"+"3"*64,"4"*64,"sha256:"+"5"*64)
    try:
        observed=runner._runtime_identity(identity,req); expected=1024**3+1200*1024**2+runner.PROXY_MEMORY_BYTES+runner.HOST_RESERVE_BYTES
        assert observed["package_memory_limit_bytes"]==1024**3 and observed["workspace_limit_bytes"]==1200*1024**2
        assert observed["proxy_memory_limit_bytes"]==runner.PROXY_MEMORY_BYTES and observed["host_reserve_bytes"]==runner.HOST_RESERVE_BYTES and observed["admission_required_bytes"]==expected
    finally: workspace_lease.cleanup(tree.lease)

def test_mount_comma_path_is_rejected(tmp_path):
    parent=tmp_path/"comma,parent"; parent.mkdir(); tree=staged(parent)
    try:
        with pytest.raises(ValueError,match="mount metacharacter"): runner._validate_request(request(tree))
    finally: workspace_lease.cleanup(tree.lease)

@pytest.mark.parametrize("value",[None,[],["no-new-privileges:true"],["no-new-privileges","seccomp=unconfined"]])
def test_package_and_proxy_require_the_exact_bare_no_new_privileges_serialization(value):
    assert runner._require_bare_no_new_privileges({"SecurityOpt":["no-new-privileges"]},"fixture") is None
    with pytest.raises(RuntimeError,match="fixture no-new-privileges serialization drift"):
        runner._require_bare_no_new_privileges({"SecurityOpt":value},"fixture")

def test_canonical_mount_source_fails_closed_after_lexical_swap(tmp_path):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True)
    moved=tree.lease.root/"moved"; tree.root.rename(moved); tree.root.symlink_to(Path.home(),target_is_directory=True)
    try:
        command=runner._create_command(request(tree),"container",capability)
        assert f"src={capability.source},dst=/input,readonly,bind-propagation=rprivate" in " ".join(command)
        assert capability.source==str(tree.root.absolute()) and "/proc/" not in capability.source
        assert os.fstat(capability.root_fd).st_ino==capability.inode
        with pytest.raises((OSError,ValueError,RuntimeError)): runner._reprove_artifact(capability)
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd)
        tree.root.unlink(); moved.rename(tree.root); workspace_lease.cleanup(tree.lease)

def test_artifact_barriers_and_proofs_are_in_exact_prestart_order(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True); events=[]
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",lambda *_args:None)
    monkeypatch.setattr(runner,"_reprove_artifact",lambda *_args:events.append("proof"))
    monkeypatch.setattr(runner,"_configured_mount_gate",lambda *_args:events.append("inspect"))
    def run(command,*_args,**_kwargs):
        events.append(command[1]); return {"returncode":0,"stdout":"a"*64 if command[1]=="create" else "","stderr":""}
    monkeypatch.setattr(runner,"_run",run)
    runner._TEST_BARRIERS.update({("artifact",stage):(lambda _path,stage=stage:events.append(stage)) for stage in ("pre_create","post_create_precheck","post_final_prestart")})
    try:
        runner._create_started_container(request(tree),"container",capability,None,runner.ResourceLedger(),"daemon")
        assert events==["proof","pre_create","create","post_create_precheck","proof","inspect","proof","post_final_prestart","start"]
    finally:
        runner._TEST_BARRIERS.clear(); os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_package_create_attempt_is_recorded_before_lost_response(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True); ledger=runner.ResourceLedger()
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",lambda *_args:None)
    monkeypatch.setattr(runner,"_reprove_artifact",lambda *_args:None); monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:(_ for _ in ()).throw(TimeoutError("lost create response")))
    try:
        with pytest.raises(TimeoutError): runner._create_started_container(request(tree),"package",capability,None,ledger,"daemon")
        assert [(item.kind,item.name,item.state) for item in ledger.events]==[("container","package","attempted")]
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_proxy_barriers_hold_python_until_sleep_mount_proofs_pass(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree); code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64); events=[]
    monkeypatch.setattr(runner.daemon_control,"run",lambda _ledger,command,timeout,control,deadline=None:control(command,timeout))
    context=runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1","python@sha256:"+"a"*64,code,8*1024**3,runner.ResourceLedger())
    monkeypatch.setattr(runner,"_reprove_proxy",lambda *_args:events.append("proof")); monkeypatch.setattr(runner,"_configured_proxy_mount_gate",lambda *_args:events.append("inspect"))
    monkeypatch.setattr(runner,"_live_proxy_source_gate",lambda *_args:events.append("live")); monkeypatch.setattr(runner,"_inspect_proxy",lambda *_args:events.append("topology")); monkeypatch.setattr(runner,"_wait_proxy",lambda *_args:events.append("ready"))
    monkeypatch.setattr(runner.proxy_supervisor,"launch",lambda *_args,**_kwargs:events.append("python") or type("Supervisor",(),{"lifecycle_deadline":time.monotonic()+30})())
    def control(command,*_args,**_kwargs):
        events.append(command[1] if command[1]!="network" else "connect"); return {"returncode":0,"stdout":"b"*64 if command[1]=="create" else "","stderr":""}
    monkeypatch.setattr(runner,"_control_run",control)
    runner._TEST_BARRIERS.update({("proxy",stage):(lambda _path,stage=stage:events.append(stage)) for stage in ("pre_create","post_create_precheck","post_final_prestart")})
    try:
        observed=runner._start_proxy(context,"package",req,runner.dependency_egress_proxy.ACQUISITION_PROFILES["block-scripts-32.4.1-smoke"])
        assert observed.supervisor is not None
        assert events==["proof","pre_create","create","post_create_precheck","proof","inspect","proof","post_final_prestart","start","live","proof","connect","topology","python","ready"]
    finally:
        runner._TEST_BARRIERS.clear(); workspace_lease.cleanup(tree.lease)

def test_copy_manifest_mismatch_fails_before_execute(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True)
    monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":0,"stdout":"tmpfs 524288 1 1 1% /workspace\ntmpfs 50000 1 1 1% /workspace\n","stderr":""})
    monkeypatch.setattr(runner,"_verify_copy",lambda *_args:artifact_staging.ArchiveVerification((),()))
    monkeypatch.setattr(runner,"_live_input_identity",lambda *_args:None); monkeypatch.setattr(runner,"_reprove_artifact",lambda *_args:None)
    try:
        with pytest.raises(RuntimeError,match="copy manifest or graph mismatch"): runner._prepare("container",request(tree),capability)
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

@pytest.mark.parametrize("code,label",[(41,"copy"),(42,"workspace-write"),(45,"block-quota"),(46,"inode-quota")])
def test_workspace_probe_reports_the_exact_bounded_failed_phase(tmp_path,monkeypatch,code,label):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True); commands=[]
    monkeypatch.setattr(runner,"_live_input_identity",lambda *_args:None)
    monkeypatch.setattr(runner,"_run",lambda command,*_args,**_kwargs:commands.append(command) or {"returncode":code,"stdout":"","stderr":"suppressed artifact detail"})
    try:
        with pytest.raises(RuntimeError,match=f"{label}.*{code}") as stopped: runner._prepare("container",request(tree),capability)
        assert "suppressed artifact detail" not in str(stopped.value)
        assert "/input/.wp-sandbox-readonly-probe" not in commands[0][-1] and "/.wp-sandbox-readonly-probe" not in commands[0][-1]
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_tainted_daemon_identity_retains_without_cleanup_retry(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree); name="wp-package-"+"1"*16; ledger=runner.ResourceLedger(); ledger.record("container",name,"created"); ledger.daemon_id="daemon"; ledger.identity_tainted=True; calls=[]
    monkeypatch.setattr(runner.provision,"run_capped",lambda *_args,**_kwargs:calls.append(True))
    try:
        result=runner._cleanup_package_result(runner._blocked(req,name,"failed"),name,ledger,time.monotonic())
        assert result.status=="blocked" and calls==[] and "retained" in result.detail
        assert ledger.events[-1]==runner.ResourceEvent("container",name,"retained")
    finally: workspace_lease.cleanup(tree.lease)

def test_cleanup_is_bracketed_by_the_authenticated_daemon(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree); name="wp-package-"+"2"*16; target="a"*64; ledger=runner.ResourceLedger(); ledger.record("container",name,"created"); ledger.bind(name,target); ledger.daemon_id="daemon"; events=[]
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",lambda *_args:events.append("daemon"))
    monkeypatch.setattr(runner.provision,"run_capped",lambda command,**_kwargs:events.append(command) or {"returncode":0,"stdout":"","stderr":""})
    try:
        result=runner._cleanup_package_result(runner._blocked(req,name,"failed"),name,ledger,time.monotonic())
        assert result.status=="blocked" and events==["daemon",["docker","rm","-f",target],"daemon"] and ledger.events[-1].state=="removed"
    finally: workspace_lease.cleanup(tree.lease)

@pytest.mark.parametrize("lost,drift_call",[(True,2),(False,3)])
def test_package_cleanup_retry_never_crosses_daemon_drift(tmp_path,monkeypatch,lost,drift_call):
    tree=staged(tmp_path); req=request(tree); name="wp-package-"+"3"*16; target="b"*64; ledger=runner.ResourceLedger(); ledger.record("container",name,"created"); ledger.bind(name,target); ledger.daemon_id="daemon"; checks=[]; removals=[]
    def require(_control,_daemon,_deadline,taint):
        checks.append(True)
        if len(checks)==drift_call: taint(); raise runner.sandbox_none_network.DaemonIdentityError("changed")
    def run(command,**_kwargs):
        removals.append(command)
        if lost: raise TimeoutError("lost response")
        return {"returncode":1,"stdout":"","stderr":""}
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",require); monkeypatch.setattr(runner.provision,"run_capped",run)
    try:
        result=runner._cleanup_package_result(runner._blocked(req,name,"failed"),name,ledger,time.monotonic())
        assert result.status=="blocked" and removals==[["docker","rm","-f",target]] and ledger.identity_tainted and ledger.events[-1].state=="retained"
        assert "original daemon" in result.detail
    finally: workspace_lease.cleanup(tree.lease)

def test_one_absolute_preparation_deadline_reaches_live_copy_and_proof(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True); deadline=time.monotonic()+30; observed=[]
    monkeypatch.setattr(runner,"_live_input_identity",lambda _name,_request,_capability,value=None:observed.append(("live",value)))
    monkeypatch.setattr(runner,"_reprove_artifact",lambda *_args:observed.append(("host-proof",None)))
    monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":0,"stdout":"tmpfs 524288 1 1 1% /workspace\ntmpfs 50000 1 1 1% /workspace\n","stderr":""})
    def verify(_name,_request,_exclude,value): observed.append(("container-proof",value)); return artifact_staging.ArchiveVerification(tree.manifest,capability.path_kinds)
    monkeypatch.setattr(runner,"_verify_copy",verify)
    try:
        runner._prepare("container",request(tree),capability,False,deadline)
        assert observed==[("live",deadline),("container-proof",deadline),("host-proof",None),("live",deadline)]
        assert 0<runner._remaining(time.monotonic()+1)<=1
        with pytest.raises(TimeoutError): runner.process_transport.dependency_root_gate("container",request(tree),runner._run,time.monotonic()-1)
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_daemon_arch_image_validation_precedes_create(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True); calls=[]
    bogus=dataclasses.replace(request(tree),image="node@sha256:"+"f"*64)
    monkeypatch.setattr(runner.sandbox_none_network,"admit",lambda *_args:("daemon","a"*64,"amd64"))
    monkeypatch.setattr(runner,"_run",lambda command,*_args,**_kwargs:calls.append(command) or {"returncode":0,"stdout":"amd64\n","stderr":""})
    try:
        with pytest.raises(ValueError,match="approved daemon-platform child"): runner._run_live(bogus,"container",capability)
        assert calls==[]
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_local_image_gate_requires_exact_repo_digest(monkeypatch):
    reference="node@sha256:"+"a"*64
    monkeypatch.setattr(runner.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":1,"stdout":"","stderr":"missing"})
    with pytest.raises(RuntimeError,match="not locally provisioned"): runner._assert_local_image(reference)
    payload=json.dumps("sha256:"+"b"*64)+" "+json.dumps(["node@sha256:"+"c"*64])
    monkeypatch.setattr(runner.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":0,"stdout":payload,"stderr":""})
    with pytest.raises(RuntimeError,match="digest evidence mismatch"): runner._assert_local_image(reference)
    source=inspect.getsource(runner._run_live)
    assert source.index("_assert_local_image(request.image,run_ledger)")<source.index("_create_acquisition_context")
    assert "package_target=_inspect_boundary" in source and "_execute(package_target,request)" in source
    proxy_source=inspect.getsource(runner._start_proxy)
    assert "proxy_target=_inspect_proxy" in proxy_source and "proxy_supervisor.launch(_proxy_target(context)" in proxy_source

def test_proxy_control_transport_is_fixed_32k_independent_of_request(monkeypatch):
    seen=[]; monkeypatch.setattr(runner.provision,"run_capped",lambda command,**kwargs:seen.append(kwargs) or {"returncode":0,"stdout":"","stderr":""})
    runner._control_run(["docker","inspect","proxy"],17)
    assert seen==[{"timeout":17,"limit":32768}]

def test_acquisition_argv_is_exact_and_source_fallback_tools_absent():
    npm=runner._acquisition_argv("npm","172.28.0.3"); composer=runner._acquisition_argv("composer","172.28.0.3")
    assert npm[-5:]==["npm","ci","--ignore-scripts","--no-audit","--no-fund"]
    assert composer[-7:]==["php","/usr/bin/composer","install","--no-scripts","--no-plugins","--no-interaction","--no-progress","--prefer-dist"][-7:]
    assert "git" not in composer and "ssh" not in composer
    assert "HTTPS_PROXY=http://172.28.0.3:8080" in npm and "NO_PROXY=" in npm
    assert not any("http://proxy" in item for item in npm)
    assert "npm_config_cache=/workspace/sandbox-cache/npm" in npm and "npm_config_maxsockets=8" in npm
    assert "COMPOSER_CACHE_DIR=/workspace/sandbox-cache/composer" in composer and "COMPOSER_MAX_PARALLEL_HTTP=4" in composer
    assert runner.dependency_egress_proxy.COMPOSER_HOSTS==frozenset({"api.github.com","codeload.github.com"})
    assert runner.COMPOSER_PARALLEL_HTTP*len(runner.dependency_egress_proxy.COMPOSER_HOSTS)==runner.dependency_egress_proxy.ProxyLimits().connections

def test_proxy_container_is_pinned_dual_network_orchestrator_without_artifact(tmp_path):
    item=runtime_image_provision.inventory()["images"]["python"]
    image=f"python@{item['amd64']}"; tree=staged(tmp_path); req=request(tree)
    code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64)
    context=runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1",image,code,8*1024**3,runner.ResourceLedger())
    command=runner._proxy_create_command(context,{"registry.npmjs.org"},req); joined=" ".join(command)
    assert image in command and "--network internal" in joined and "--network-alias" not in command
    assert "--pull=never" in command
    assert "--read-only" in command and "--cap-drop ALL" in joined and "--log-driver none" in joined
    assert f"src={code.source},dst=/proxy.py,readonly,bind-propagation=rprivate" in joined and "/proc/" not in joined and "/input" not in joined and "--env" not in command
    assert f"--memory-swap {runner.PROXY_MEMORY_BYTES}" in joined and "nofile=1024:1024" in joined and f"--user {req.user}" in joined
    workspace_lease.cleanup(tree.lease)

def test_acquisition_rejects_artifact_package_credentials(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/".npmrc").write_text("token=secret")
    (source/"package.json").write_text('{"dependencies":{}}'); (source/"package-lock.json").write_text('{"lockfileVersion":3,"packages":{"":{"dependencies":{}}}}')
    tree=artifact_staging.stage_tree(source,tmp_path/"leases"); req=dataclasses.replace(request(tree),acquisition="block-scripts-32.4.1-smoke"); capability=runner._validate_request(req,retain=True)
    try:
        with pytest.raises(ValueError,match="credential"): runner._validate_acquisition(req,capability)
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_acquisition_profiles_directly_bind_inventory_child_digests():
    inventory=runtime_image_provision.inventory()["images"]
    for profile in runner.dependency_egress_proxy.ACQUISITION_PROFILES.values():
        assert (profile.amd64_digest,profile.arm64_digest)==(inventory[profile.image_key]["amd64"],inventory[profile.image_key]["arm64"])

def test_non_linux_is_blocked_without_fallback(tmp_path,monkeypatch):
    tree=staged(tmp_path); calls=[]; monkeypatch.setattr(runner.platform,"system",lambda:"Darwin")
    monkeypatch.setattr(runner.provision,"run_capped",lambda command,**kwargs:calls.append(command) or {"returncode":0,"stdout":"","stderr":""})
    try:
        result=runner.run_sandbox(request(tree)); assert result.status=="blocked"
        assert calls==[]
    finally: workspace_lease.cleanup(tree.lease)

def test_root_host_is_rejected_before_any_docker_command(tmp_path,monkeypatch):
    tree=staged(tmp_path); calls=[]; original=runner.os.getuid
    monkeypatch.setattr(runner.os,"getuid",lambda:0)
    monkeypatch.setattr(runner.provision,"run_capped",lambda command,**kwargs:calls.append(command) or {"returncode":0,"stdout":"","stderr":""})
    try:
        result=runner.run_sandbox(request(tree)); assert result.status=="blocked" and "root host UID" in result.detail
        assert calls==[]
    finally:
        monkeypatch.setattr(runner.os,"getuid",original); workspace_lease.cleanup(tree.lease)

def test_proxy_interpreter_preflight_precedes_acquisition_context_and_mounts(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=dataclasses.replace(request(tree),acquisition="block-scripts-32.4.1-smoke"); capability=runner._validate_request(req,retain=True); events=[]
    profile=runner.dependency_egress_proxy.ACQUISITION_PROFILES[req.acquisition]
    monkeypatch.setattr(runner.sandbox_none_network,"admit",lambda *_args:("daemon","a"*64,"amd64"))
    monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":0,"stdout":"","stderr":""})
    monkeypatch.setattr(runner,"_validate_image",lambda *_args:None); monkeypatch.setattr(runner,"_assert_local_image",lambda *_args:"sha256:"+"1"*64)
    monkeypatch.setattr(runner.python_preflight,"run",lambda *_args:events.append("zero-mount-preflight"))
    monkeypatch.setattr(runner,"_create_acquisition_context",lambda *_args:events.append("acquisition-context") or (_ for _ in ()).throw(RuntimeError("stop")))
    try:
        with pytest.raises(runner.SandboxBoundaryError): runner._run_live(req,"wp-package-"+"1"*16,capability,profile,runner.ResourceLedger())
        assert events==["zero-mount-preflight","acquisition-context"]
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_output_export_is_uncompressed_streaming_tar():
    body=inspect.getsource(runner._import_output)
    command=runner._tar_command("container",True)
    assert command[:5]==["docker","exec","container","tar","-C"] and command[-3:]==["-cf","-","."]
    assert "--exclude=./node_modules" in command and "--exclude=./vendor" in command
    assert "--exclude=./sandbox-cache" in command and not any("--exclude=" in item for item in runner._tar_command("container",False))
    assert [item for item in command if item.startswith("--exclude=")]==["--exclude=./node_modules","--exclude=./vendor","--exclude=./sandbox-cache"]
    assert "process_transport.import_output" in body and "process_transport.verify_copy" in inspect.getsource(runner._verify_copy)
    assert "dependency_root_gate(name,request,run)" in inspect.getsource(runner.process_transport.import_output)
    assert "dependency_root_gate(name,request,run,deadline)" in inspect.getsource(runner.process_transport.verify_copy)
    assert 'dependency_policy="strict"' in inspect.getsource(runner.process_transport.import_output)
    assert "communicate(" not in body and "capture_output" not in body
    transport=inspect.getsource(runner.process_transport._tar_process)
    assert "threading.Timer" in transport and 'env={"PATH":"/usr/bin:/bin"}' in transport
    cleanup=inspect.getsource(runner.process_transport._cleanup_transport)
    assert "_cleanup_transport" in transport and "for index,thread in enumerate(threads)" in cleanup
    assert '"watchdog join"' in cleanup and "for index,stream in enumerate(streams)" in cleanup
    assert "process.wait()" not in body and "watchdog.join(1)" not in body
    assert "active_daemon.process" in inspect.getsource(runner._run_capped_process)
    assert 'env={"PATH":"/usr/bin:/bin"}' in inspect.getsource(runner.process_transport.run_capped_process)

def test_inspection_failure_is_fail_closed(tmp_path,monkeypatch):
    tree=staged(tmp_path); monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":1,"stdout":"","stderr":"inspect"})
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",lambda *_args:None)
    try:
        with pytest.raises(RuntimeError,match="inspection failed"): runner._inspect_boundary("container",request(tree),deadline=time.monotonic()+10,daemon_id="daemon",network_id="a"*64,ledger=runner.ResourceLedger())
    finally: workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("stage",["pre_create","post_create_precheck","post_final_prestart"])
def test_docker_artifact_canonical_source_swap_blocks_before_generated_execution(tmp_path,stage):
    tree=staged(tmp_path); req=docker_request(tree,"console.log('GENERATED_SENTINEL')"); invoked=[]
    def replace_source(path):
        invoked.append(stage); original=path.with_name("artifact-original"); path.rename(original); path.mkdir(mode=0o700); path.chmod(0o700)
        (path/"substituted.js").write_text("console.log('SUBSTITUTED_SENTINEL')"); (path/"substituted.js").chmod(0o600)
    runner._TEST_BARRIERS[("artifact",stage)]=replace_source
    try:
        result=runner.run_sandbox(req)
        assert result.status=="blocked" and invoked==[stage]
        assert "GENERATED_SENTINEL" not in result.stdout+result.stderr+result.detail and "SUBSTITUTED_SENTINEL" not in result.stdout+result.stderr+result.detail
        assert_complete_resource_cleanup(result)
    finally:
        runner._TEST_BARRIERS.clear(); workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("stage",["pre_create","post_create_precheck","post_final_prestart"])
def test_docker_proxy_canonical_source_swap_never_executes_substitute(tmp_path,stage):
    tree=approved_npm_tree(tmp_path); req=docker_request(tree,"console.log('GENERATED_SENTINEL')",acquisition="block-scripts-32.4.1-smoke",workspace_bytes=1200*1024**2,workspace_inodes=100000,timeout=900); invoked=[]
    def replace_source(path):
        invoked.append(stage); original=path.with_name("proxy-original.py"); path.rename(original)
        path.write_text("raise SystemExit('SUBSTITUTED_PROXY_SENTINEL')\n"); path.chmod(0o400)
    runner._TEST_BARRIERS[("proxy",stage)]=replace_source
    try:
        result=runner.run_sandbox(req)
        assert result.status=="blocked" and invoked==[stage]
        assert "GENERATED_SENTINEL" not in result.stdout+result.stderr+result.detail and "SUBSTITUTED_PROXY_SENTINEL" not in result.stdout+result.stderr+result.detail
        assert_complete_resource_cleanup(result)
    finally:
        runner._TEST_BARRIERS.clear(); workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_child_mutation_during_single_preparation_copy_blocks(tmp_path,monkeypatch):
    source=tmp_path/"copy-source"; source.mkdir(); (source/"large.bin").write_bytes(b"a"*(32*1024*1024)); tree=artifact_staging.stage_tree(source,tmp_path/"copy-leases")
    req=docker_request(tree,"console.log('GENERATED_SENTINEL')",workspace_bytes=128*1024*1024); original=runner._run; mutated=[]
    def intercept(command,request,timeout=None):
        if command[:2]==["docker","exec"] and command[-1].startswith("cp -R /input"):
            stop=threading.Event()
            def change():
                with (tree.root/"large.bin").open("r+b",buffering=0) as stream:
                    while not stop.is_set(): stream.seek(0); stream.write(b"b"); mutated.append(True)
            worker=threading.Thread(target=change,daemon=True); worker.start()
            try: return original(command,request,timeout)
            finally: stop.set(); worker.join(2)
        return original(command,request,timeout)
    monkeypatch.setattr(runner,"_run",intercept)
    try:
        result=runner.run_sandbox(req); assert mutated and result.status=="blocked"
        assert "GENERATED_SENTINEL" not in result.stdout+result.stderr+result.detail
        assert_complete_resource_cleanup(result)
    finally: workspace_lease.cleanup(tree.lease)
