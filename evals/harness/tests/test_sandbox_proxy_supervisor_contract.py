import json
import os
import platform
import subprocess
import time
import uuid
from types import SimpleNamespace

import pytest

import runtime_image_provision as provision
import sandbox_proxy_supervisor as supervisor
import sandbox_python_preflight as preflight


ARGV=("/usr/local/bin/python","-I","-S","-c","import time;time.sleep(60)")
EXECUTABLE="/usr/local/bin/python3.13"


def evidence(**changes):
    value={
        "uid":[str(os.getuid())]*4,
        "gid":[str(os.getgid())]*4,
        "exe":EXECUTABLE,
        "argv":list(ARGV),
    }
    value.update(changes)
    return json.dumps(value,separators=(",",":"),sort_keys=True)+"\n"


@pytest.mark.parametrize("result,match",[
    ({"returncode":7,"stdout":"","stderr":"denied"},"unavailable"),
    ({"returncode":0,"stdout":"not-json","stderr":""},"Expecting value"),
])
def test_process_evidence_rejects_nonzero_and_malformed_json(result,match):
    with pytest.raises((RuntimeError,json.JSONDecodeError),match=match):
        supervisor._process_evidence(lambda *_args:result,"proxy",27,ARGV,EXECUTABLE,time.monotonic()+1)


@pytest.mark.parametrize("payload",[
    evidence(uid=["-1"]*4),evidence(gid=["-1"]*4),evidence(exe="/tmp/python"),
    evidence(argv=[*ARGV,"extra"]),evidence(argv=list(reversed(ARGV))),
])
def test_process_evidence_rejects_every_identity_dimension(payload):
    control=lambda *_args:{"returncode":0,"stdout":payload,"stderr":""}
    with pytest.raises(RuntimeError,match="identity drift"):
        supervisor._process_evidence(control,"proxy",27,ARGV,EXECUTABLE,time.monotonic()+1)


def top_result(commands,returncode=0):
    rows=["PID ARGS",*(f"{index+10} {command}" for index,command in enumerate(commands))]
    return {"returncode":returncode,"stdout":"\n".join(rows)+"\n","stderr":""}


@pytest.mark.parametrize("commands",[
    [],["sleep infinity"],[" ".join(ARGV)],["sleep infinity","sleep infinity"," ".join(ARGV)],
    ["sleep infinity"," ".join(ARGV),"sleep 60"],["sleep infinity"," ".join(ARGV)," ".join(ARGV)],
])
def test_top_gate_rejects_missing_duplicate_and_extra_processes(commands):
    with pytest.raises(RuntimeError,match="inventory drift"):
        supervisor._top_gate(lambda *_args:top_result(commands),"proxy",ARGV,time.monotonic()+1)


def test_top_gate_rejects_nonzero_even_with_exact_inventory():
    with pytest.raises(RuntimeError,match="inventory drift"):
        supervisor._top_gate(lambda *_args:top_result(["sleep infinity"," ".join(ARGV)],7),"proxy",ARGV,time.monotonic()+1)


def test_top_gate_failure_reports_only_bounded_process_fingerprints():
    secret="authorization-token-must-not-appear"
    with pytest.raises(RuntimeError) as caught:
        supervisor._top_gate(lambda *_args:top_result(["sleep infinity",secret]),"proxy",ARGV,time.monotonic()+1)
    message=str(caught.value)
    assert secret not in message and '"count":2' in message and '"argv_sha256"' in message


@pytest.mark.parametrize("commands",[
    [],[" ".join(ARGV)],["sleep infinity","sleep infinity"],
    ["sleep infinity"," ".join(ARGV),"helper signal"],["sleep infinity","sleep 60"],
])
def test_top_no_helper_gate_rejects_missing_duplicate_extra_and_surviving_helper(commands):
    with pytest.raises(RuntimeError,match="helper survived|inventory drifted"):
        supervisor._top_no_helper_gate(lambda *_args:top_result(commands),"proxy",ARGV,time.monotonic()+1)


def docker_ready():
    if platform.system()!="Linux": return False
    try: return subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode==0
    except (FileNotFoundError,subprocess.TimeoutExpired): return False


class Ledger:
    def __init__(self): self.events=[]
    def record(self,*event): self.events.append(event)


def docker_control(command,timeout):
    return provision.run_capped(command,timeout=timeout,limit=32768)


def wait_pid(name,deadline):
    while time.monotonic()<deadline:
        result=docker_control(["docker","exec",name,"cat","/tmp/expected.pid"],min(2,deadline-time.monotonic()))
        if result["returncode"]==0 and result["stdout"].strip().isdigit(): return int(result["stdout"].strip())
        time.sleep(0.05)
    raise TimeoutError("expected Python child PID did not appear")


@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_real_process_gate_rejects_unauthorized_long_lived_process():
    inventory=provision.inventory()["images"]["python"]; arch=provision.normalize_arch(platform.machine())
    image=f"{inventory['tag'].split(':')[0]}@{inventory[arch]}"; name=f"wp-proxy-inventory-{uuid.uuid4().hex[:16]}"
    user=f"{os.getuid()}:{os.getgid()}"; container_id=""; attempted=False; ledger=Ledger()
    expected_script="import os,time;open('/tmp/expected.pid','w').write(str(os.getpid()));time.sleep(60)"
    expected_argv=("/usr/local/bin/python","-I","-S","-c",expected_script)
    create=["docker","create","--pull=never","--name",name,"--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user",user,"--pids-limit","32","--memory","67108864","--memory-swap","67108864","--cpus","0.25","--log-driver","none","--tmpfs",f"/tmp:size=1048576,nr_inodes=64,mode=0700,uid={os.getuid()},gid={os.getgid()},noexec,nosuid,nodev","--entrypoint","sleep",image,"infinity"]
    try:
        attempted=True; created=docker_control(create,60); container_id=created["stdout"].strip()
        assert created["returncode"]==0 and len(container_id)==64
        assert docker_control(["docker","start",name],30)["returncode"]==0
        expected=["docker","exec","-d","--user",user,"--",name,"/usr/bin/env","-i",*expected_argv]
        assert docker_control(expected,30)["returncode"]==0; pid=wait_pid(name,time.monotonic()+10)
        process=SimpleNamespace(poll=lambda:None)
        item=SimpleNamespace(overflow=[],process=process,container=name,pid=pid,argv=expected_argv,executable=EXECUTABLE,lifecycle_deadline=time.monotonic()+30)
        supervisor.process_gate(item,docker_control)
        unauthorized=["docker","exec","-d","--user",user,"--",name,"/usr/bin/env","-i","/usr/local/bin/python","-I","-S","-c","import time;time.sleep(60)"]
        assert docker_control(unauthorized,30)["returncode"]==0
        with pytest.raises(RuntimeError,match="inventory drift"): supervisor.process_gate(item,docker_control)
    finally:
        preflight._remove(docker_control,name,container_id,ledger,None,attempted)
