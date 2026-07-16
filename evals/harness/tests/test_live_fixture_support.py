import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS), str(HARNESS)]

import live_fixture_support as support
import sandboxed_package_runner as runner


def result(returncode=0, stdout="", stderr=""):
    return {"returncode": returncode, "stdout": stdout, "stderr": stderr}


def test_create_binds_only_exact_created_identity(monkeypatch):
    ledger = runner.ResourceLedger()
    target = "a" * 64
    monkeypatch.setattr(runner, "_bound_control", lambda command_ledger, command, timeout: result(stdout=target + "\n"))

    assert support.create(ledger, "container", "logical", ["docker", "create"]) == target
    assert ledger.target("logical") == target
    assert [(event.state, event.name) for event in ledger.events] == [("attempted", "logical"), ("created", "logical")]


def test_cleanup_mutates_and_verifies_only_bound_exact_identity(monkeypatch):
    ledger = runner.ResourceLedger()
    target = "b" * 64
    ledger.bind("logical", target)
    ledger.record("container", "logical", "created")
    calls = []

    def control(command_ledger, command, timeout):
        calls.append(command)
        return result()

    monkeypatch.setattr(runner, "_bound_control", control)
    assert support.cleanup(ledger, ("logical", "never-attempted"), ()) == []
    assert calls[0] == ["docker", "rm", "-f", target]
    assert [command[command.index("--filter") + 1] for command in calls[1:]] == [f"id={target}", "name=^/logical$"]


@pytest.mark.parametrize("tainted", [False, True])
def test_cleanup_refuses_unverified_or_tainted_identity(monkeypatch, tainted):
    ledger = runner.ResourceLedger()
    ledger.record("network", "logical", "attempted")
    if tainted:
        ledger.bind("logical", "c" * 64)
        ledger.record("network", "logical", "created")
        ledger.identity_tainted = True
    calls = []
    monkeypatch.setattr(runner, "_bound_control", lambda *args: calls.append(args))

    retained = support.cleanup(ledger, (), ("logical",))
    assert retained and ("daemon-tainted" if tainted else "unverified") in retained[0]
    assert calls == []


def test_cleanup_detects_name_replacement_without_deleting_it(monkeypatch):
    ledger = runner.ResourceLedger(); target = "d" * 64; replacement = "e" * 64
    ledger.bind("logical", target); ledger.record("container", "logical", "created"); calls = []
    def control(command_ledger, command, timeout):
        calls.append(command)
        if "name=^/logical$" in command: return result(stdout=f"{replacement}\tlogical\n")
        return result()
    monkeypatch.setattr(runner, "_bound_control", control)
    retained = support.cleanup(ledger, ("logical",), ())
    assert retained == [f"container:logical:name-replaced:{replacement}"]
    assert ["docker", "rm", "-f", replacement] not in calls


@pytest.mark.parametrize("listing", [result(1, stderr="permission denied"), result(stdout="malformed\n")])
def test_cleanup_rejects_failed_or_malformed_absence_listing(monkeypatch, listing):
    ledger = runner.ResourceLedger(); target = "f" * 64
    ledger.bind("logical", target); ledger.record("network", "logical", "created")
    calls = []
    def control(command_ledger, command, timeout):
        calls.append(command)
        return result() if command[:3] == ["docker", "network", "rm"] else listing
    monkeypatch.setattr(runner, "_bound_control", control)
    assert "id-absence-RuntimeError" in support.cleanup(ledger, (), ("logical",))[0]
    assert calls == [["docker", "network", "rm", target], support._absence_command("network", "id", target)]


def test_finish_blocks_evidence_when_abort_and_host_reap_both_fail(monkeypatch):
    ledger = runner.ResourceLedger(); context = SimpleNamespace(supervisor=object())
    capability = SimpleNamespace(root_fd=3, lease_fd=4); tree = SimpleNamespace(lease=object())
    monkeypatch.setattr(runner.proxy_supervisor, "abort", lambda *args: (_ for _ in ()).throw(RuntimeError("abort")))
    monkeypatch.setattr(runner.proxy_supervisor, "reap_host", lambda *args: (_ for _ in ()).throw(RuntimeError("reap")))
    monkeypatch.setattr(support, "cleanup", lambda *args: []); monkeypatch.setattr(support.os, "close", lambda fd: None)
    released=[]; written=[]
    monkeypatch.setattr(runner, "_release_proxy_code", lambda code: released.append(code))
    monkeypatch.setattr(support.workspace_lease, "cleanup", lambda lease: released.append(lease))
    monkeypatch.setattr(support.step4_evidence, "write_leg", lambda *args: written.append(args))
    with pytest.raises(AssertionError, match="supervisor:abort-RuntimeError:reap-RuntimeError"):
        support.finish(context,False,ledger,(),(),object(),capability,tree,{"topology":{}})
    assert released == [] and written == []
