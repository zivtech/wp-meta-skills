"""Focused contract tests for isolated built-block artifact evidence."""
from __future__ import annotations

import sys
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import isolated_runtime_contract as contract
from wp_runtime_types import BlockRuntimeAssertion, RuntimeResult


INPUT_DIGEST = "a" * 64
MANIFEST_DIGEST = "b" * 64
EXECUTION_DIGEST = "c" * 64
BLOCK_ASSERTION = BlockRuntimeAssertion(
    "acme/runtime-card", ".wp-block-acme-runtime-card", "Exact runtime text",
)
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


def _gate(status: str, check_id: str, digest: str | None = None) -> dict:
    gate = {"status": status, "pass": status == "pass", "checks": [
        {"id": check_id, "status": status, "required": True},
    ]}
    if digest is not None:
        gate["execution_proof_digest"] = digest
    return gate


def _adapt_block(**changes) -> dict:
    options = {
        "artifact_kind": "block",
        "expected_manifest_digest": MANIFEST_DIGEST,
        "block_build_requested": True,
        "block_build_gate": _gate("pass", "npm_build"),
        "block_runtime_artifact_requested": True,
        "block_runtime_artifact_gate": _gate(
            "pass", "runtime_artifact", EXECUTION_DIGEST,
        ),
        "execution_proof_digest": EXECUTION_DIGEST,
        "phpunit_requested": False,
    }
    options.update(changes)
    return contract.adapt_runtime_result(_runtime(), _request(), **options)


def _persisted_block() -> dict:
    services, created, networks = _persisted_topology()
    checks = [
        {"id": check_id, "status": "pass", "required": True, "duration_sec": 0.1}
        for check_id in contract.REQUIRED_CHECKS_BY_PROFILE[contract.BLOCK_PROFILE]
    ]
    text_digest = hashlib.sha256(BLOCK_ASSERTION.expected_frontend_text.encode()).hexdigest()
    checks[-1]["proof"] = {
        "status": "pass", "block_name": BLOCK_ASSERTION.block_name,
        "frontend_selector": BLOCK_ASSERTION.frontend_selector,
        "expected_text_sha256": text_digest, "observed_text_sha256": text_digest,
        "match_count": 1, "visible": True,
        "normalization": "unicode-nfc-whitespace-collapse-trim",
    }
    checks.append({"id": "runtime_identity", "status": "pass", "required": True})
    return {
        "schema_version": 1, "run_id": "run", "evidence_id": "evidence",
        "artifact_kind": "block", "input_artifact_digest": INPUT_DIGEST,
        "runtime_pre_command_manifest_digest": MANIFEST_DIGEST,
        "post_command_manifest_digest": MANIFEST_DIGEST,
        "runtime_profile_id": contract.BLOCK_PROFILE,
        "status": "pass", "pass": True, "checks": checks,
        "block_build_smoke_requested": True, "block_build_smoke_status": "pass",
        "block_build_gate": {"status": "pass"},
        "block_runtime_artifact_requested": True,
        "block_runtime_artifact_gate_status": "pass",
        "block_runtime_artifact_gate": _persisted_artifact_gate(),
        "execution_proof_digest": EXECUTION_DIGEST,
        "provision_full_profile": True, "strict_full_profile": True,
        "inspection": {
            "normalized": {"services": sorted(services),
                           "images": {name: value["image"] for name, value in services.items()},
                           "networks": ["application", "backend", "frontend"]},
            "created": {"services": created, "networks": {}, "require_running": False},
            "started": {"services": services, "networks": networks, "require_running": True},
            "post_oracle": {"services": copy.deepcopy(services),
                            "networks": copy.deepcopy(networks), "require_running": True},
            "artifact_seal": {"component": "runtime_artifact_image", "state": "sealed",
                              "seed_started": False, "seed_removed": True,
                              "artifact_mounts": 0, "base_image": "sha256:wordpress",
                              "derived_image": "sha256:derived"},
        },
        "cleanup": _persisted_cleanup(),
        "artifact_execution_retained": False,
        "artifact_retention": {"retained": False, "resources": [
            {"component": component, "state": "removed", "exists": False,
             "live": False, "resource_path": f"/tmp/{component}",
             "error": None, "recovery_path": None}
            for component in ("input_copy", "synthesized_runtime", "sandbox_output", "scan_handoff")
        ]},
        "sandbox_posture": {"host_fallback": False, "static_scan_root": "staged_copy",
                            "generated_execution": {"php": "pass", "browser": "pass",
                                                    "npm_build": "pass",
                                                    "block_runtime_artifact": "pass"}},
        "full_plugin_runtime_profile": {"status": "pass", "pass": True, "checks": [
            {"id": "phpcs_wpcs", "status": "pass", "required": True},
            {"id": "plugin_check", "status": "pass", "required": True},
            {"id": "wp_env_smoke", "status": "pass", "required": True},
        ]},
    }


def _persisted_topology():
    service_networks = contract.SERVICE_NETWORKS
    services = {
        name: {"id": f"id-{name}", "image": f"sha256:{name}", "mounts": [],
               "networks": [f"project_{network}" for network in networks],
               "addresses": {f"project_{network}": "172.20.0.2" for network in networks},
               "seccomp": 2}
        for name, networks in service_networks.items()
    }
    created = copy.deepcopy(services)
    for service in created.values():
        service.pop("seccomp")
        service["addresses"] = {name: "" for name in service["networks"]}
    networks = {
        f"project_{network}": {"id": f"id-{network}", "internal": True,
            "members": sorted(service["id"] for name, service in services.items()
                              if network in service_networks[name]),
            "gateway": [], "gateway_mode": "isolated", "subnet": "172.20.0.0/24"}
        for network in contract.RUNTIME_NETWORKS
    }
    return services, created, networks


