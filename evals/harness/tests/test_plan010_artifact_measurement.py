"""Hermetic contract tests for the Plan 010 boundary measurement."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "measure-plan010-artifact-path.py"
SPEC = importlib.util.spec_from_file_location("plan010_artifact_measurement", SCRIPT)
measurement = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = measurement
assert SPEC.loader is not None
SPEC.loader.exec_module(measurement)


def _invocations(spec):
    result = []
    for phase, count in measurement._expected_invocation_breakdown(spec).items():
        result.extend(
            {"phase": phase, "status": "bounded", "returncode": 0}
            for _index in range(count)
        )
    return result


def _passing_record(spec, ceilings):
    exact = measurement._exact_expectations(spec)
    metrics = {
        **exact,
        "certification_wall_seconds": 1.0,
        "wall_time_seconds": 2.0,
        "max_observed_process_rss_bytes": 1024,
        "synthesized_bytes": spec.runtime_bytes + 1024,
        "authenticated_sandbox_output": True,
        "gate_checks": [
            {"id": check_id, "status": "pass"}
            for check_id in measurement.EXPECTED_GATE_CHECKS
        ],
        "artifact_proof_digest": "a" * 64,
        "bound_artifact_digest": "a" * 64,
        "runtime_artifact_digest": "a" * 64,
        "execution_proof_digest": "b" * 64,
        "runtime_execution_proof_digest": "b" * 64,
        "bounded_invocations": _invocations(spec),
        "hold_entries": measurement.EXPECTED_HOLD_BREAKDOWN.copy(),
        "hold_exits": measurement.EXPECTED_HOLD_BREAKDOWN.copy(),
        "streamed_copies": {
            "scan_handoff": {
                "members": exact["runtime_entries"], "bytes": spec.runtime_bytes
            },
            "runtime_stream": {
                "members": exact["runtime_entries"], "bytes": spec.runtime_bytes
            },
            "php_scanner_alias": {
                "members": 2 * spec.php_candidate_count,
                "bytes": 2 * spec.php_candidate_bytes,
            },
        },
        "full_tree_materialization_attempts": 0,
    }
    cleanup = {
        "gate_handoff_0": {
            "state": "removed", "exists": False, "live": False, "error": None
        }
    }
    return {"metrics": metrics, "cleanup": cleanup}


@pytest.mark.parametrize(
    ("spec", "ceilings"), measurement.CI_PROFILES,
    ids=lambda item: item.name if hasattr(item, "name") else None,
)
def test_profile_fixture_arithmetic_is_exact(tmp_path, spec, ceilings):
    source, output = measurement._write_fixture(tmp_path, spec)
    files = [path for path in output.rglob("*") if path.is_file()]
    assert len(files) == spec.entry_count
    assert sum(path.stat().st_size for path in files) == spec.output_bytes
    metadata = output / "blocks" / "card" / "build" / "block.json"
    assert metadata.stat().st_size == spec.metadata_bytes
    value = json.loads(metadata.read_text(encoding="utf-8"))
    assert measurement.plan010_measurement_fixture.json_depth(value) == spec.metadata_depth
    assert source.joinpath("blocks/card/block.json").is_file()
    assert measurement.assess(
        _passing_record(spec, ceilings), spec, ceilings
    )["status"] == "pass"


def test_assess_rejects_missing_or_false_observations():
    spec, ceilings = measurement.CI_PROFILES[0]
    cases = []
    record = _passing_record(spec, ceilings)
    record["metrics"].pop("max_observed_process_rss_bytes")
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["metrics"]["certification_wall_seconds"] = 181.0
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["metrics"]["gate_checks"][5]["status"] = "blocked"
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["metrics"]["bounded_invocations"].pop()
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["metrics"]["bounded_invocations"][0]["status"] = "blocked"
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["metrics"]["bound_artifact_digest"] = "c" * 64
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["metrics"]["full_tree_materialization_attempts"] = 1
    cases.append(record)
    record = _passing_record(spec, ceilings)
    record["cleanup"]["gate_handoff_0"]["exists"] = True
    cases.append(record)
    for case in cases:
        assessed = measurement.assess(copy.deepcopy(case), spec, ceilings)
        assert assessed["status"] == "fail"
        assert assessed["violations"]


def test_failed_measurement_preserves_cleanup_receipts(tmp_path, monkeypatch):
    spec, ceilings = measurement.CI_PROFILES[1]

    def fail_boundary(*_args, **_kwargs):
        raise RuntimeError("forced measurement failure")

    monkeypatch.setattr(measurement, "_run_boundary", fail_boundary)
    record = measurement.measure(spec, ceilings, tmp_path)
    assert record["status"] == "fail"
    assert record["error"]["detail"] == "forced measurement failure"
    assert set(record["cleanup"]) == {"sandbox_output", "source_input"}
    assert all(item["state"] == "removed" for item in record["cleanup"].values())


def test_main_uses_repo_local_temporary_parent(tmp_path, monkeypatch):
    observed = {}

    class Temporary:
        def __init__(self, *, prefix, dir):
            observed.update({"prefix": prefix, "dir": dir})

        def __enter__(self):
            return str(tmp_path)

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(measurement.tempfile, "TemporaryDirectory", Temporary)
    monkeypatch.setattr(
        measurement,
        "measure_profiles",
        lambda _profiles, _parent: {"status": "pass"},
    )
    output = tmp_path / "record.json"
    assert measurement.main(["--profile", "aggregate", "--output", str(output)]) == 0
    assert observed["dir"] == measurement.ROOT / "tmp"
    assert observed["dir"].resolve() == observed["dir"]
