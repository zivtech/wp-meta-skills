"""Exact producer/consumer tests for isolated runtime evidence."""
from __future__ import annotations

import sys
import hashlib
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import isolated_runtime_contract as contract
import wp_runtime_topology as topology
from wp_runtime_types import BlockRuntimeAssertion, RuntimeResult


DIGEST = "a" * 64
MANIFEST = "b" * 64
CHECKS = (
    {"id": "wp_cli_activation", "status": "pass", "required": True, "duration_sec": 0.1},
    {"id": "plugin_check", "status": "pass", "required": True, "duration_sec": 0.2},
    {"id": "container_browser", "status": "pass", "required": True, "duration_sec": 0.3},
)
PERSISTED_CHECKS = (*CHECKS, {"id": "runtime_identity", "status": "pass", "required": True})


def _request():
    return SimpleNamespace(evidence_id="evidence", input_artifact_digest=DIGEST)


def _runtime(**changes):
    values = {
        "status": "pass", "evidence_id": "evidence", "input_artifact_digest": DIGEST,
        "post_command_manifest_digest": MANIFEST, "checks": CHECKS,
    }
    values.update(changes)
    return RuntimeResult(**values)


def _adapt(runtime=None, **changes):
    options = {
        "artifact_kind": "plugin", "expected_manifest_digest": MANIFEST,
        "block_build_requested": False, "block_build_gate": None,
        "phpunit_requested": False,
    }
    options.update(changes)
    return contract.adapt_runtime_result(runtime or _runtime(), _request(), **options)


def test_exact_identity_and_both_isolated_oracles_are_required_for_green():
    result = _adapt()
    assert result["status"] == "pass" and result["pass"] is True
    assert result["runtime_pre_command_manifest_digest"] == MANIFEST
    assert result["post_command_manifest_digest"] == MANIFEST
    assert result["wp_cli_activation_status"] == "pass"
    assert result["container_browser_status"] == "pass"
    assert result["runtime_profile_id"] == contract.STANDARD_PROFILE
    assert tuple(result["required_runtime_checks"]) == contract.REQUIRED_ORACLE_CHECKS


def test_identity_mismatch_and_missing_oracle_cannot_false_green():
    identity = _adapt(_runtime(evidence_id="forged"))
    missing = _adapt(_runtime(checks=CHECKS[:1]))
    assert identity["status"] == "blocked" and identity["pass"] is False
    assert missing["status"] == "blocked" and missing["container_browser_status"] == "blocked"


def test_requested_gate_order_is_blocked_then_fail_then_pass():
    runtime = _runtime(status="fail", checks=(
        {"id": "wp_cli_activation", "status": "fail"},
        {"id": "container_browser", "status": "blocked"},
    ))
    result = _adapt(runtime)
    assert result["status"] == "blocked"
    assert contract.dominant_status(["pass", "fail"]) == "fail"


def test_phpunit_gate_is_required_and_artifact_kind_is_preserved():
    result = _adapt(
        artifact_kind="block", block_build_requested=True,
        block_build_gate={"status": "pass", "checks": []}, phpunit_requested=True,
        phpunit_gate={"status": "pass", "pass": True, "checks": [
            {"id": "phpunit", "status": "pass", "required": True},
        ]},
    )
    assert result["status"] == "pass" and result["artifact_kind"] == "block"
    assert result["block_build_smoke_status"] == "pass"
    assert result["phpunit_smoke_status"] == "pass"
    assert result["phpunit_gate"]["checks"][0]["id"] == "phpunit"


def test_requested_phpunit_without_exact_gate_blocks():
    result = _adapt(phpunit_requested=True)
    assert result["status"] == "blocked" and result["phpunit_smoke_status"] == "blocked"


def test_full_profile_combines_trusted_wpcs_and_isolated_runtime():
    result = _adapt(
        full_profile_requested=True,
        wpcs_gate={"status": "pass", "pass": True, "checks": [
            {"id": "phpcs_wpcs", "status": "pass", "required": True},
        ]},
        trusted_provisioning={"composer_install": {"returncode": 0}},
    )
    assert result["status"] == "pass"
    assert result["full_plugin_runtime_profile"]["status"] == "pass"
    assert [check["id"] for check in result["full_plugin_runtime_profile"]["checks"]] == [
        "phpcs_wpcs", "plugin_check", "wp_env_smoke",
    ]
    assert "not WPCS proof" not in result["negative_space"]


def test_full_profile_cannot_ignore_a_blocked_parent_wpcs_gate():
    result = _adapt(
        full_profile_requested=True,
        wpcs_gate={"status": "blocked", "pass": False, "checks": [
            {"id": "phpcs_wpcs", "status": "pass", "required": True},
        ]},
    )
    assert result["status"] == "blocked" and result["pass"] is False
    assert result["full_plugin_runtime_profile"]["checks"][0]["status"] == "blocked"


