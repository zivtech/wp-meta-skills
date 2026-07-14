"""Exact producer/consumer tests for isolated runtime evidence."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HARNESS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS))

import isolated_runtime_contract as contract
from wp_runtime_types import RuntimeResult


DIGEST = "a" * 64
MANIFEST = "b" * 64
CHECKS = (
    {"id": "wp_cli_activation", "status": "pass", "required": True},
    {"id": "plugin_check", "status": "pass", "required": True},
    {"id": "container_browser", "status": "pass", "required": True},
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
    return {
        "schema_version": 1, "run_id": "run", "evidence_id": "evidence",
        "artifact_kind": "plugin", "input_artifact_digest": DIGEST,
        "runtime_pre_command_manifest_digest": MANIFEST,
        "post_command_manifest_digest": MANIFEST, "status": "pass", "pass": True,
        "checks": list(PERSISTED_CHECKS),
        "provision_full_profile": True, "strict_full_profile": True,
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


def test_adversarial_persisted_profile_requires_every_named_check():
    checks = [
        {"id": check_id, "status": "pass", "required": True}
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
