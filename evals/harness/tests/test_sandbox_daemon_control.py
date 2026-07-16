import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HARNESS))
import sandbox_daemon_control as control
import sandbox_active_daemon as active_daemon
import sandbox_none_network
import sandboxed_package_runner as runner

DAEMON="daemon-instance-1234567890abcdef"
OTHER="daemon-instance-fedcba0987654321"


def payload(value):
    return json.dumps(value,separators=(",",":"))+"\n"


class Ledger:
    daemon_id=DAEMON
    identity_tainted=False


def result(stdout="",returncode=0):
    return {"returncode":returncode,"stdout":stdout,"stderr":""}


def test_daemon_bound_operation_is_bracketed_before_and_after():
    calls=[]
    def run(command,_timeout):
        calls.append(command[1]); return result(payload(DAEMON)) if command[1]=="info" else result()
    assert control.run(Ledger(),["docker","rm","-f","owned"],10,run,time.monotonic()+30)==result()
    assert calls==["info","rm","info"]


@pytest.mark.parametrize("lost",[False,True])
def test_identity_drift_before_cleanup_retry_issues_no_second_mutation(lost):
    ledger=Ledger(); info=iter([DAEMON,OTHER] if lost else [DAEMON,DAEMON,OTHER]); mutations=[]
    def run(command,_timeout):
        if command[1]=="info": return result(payload(next(info)))
        mutations.append(command)
        if lost: raise TimeoutError("lost response")
        return result(returncode=1)
    with pytest.raises(sandbox_none_network.DaemonIdentityError):
        control.retry(ledger,["docker","rm","-f","owned"],run,time.monotonic()+60)
    assert len(mutations)==1 and ledger.identity_tainted


def test_previously_tainted_identity_issues_zero_docker_commands():
    ledger=Ledger(); ledger.identity_tainted=True; calls=[]
    with pytest.raises(sandbox_none_network.DaemonIdentityError,match="previously tainted"):
        control.run(ledger,["docker","rm","-f","owned"],10,lambda *_args:calls.append(True),time.monotonic()+30)
    assert calls==[]


def test_tainted_acquisition_cleanup_retains_every_docker_resource_without_commands(monkeypatch):
    ledger=runner.ResourceLedger(); ledger.daemon_id=DAEMON; ledger.identity_tainted=True
    code=SimpleNamespace(lease=SimpleNamespace(root=Path("/tmp/proxy-code")))
    supervised=SimpleNamespace(termination=())
    context=runner.AcquisitionContext("internal","egress","proxy","nonce","ip","ip","ip","image",code,1,ledger,supervised)
    for kind,name in (("network","internal"),("network","egress"),("container","proxy"),("container","package"),("lease","/tmp/proxy-code")): ledger.record(kind,name,"created")
    calls=[]; reaped=[]; monkeypatch.setattr(runner,"_control_run",lambda *_args:calls.append(True)); monkeypatch.setattr(runner,"_release_proxy_code",lambda *_args:None)
    monkeypatch.setattr(runner.proxy_supervisor,"reap_host",lambda item:reaped.append(item))
    with pytest.raises(RuntimeError,match="original Docker daemon"):
        runner._cleanup_acquisition(context,"package",force=True)
    assert calls==[] and reaped==[supervised]
    latest={(item.kind,item.name):item.state for item in ledger.events}
    assert latest[("container","proxy")]==latest[("container","package")]=="retained"
    assert latest[("network","internal")]==latest[("network","egress")]=="retained" and latest[("lease","/tmp/proxy-code")] == "retained"


def test_active_transport_blocks_before_launch_when_daemon_identity_drifted(monkeypatch):
    ledger=Ledger(); launched=[]
    def drift(_run,_expected,_deadline,taint): taint(); raise sandbox_none_network.DaemonIdentityError("changed")
    monkeypatch.setattr(sandbox_none_network,"require_daemon",drift)
    token=active_daemon.activate(ledger)
    try:
        raw=lambda *_args,**_kwargs:launched.append(True)
        request=SimpleNamespace(timeout=10)
        with pytest.raises(sandbox_none_network.DaemonIdentityError): active_daemon.process(raw,["docker","exec","owned"],request)
        assert launched==[] and ledger.identity_tainted
    finally: active_daemon.reset(token)


def test_active_transport_periodic_gate_detects_midstream_daemon_drift(monkeypatch):
    ledger=Ledger(); checks=[]; launched=[]
    def require(_run,_expected,_deadline,taint):
        checks.append(True)
        if len(checks)==2: taint(); raise sandbox_none_network.DaemonIdentityError("changed")
    monkeypatch.setattr(sandbox_none_network,"require_daemon",require)
    def raw(_command,_request,deadline=None,health_check=None): launched.append(True); health_check()
    token=active_daemon.activate(ledger)
    try:
        with pytest.raises(sandbox_none_network.DaemonIdentityError): active_daemon.process(raw,["docker","exec","owned"],SimpleNamespace(timeout=10))
        assert launched==[True] and ledger.identity_tainted and len(checks)==2
    finally: active_daemon.reset(token)


def test_post_operation_identity_failure_releases_returned_result(monkeypatch):
    ledger=Ledger(); checks=[]; released=[]; output=SimpleNamespace(lease=object())
    def require(_run,_expected,_deadline,taint):
        checks.append(True)
        if len(checks)==2: taint(); raise sandbox_none_network.DaemonIdentityError("changed")
    monkeypatch.setattr(sandbox_none_network,"require_daemon",require)
    token=active_daemon.activate(ledger)
    try:
        with pytest.raises(sandbox_none_network.DaemonIdentityError): active_daemon.call(lambda:output,cleanup=lambda item:released.append(item))
        assert released==[output] and ledger.identity_tainted
    finally: active_daemon.reset(token)