def _persisted():
    services = {
        name: {
            "id": f"id-{name}", "image": f"sha256:{name}", "mounts": [],
            "networks": [f"project_{network}" for network in networks],
            "addresses": {
                f"project_{network}": f"172.20.0.{index + 2}"
                for index, network in enumerate(networks)
            },
            "seccomp": 2,
        }
        for name, networks in topology.SERVICE_NETWORKS.items()
    }
    created = copy.deepcopy(services)
    for service in created.values():
        service.pop("seccomp")
        service["addresses"] = {name: "" for name in service["networks"]}
    networks = {
        f"project_{network}": {
            "id": f"id-{network}", "internal": True,
            "members": sorted(
                service["id"] for name, service in services.items()
                if network in topology.SERVICE_NETWORKS[name]
            ),
            "gateway": [], "gateway_mode": "isolated",
            "subnet": f"172.{20 + index}.0.0/24",
        }
        for index, network in enumerate(("backend", "application", "frontend"))
    }
    return {
        "schema_version": 1, "run_id": "run", "evidence_id": "evidence",
        "artifact_kind": "plugin", "input_artifact_digest": DIGEST,
        "runtime_pre_command_manifest_digest": MANIFEST,
        "post_command_manifest_digest": MANIFEST, "status": "pass", "pass": True,
        "checks": [dict(check) for check in PERSISTED_CHECKS],
        "provision_full_profile": True, "strict_full_profile": True,
        "inspection": {
            "normalized": {"services": sorted(services),
                           "images": {name: value["image"] for name, value in services.items()},
                           "networks": ["application", "backend", "frontend"]},
            "created": {"services": created, "networks": {}, "require_running": False},
            "started": {"services": services, "networks": networks,
                        "require_running": True},
            "post_oracle": {"services": copy.deepcopy(services),
                            "networks": copy.deepcopy(networks),
                            "require_running": True},
            "artifact_seal": {
                "component": "runtime_artifact_image", "state": "sealed",
                "seed_started": False, "seed_removed": True, "artifact_mounts": 0,
                "base_image": "sha256:wordpress", "derived_image": "sha256:derived",
            },
        },
        "cleanup": {
            "compose": {"component": "compose", "state": "removed", "errors": [],
                        "remaining": {"containers": [], "networks": [], "volumes": []},
                        "recovery": []},
            "images": {"component": "runtime_images", "state": "removed",
                       "error": None, "remaining": [], "recovery": []},
            "export": {"component": "runtime_artifact_image", "state": "released",
                       "error": None, "recovery": None},
            "workspace": {"component": "runtime_workspace", "state": "removed",
                          "error": None},
        },
        "artifact_execution_retained": False,
        "artifact_retention": {"retained": False, "resources": [
            {"component": component, "state": "removed", "exists": False,
             "live": False, "resource_path": f"/tmp/{component}",
             "error": None, "recovery_path": None}
            for component in ("input_copy", "synthesized_runtime")
        ]},
        "sandbox_posture": {"host_fallback": False, "static_scan_root": "staged_copy",
                            "generated_execution": {"php": "pass", "browser": "pass"}},
        "full_plugin_runtime_profile": {"status": "pass", "pass": True, "checks": [
            {"id": "phpcs_wpcs", "status": "pass", "required": True},
            {"id": "plugin_check", "status": "pass", "required": True},
            {"id": "wp_env_smoke", "status": "pass", "required": True},
        ]},
    }


def test_repair_consumer_requires_exact_identity_manifest_and_oracles():
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="plugin", input_digest=DIGEST)
    assert contract.persisted_runtime_errors(_persisted(), **expected) == []
    for field, bad in (
        ("evidence_id", "stale"), ("input_artifact_digest", "0" * 64),
        ("post_command_manifest_digest", "0" * 64),
    ):
        data = _persisted(); data[field] = bad
        assert contract.persisted_runtime_errors(data, **expected)
    data = _persisted(); data["checks"] = [PERSISTED_CHECKS[0], PERSISTED_CHECKS[1], PERSISTED_CHECKS[3]]
    assert "container_browser did not pass" in contract.persisted_runtime_errors(data, **expected)


def test_requested_profiles_have_exact_distinct_check_registries():
    assert contract.profile_for_requested(contract.STANDARD_REQUESTED_ORACLES) == "standard"
    assert contract.profile_for_requested(contract.ADVERSARIAL_REQUESTED_ORACLES) == "adversarial-test"
    assert contract.REQUIRED_CHECKS_BY_PROFILE["standard"] == (
        "wp_cli_activation", "plugin_check", "container_browser",
    )
    assert "generated_php_canary" in contract.REQUIRED_CHECKS_BY_PROFILE["adversarial-test"]
    assert "generated_browser_editor_js" in contract.REQUIRED_CHECKS_BY_PROFILE["adversarial-test"]


