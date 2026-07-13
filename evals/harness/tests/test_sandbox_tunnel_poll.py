import dataclasses
import json
import os
import platform
import subprocess
import time
import uuid
from types import SimpleNamespace

import pytest

import artifact_staging
import runtime_image_provision
import sandbox_native_poll as poll
import sandboxed_package_runner as runner
import workspace_lease


def staged(tmp_path):
    source=tmp_path/"source"; source.mkdir(); (source/"input.txt").write_text("safe")
    return artifact_staging.stage_tree(source,tmp_path/"leases")


def request(tree):
    item=runtime_image_provision.inventory()["images"]["node"]
    image=f"node@{runtime_image_provision.platform_digest(item,platform.machine())}"
    return dataclasses.replace(runner.SandboxRequest(tree,image,("node","-e","process.exit(0)")))


def docker_ready():
    if platform.system()!="Linux": return False
    try: return subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode==0
    except (FileNotFoundError,subprocess.TimeoutExpired): return False


class Clock:
    def __init__(self,now=0): self.now=now; self.reads=0
    def monotonic(self): self.reads+=1; return self.now
    def sleep(self,value): self.now+=value


def test_poll_accepts_success_launched_in_budget_even_when_return_crosses_deadline(monkeypatch):
    clock=Clock(0.9); calls=[]
    monkeypatch.setattr(poll.time,"monotonic",clock.monotonic); monkeypatch.setattr(poll.time,"sleep",clock.sleep)
    def run(timeout): calls.append(timeout); clock.now=1.1; return SimpleNamespace(returncode=0)
    assert poll.until_success(run,1.0)==1
    assert calls==[pytest.approx(0.1)] and clock.reads==1


def test_poll_repeated_failures_expire_without_extra_command(monkeypatch):
    clock=Clock(); calls=[]
    monkeypatch.setattr(poll.time,"monotonic",clock.monotonic); monkeypatch.setattr(poll.time,"sleep",clock.sleep)
    def run(timeout): calls.append((clock.now,timeout)); clock.now+=0.24; return SimpleNamespace(returncode=1)
    with pytest.raises(TimeoutError,match="deadline"):
        poll.until_success(run,0.5,interval=0.02)
    assert len(calls)==2
    assert all(timeout<=0.5-start for start,timeout in calls)


def test_poll_failure_returning_at_expiry_never_launches_post_expiry(monkeypatch):
    clock=Clock(2.0); calls=[]
    monkeypatch.setattr(poll.time,"monotonic",clock.monotonic); monkeypatch.setattr(poll.time,"sleep",clock.sleep)
    def run(timeout): calls.append(timeout); clock.now=3.0; return SimpleNamespace(returncode=1)
    with pytest.raises(TimeoutError,match="deadline"): poll.until_success(run,3.0)
    assert calls==[pytest.approx(1.0)]


def test_poll_passes_each_command_no_more_than_positive_remaining(monkeypatch):
    clock=Clock(5.0); calls=[]
    monkeypatch.setattr(poll.time,"monotonic",clock.monotonic); monkeypatch.setattr(poll.time,"sleep",clock.sleep)
    def run(timeout):
        calls.append((clock.now,timeout)); clock.now+=0.1
        return SimpleNamespace(returncode=0 if len(calls)==3 else 1)
    assert poll.until_success(run,6.0,interval=0.05)==3
    assert all(0<timeout<=6.0-start for start,timeout in calls)


def test_poll_propagates_bounded_command_timeout_without_retry(monkeypatch):
    clock=Clock(10.0); calls=[]
    monkeypatch.setattr(poll.time,"monotonic",clock.monotonic)
    def run(timeout): calls.append(timeout); raise subprocess.TimeoutExpired(["docker","exec"],timeout)
    with pytest.raises(subprocess.TimeoutExpired): poll.until_success(run,10.25)
    assert calls==[pytest.approx(0.25)]


