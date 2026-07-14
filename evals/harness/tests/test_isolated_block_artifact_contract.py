"""Focused contract tests for isolated built-block artifact evidence."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import isolated_runtime_contract as contract
from wp_runtime_types import RuntimeResult


INPUT_DIGEST = "a" * 64
MANIFEST_DIGEST = "b" * 64
EXECUTION_DIGEST = "c" * 64
RUNTIME_CHECKS = (
    {"id": "wp_cli_activation", "status": "pass", "required": True,
     "duration_sec": 0.1},
    {"id": "plugin_check", "status": "pass", "required": True,
     "duration_sec": 0.2},
    {"id": "container_browser", "status": "pass", "required": True,
     "duration_sec": 0.3},
)


def _request():
    return SimpleNamespace(evidence_id="evidence", input_artifact_digest=INPUT_DIGEST)


def _runtime() -> RuntimeResult:
    return RuntimeResult(
        status="pass", evidence_id="evidence", input_artifact_digest=INPUT_DIGEST,
        post_command_manifest_digest=MANIFEST_DIGEST, checks=RUNTIME_CHECKS,
    )


def _gate(status: str, check_id: str) -> dict:
    return {"status": status, "pass": status == "pass", "checks": [
        {"id": check_id, "status": status, "required": True},
    ]}


def _adapt_block(**changes) -> dict:
    options = {
        "artifact_kind": "block",
        "expected_manifest_digest": MANIFEST_DIGEST,
        "block_build_requested": True,
        "block_build_gate": _gate("pass", "npm_build"),
        "block_runtime_artifact_requested": True,
        "block_runtime_artifact_gate": _gate("pass", "runtime_artifact"),
        "execution_proof_digest": EXECUTION_DIGEST,
        "phpunit_requested": False,
    }
    options.update(changes)
    return contract.adapt_runtime_result(_runtime(), _request(), **options)


def _persisted_block() -> dict:
    checks = [dict(check) for check in RUNTIME_CHECKS]
    checks.append({"id": "runtime_identity", "status": "pass", "required": True})
    return {
        "schema_version": 1, "run_id": "run", "evidence_id": "evidence",
        "artifact_kind": "block", "input_artifact_digest": INPUT_DIGEST,
        "runtime_pre_command_manifest_digest": MANIFEST_DIGEST,
        "post_command_manifest_digest": MANIFEST_DIGEST,
        "runtime_profile_id": contract.STANDARD_PROFILE,
        "status": "pass", "pass": True, "checks": checks,
        "block_runtime_artifact_requested": True,
        "block_runtime_artifact_gate_status": "pass",
        "block_runtime_artifact_gate": _gate("pass", "runtime_artifact"),
        "execution_proof_digest": EXECUTION_DIGEST,
        "full_plugin_runtime_profile": {"status": "pass", "pass": True, "checks": [
            {"id": "phpcs_wpcs", "status": "pass", "required": True},
            {"id": "plugin_check", "status": "pass", "required": True},
            {"id": "wp_env_smoke", "status": "pass", "required": True},
        ]},
    }


def _persisted_errors(data: dict, expected: str | None = EXECUTION_DIGEST) -> list[str]:
    return contract.persisted_runtime_errors(
        data, run_id="run", evidence_id="evidence", artifact_kind=data["artifact_kind"],
        input_digest=INPUT_DIGEST, execution_proof_digest=expected,
    )


def test_built_block_requires_both_separate_gates_and_exact_digest():
    result = _adapt_block()
    assert result["status"] == "pass" and result["pass"] is True
    assert result["block_build_smoke_status"] == "pass"
    assert result["block_runtime_artifact_gate_status"] == "pass"
    assert result["block_runtime_artifact_gate"]["checks"][0]["id"] == "runtime_artifact"
    assert result["execution_proof_digest"] == EXECUTION_DIGEST


def test_dual_gate_status_preserves_blocked_over_fail_precedence():
    blocked = _adapt_block(
        block_build_gate=_gate("fail", "npm_build"),
        block_runtime_artifact_gate=_gate("blocked", "runtime_artifact"),
    )
    failed = _adapt_block(
        block_build_gate=_gate("fail", "npm_build"),
        block_runtime_artifact_gate=_gate("pass", "runtime_artifact"),
    )
    assert blocked["status"] == "blocked" and blocked["pass"] is False
    assert failed["status"] == "fail" and failed["pass"] is False


def test_missing_or_non_lowercase_execution_digest_blocks_green():
    assert _adapt_block(execution_proof_digest=None)["status"] == "blocked"
    uppercase = _adapt_block(execution_proof_digest="C" * 64)
    assert uppercase["status"] == "blocked" and uppercase["pass"] is False


def test_artifact_request_without_build_request_is_inconsistent_and_blocked():
    result = _adapt_block(block_build_requested=False, block_build_gate=None)
    assert result["status"] == "blocked"
    assert result["block_build_smoke_status"] == "not_run"


def test_stopped_result_keeps_both_gates_digest_and_receipts():
    receipts = [{"component": "sandbox_output", "state": "removed"}]
    result = contract.stopped_block_prerequisite_result(
        artifact_kind="block", digest=INPUT_DIGEST,
        build_gate=_gate("fail", "npm_build"),
        runtime_artifact_gate=_gate("blocked", "runtime_artifact"),
        execution_proof_digest=EXECUTION_DIGEST, receipts=receipts,
        phpunit_requested=False,
    )
    assert result["status"] == "fail" and result["pass"] is False
    assert result["block_build_smoke_status"] == "fail"
    assert result["block_runtime_artifact_gate_status"] == "not_run"
    assert result["execution_proof_digest"] == EXECUTION_DIGEST
    assert result["_artifact_retention_receipts"] is receipts


def test_stopped_build_wrapper_preserves_pre_artifact_callers():
    result = contract.stopped_build_result(
        artifact_kind="block", digest=INPUT_DIGEST,
        gate=_gate("fail", "npm_build"), receipts=[], phpunit_requested=False,
    )
    assert result["status"] == "fail"
    assert result["block_runtime_artifact_requested"] is False
    assert result["block_runtime_artifact_gate_status"] == "not_run"


def test_persisted_block_requires_exact_digest_and_passing_artifact_gate():
    data = _persisted_block()
    assert _persisted_errors(data) == []

    missing = _persisted_block()
    missing.pop("execution_proof_digest")
    assert "execution proof digest mismatch" in _persisted_errors(missing)

    mismatch = _persisted_block()
    mismatch["execution_proof_digest"] = "d" * 64
    assert "execution proof digest mismatch" in _persisted_errors(mismatch)

    failed = _persisted_block()
    failed["block_runtime_artifact_gate"] = _gate("fail", "runtime_artifact")
    assert "block runtime artifact gate did not pass" in _persisted_errors(failed)


def test_plugin_and_nonbuilt_results_do_not_require_artifact_proof():
    adapted = contract.adapt_runtime_result(
        _runtime(), _request(), artifact_kind="plugin",
        expected_manifest_digest=MANIFEST_DIGEST, block_build_requested=False,
        block_build_gate=None, phpunit_requested=False,
    )
    assert adapted["status"] == "pass"
    assert adapted["block_runtime_artifact_requested"] is False
    assert adapted["block_runtime_artifact_gate_status"] == "not_run"
    assert adapted["execution_proof_digest"] is None

    persisted = _persisted_block()
    persisted["artifact_kind"] = "plugin"
    for field in (
        "block_runtime_artifact_requested", "block_runtime_artifact_gate_status",
        "block_runtime_artifact_gate", "execution_proof_digest",
    ):
        persisted.pop(field)
    assert _persisted_errors(persisted, expected=None) == []