def test_producer_and_persisted_consumer_reject_check_inventory_drift():
    with pytest.raises(RuntimeError, match="inventory drift"):
        contract.require_exact_profile_checks(
            contract.STANDARD_PROFILE,
            (*CHECKS, {"id": "unregistered", "status": "pass", "required": True}),
        )
    data = _persisted()
    data["runtime_profile_id"] = contract.STANDARD_PROFILE
    data["checks"].append({"id": "unregistered", "status": "pass", "required": True})
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="plugin", input_digest=DIGEST)
    assert "runtime check inventory mismatch" in contract.persisted_runtime_errors(data, **expected)


def test_producer_adapter_and_consumer_require_finite_nonnegative_durations():
    missing = tuple({key: value for key, value in check.items() if key != "duration_sec"}
                    for check in CHECKS)
    with pytest.raises(RuntimeError, match="timing drift"):
        contract.require_exact_profile_checks(contract.STANDARD_PROFILE, missing)
    assert _adapt(_runtime(checks=missing))["status"] == "blocked"
    data = _persisted()
    data["checks"][0]["duration_sec"] = float("nan")
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="plugin", input_digest=DIGEST)
    assert "runtime check timing evidence invalid" in contract.persisted_runtime_errors(
        data, **expected,
    )


def test_adversarial_persisted_profile_requires_every_named_check():
    checks = [
        {"id": check_id, "status": "pass", "required": True, "duration_sec": 0.1}
        for check_id in contract.REQUIRED_CHECKS_BY_PROFILE[contract.ADVERSARIAL_PROFILE]
    ]
    data = _persisted()
    data["runtime_profile_id"] = contract.ADVERSARIAL_PROFILE
    data["checks"] = [*checks, {"id": "runtime_identity", "status": "pass", "required": True}]
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="plugin", input_digest=DIGEST)
    assert contract.persisted_runtime_errors(data, **expected) == []
    data["checks"] = data["checks"][:-2] + data["checks"][-1:]
    missing = contract.REQUIRED_CHECKS_BY_PROFILE[contract.ADVERSARIAL_PROFILE][-1]
    assert f"{missing} did not pass" in contract.persisted_runtime_errors(data, **expected)


def _block_assertion():
    return BlockRuntimeAssertion(
        "acme/runtime-card", ".wp-block-acme-runtime-card", "Exact runtime text"
    )


def _block_persisted():
    data = _persisted()
    assertion = _block_assertion()
    text_hash = hashlib.sha256(assertion.expected_frontend_text.encode()).hexdigest()
    proof = {
        "status": "pass", "block_name": assertion.block_name,
        "frontend_selector": assertion.frontend_selector,
        "expected_text_sha256": text_hash, "observed_text_sha256": text_hash,
        "match_count": 1, "visible": True,
        "normalization": "unicode-nfc-whitespace-collapse-trim",
    }
    data.update({
        "artifact_kind": "block", "runtime_profile_id": contract.BLOCK_PROFILE,
        "checks": [
            {"id": "wp_cli_activation", "status": "pass", "duration_sec": 0.1},
            {"id": "plugin_check", "status": "pass", "duration_sec": 0.1},
            {"id": "block_registration", "status": "pass", "duration_sec": 0.1},
            {"id": "container_browser", "status": "pass", "duration_sec": 0.1},
            {"id": "block_editor_frontend", "status": "pass", "duration_sec": 0.1,
             "proof": proof},
            {"id": "runtime_identity", "status": "pass"},
        ],
        "block_build_smoke_requested": True, "block_build_smoke_status": "pass",
        "block_build_gate": {"status": "pass"},
        "block_runtime_artifact_requested": True,
        "block_runtime_artifact_gate_status": "pass", "execution_proof_digest": "c" * 64,
        "block_runtime_artifact_gate": {
            "schema": "wp-meta-skills/block-execution-artifact-gate", "schema_version": 1,
            "id": "block_runtime_artifact_gate", "status": "pass",
            "blocked_reason": None,
            "checks": [{"id": "execution_graph", "status": "pass", "detail": "passed"}],
            "execution_proof_digest": "c" * 64, "artifact_proof_digest": "d" * 64,
            "wrapper_sha256": "e" * 64, "wrapper_validation_digest": "f" * 64,
            "synthesized_manifest_sha256": "1" * 64,
            "output_manifest_sha256": "2" * 64, "source_manifest_sha256": "3" * 64,
            "rule_digest": "4" * 64,
            "core": {"version": "6.8.2", "archive_sha256": "8" * 64,
                     "blocks_php_sha256": "9" * 64},
            "selected_root": "blocks/runtime-card/build",
            "selected_block_json": "blocks/runtime-card/build/block.json",
            "selection_reason": "built_block_json", "edges": [], "files": [],
            "scan_files": [], "scanner_aliases": [], "scanner_evidence": {},
            "component_digests": {
                "metadata_graph": "5" * 64, "php_set": "6" * 64,
                "scanner_aliases": "7" * 64, "artifact": "d" * 64,
            },
            "wrapper_path": "runtime-card/runtime-card.php", "wrapper_size": 400,
            "wrapper_checks": [
                {"id": "bootstrap_exact", "status": "pass"},
                {"id": "php_syntax", "status": "pass"},
            ],
        },
    })
    data["artifact_retention"]["resources"].extend([
        {"component": component, "state": "removed", "exists": False, "live": False,
         "resource_path": f"/tmp/{component}", "error": None, "recovery_path": None}
        for component in ("sandbox_output", "scan_handoff")
    ])
    data["sandbox_posture"]["generated_execution"].update({
        "npm_build": "pass", "block_runtime_artifact": "pass",
    })
    return data, assertion