def _observe_file(package,path,deadline):
    command=["docker","exec",package,"test","-f",path]
    return poll.until_success(
        lambda timeout:subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=timeout),
        deadline,
    )


@pytest.mark.docker_boundary
@pytest.mark.skipif(not docker_ready(),reason="Linux Docker boundary unavailable")
def test_docker_disconnect_breaks_established_tunnel(tmp_path):
    tree=staged(tmp_path); req=request(tree); capability=runner._validate_request(req,retain=True); token=uuid.uuid4().hex[:12]
    network=f"wp-tunnel-break-{token}"; package=f"wp-package-tunnel-{token}"; server=f"wp-acquire-proxy-break-{token}"
    python_image=runner._proxy_image(runner._normalize_server_arch(subprocess.check_output(["docker","info","--format","{{.Architecture}}"],text=True,timeout=30)))
    try:
        spec=runner.sandbox_network_policy.specification(token,"fixture"); subprocess.run(runner.sandbox_network_policy.create_command(network,spec,internal=True),check=True,stdout=subprocess.DEVNULL,timeout=60)
        _gateway,package_ip,server_ip=runner.sandbox_network_policy.inspect(runner._control_run,network,spec,internal=True).addresses
        user=f"{os.getuid()}:{os.getgid()}"; tmpfs=f"/tmp:size=1048576,nr_inodes=64,mode=0700,uid={os.getuid()},gid={os.getgid()},noexec,nosuid,nodev"
        create=["docker","create","--pull=never","--name",package,"--network",network,"--ip",package_ip,"--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user",user,"--pids-limit","32","--memory","67108864","--memory-swap","67108864","--tmpfs",tmpfs,"--entrypoint","sleep",python_image,"infinity"]
        subprocess.run(create,check=True,stdout=subprocess.DEVNULL,timeout=120)
        listener="import socket,time;s=socket.create_server(('0.0.0.0',9090));c,_=s.accept();\nwhile True:\n c.sendall(b'x');time.sleep(.05)"
        subprocess.run(["docker","create","--pull=never","--name",server,"--network",network,"--ip",server_ip,"--entrypoint","python",python_image,"-c",listener],check=True,stdout=subprocess.DEVNULL,timeout=120)
        subprocess.run(["docker","start",server,package],check=True,stdout=subprocess.DEVNULL,timeout=60); time.sleep(0.2)
        script=f"""import socket
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE,1);s.setsockopt(socket.IPPROTO_TCP,socket.TCP_USER_TIMEOUT,1000);s.settimeout(1);s.connect(('{server_ip}',9090))
try:
 first=True
 while True:
  if not s.recv(1): raise EOFError()
  if first: open('/tmp/heartbeat','w').write('1');first=False
except (EOFError,OSError,TimeoutError):
 open('/tmp/broken','w').write('1')
"""
        subprocess.run(["docker","exec","-d",package,"/usr/local/bin/python","-I","-S","-B","-c",script],check=True,timeout=30)
        assert _observe_file(package,"/tmp/heartbeat",time.monotonic()+5)>0
        assert subprocess.run(["docker","exec",package,"test","!","-f","/tmp/broken"],timeout=5).returncode==0
        subprocess.run(["docker","network","disconnect",network,package],check=True,timeout=60)
        inspected=json.loads(subprocess.check_output(["docker","inspect",package],text=True,timeout=30))[0]
        network_data=json.loads(subprocess.check_output(["docker","network","inspect",network],text=True,timeout=30))[0]
        assert inspected["NetworkSettings"]["Networks"]=={} and inspected["Id"] not in network_data.get("Containers",{})
        assert _observe_file(package,"/tmp/broken",time.monotonic()+5)>0
    finally:
        subprocess.run(["docker","rm","-f",package,server],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        subprocess.run(["docker","network","rm",network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        os.close(capability.root_fd); os.close(capability.lease_fd); workspace_lease.cleanup(tree.lease)
