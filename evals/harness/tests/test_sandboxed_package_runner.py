import dataclasses, inspect, io, ipaddress, json, os, platform, re, select, shutil, signal, socket, stat, subprocess, sys, threading, time
from pathlib import Path
import pytest
TESTS=Path(__file__).resolve().parent; HARNESS=TESTS.parent; sys.path.insert(0,str(TESTS)); sys.path.insert(0,str(HARNESS))
import artifact_staging, live_fixture_support, materialize_wordpress_executor_packet as materializer, runtime_image_provision, sandbox_native_poll as native_poll, sandboxed_package_runner as runner, step4_evidence, workspace_lease
def staged(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"input.txt").write_text("safe")
    return artifact_staging.stage_tree(source,tmp_path/"leases")
def request(tree,**changes):
    item=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(item,platform.machine())}"
    base=runner.SandboxRequest(tree,image,("node","-e","process.exit(0)"))
    return dataclasses.replace(base,**changes)
def bypass_daemon(monkeypatch):
    monkeypatch.setattr(runner.daemon_control,"run",lambda _ledger,command,timeout,control,deadline=None:control(command,timeout))
def test_request_and_result_are_frozen(tmp_path):
    tree=staged(tmp_path)
    try:
        with pytest.raises(dataclasses.FrozenInstanceError): request(tree).timeout=1
        assert runner.SandboxResult("blocked",None,"","",None,"x","n").status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)

def test_create_policy_has_one_readonly_bind_and_bounded_mounts(tmp_path):
    tree=staged(tmp_path)
    try:
        command=runner._create_command(request(tree),"unique")
        joined=" ".join(command)
        assert command.count("--mount")==1 and "dst=/input,readonly" in joined
        assert "--network none" in joined and "--read-only" in command and "--pull=never" in command
        assert "--cap-drop ALL" in joined and "no-new-privileges" in joined
        assert "/workspace:size=" in joined and "exec,nosuid,nodev" in joined
        assert joined.count("noexec,nosuid,nodev")==3
        assert "docker.sock" not in joined and "shell=True" not in joined
    finally: workspace_lease.cleanup(tree.lease)

def test_generated_execution_is_direct_argv_not_shell(tmp_path,monkeypatch):
    tree=staged(tmp_path); seen=[]
    monkeypatch.setattr(runner,"_run_capped_process",lambda command,*_args,**_kwargs:seen.append(command) or {"returncode":0,"stdout":"","stderr":""})
    try:
        runner._execute("container",request(tree,argv=("node","-e","console.log('x')")))
        assert seen[0][-3:]==["node","-e","console.log('x')"]
        marker=seen[0].index("--"); assert seen[0][marker:marker+5]==["--","container","/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin"]
        assert "sh" not in seen[0] and "-c" not in seen[0]
    finally: workspace_lease.cleanup(tree.lease)

def test_unpinned_root_and_empty_requests_block(tmp_path,monkeypatch):
    tree=staged(tmp_path); monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    try:
        assert runner.run_sandbox(request(tree,image="node:22")).status=="blocked"
        assert runner.run_sandbox(request(tree,argv=())).status=="blocked"
        assert runner.run_sandbox(request(tree,user="0:0")).status=="blocked"
        assert runner.run_sandbox(request(tree,user="1:")).status=="blocked"
        assert runner.run_sandbox(request(tree,pids=0)).status=="blocked"
        assert runner.run_sandbox(request(tree,cpus="inf")).status=="blocked"
        assert runner.run_sandbox(request(tree,workspace_bytes=runner.MAX_WORKSPACE_BYTES+1)).status=="blocked"
        assert runner.run_sandbox(request(tree,environment=(("HTTP_PROXY","http://proxy"),))).status=="blocked"
        assert runner.run_sandbox(request(tree,environment=(("HOME","/home/sandbox\x00evil"),))).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)

def test_stale_or_forged_staged_tree_is_rejected(tmp_path):
    tree=staged(tmp_path)
    try:
        (tree.root/"input.txt").write_text("changed")
        with pytest.raises(ValueError,match="manifest is stale"): runner._validate_request(request(tree))
        forged=dataclasses.replace(tree,lease=dataclasses.replace(tree.lease,lease_id="forged"))
        with pytest.raises(ValueError,match="live and authentic"): runner._validate_request(request(forged))
        escaped=dataclasses.replace(tree,root=Path.home())
        with pytest.raises(ValueError,match="outside its live lease"): runner._validate_request(request(escaped))
    finally: workspace_lease.cleanup(tree.lease)

def test_asymmetric_stdout_stderr_caps_and_timeout(tmp_path):
    tree=staged(tmp_path)
    try:
        with pytest.raises(RuntimeError,match="stdout"):
            runner._run_capped_process(["/bin/sh","-c","printf 123456789"],request(tree,stdout_limit=5,stderr_limit=100))
        with pytest.raises(RuntimeError,match="stderr"):
            runner._run_capped_process(["/bin/sh","-c","printf 123456789 >&2"],request(tree,stdout_limit=100,stderr_limit=5))
        with pytest.raises((TimeoutError,RuntimeError)):
            runner._run_capped_process(["/bin/sh","-c","sleep 2"],request(tree,timeout=0.05))
        with pytest.raises(TimeoutError,match="reap"):
            runner._run_capped_process(["/bin/sh","-c","exec >/dev/null 2>/dev/null; sleep 2"],request(tree,timeout=0.05))
    finally: workspace_lease.cleanup(tree.lease)

def test_killed_process_surviving_reap_deadline_is_rejected(monkeypatch):
    class Process:
        pid=999999
        def poll(self): return None
        def kill(self): pass
        def wait(self,timeout): raise subprocess.TimeoutExpired("fake",timeout)
    def killpg(_pid,signal_number):
        if signal_number==0: raise ProcessLookupError("gone")
        raise OSError("kill failed")
    monkeypatch.setattr(runner.os,"killpg",killpg)
    with pytest.raises(RuntimeError,match="survived reap deadline"): runner._terminate_process(Process(),time.monotonic()+0.01)

def test_expired_absolute_reap_deadline_never_grants_hidden_milliseconds(monkeypatch):
    waits=[]
    class Process:
        pid=999999
        def poll(self): return None
        def kill(self): pass
        def wait(self,timeout): waits.append(timeout); raise AssertionError("expired deadline must not wait")
    monkeypatch.setattr(runner.os,"killpg",lambda *_args:None)
    with pytest.raises(RuntimeError,match="survived reap deadline"): runner._terminate_process(Process(),time.monotonic()-1)
    assert waits==[]

def test_expired_process_deadline_blocks_before_launch(monkeypatch,tmp_path):
    tree=staged(tmp_path); launches=[]
    monkeypatch.setattr(runner.process_transport.subprocess,"Popen",lambda *_args,**_kwargs:launches.append(1))
    try:
        with pytest.raises(TimeoutError,match="no positive execution budget"):
            runner._run_capped_process(["ignored"],request(tree),deadline=time.monotonic()-1)
        assert launches==[]
    finally: workspace_lease.cleanup(tree.lease)

