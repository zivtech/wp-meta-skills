"""Live Docker cleanup, output, and quota tests for the package sandbox."""
import dataclasses
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

TESTS=Path(__file__).resolve().parent; HARNESS=TESTS.parent
sys.path.insert(0,str(TESTS)); sys.path.insert(0,str(HARNESS))
import artifact_staging, runtime_image_provision, sandboxed_package_runner as runner, workspace_lease


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


def authenticated_docker_ledger():
    ledger=runner.ResourceLedger()
    ledger.daemon_id=runner.sandbox_none_network._daemon(runner._control_run,time.monotonic()+30)
    return ledger


def docker_request(tree,script,**changes):
    inv=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(inv,platform.machine())}"
    return dataclasses.replace(runner.SandboxRequest(tree,image,("node","-e",script)),**changes)


def docker_cleanup_context(tmp_path):
    tree=staged(tmp_path); req=dataclasses.replace(request(tree),acquisition="block-scripts-32.4.1-smoke")
    arch=runner._normalize_server_arch(subprocess.check_output(["docker","info","--format","{{.Architecture}}"],text=True,timeout=30))
    context=runner._create_acquisition_context(req,arch,authenticated_docker_ledger())
    name="wp-cleanup-test-"+__import__("uuid").uuid4().hex[:10]
    command=["docker","create","--pull=never","--name",name,"--network",context.ledger.target(context.internal),"--ip",context.package_ip,"--dns","127.0.0.1","--entrypoint","sleep",req.image,"infinity"]
    package_id=subprocess.check_output(command,text=True,timeout=120).strip()
    assert re.fullmatch(r"[0-9a-f]{64}",package_id); context.ledger.bind(name,package_id)
    context.ledger.record("container",name,"created"); context.ledger.record("network",context.internal,"attached")
    created=runner._run(runner._proxy_create_command(context,{"registry.npmjs.org"},req),req,120)
    assert created["returncode"]==0; context.ledger.bind(context.proxy,created["stdout"].strip())
    context.ledger.record("container",context.proxy,"created"); context.ledger.record("network",context.internal,"attached")
    assert runner._run(["docker","network","connect",context.ledger.target(context.egress),context.ledger.target(context.proxy)],req,60)["returncode"]==0
    context.ledger.record("network",context.egress,"attached")
    return tree,req,context,name


def cleanup_docker_context(tree,context,name):
    commands=(["docker","rm","-f",context.ledger.target(context.proxy)],["docker","rm","-f",context.ledger.target(name)],["docker","network","rm",context.ledger.target(context.egress)],["docker","network","rm",context.ledger.target(context.internal)])
    for command in commands:
        subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
    if context.ledger.needs_cleanup("lease",str(context.proxy_code.lease.root)):
        runner._release_proxy_code(context.proxy_code)
    workspace_lease.cleanup(tree.lease)


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
    try: assert result.status=="pass" and (result.output.root/"output.txt").read_text()=="ok"
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
