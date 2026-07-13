import dataclasses
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
    capability = SimpleNamespace(budget=None); profile = SimpleNamespace(kind="composer"); order=[]; seen={}
    monkeypatch.setattr(runner.sandbox_none_network,"admit",lambda *args:("daemon","f"*64,"amd64"))
    monkeypatch.setattr(runner.sandbox_none_network,"require_daemon",lambda *args:None)
    monkeypatch.setattr(runner,"_validate_image",lambda *args:None); monkeypatch.setattr(runner,"_assert_local_image",lambda *args:"sha256:"+"1"*64)
    monkeypatch.setattr(runner.python_preflight,"run",lambda *args:None); monkeypatch.setattr(runner,"_create_acquisition_context",lambda *args:context)
    monkeypatch.setattr(runner,"_create_started_container",lambda *args:time.monotonic()+30); monkeypatch.setattr(runner,"_inspect_boundary",lambda *args:ledger.target("package")); monkeypatch.setattr(runner,"_prepare",lambda *args:None)
    monkeypatch.setattr(runner,"_start_acquisition",lambda *args:supervised); monkeypatch.setattr(runner,"_acquire",lambda *args:(_ for _ in ()).throw(RuntimeError("forced acquisition failure")))
    monkeypatch.setattr(runner.proxy_supervisor,"abort",lambda *args:order.append("abort")); monkeypatch.setattr(runner,"_remove_retry",lambda command,*args,**kwargs:order.append(tuple(command)))
    monkeypatch.setattr(runner,"_release_proxy_code",lambda code:order.append("lease"))
    original_cleanup=runner._cleanup_acquisition
    def cleanup(live,*args,**kwargs): seen["context"]=live; return original_cleanup(live,*args,**kwargs)
    monkeypatch.setattr(runner,"_cleanup_acquisition",cleanup)
    with pytest.raises(runner.SandboxBoundaryError) as failure:
        runner._run_live(request,"package",capability,profile,ledger)
    assert seen["context"].supervisor is supervisor and order[0]=="abort" and order[-1]=="lease"
    assert any(item["kind"]=="termination" and item["state"]=="whole-container-cleanup" for item in failure.value.resources)