def test_cleanup_failure_blocks_prior_failure_status(tmp_path,monkeypatch):
    tree=staged(tmp_path); monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    def live(_request,name,_capability,_profile,ledger):
        ledger.record("container",name,"created"); return runner.SandboxResult("fail",9,"","",None,"generated failed",name)
    monkeypatch.setattr(runner,"_run_live",live)
    monkeypatch.setattr(runner.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":1,"stdout":"","stderr":"cleanup"})
    try:
        result=runner.run_sandbox(request(tree)); evidence=json.loads(result.detail)
        assert result.status=="blocked" and evidence["prior_outcome"]=="unknown"
        assert len(evidence["errors"])==2 and {"cleanup","end_to_end"}<=set(evidence["timings_seconds"])
        assert {item["state"] for item in evidence["resource_events"]}>={"created","retained"}
    finally: workspace_lease.cleanup(tree.lease)

def test_cleanup_exception_closes_successful_output_lease(tmp_path,monkeypatch):
    tree=staged(tmp_path); output_parent=tmp_path/"output-parent"; output_parent.mkdir(); output=staged(output_parent); monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    bypass_daemon(monkeypatch)
    def live(_request,name,_capability,_profile,ledger):
        ledger.record("container",name,"created"); return runner.SandboxResult("pass",0,"","",output,"passed",name)
    monkeypatch.setattr(runner,"_run_live",live)
    calls=[]
    def cleanup(*_args,**_kwargs):
        calls.append(1)
        if len(calls)==1: raise RuntimeError("cleanup exploded")
        return {"returncode":0,"stdout":"","stderr":""}
    monkeypatch.setattr(runner.provision,"run_capped",cleanup)
    try:
        assert runner.run_sandbox(request(tree)).status=="blocked"
        assert not output.lease.root.exists() and len(calls)==2
    finally: workspace_lease.cleanup(tree.lease)

def test_staged_descriptors_remain_open_through_container_removal(tmp_path,monkeypatch):
    tree=staged(tmp_path); held={}; original_validate=runner._validate_request
    bypass_daemon(monkeypatch)
    monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    def validate(req,retain=False):
        capability=original_validate(req,retain); held["capability"]=capability; return capability
    def live(_request,name,capability,_profile,ledger):
        os.fstat(capability.root_fd); os.fstat(capability.lease_fd); ledger.record("container",name,"created")
        return runner.SandboxResult("fail",9,"","",None,"generated failed",name)
    def cleanup(*_args,**_kwargs):
        capability=held["capability"]; os.fstat(capability.root_fd); os.fstat(capability.lease_fd)
        return {"returncode":0,"stdout":"","stderr":""}
    monkeypatch.setattr(runner,"_validate_request",validate); monkeypatch.setattr(runner,"_run_live",live); monkeypatch.setattr(runner.provision,"run_capped",cleanup)
    try:
        assert runner.run_sandbox(request(tree)).status=="fail"
        with pytest.raises(OSError): os.fstat(held["capability"].root_fd)
        with pytest.raises(OSError): os.fstat(held["capability"].lease_fd)
    finally: workspace_lease.cleanup(tree.lease)

def test_run_sandbox_emits_one_authoritative_nonresurrecting_resource_history(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=dataclasses.replace(request(tree),acquisition="block-scripts-32.4.1-smoke")
    profile=runner.dependency_egress_proxy.ACQUISITION_PROFILES[req.acquisition]
    bypass_daemon(monkeypatch)
    monkeypatch.setattr(runner,"_validate_acquisition",lambda *_args:profile); monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    monkeypatch.setattr(runner.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":0,"stdout":"","stderr":""})
    def live(_request,name,_capability,_profile,ledger):
        token=name.removeprefix("wp-package-"); proxy=f"wp-acquire-proxy-{token}"; internal=f"wp-acquire-internal-{token}"; egress=f"wp-acquire-egress-{token}"; lease=f"/tmp/wp-meta-skills-artifact-execution-{token}"
        for kind,resource,state in (("lease",lease,"created"),("network",internal,"created"),("network",egress,"created"),("container",name,"created"),("network",internal,"attached"),("container",proxy,"created"),("network",internal,"attached"),("network",egress,"attached"),("container",proxy,"removed"),("container",name,"detached"),("network",egress,"detached"),("network",internal,"detached"),("network",egress,"removed"),("network",internal,"removed"),("lease",lease,"removed")): ledger.record(kind,resource,state)
        return runner.SandboxResult("pass",0,"","",None,runner.sandbox_evidence.encode("pass"),name)
    monkeypatch.setattr(runner,"_run_live",live)
    try:
        result=runner.run_sandbox(req); events=json.loads(result.detail)["resource_events"]; package=[item["state"] for item in events if item["name"]==result.container_name]
        assert result.status=="pass" and package==["created","detached","removed"]
        assert sum(item["state"]=="created" and item["name"]==result.container_name for item in events)==1
    finally: workspace_lease.cleanup(tree.lease)
@pytest.mark.parametrize("kind",["symlink","special"])
def test_dependency_root_type_gate_rejects_non_directory(kind,tmp_path,monkeypatch):
    tree=staged(tmp_path)
    monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":41,"stdout":"","stderr":kind})
    try:
        with pytest.raises(RuntimeError,match="symlink or special"): runner._dependency_root_gate("container",request(tree))
    finally: workspace_lease.cleanup(tree.lease)

def fake_context(tree):
    code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64)
    return runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1","python@sha256:"+"a"*64,code,8*1024**3,runner.ResourceLedger())

def test_acquisition_package_is_created_directly_internal_with_dns_denial(tmp_path):
    tree=staged(tmp_path); context=fake_context(tree)
    try:
        command=runner._create_command(request(tree),"package",None,context.internal,context.package_ip); joined=" ".join(command)
        assert "--network internal" in joined and "--ip 172.28.0.2" in joined and "--dns 127.0.0.1" in joined
        source=inspect.getsource(runner._run_live)+inspect.getsource(runner._acquire)
        assert '["docker","network","connect",context.internal,name]' not in source
    finally: workspace_lease.cleanup(tree.lease)

def test_normal_detach_is_not_forced_and_cleanup_force_is_ledger_bounded(tmp_path,monkeypatch):
    tree=staged(tmp_path); context=fake_context(tree); calls=[]; package_target="a"*64; proxy_target="b"*64
    for kind,name in (("network","internal"),("network","egress"),("container","proxy"),("container","package"),("lease",str(tree.lease.root))): context.ledger.record(kind,name,"created")
    context.ledger.bind("package",package_target); context.ledger.bind("proxy",proxy_target)
    monkeypatch.setattr(runner,"_remove_retry",lambda command,*_args:calls.append(command))
    monkeypatch.setattr(runner,"_release_proxy_code",lambda _capability:None)
    runner._detach_acquisition(context,"package",request(tree))
    assert ["docker","rm",proxy_target] in calls and ["docker","network","disconnect","internal",package_target] in calls
    assert not any("-f" in command for command in calls)
    calls.clear(); cleanup=fake_context(tree)
    for kind,name in (("network","internal"),("network","egress"),("container","proxy"),("container","package"),("lease",str(tree.lease.root))): cleanup.ledger.record(kind,name,"created")
    cleanup.ledger.bind("package",package_target); cleanup.ledger.bind("proxy",proxy_target)
    runner._cleanup_acquisition(cleanup,"package",force=True)
    assert ["docker","rm","-f",proxy_target] in calls and ["docker","network","disconnect","-f","internal",package_target] in calls
    workspace_lease.cleanup(tree.lease)

def test_proxy_code_lease_cleanup_failure_has_safe_manual_recovery_instruction(tmp_path,monkeypatch):
    tree=staged(tmp_path); context=fake_context(tree); lease_name=str(tree.lease.root)
    context.ledger.record("lease",lease_name,"created")
    failure=lambda _capability:(_ for _ in ()).throw(RuntimeError("injected lease failure"))
    monkeypatch.setattr(runner,"_release_proxy_code",failure)
    with pytest.raises(RuntimeError,match="manual verification required before removing run-owned proxy-code lease"): runner._cleanup_acquisition(context,"package",force=True)
    workspace_lease.cleanup(tree.lease)

def event_history(action="disconnect"):
    return [
        {"Type":"container","Action":"exec_create: true pre","Actor":{"ID":"package-id","Attributes":{}}},
        {"Type":"network","Action":"disconnect","Actor":{"ID":"network-id","Attributes":{"container":"package-id"}}},
        {"Type":"network","Action":action,"Actor":{"ID":"network-id","Attributes":{"container":"package-id"}}},
        {"Type":"container","Action":"exec_create: true post","Actor":{"ID":"package-id","Attributes":{}}},
    ]

def test_continuous_event_history_requires_sentinels_and_exact_disconnect():
    runner.docker_event_guard.validate_history(event_history(),"package-id","network-id","pre","post")
    source=inspect.getsource(runner._run_live)
    assert source.index("_stop_proxy")<source.index("_start_event_channel")<source.index("_detach_acquisition")
    assert "docker_event_guard.start" in inspect.getsource(runner._start_event_channel)
    with pytest.raises(RuntimeError,match="lacks disconnect or sentinel"): runner.docker_event_guard.validate_history([],"package-id","network-id","pre","post")

@pytest.mark.parametrize("events",[
    event_history()[1:2]+event_history()[0:1]+event_history()[3:],
    event_history()[0:1]+event_history()[3:]+event_history()[1:2],
])
def test_continuous_event_history_rejects_out_of_order_boundaries(events):
    with pytest.raises(RuntimeError,match="out of order"): runner.docker_event_guard.validate_history(events,"package-id","network-id","pre","post")

def test_continuous_event_history_rejects_reconnect_even_if_followed_by_disconnect():
    events=event_history("connect")
    events.insert(3,{"Type":"network","Action":"disconnect","Actor":{"ID":"network-id","Attributes":{"container":"package-id"}}})
    with pytest.raises(RuntimeError,match="reconnected"): runner.docker_event_guard.validate_history(events,"package-id","network-id","pre","post")

def test_continuous_event_history_rejects_alternate_network_and_restart():
    alternate=event_history()
    alternate.insert(3,{"Type":"network","Action":"connect","Actor":{"ID":"alternate-id","Attributes":{"container":"package-id"}}})
    with pytest.raises(RuntimeError,match="reconnected to a network"): runner.docker_event_guard.validate_history(alternate,"package-id","network-id","pre","post")
    restarted=event_history()
    restarted.insert(3,{"Type":"container","Action":"restart","Actor":{"ID":"package-id","Attributes":{}}})
    with pytest.raises(RuntimeError,match="restarted"): runner.docker_event_guard.validate_history(restarted,"package-id","network-id","pre","post")

def test_event_finish_rechecks_transport_flags_after_reader_shutdown(monkeypatch):
    process=type("Process",(),{"poll":lambda self:None})()
    follower=runner.docker_event_guard.EventFollower(process,"package-id")
    def stop(item,_signal): item.malformed=True
    monkeypatch.setattr(runner.docker_event_guard,"_stop",stop)
    with pytest.raises(RuntimeError,match="malformed"): runner.docker_event_guard.finish(follower,"network-id","pre","post")

def test_continuous_event_follower_gap_malformed_and_overflow_block():
    class Process:
        def poll(self): return 1
    follower=runner.docker_event_guard.EventFollower(Process(),"package-id")
    with pytest.raises(RuntimeError,match="exited"): runner.docker_event_guard._health(follower)
    follower.process=type("Alive",(),{"poll":lambda self:None})()
    follower.malformed=True
    with pytest.raises(RuntimeError,match="malformed"): runner.docker_event_guard._health(follower)
    follower.malformed=False; follower.overflow=True
    with pytest.raises(RuntimeError,match="32 KiB"): runner.docker_event_guard._health(follower)

def test_event_sentinel_uses_bound_runner_and_daemon_gate(monkeypatch):
    process=type("Process",(),{"poll":lambda self:None})(); gates=[]; commands=[]
    follower=runner.docker_event_guard.EventFollower(process,"package-id",gate=lambda:gates.append(True))
    monkeypatch.setattr(runner.docker_event_guard,"_wait_for",lambda *_args,**_kwargs:None)
    run=lambda command,timeout:commands.append((command,timeout)) or {"returncode":0,"stdout":"","stderr":""}
    runner.docker_event_guard.sentinel(follower,"a"*64,"label",run)
    assert commands==[(["docker","exec","a"*64,"/usr/bin/env","true","label"],10)] and gates==[True,True]

def test_memory_admission_includes_package_workspace_proxy_and_reserve(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree,memory="1g",workspace_bytes=512*1024**2)
    monkeypatch.setattr("builtins.open",lambda *_args,**_kwargs:io.StringIO("MemAvailable: 2000000 kB\n"))
    try:
        with pytest.raises(RuntimeError,match="memory admission"): runner._memory_admission(req)
    finally: workspace_lease.cleanup(tree.lease)

def test_partial_acquisition_context_preserves_original_and_cleanup_failure(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree); code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64); calls=[]; commands=[]
    bypass_daemon(monkeypatch)
    monkeypatch.setattr(runner,"_memory_admission",lambda _request:8*1024**3); monkeypatch.setattr(runner,"_stage_proxy_code",lambda *_args:code)
    monkeypatch.setattr(runner,"_control_run",lambda command,*_args:commands.append(command) or {"returncode":0 if "create" in command else 1,"stdout":"a"*64 if "create" in command else "","stderr":"inspect failed"})
    def cleanup(context,*_args,**_kwargs): calls.extend(context.ledger.events); raise RuntimeError("retained internal network")
    monkeypatch.setattr(runner,"_cleanup_acquisition",cleanup)
    try:
        with pytest.raises(RuntimeError,match="sandbox network inspection failed.*cleanup also failed.*retained internal"): runner._create_acquisition_context(req,"amd64")
        assert any(event.state=="created" and event.kind=="network" for event in calls) and {"--subnet","--gateway","--internal"}<=set(commands[0])
    finally: workspace_lease.cleanup(tree.lease)

def test_network_create_attempt_is_recorded_before_lost_response(tmp_path,monkeypatch):
    tree=staged(tmp_path); code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64); captured=[]
    bypass_daemon(monkeypatch)
    monkeypatch.setattr(runner,"_memory_admission",lambda _request:8*1024**3); monkeypatch.setattr(runner,"_stage_proxy_code",lambda *_args:code)
    monkeypatch.setattr(runner,"_control_run",lambda *_args,**_kwargs:(_ for _ in ()).throw(TimeoutError("lost network response")))
    monkeypatch.setattr(runner,"_cleanup_acquisition",lambda context,*_args,**_kwargs:captured.extend(context.ledger.events))
    try:
        with pytest.raises(TimeoutError): runner._create_acquisition_context(request(tree),"amd64")
        assert any(item.kind=="network" and item.state=="attempted" for item in captured)
    finally: workspace_lease.cleanup(tree.lease)

