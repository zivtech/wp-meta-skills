import dataclasses, inspect, json, os, platform, socket, subprocess, sys
from pathlib import Path
import pytest
HARNESS=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(HARNESS))
import artifact_staging, runtime_image_provision, sandboxed_package_runner as runner, workspace_lease

def staged(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"input.txt").write_text("safe")
    return artifact_staging.stage_tree(source,tmp_path/"leases")

def request(tree,**changes):
    item=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(item,platform.machine())}"
    base=runner.SandboxRequest(tree,image,("node","-e","process.exit(0)"))
    return dataclasses.replace(base,**changes)

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
        assert "--network none" in joined and "--read-only" in command
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

def test_cleanup_failure_blocks_prior_failure_status(tmp_path,monkeypatch):
    tree=staged(tmp_path); monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    monkeypatch.setattr(runner,"_run_live",lambda *_args:runner.SandboxResult("fail",9,"","",None,"generated failed","name"))
    monkeypatch.setattr(runner.provision,"run_capped",lambda *_args,**_kwargs:{"returncode":1,"stdout":"","stderr":"cleanup"})
    try: assert runner.run_sandbox(request(tree)).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)

def test_cleanup_exception_closes_successful_output_lease(tmp_path,monkeypatch):
    tree=staged(tmp_path); output_parent=tmp_path/"output-parent"; output_parent.mkdir(); output=staged(output_parent); monkeypatch.setattr(runner.platform,"system",lambda:"Linux")
    monkeypatch.setattr(runner,"_run_live",lambda *_args:runner.SandboxResult("pass",0,"","",output,"passed","name"))
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

def test_mount_comma_path_is_rejected(tmp_path):
    parent=tmp_path/"comma,parent"; parent.mkdir(); tree=staged(parent)
    try:
        with pytest.raises(ValueError,match="mount metacharacter"): runner._validate_request(request(tree))
    finally: workspace_lease.cleanup(tree.lease)

def test_descriptor_mount_survives_lexical_swap(tmp_path):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True)
    moved=tree.lease.root/"moved"; tree.root.rename(moved); tree.root.symlink_to(Path.home(),target_is_directory=True)
    try:
        command=runner._create_command(request(tree),"container",capability)
        assert f"src={capability.source},dst=/input,readonly" in " ".join(command)
        assert os.fstat(capability.root_fd).st_ino==capability.inode
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd)
        tree.root.unlink(); moved.rename(tree.root); workspace_lease.cleanup(tree.lease)

def test_copy_manifest_mismatch_fails_before_execute(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True)
    monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":0,"stdout":"tmpfs 524288 1 1 1% /workspace\ntmpfs 50000 1 1 1% /workspace\n","stderr":""})
    monkeypatch.setattr(runner,"_verify_copy",lambda *_args:artifact_staging.ArchiveVerification((),()))
    try:
        with pytest.raises(RuntimeError,match="copy manifest or graph mismatch"): runner._prepare("container",request(tree),capability)
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_daemon_arch_image_validation_precedes_create(tmp_path,monkeypatch):
    tree=staged(tmp_path); capability=runner._validate_request(request(tree),retain=True); calls=[]
    bogus=dataclasses.replace(request(tree),image="node@sha256:"+"f"*64)
    monkeypatch.setattr(runner,"_run",lambda command,*_args,**_kwargs:calls.append(command) or {"returncode":0,"stdout":"amd64\n","stderr":""})
    try:
        with pytest.raises(ValueError,match="approved daemon-platform child"): runner._run_live(bogus,"container",capability)
        assert calls==[["docker","info","--format","{{.Architecture}}"]]
    finally:
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)

def test_non_linux_is_blocked_without_fallback(tmp_path,monkeypatch):
    tree=staged(tmp_path); calls=[]; monkeypatch.setattr(runner.platform,"system",lambda:"Darwin")
    monkeypatch.setattr(runner.provision,"run_capped",lambda command,**kwargs:calls.append(command) or {"returncode":0,"stdout":"","stderr":""})
    try:
        result=runner.run_sandbox(request(tree)); assert result.status=="blocked"
        assert calls==[]
    finally: workspace_lease.cleanup(tree.lease)

def test_output_export_is_uncompressed_streaming_tar():
    body=inspect.getsource(runner._import_output)
    assert '"tar","-C","/workspace","-cf","-","."' in body
    assert "communicate(" not in body and "capture_output" not in body
    assert "threading.Timer" in body and 'env={"PATH":"/usr/bin:/bin"}' in body
    assert "thread.join(1)" in body and "watchdog.join(1)" in body
    assert 'env={"PATH":"/usr/bin:/bin"}' in inspect.getsource(runner._run_capped_process)

def test_inspection_failure_is_fail_closed(tmp_path,monkeypatch):
    tree=staged(tmp_path); monkeypatch.setattr(runner,"_run",lambda *_args,**_kwargs:{"returncode":1,"stdout":"","stderr":"inspect"})
    try:
        with pytest.raises(RuntimeError,match="inspection failed"): runner._inspect_boundary("container",request(tree))
    finally: workspace_lease.cleanup(tree.lease)

def docker_ready():
    if platform.system()!="Linux": return False
    return subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0

def docker_request(tree,script,**changes):
    inv=runtime_image_provision.inventory()["images"]["node"]
    arch=platform.machine(); image=f"node@{runtime_image_provision.platform_digest(inv,arch)}"
    return dataclasses.replace(runner.SandboxRequest(tree,image,("node","-e",script)),**changes)

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
def test_docker_symlink_output_and_sibling_sentinel_are_inaccessible(tmp_path):
    tree=staged(tmp_path); (tree.lease.root/"sibling-secret").write_text("SECRET")
    script="const f=require('fs');try{f.readFileSync('/input/../sibling-secret');process.exit(2)}catch(e){};f.symlinkSync('/etc/passwd','link')"
    try: assert runner.run_sandbox(docker_request(tree,script)).status=="blocked"
    finally: workspace_lease.cleanup(tree.lease)