def _persisted_cleanup():
    return {
        "compose": {"component": "compose", "state": "removed", "errors": [],
                    "remaining": {"containers": [], "networks": [], "volumes": []},
                    "recovery": []},
        "images": {"component": "runtime_images", "state": "removed", "error": None,
                   "remaining": [], "recovery": []},
        "export": {"component": "runtime_artifact_image", "state": "released",
                   "error": None, "recovery": None},
        "workspace": {"component": "runtime_workspace", "state": "removed", "error": None},
    }


def _persisted_artifact_gate():
    return {
        "schema": "wp-meta-skills/block-execution-artifact-gate", "schema_version": 1,
        "id": "block_runtime_artifact_gate", "status": "pass", "blocked_reason": None,
        "checks": [{"id": "execution_graph", "status": "pass", "detail": "passed"}],
        "selected_root": "blocks/runtime-card/build",
        "selected_block_json": "blocks/runtime-card/build/block.json",
        "selection_reason": "built_block_json", "edges": [], "files": [], "scan_files": [],
        "scanner_aliases": [], "scanner_evidence": {},
        "component_digests": {"metadata_graph": "5" * 64, "php_set": "6" * 64,
                              "scanner_aliases": "7" * 64, "artifact": "d" * 64},
        "artifact_proof_digest": "d" * 64, "output_manifest_sha256": "2" * 64,
        "source_manifest_sha256": "3" * 64,
        "core": {"version": "6.8.2", "archive_sha256": "8" * 64,
                 "blocks_php_sha256": "9" * 64},
        "rule_digest": "4" * 64, "wrapper_path": "runtime-card/runtime-card.php",
        "wrapper_size": 400, "wrapper_sha256": "e" * 64,
        "wrapper_validation_digest": "f" * 64,
        "wrapper_checks": [{"id": "bootstrap_exact", "status": "pass"},
                           {"id": "php_syntax", "status": "pass"}],
        "synthesized_manifest_sha256": "1" * 64,
        "execution_proof_digest": EXECUTION_DIGEST,
    }


def _persisted_errors(data: dict, expected: str | None = EXECUTION_DIGEST) -> list[str]:
    return contract.persisted_runtime_errors(
        data, run_id="run", evidence_id="evidence", artifact_kind=data["artifact_kind"],
        input_digest=INPUT_DIGEST, expected_profile=data["runtime_profile_id"],
        execution_proof_digest=expected,
        block_assertion=BLOCK_ASSERTION if data["artifact_kind"] == "block" else None,
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
        block_runtime_artifact_gate=_gate(
            "pass", "runtime_artifact", EXECUTION_DIGEST,
        ),
    )
    artifact_failed = _adapt_block(
        block_runtime_artifact_gate=_gate("fail", "runtime_artifact"),
    )
    assert blocked["status"] == "blocked" and blocked["pass"] is False
    assert failed["status"] == "fail" and failed["pass"] is False
    assert artifact_failed["status"] == "fail" and artifact_failed["pass"] is False


def test_missing_or_non_lowercase_execution_digest_blocks_green():
    assert _adapt_block(execution_proof_digest=None)["status"] == "blocked"
    uppercase = _adapt_block(execution_proof_digest="C" * 64)
    assert uppercase["status"] == "blocked" and uppercase["pass"] is False


def test_live_contract_requires_gate_and_result_digest_equality():
    missing = _adapt_block(
        block_runtime_artifact_gate=_gate("pass", "runtime_artifact")
    )
    mismatch = _adapt_block(
        block_runtime_artifact_gate=_gate(
            "pass", "runtime_artifact", "d" * 64,
        )
    )
    assert missing["status"] == "blocked" and missing["pass"] is False
    assert mismatch["status"] == "blocked" and mismatch["pass"] is False


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

    missing_gate_digest = _persisted_block()
    missing_gate_digest["block_runtime_artifact_gate"].pop("execution_proof_digest")
    assert "execution proof digest mismatch" in _persisted_errors(missing_gate_digest)

    mismatched_gate_digest = _persisted_block()
    mismatched_gate_digest["block_runtime_artifact_gate"][
        "execution_proof_digest"
    ] = "d" * 64
    assert "execution proof digest mismatch" in _persisted_errors(mismatched_gate_digest)

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

    nonbuilt_block = contract.adapt_runtime_result(
        _runtime(), _request(), artifact_kind="block",
        expected_manifest_digest=MANIFEST_DIGEST, block_build_requested=False,
        block_build_gate=None, phpunit_requested=False,
    )
    assert nonbuilt_block["status"] == "pass"
    assert nonbuilt_block["block_runtime_artifact_requested"] is False
    assert nonbuilt_block["block_runtime_artifact_gate_status"] == "not_run"
    assert nonbuilt_block["execution_proof_digest"] is None

    persisted = _persisted_block()
    persisted["artifact_kind"] = "plugin"
    persisted["runtime_profile_id"] = contract.STANDARD_PROFILE
    persisted["checks"] = [
        *[dict(check) for check in RUNTIME_CHECKS],
        {"id": "runtime_identity", "status": "pass", "required": True},
    ]
    for field in (
        "block_runtime_artifact_requested", "block_runtime_artifact_gate_status",
        "block_runtime_artifact_gate", "execution_proof_digest",
    ):
        persisted.pop(field)
    assert _persisted_errors(persisted, expected=None) == []