def test_proxy_create_attempt_is_recorded_before_lost_response(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree); code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64); ledger=runner.ResourceLedger()
    bypass_daemon(monkeypatch)
    context=runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1","python@sha256:"+"a"*64,code,8*1024**3,ledger)
    monkeypatch.setattr(runner,"_reprove_proxy",lambda *_args:None); monkeypatch.setattr(runner,"_control_run",lambda *_args,**_kwargs:(_ for _ in ()).throw(TimeoutError("lost proxy response")))
    try:
        with pytest.raises(TimeoutError): runner._start_proxy(context,"package",req,runner.dependency_egress_proxy.ACQUISITION_PROFILES["block-scripts-32.4.1-smoke"])
        assert any(item.kind=="container" and item.name=="proxy" and item.state=="attempted" for item in ledger.events)
    finally: workspace_lease.cleanup(tree.lease)

def test_wait_proxy_idle_chooses_earlier_lifecycle_and_keeps_ten_second_cap(monkeypatch):
    now=100.0; seen=[]
    monkeypatch.setattr(runner.time,"monotonic",lambda:now)
    monkeypatch.setattr(runner.time,"sleep",lambda _delay:pytest.fail("idle status was not immediately drained"))
    monkeypatch.setattr(runner,"_read_proxy_status",lambda _context,_request,deadline:seen.append(deadline) or {"active":0})
    for lifecycle in (now+5,now+20):
        supervised=type("Supervisor",(),{"lifecycle_deadline":lifecycle})()
        context=type("Context",(),{"supervisor":supervised})()
        assert runner._wait_proxy_idle(context,object())["active"]==0
    assert seen==[now+5,now+10]