def test_block_persisted_consumer_requires_exact_profile_proof_and_cleanup():
    data, assertion = _block_persisted()
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="block",
                    input_digest=DIGEST, block_assertion=assertion)
    assert contract.persisted_runtime_errors(data, **expected) == []
    mutations = []
    for key, value in (("match_count", 2), ("visible", False),
                       ("observed_text_sha256", "0" * 64)):
        changed = copy.deepcopy(data)
        changed["checks"][4]["proof"][key] = value
        mutations.append(changed)
    changed = copy.deepcopy(data)
    changed["checks"][4]["proof"]["extra"] = True
    mutations.append(changed)
    for changed in mutations:
        assert "block editor/frontend proof mismatch" in contract.persisted_runtime_errors(
            changed, **expected,
        )


@pytest.mark.parametrize("status", ("fail", "blocked"))
def test_block_persisted_consumer_never_certifies_nonpass(status):
    data, assertion = _block_persisted()
    data["status"] = status
    data["pass"] = False
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="block",
                    input_digest=DIGEST, block_assertion=assertion)
    assert "top-level runtime status did not pass" in contract.persisted_runtime_errors(
        data, **expected,
    )


def test_block_persisted_consumer_requires_topology_posture_digest_and_cleanup():
    data, assertion = _block_persisted()
    expected = dict(run_id="run", evidence_id="evidence", artifact_kind="block",
                    input_digest=DIGEST, block_assertion=assertion)
    mutations = []
    changed = copy.deepcopy(data); changed["inspection"].pop("post_oracle"); mutations.append(changed)
    changed = copy.deepcopy(data); changed["sandbox_posture"]["host_fallback"] = True; mutations.append(changed)
    changed = copy.deepcopy(data); changed["cleanup"]["workspace"]["state"] = "retained"; mutations.append(changed)
    changed = copy.deepcopy(data); changed["artifact_retention"]["resources"][0]["live"] = True; mutations.append(changed)
    changed = copy.deepcopy(data); changed["block_runtime_artifact_gate"]["execution_proof_digest"] = "0" * 64; mutations.append(changed)
    changed = copy.deepcopy(data); changed["inspection"]["normalized"]["images"].pop("browser"); mutations.append(changed)
    changed = copy.deepcopy(data); changed["inspection"]["started"]["networks"]["project_frontend"]["internal"] = False; mutations.append(changed)
    changed = copy.deepcopy(data); changed["inspection"]["artifact_seal"]["seed_removed"] = False; mutations.append(changed)
    changed = copy.deepcopy(data); changed["cleanup"]["compose"]["remaining"]["containers"] = ["leftover"]; mutations.append(changed)
    changed = copy.deepcopy(data); changed["artifact_retention"]["resources"].append("malformed"); mutations.append(changed)
    changed = copy.deepcopy(data); changed["block_runtime_artifact_gate"]["component_digests"].pop("artifact"); mutations.append(changed)
    changed = copy.deepcopy(data); changed["block_runtime_artifact_gate"]["selected_block_json"] = "other/block.json"; mutations.append(changed)
    changed = copy.deepcopy(data); changed["block_runtime_artifact_gate"]["wrapper_checks"][1]["status"] = "fail"; mutations.append(changed)
    for changed in mutations:
        assert contract.persisted_runtime_errors(changed, **expected)
