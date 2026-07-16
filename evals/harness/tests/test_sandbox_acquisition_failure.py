import dataclasses
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import sandboxed_package_runner as runner


def acquisition_context(ledger):
    code = SimpleNamespace(lease=SimpleNamespace(root=Path("/tmp/test-proxy-code")))
    context = runner.AcquisitionContext("internal","egress","proxy","nonce","172.28.0.2","172.28.0.3","172.28.0.1","python@sha256:"+"a"*64,code,8*1024**3,ledger)
    resources = (("network","internal","a"),("network","egress","b"),("container","package","c"),("container","proxy","d"))
    ledger.record("lease", str(code.lease.root), "created")
    for kind,name,prefix in resources:
        ledger.bind(name, prefix * 64); ledger.record(kind, name, "created")
    return context


def test_failed_acquisition_cleans_the_stored_live_supervisor_before_lease(monkeypatch):
    ledger = runner.ResourceLedger(); ledger.daemon_id = "daemon"; context = acquisition_context(ledger)
    supervisor = SimpleNamespace(termination=(), lifecycle_deadline=time.monotonic()+30)
    supervised = dataclasses.replace(context, supervisor=supervisor, proxy_target=ledger.target("proxy"))
    request = SimpleNamespace(image="composer@sha256:"+"e"*64, timeout=30, user="1000:1000")
    capability = SimpleNamespace(budget=None); profile = SimpleNamespace(kind="composer",allowed_hosts=frozenset({"api.github.com"})); order=[]; seen={}
    monkeypatch.setattr(runner.sandbox_none_network,"admit",lambda *args:("daemon","f"*64,"amd64"))
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",lambda *args:None)
    monkeypatch.setattr(runner,"_validate_image",lambda *args:None); monkeypatch.setattr(runner,"_assert_local_image",lambda *args:"sha256:"+"1"*64)
    monkeypatch.setattr(runner.python_preflight,"run",lambda *args:None); monkeypatch.setattr(runner,"_create_acquisition_context",lambda *args:context)
    monkeypatch.setattr(runner,"_create_started_container",lambda *args:time.monotonic()+30); monkeypatch.setattr(runner,"_inspect_boundary",lambda *args:ledger.target("package")); monkeypatch.setattr(runner,"_prepare",lambda *args:None)
    monkeypatch.setattr(runner,"_start_acquisition",lambda *args:supervised)
    monkeypatch.setattr(runner,"_run_capped_process",lambda *args,**kwargs:{"returncode":1,"stdout":"Bearer hidden","stderr":"curl error 7"})
    status={"nonce":"secret-nonce","accepted":0,"active":0,"completed":0,"rejected":1,"rejected_peer":0,"rejected_capacity":1,"rejected_handler":0,"client_bytes":0,"upstream_bytes":0}
    monkeypatch.setattr(runner,"_read_proxy_status",lambda *args,**kwargs:seen.setdefault("status_read",status))
    monkeypatch.setattr(runner.proxy_supervisor,"abort",lambda *args:order.append("abort")); monkeypatch.setattr(runner,"_remove_retry",lambda command,*args,**kwargs:order.append(tuple(command)))
    monkeypatch.setattr(runner,"_release_proxy_code",lambda code:order.append("lease"))
    original_cleanup=runner._cleanup_acquisition
    def cleanup(live,*args,**kwargs): seen["context"]=live; return original_cleanup(live,*args,**kwargs)
    monkeypatch.setattr(runner,"_cleanup_acquisition",cleanup)
    with pytest.raises(runner.SandboxBoundaryError) as failure:
        runner._run_live(request,"package",capability,profile,ledger)
    assert seen["context"].supervisor is supervisor and seen["status_read"] is status and order[0]=="abort" and order[-1]=="lease"
    assert "rejected_capacity" in str(failure.value) and "secret-nonce" not in str(failure.value) and "hidden" not in str(failure.value)
    assert any(item["kind"]=="termination" and item["state"]=="whole-container-cleanup" for item in failure.value.resources)


def test_failed_acquisition_status_read_failure_is_generic_and_fail_closed(monkeypatch):
    profile=SimpleNamespace(kind="composer",allowed_hosts=frozenset()); context=SimpleNamespace(supervisor=SimpleNamespace(lifecycle_deadline=time.monotonic()+10),proxy_ip="172.28.0.3")
    monkeypatch.setattr(runner,"_run_capped_process",lambda *args,**kwargs:{"returncode":1,"stdout":"secret","stderr":"raw status error"})
    monkeypatch.setattr(runner,"_read_proxy_status",lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError("Bearer hidden")))
    with pytest.raises(RuntimeError,match="authenticated proxy status unavailable") as failure: runner._acquire("package",SimpleNamespace(),profile,context,SimpleNamespace())
    assert "hidden" not in str(failure.value) and failure.value.__cause__ is None


@pytest.mark.parametrize("change",[{"active":False},{"rejected_capacity":-1},{"rejected":1}])
def test_fallback_proxy_status_rejects_boolean_negative_and_reason_sum(monkeypatch,change):
    status={"nonce":"n","accepted":0,"active":0,"completed":0,"rejected":0,"rejected_peer":0,"rejected_capacity":0,"rejected_handler":0,"client_bytes":0,"upstream_bytes":0,**change}
    payload=json.dumps(status); responses=iter(({"returncode":0,"stdout":f"600:1000:1000:{len(payload)}","stderr":""},{"returncode":0,"stdout":payload,"stderr":""}))
    monkeypatch.setattr(runner,"_bound_control",lambda *args:next(responses))
    context=SimpleNamespace(ledger=runner.ResourceLedger(),supervisor=None,proxy_target="proxy",proxy="proxy",nonce="n")
    with pytest.raises(RuntimeError,match="proxy status"): runner._read_proxy_status(context,SimpleNamespace(user="1000:1000"))