def test_proxy_readiness_and_acquisition_share_launch_lifecycle_deadline(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree,timeout=300); capability=runner._validate_request(req,retain=True); lifecycle=time.monotonic()+2; seen={}
    process=type("Process",(),{"poll":lambda self:None})()
    supervised=type("Supervisor",(),{"lifecycle_deadline":lifecycle,"overflow":[],"process":process})()
    code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64)
    context=runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1","python@sha256:"+"a"*64,code,8*1024**3,runner.ResourceLedger(),supervised)
    profile=runner.dependency_egress_proxy.ACQUISITION_PROFILES["block-scripts-32.4.1-smoke"]
    monkeypatch.setattr(runner,"_probe_versions",lambda *_args:None); monkeypatch.setattr(runner.sandbox_dns_guard,"pre_acquisition",lambda *_args:None)
    monkeypatch.setattr(runner,"_prepare_acquisition_paths",lambda *_args:None); monkeypatch.setattr(runner,"_start_proxy",lambda *_args:context)
    monkeypatch.setattr(runner.proxy_supervisor,"check",lambda target:seen.setdefault("health",target))
    def transport(_command,_request,**kwargs): seen["transport"]=kwargs; kwargs["health_check"](); return {"returncode":0,"stdout":"","stderr":""}
    monkeypatch.setattr(runner,"_run_capped_process",transport)
    monkeypatch.setattr(runner,"_assert_package_process",lambda _name,_request,deadline:seen.setdefault("package",deadline))
    monkeypatch.setattr(runner,"_wait_proxy_idle",lambda *_args:{"active":0}); monkeypatch.setattr(runner,"_assert_proxy_process",lambda *_args:None)
    def verify(_name,_request,exclude_dependencies=False,deadline=None):
        seen["proof"]=(exclude_dependencies,deadline); return artifact_staging.ArchiveVerification(tree.manifest,capability.path_kinds)
    monkeypatch.setattr(runner,"_verify_copy",verify)
    try:
        assert runner._acquire("package",req,profile,context,capability).supervisor is supervised
        assert seen["transport"]["deadline"]==lifecycle and seen["package"]==lifecycle and seen["proof"]==(True,lifecycle)
        assert seen["health"] is supervised
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_proxy_health_failure_aborts_live_acquisition_transport_before_absolute_deadline(tmp_path):
    tree=staged(tmp_path); started=time.monotonic(); deadline=started+5.5; checks=[]
    def failed_health(): checks.append(time.monotonic()); raise RuntimeError("proxy workload exited early")
    try:
        with pytest.raises(RuntimeError,match="proxy workload exited early"):
            runner._run_capped_process(["/bin/sh","-c","sleep 2"],request(tree,timeout=10),deadline=deadline,health_check=failed_health)
        assert checks and time.monotonic()<deadline
    finally: workspace_lease.cleanup(tree.lease)

def test_wait_proxy_readiness_uses_only_remaining_lifecycle_time(monkeypatch):
    deadline=time.monotonic()+0.25; seen=[]; ledger=runner.ResourceLedger(); bypass_daemon(monkeypatch)
    monkeypatch.setattr(runner,"_control_run",lambda _command,timeout:seen.append(timeout) or {"returncode":0,"stdout":"","stderr":""})
    runner._wait_proxy("package","npm","172.28.0.3",object(),deadline,ledger)
    assert len(seen)==1 and 0<seen[0]<=0.25

