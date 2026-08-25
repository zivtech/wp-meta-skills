"""The handoff re-certification CLI must bind provenance and reuse the loop gate."""

import hashlib
import json

import pytest

import recertify_wordpress_executor_packet as recertify
import run_executor_repair_loop as repair_loop
from workspace_lease import WorkspacePurpose, create_named


@pytest.fixture()
def packet(tmp_path):
    path = tmp_path / "packet.md"
    path.write_text("# Implementation Packets\n", encoding="utf-8")
    return path


@pytest.fixture()
def results_root(tmp_path, monkeypatch):
    root = tmp_path / "results"
    root.mkdir()
    monkeypatch.setattr(repair_loop, "RESULTS", root)
    return root


def canned_certify(monkeypatch, verdict, seen):
    def fake_make_certify(suite, executor, run_dir, profile, timeout, assertion=None):
        seen.update(suite=suite, executor=executor, run_dir=run_dir,
                    profile=profile, timeout=timeout, assertion=assertion)

        def certify(iteration, packet_path):
            seen.update(iteration=iteration, packet=packet_path)
            return dict(verdict)

        return certify

    monkeypatch.setattr(repair_loop, "make_certify", fake_make_certify)


def test_refuses_packet_sha_mismatch(packet, results_root, capsys):
    status = recertify.main([
        "--packet", str(packet), "--run-id", "handoff-x",
        "--expected-packet-sha256", "0" * 64,
    ])
    assert status == 2
    assert "does not match expected" in capsys.readouterr().err
    assert not (results_root / "handoff-x").exists()


def test_refuses_existing_run_workspace(packet, results_root, monkeypatch, capsys):
    canned_certify(monkeypatch, {"passed": True}, {})
    create_named(results_root, "handoff-x", WorkspacePurpose.REPAIR_RUN)
    status = recertify.main(["--packet", str(packet), "--run-id", "handoff-x"])
    assert status == 2
    assert "re-certification refused" in capsys.readouterr().err


def test_green_verdict_passes_through_with_bound_provenance(
        packet, results_root, monkeypatch, capsys):
    seen = {}
    verdict = {"passed": True, "failing_gates": [],
               "gate_vector": {"phpcs_wpcs": "pass"}, "failures": ""}
    canned_certify(monkeypatch, verdict, seen)
    expected_sha = hashlib.sha256(packet.read_bytes()).hexdigest()
    status = recertify.main([
        "--packet", str(packet), "--run-id", "handoff-x",
        "--expected-packet-sha256", expected_sha,
    ])
    assert status == 0
    assert seen["executor"] == "plugin" and seen["profile"] == "runtime"
    assert seen["iteration"] == 0 and seen["packet"] == packet
    assert seen["run_dir"] == results_root / "handoff-x"
    record = json.loads((results_root / "handoff-x" / "recertification.json")
                        .read_text(encoding="utf-8"))
    assert record["passed"] is True
    assert record["packet_sha256"] == expected_sha
    assert record["gate_vector"] == {"phpcs_wpcs": "pass"}
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_failing_verdict_exits_nonzero_and_records_gates(
        packet, results_root, monkeypatch):
    verdict = {"passed": False, "failing_gates": ["plugin_check"],
               "gate_vector": {"plugin_check": "fail"}, "failures": "detail"}
    canned_certify(monkeypatch, verdict, {})
    status = recertify.main(["--packet", str(packet), "--run-id", "handoff-x"])
    assert status == 1
    record = json.loads((results_root / "handoff-x" / "recertification.json")
                        .read_text(encoding="utf-8"))
    assert record["failing_gates"] == ["plugin_check"]
    assert record["failures"] == "detail"


def test_block_runtime_requires_suite_and_fixture(packet, results_root, capsys):
    status = recertify.main([
        "--packet", str(packet), "--run-id", "handoff-x",
        "--executor", "block", "--profile", "runtime",
    ])
    assert status == 2
    assert "requires --suite and --fixture" in capsys.readouterr().err
    assert not (results_root / "handoff-x").exists()