def test_proxy_readiness_preserves_original_and_abort_failure(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=request(tree); code=runner.ProxyCapability(tree.lease,3,4,str(tree.lease.root/"proxy.py"),"a"*64); ledger=runner.ResourceLedger()
    bypass_daemon(monkeypatch)
    context=runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1","python@sha256:"+"a"*64,code,8*1024**3,ledger)
    monkeypatch.setattr(runner,"_reprove_proxy",lambda *_args:None); monkeypatch.setattr(runner,"_configured_proxy_mount_gate",lambda *_args:None); monkeypatch.setattr(runner,"_live_proxy_source_gate",lambda *_args:None); monkeypatch.setattr(runner,"_inspect_proxy",lambda *_args:None)
    monkeypatch.setattr(runner,"_control_run",lambda command,*_args,**_kwargs:{"returncode":0,"stdout":"a"*64 if command[1]=="create" else "","stderr":""}); monkeypatch.setattr(runner.proxy_supervisor,"launch",lambda *_args,**_kwargs:type("Supervisor",(),{"lifecycle_deadline":time.monotonic()+30})())
    monkeypatch.setattr(runner,"_wait_proxy",lambda *_args:(_ for _ in ()).throw(RuntimeError("readiness original"))); monkeypatch.setattr(runner.proxy_supervisor,"abort",lambda *_args:(_ for _ in ()).throw(RuntimeError("abort cleanup")))
    try:
        with pytest.raises(RuntimeError,match="readiness original.*abort cleanup"): runner._start_proxy(context,"package",req,runner.dependency_egress_proxy.ACQUISITION_PROFILES["block-scripts-32.4.1-smoke"])
    finally: workspace_lease.cleanup(tree.lease)

def test_partial_context_ledger_reaches_final_sandbox_evidence(tmp_path,monkeypatch):
    tree=staged(tmp_path); req=dataclasses.replace(request(tree),acquisition="block-scripts-32.4.1-smoke")
    profile=runner.dependency_egress_proxy.ACQUISITION_PROFILES[req.acquisition]; retained="wp-acquire-internal-retained"
    monkeypatch.setattr(runner,"_validate_acquisition",lambda *_args:profile)
    monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    monkeypatch.setattr(runner.sandbox_none_network,"admit",lambda *_args:("daemon","a"*64,"amd64"))
    monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":0,"stdout":"amd64","stderr":""})
    monkeypatch.setattr(runner,"_validate_image",lambda *_args:None); monkeypatch.setattr(runner,"_assert_local_image",lambda *_args:None)
    monkeypatch.setattr(runner.python_preflight,"run",lambda *_args:None)
    def fail_setup(_request,_arch,ledger,_run_token,_proof_budget=None):
        ledger.record("network",retained,"created"); ledger.record("network",retained,"retained")
        raise RuntimeError(f"original IPAM failure; cleanup retained {retained}; recovery: docker network rm {retained}")
    monkeypatch.setattr(runner,"_create_acquisition_context",fail_setup)
    result=runner.run_sandbox(req); evidence=json.loads(result.detail)
    try:
        assert result.status=="blocked" and retained in evidence["errors"][0]
        assert f"docker network rm {retained}" in evidence["errors"][0]
        history=[item for item in evidence["resource_events"] if item["name"]==retained]
        assert [item["state"] for item in history]==["created","retained"]
    finally: workspace_lease.cleanup(tree.lease)

def docker_ready():
    if platform.system()!="Linux": return False
    try: return subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode==0
    except (FileNotFoundError,subprocess.TimeoutExpired): return False
def authenticated_docker_ledger(): ledger=runner.ResourceLedger(); ledger.daemon_id=runner.sandbox_none_network._daemon(runner._control_run,time.monotonic()+30); return ledger
def wait_container_listen(target,port_hex,ledger):
    deadline=time.monotonic()+5
    script=f"import pathlib,sys;sys.exit(0 if any(':{port_hex}' in l and l.split()[3]=='0A' for l in pathlib.Path('/proc/net/tcp').read_text().splitlines()[1:]) else 1)"
    while time.monotonic()<deadline:
        result=runner._bound_control(ledger,["docker","exec",target,"python","-c",script],5)
        if not result["returncode"]: return
        time.sleep(0.05)
    raise RuntimeError(f"{target} did not listen on {port_hex}")

def docker_request(tree,script,**changes):
    inv=runtime_image_provision.inventory()["images"]["node"]
    arch=platform.machine(); image=f"node@{runtime_image_provision.platform_digest(inv,arch)}"
    return dataclasses.replace(runner.SandboxRequest(tree,image,("node","-e",script)),**changes)

def approved_npm_tree(tmp_path):
    packet=HARNESS.parent/"suites/wordpress-block-executor/examples/smoke-wordpress-v1.materializable-packet.md"
    source=tmp_path/"approved-source"
    result=materializer.materialize_packet("block",packet.read_text(),source)
    assert result["pass"]
    return artifact_staging.stage_tree(source,tmp_path/"approved-leases")

def approved_composer_tree(tmp_path):
    packet=HARNESS.parent/"suites/wordpress-plugin-executor/examples/phpunit-wordpress-v1.materializable-packet.md"
    source=tmp_path/"approved-composer-source"; result=materializer.materialize_packet("plugin",packet.read_text(),source)
    assert result["pass"]
    return artifact_staging.stage_tree(source/"acme-runtime-tested",tmp_path/"approved-composer-leases")

def composer_request(tree,script,**changes):
    item=runtime_image_provision.inventory()["images"]["composer"]
    image=f"composer@{runtime_image_provision.platform_digest(item,platform.machine())}"
    base=runner.SandboxRequest(tree,image,("php","-r",script))
    return dataclasses.replace(base,**changes)

def lifecycle_identity(req):
    arch=runner._normalize_server_arch(subprocess.check_output(["docker","info","--format","{{.Architecture}}"],text=True,timeout=30))
    profile=runner.dependency_egress_proxy.ACQUISITION_PROFILES[req.acquisition]; proxy_ref=runner._proxy_image(arch)
    return {"profile_id":req.acquisition,"manifest_sha256":profile.manifest_sha256,"lock_sha256":profile.lock_sha256,"package_image_ref":req.image,"proxy_image_ref":proxy_ref,"package_local_image_id":runner._assert_local_image(req.image),"proxy_local_image_id":runner._assert_local_image(proxy_ref),"toolchain_versions":list(profile.versions),"runner_os":platform.system(),"runner_arch":arch}

def docker_cleanup_context(tmp_path):
    tree=staged(tmp_path); req=dataclasses.replace(request(tree),acquisition="block-scripts-32.4.1-smoke")
    arch=runner._normalize_server_arch(subprocess.check_output(["docker","info","--format","{{.Architecture}}"],text=True,timeout=30))
    context=runner._create_acquisition_context(req,arch,authenticated_docker_ledger()); name="wp-cleanup-test-"+__import__("uuid").uuid4().hex[:10]
    command=["docker","create","--pull=never","--name",name,"--network",context.ledger.target(context.internal),"--ip",context.package_ip,"--dns","127.0.0.1","--entrypoint","sleep",req.image,"infinity"]
    package_id=subprocess.check_output(command,text=True,timeout=120).strip(); assert re.fullmatch(r"[0-9a-f]{64}",package_id); context.ledger.bind(name,package_id)
    context.ledger.record("container",name,"created"); context.ledger.record("network",context.internal,"attached")
    created=runner._run(runner._proxy_create_command(context,{"registry.npmjs.org"},req),req,120); assert created["returncode"]==0; context.ledger.bind(context.proxy,created["stdout"].strip())
    context.ledger.record("container",context.proxy,"created"); context.ledger.record("network",context.internal,"attached")
    assert runner._run(["docker","network","connect",context.ledger.target(context.egress),context.ledger.target(context.proxy)],req,60)["returncode"]==0
    context.ledger.record("network",context.egress,"attached")
    return tree,req,context,name

def cleanup_docker_context(tree,context,name):
    for command in (["docker","rm","-f",context.ledger.target(context.proxy)],["docker","rm","-f",context.ledger.target(name)],["docker","network","rm",context.ledger.target(context.egress)],["docker","network","rm",context.ledger.target(context.internal)]):
        subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    if context.ledger.needs_cleanup("lease",str(context.proxy_code.lease.root)):
        runner._release_proxy_code(context.proxy_code)
    workspace_lease.cleanup(tree.lease)

def _stop_tcpdump(process,deadline):
    if process.poll() is None:
        try: os.killpg(process.pid,signal.SIGINT)
        except ProcessLookupError: pass
    now=time.monotonic(); grace=min(deadline,now+max(0,min(1,(deadline-now)/2)))
    while process.poll() is None and time.monotonic()<grace: time.sleep(0.01)
    if process.poll() is None:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    remaining=deadline-time.monotonic()
    if remaining<=0 and process.poll() is None: raise RuntimeError("tcpdump exceeded absolute teardown deadline")
    try: process.wait(timeout=max(0.001,remaining))
    except subprocess.TimeoutExpired as exc: raise RuntimeError("tcpdump survived SIGKILL") from exc
    if process.poll() is None: raise RuntimeError("tcpdump was not reaped")
    if getattr(process,"stderr",None) is not None:
        remainder=process.stderr.read(4097); process.stderr.close()
        if len(remainder)>4096: raise RuntimeError("tcpdump diagnostics exceeded 4 KiB")

def _wait_tcpdump_ready(process,deadline):
    while process.poll() is None and time.monotonic()<deadline:
        readable,_,_=select.select([process.stderr],[],[],max(0,deadline-time.monotonic()))
        if not readable: break
        line=process.stderr.readline(1025)
        if len(line)>1024: raise RuntimeError("tcpdump readiness output exceeded 1 KiB")
        if b"listening on" in line.lower(): return
    raise RuntimeError("tcpdump did not confirm capture readiness")

def _dns_query_packet(domain):
    labels=b"".join(bytes([len(label)])+label.encode() for label in domain.split("."))
    return b"\x57\x50\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"+labels+b"\x00\x00\x01\x00\x01"

def test_tcpdump_teardown_escalates_and_reaps(monkeypatch):
    signals=[]
    class Process:
        pid=123; returncode=None; waited=False
        def poll(self): return self.returncode
        def wait(self,timeout): self.waited=True; return self.returncode
    process=Process()
    def killpg(_pid,sig):
        signals.append(sig)
        if sig==signal.SIGKILL: process.returncode=-sig
    monkeypatch.setattr(os,"killpg",killpg)
    _stop_tcpdump(process,time.monotonic()+0.03)
    assert signals==[signal.SIGINT,signal.SIGKILL] and process.waited

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_approved_acquisition_proxy_endpointless_denials_and_strict_export(tmp_path):
    tree=approved_npm_tree(tmp_path)
    script="const f=require('fs');if(!f.existsSync('node_modules/@wordpress/scripts'))process.exit(2);f.writeFileSync('acquired.txt','ok')"
    req=docker_request(tree,script,acquisition="block-scripts-32.4.1-smoke",workspace_bytes=1200*1024**2,workspace_inodes=100000,timeout=900)
    result=runner.run_sandbox(req)
    step4_evidence.write_leg("npm_lifecycle",step4_evidence.lifecycle_payload(result,lifecycle_identity(req)))
    try:
        assert result.status=="pass",result.detail
        assert (result.output.root/"acquired.txt").read_text()=="ok"
        assert not (result.output.root/"node_modules").exists()
        evidence=json.loads(result.detail)
        assert {"dependency_acquisition","detach","detached_gate","generated","export","cleanup","end_to_end"}<=set(evidence["timings_seconds"])
        assert evidence["metrics"]["proxy_memory_peak"]>0 and evidence["metrics"]["package_memory_peak"]>0
    finally:
        if result.output: workspace_lease.cleanup(result.output.lease)
        workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_approved_composer_acquisition_endpointless_and_strict_export(tmp_path):
    tree=approved_composer_tree(tmp_path)
    script="if(!file_exists('vendor/bin/phpunit'))exit(2);file_put_contents('composer-acquired.txt','ok');"
    req=composer_request(tree,script,acquisition="plugin-phpunit-12.5.31",workspace_bytes=1200*1024**2,workspace_inodes=100000,timeout=900)
    result=runner.run_sandbox(req)
    step4_evidence.write_leg("composer_lifecycle",step4_evidence.lifecycle_payload(result,lifecycle_identity(req)))
    try:
        assert result.status=="pass",result.detail
        assert (result.output.root/"composer-acquired.txt").read_text()=="ok"
        assert not (result.output.root/"vendor").exists() and not (result.output.root/"sandbox-cache").exists()
    finally:
        if result.output: workspace_lease.cleanup(result.output.lease)
        workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_dns_query_never_reaches_host_egress_interface(tmp_path):
    assert shutil.which("tcpdump") and subprocess.run(["sudo","-n","true"],timeout=5).returncode==0
    tree=staged(tmp_path); req=request(tree); capability=runner._validate_request(req,retain=True)
    token=__import__("uuid").uuid4().hex; network=f"wp-dns-observe-{token[:12]}"; name=f"wp-package-dns-{token[:12]}"; capture=tmp_path/"dns.pcap"
    watcher=None; stop_deadline=None
    try:
        spec=runner.sandbox_network_policy.specification(token[:12],"fixture"); subprocess.run(runner.sandbox_network_policy.create_command(network,spec,internal=True),check=True,stdout=subprocess.DEVNULL,timeout=60)
        _gateway,package_ip,_proxy_ip=runner.sandbox_network_policy.inspect(runner._control_run,network,spec,internal=True).addresses
        network_id=subprocess.check_output(["docker","network","inspect",network,"--format","{{.Id}}"],text=True,timeout=30).strip()
        bridge=f"br-{network_id[:12]}"
        if bridge not in {name for _index,name in socket.if_nameindex()}: raise RuntimeError("owned Docker bridge interface is unavailable")
        subprocess.run(runner._create_command(req,name,capability,network,package_ip),check=True,stdout=subprocess.DEVNULL,timeout=120)
        subprocess.run(["docker","start",name],check=True,stdout=subprocess.DEVNULL,timeout=60)
        command=["sudo","-n","tcpdump","-i",bridge,"-U","-c","64","-s","128","-w",str(capture),"udp","port","53","or","tcp","port","53"]
        watcher=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,start_new_session=True)
        stop_deadline=time.monotonic()+10
        _wait_tcpdump_ready(watcher,min(stop_deadline,time.monotonic()+3))
        needle=lambda value:b"".join(bytes([len(label)])+label.encode() for label in value.split("."))
        positive=f"wp-positive-{token}.invalid"; udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        def emit_positive(timeout):
            udp.sendto(_dns_query_packet(positive),(package_ip,53))
            time.sleep(min(0.05,timeout))
            visible=capture.exists() and needle(positive) in capture.read_bytes()
            return subprocess.CompletedProcess([],0 if visible else 1)
        try: native_poll.until_success(emit_positive,min(stop_deadline,time.monotonic()+3))
        finally: udp.close()
        assert watcher.poll() is None
        domain=f"wp-step4-{token}.invalid"; script=f"require('dns').lookup('{domain}',e=>process.exit(e?0:1));setTimeout(()=>process.exit(2),1800)"
        lookup=subprocess.run(["docker","exec",name,"timeout","2","node","-e",script],timeout=5)
        assert lookup.returncode==0; time.sleep(0.25); assert watcher.poll() is None
        _stop_tcpdump(watcher,stop_deadline); watcher=None
        payload=capture.read_bytes()
        assert len(payload)<=64*(128+32)+24 and needle(positive) in payload and needle(domain) not in payload
    finally:
        if watcher is not None: _stop_tcpdump(watcher,stop_deadline or time.monotonic()+5)
        subprocess.run(["docker","rm","-f",name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        subprocess.run(["docker","network","rm",network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("mutation",["alternate-network","restart"])
def test_docker_continuous_event_guard_rejects_post_detach_mutation(tmp_path,mutation):
    tree=staged(tmp_path); req=request(tree); capability=runner._validate_request(req,retain=True); token=__import__("uuid").uuid4().hex[:12]; alternate_token=__import__("uuid").uuid4().hex[:12]
    network=f"wp-event-mutation-{token}"; alternate=f"wp-event-alternate-{alternate_token}"; name=f"wp-package-event-{token}"; follower=None
    try:
        spec=runner.sandbox_network_policy.specification(token,"fixture"); subprocess.run(runner.sandbox_network_policy.create_command(network,spec,internal=True),check=True,stdout=subprocess.DEVNULL,timeout=60)
        _gateway,package_ip,_proxy_ip=runner.sandbox_network_policy.inspect(runner._control_run,network,spec,internal=True).addresses
        subprocess.run(runner._create_command(req,name,capability,network,package_ip),check=True,stdout=subprocess.DEVNULL,timeout=120)
        subprocess.run(["docker","start",name],check=True,stdout=subprocess.DEVNULL,timeout=60)
        container_id=subprocess.check_output(["docker","inspect",name,"--format","{{.Id}}"],text=True,timeout=30).strip()
        network_id=subprocess.check_output(["docker","network","inspect",network,"--format","{{.Id}}"],text=True,timeout=30).strip()
        follower=runner.docker_event_guard.start(container_id); runner.docker_event_guard.sentinel(follower,name,"pre-reconnect")
        subprocess.run(["docker","network","disconnect",network,name],check=True,timeout=60); runner.docker_event_guard.await_disconnect(follower,network_id)
        if mutation=="alternate-network":
            alternate_spec=runner.sandbox_network_policy.specification(alternate_token,"fixture"); subprocess.run(runner.sandbox_network_policy.create_command(alternate,alternate_spec,internal=True),check=True,stdout=subprocess.DEVNULL,timeout=60); runner.sandbox_network_policy.inspect(runner._control_run,alternate,alternate_spec,internal=True)
            subprocess.run(["docker","network","connect",alternate,name],check=True,timeout=60); subprocess.run(["docker","network","disconnect",alternate,name],check=True,timeout=60)
        else: subprocess.run(["docker","restart",name],check=True,stdout=subprocess.DEVNULL,timeout=60)
        runner.docker_event_guard.sentinel(follower,name,"post-reconnect")
        with pytest.raises(RuntimeError,match="reconnected|restarted"): runner.docker_event_guard.finish(follower,network_id,"pre-reconnect","post-reconnect")
        follower=None
    finally:
        if follower:
            try: runner.docker_event_guard.abort(follower)
            except RuntimeError: pass
        subprocess.run(["docker","rm","-f",name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        subprocess.run(["docker","network","rm",alternate,network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_production_proxy_connect_canary_uses_only_fake_public_egress_endpoint(tmp_path):
    tree=staged(tmp_path); req=request(tree); capability=runner._validate_request(req,retain=True); token=__import__("uuid").uuid4().hex[:12]
    internal=f"wp-fake-internal-{token}"; egress=f"wp-fake-egress-{token}"; package=f"wp-package-fake-{token}"; proxy_name=f"wp-proxy-fake-{token}"; registry=f"wp-registry-fake-{token}"; code=None; controlled_payload=None; context=None; stopped=False
    ledger=authenticated_docker_ledger(); bound=lambda command,timeout:runner._bound_control(ledger,command,timeout); daemon=live_fixture_support.run(ledger,["docker","info","--format","{{.Architecture}}"],30,"Docker architecture fixture lookup failed")
    arch=runner._normalize_server_arch(daemon["stdout"]); python_image=runner._proxy_image(arch)
    try:
        spec=runner.sandbox_network_policy.specification(token,"fixture"); internal_id=live_fixture_support.create(ledger,"network",internal,runner.sandbox_network_policy.create_command(internal,spec,internal=True),60)
        # Exact globally classified subnet is a controlled-CONNECT canary only; production allocation never uses it.
        egress_id=live_fixture_support.create(ledger,"network",egress,["docker","network","create","--subnet",step4_evidence.FAKE_PUBLIC_SUBNET,"--gateway",step4_evidence.FAKE_PUBLIC_GATEWAY,egress],60)
        gateway,package_ip,proxy_ip=runner.sandbox_network_policy.inspect(bound,internal,spec,internal=True,target=internal_id).addresses; code=runner._stage_proxy_code()
        run_nonce=f"wp-status-{__import__('uuid').uuid4().hex}"; context=runner.AcquisitionContext(internal,egress,proxy_name,run_nonce,package_ip,proxy_ip,gateway,python_image,code,8*1024**3,ledger)
        package_id=live_fixture_support.create(ledger,"container",package,runner._create_command(req,package,capability,internal_id,package_ip)); ledger.record("network",internal,"attached")
        relay_nonce=f"wp-{token}"; server=f"import socket;s=socket.create_server(('0.0.0.0',443));c,_=s.accept();d=c.recv(64);c.sendall(d if d==b'{relay_nonce}' else b'bad');c.close()"
        registry_command=["docker","create","--pull=never","--name",registry,"--network",egress_id,"--ip",step4_evidence.FAKE_REGISTRY_IP,"--network-alias","registry.npmjs.org","--entrypoint","python",python_image,"-c",server]
        registry_id=live_fixture_support.create(ledger,"container",registry,registry_command); ledger.record("network",egress,"attached")
        proxy_id=live_fixture_support.create(ledger,"container",proxy_name,runner._proxy_create_command(context,{"registry.npmjs.org"},req)); ledger.record("network",internal,"attached")
        live_fixture_support.run(ledger,["docker","network","connect",egress_id,proxy_id],60,"controlled proxy egress attachment failed"); ledger.record("network",egress,"attached")
        live_fixture_support.run(ledger,["docker","start",registry_id,proxy_id,package_id],60,"controlled fixture start failed")
        fixture_deadline=time.monotonic()+req.timeout+30; gate=lambda:runner.daemon_control.require(ledger,runner._control_run,fixture_deadline)
        control=lambda command,timeout:runner._bound_control(ledger,command,timeout,fixture_deadline)
        supervised=runner.proxy_supervisor.launch(proxy_id,context.nonce,runner._proxy_argv(context,{"registry.npmjs.org"}),req.user,control,req.timeout,gate)
        context=dataclasses.replace(context,supervisor=supervised,proxy_target=proxy_id)
        wait_container_listen(registry_id,"01BB",ledger); wait_container_listen(proxy_id,"1F90",ledger)
        containers=live_fixture_support.run(ledger,["docker","inspect",proxy_id,package_id,registry_id],30,"controlled container inspection failed")
        networks=live_fixture_support.run(ledger,["docker","network","inspect",internal_id,egress_id],30,"controlled network inspection failed")
        proxy_data,package_data,registry_data=json.loads(containers["stdout"]); internal_data,egress_data=json.loads(networks["stdout"])
        assert all(re.fullmatch(r"[0-9a-f]{64}",item["Id"]) for item in (proxy_data,package_data,registry_data,internal_data,egress_data))
        assert (internal_data["Name"],egress_data["Name"])==(internal,egress)
        assert package_data["NetworkSettings"]["Networks"][internal]["IPAddress"]==package_ip
        assert proxy_data["NetworkSettings"]["Networks"][internal]["IPAddress"]==proxy_ip and set(proxy_data["NetworkSettings"]["Networks"])=={internal,egress}
        proxy_egress_ip=proxy_data["NetworkSettings"]["Networks"][egress]["IPAddress"]
        assert ipaddress.ip_address(proxy_egress_ip) in ipaddress.ip_network(step4_evidence.FAKE_PUBLIC_SUBNET)
        assert registry_data["NetworkSettings"]["Networks"][egress]["IPAddress"]==step4_evidence.FAKE_REGISTRY_IP
        assert set(internal_data["Containers"])=={package_data["Id"],proxy_data["Id"]} and set(egress_data["Containers"])=={proxy_data["Id"],registry_data["Id"]}
        assert internal_data["Containers"][package_data["Id"]]["IPv4Address"].split("/")[0]==package_ip and internal_data["Containers"][proxy_data["Id"]]["IPv4Address"].split("/")[0]==proxy_ip
        assert egress_data["Containers"][proxy_data["Id"]]["IPv4Address"].split("/")[0]==proxy_egress_ip and egress_data["Containers"][registry_data["Id"]]["IPv4Address"].split("/")[0]==step4_evidence.FAKE_REGISTRY_IP
        direct=f"const n=require('net'),s=n.connect(443,'{step4_evidence.FAKE_REGISTRY_IP}',()=>process.exit(1));s.on('error',()=>process.exit(0));s.setTimeout(800,()=>{{s.destroy();process.exit(0)}})"
        assert bound(["docker","exec",package_id,"timeout","2","node","-e",direct],5)["returncode"]==0
        connect=f"const n=require('net'),s=n.connect(8080,'{proxy_ip}');let b='',up=false;s.on('connect',()=>s.write('CONNECT registry.npmjs.org:443 HTTP/1.1\\r\\nHost: registry.npmjs.org:443\\r\\n\\r\\n'));s.on('data',d=>{{b+=d;if(Buffer.byteLength(b)>4096)process.exit(5);if(!up&&b.includes('\\r\\n\\r\\n')){{if(!b.startsWith('HTTP/1.1 200'))process.exit(2);up=true;b='';s.write('{relay_nonce}')}}else if(up&&b.includes('{relay_nonce}'))process.exit(0)}});s.on('error',()=>process.exit(3));setTimeout(()=>process.exit(4),3000)"
        assert bound(["docker","exec",package_id,"timeout","4","node","-e",connect],8)["returncode"]==0
        status=runner._wait_proxy_idle(context,req)
        assert status["nonce"]==context.nonce and status["accepted"]==status["completed"]==1 and status["active"]==status["rejected"]==0
        assert status["client_bytes"]==status["upstream_bytes"]==len(relay_nonce)
        runner._stop_proxy(context,req); stopped=True
        internal_config=internal_data["IPAM"]["Config"][0]; egress_config=egress_data["IPAM"]["Config"][0]
        controlled_payload={"cleanup_disposition":None,"proxy_status":status.value,"relay_nonce":relay_nonce,"run_nonce":run_nonce,"topology":{"containers":{"package":{"id":package_data["Id"],"name":package,"ips":{internal:package_ip}},"proxy":{"id":proxy_data["Id"],"name":proxy_name,"ips":{internal:proxy_ip,egress:proxy_egress_ip}},"registry":{"id":registry_data["Id"],"name":registry,"ips":{egress:step4_evidence.FAKE_REGISTRY_IP}}},"networks":{"internal":{"id":internal_data["Id"],"name":internal,"internal":internal_data["Internal"],"subnet":internal_config["Subnet"],"gateway":internal_config["Gateway"]},"egress":{"id":egress_data["Id"],"name":egress,"internal":egress_data["Internal"],"subnet":egress_config["Subnet"],"gateway":egress_config["Gateway"]}}}}
    finally:
        live_fixture_support.finish(context,stopped,ledger,(package,proxy_name,registry),(internal,egress),code,capability,tree,controlled_payload)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_residual_generated_child_is_rejected(tmp_path):
    tree=staged(tmp_path)
    script="require('child_process').spawn('sleep',['60'],{detached:true,stdio:'ignore'}).unref()"
    try: assert runner.run_sandbox(docker_request(tree,script)).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("script,changes",[
    ("require('fs').writeFileSync('near-byte-limit',Buffer.alloc(60*1024*1024))",{"workspace_bytes":64*1024*1024}),
    ("const f=require('fs');for(let i=0;i<900;i++)f.writeFileSync('near-inode-'+i,'')",{"workspace_inodes":1024}),
])
def test_docker_near_limit_byte_and_inode_profiles_pass_without_weakening_quota(tmp_path,script,changes):
    tree=staged(tmp_path); result=runner.run_sandbox(docker_request(tree,script,**changes))
    try: assert result.status=="pass",result.detail
    finally:
        if result.output: workspace_lease.cleanup(result.output.lease)
        workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_disconnect_failure_uses_forced_owned_cleanup(tmp_path,monkeypatch):
    tree,req,context,name=docker_cleanup_context(tmp_path); original=runner._remove_retry
    def inject(command,*args,**kwargs):
        if command==["docker","network","disconnect",context.ledger.target(context.internal),context.ledger.target(name)]: raise RuntimeError("injected normal disconnect failure")
        return original(command,*args,**kwargs)
    monkeypatch.setattr(runner,"_remove_retry",inject)
    try:
        with pytest.raises(RuntimeError,match="injected normal disconnect"): runner._detach_acquisition(context,name,req)
        monkeypatch.setattr(runner,"_remove_retry",original); runner._cleanup_acquisition(context,name,force=True)
        assert subprocess.run(["docker","network","inspect",context.ledger.target(context.internal)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode!=0
    finally: cleanup_docker_context(tree,context,name)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("target",["proxy","package","egress","internal"])
def test_docker_cleanup_failure_reports_exact_retained_resource_at_each_boundary(tmp_path,monkeypatch,target):
    tree,req,context,name=docker_cleanup_context(tmp_path); original=runner.provision.run_capped
    commands={"proxy":["docker","rm","-f",context.ledger.target(context.proxy)],"package":["docker","network","disconnect","-f",context.ledger.target(context.internal),context.ledger.target(name)],"egress":["docker","network","rm",context.ledger.target(context.egress)],"internal":["docker","network","rm",context.ledger.target(context.internal)]}
    def inject(command,**kwargs):
        if command==commands[target]: return {"returncode":1,"stdout":"","stderr":"injected"}
        return original(command,**kwargs)
    monkeypatch.setattr(runner.provision,"run_capped",inject)
    try:
        expected={"proxy":context.ledger.target(context.proxy),"package":context.ledger.target(name),"egress":context.ledger.target(context.egress),"internal":context.ledger.target(context.internal)}[target]
        with pytest.raises(RuntimeError,match=expected): runner._cleanup_acquisition(context,name,force=True)
    finally:
        monkeypatch.setattr(runner.provision,"run_capped",original); cleanup_docker_context(tree,context,name)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_safe_output_and_host_boundaries(tmp_path,monkeypatch):
    tree=staged(tmp_path); monkeypatch.setenv("HOST_SECRET","sentinel")
    script="const f=require('fs');if(process.env.HOST_SECRET)process.exit(2);try{f.writeFileSync('/outside','x');process.exit(3)}catch(e){};f.writeFileSync('output.txt','ok')"
    result=runner.run_sandbox(docker_request(tree,script,environment=(("HOME","/home/sandbox"),)))
    try:
        assert result.status=="pass" and (result.output.root/"output.txt").read_text()=="ok"
    finally:
        if result.output: workspace_lease.cleanup(result.output.lease)
        workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("script,changes",[("process.stdout.write('x'.repeat(200000))",{}),("process.stderr.write('x'.repeat(200000))",{}),("setInterval(()=>{},1000)",{"timeout":1}),("require('fs').writeFileSync('huge',Buffer.alloc(20*1024*1024))",{"workspace_bytes":8*1024*1024}),("const f=require('fs');for(let i=0;i<1000;i++)f.writeFileSync('i'+i,'')",{"workspace_inodes":64})])
def test_docker_output_and_quota_limits_block(tmp_path,script,changes):
    tree=staged(tmp_path)
    try: assert runner.run_sandbox(docker_request(tree,script,**changes)).status!="pass"
    finally: workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_cannot_reach_host_listener(tmp_path):
    tree=staged(tmp_path); listener=socket.socket(); listener.bind(("0.0.0.0",0)); listener.listen(1)
    host=socket.gethostbyname(socket.gethostname())
    if host.startswith("127."): listener.close(); workspace_lease.cleanup(tree.lease); pytest.skip("no non-loopback host address")
    script=f"const n=require('net');const s=n.connect({listener.getsockname()[1]},'{host}',()=>process.exit(1));s.on('error',()=>process.exit(0));setTimeout(()=>{{s.destroy();process.exit(0)}},1500)"
    result=runner.run_sandbox(docker_request(tree,script)); listener.close()
    try: assert result.status=="pass"
    finally:
        if result.output: workspace_lease.cleanup(result.output.lease)
        workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_special_output_is_rejected_by_importer(tmp_path):
    tree=staged(tmp_path); req=dataclasses.replace(docker_request(tree,"process.exit(0)"),argv=("mkfifo","special"))
    try: assert runner.run_sandbox(req).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)


@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
@pytest.mark.parametrize("argv",[("ln","-s","/etc","node_modules"),("mkfifo","vendor")])
def test_docker_direct_dependency_root_symlink_or_special_is_not_silently_excluded(tmp_path,argv):
    tree=staged(tmp_path); req=dataclasses.replace(docker_request(tree,"process.exit(0)"),argv=argv)
    try: assert runner.run_sandbox(req).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)

@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_symlink_output_and_sibling_sentinel_are_inaccessible(tmp_path):
    tree=staged(tmp_path); (tree.lease.root/"sibling-secret").write_text("SECRET")
    script="const f=require('fs');try{f.readFileSync('/input/../sibling-secret');process.exit(2)}catch(e){};f.symlinkSync('/etc/passwd','link')"
    try: assert runner.run_sandbox(docker_request(tree,script)).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)
