"""Exact producer and consumer contract for isolated WordPress runtime evidence."""
from __future__ import annotations

import math
import re
from typing import Any

from wp_runtime_types import RuntimeRequest, RuntimeResult


VALID_STATUSES = frozenset({"pass", "fail", "blocked"})
STANDARD_PROFILE = "standard"
ADVERSARIAL_PROFILE = "adversarial-test"
STANDARD_REQUESTED_ORACLES = ("activation", "browser")
# RuntimeRequest currently exposes only the two reviewed oracle capabilities.
# Reversing their exact requested order is the explicit test-only profile token;
# it does not widen the production capability vocabulary.
ADVERSARIAL_REQUESTED_ORACLES = ("browser", "activation")
REQUIRED_CHECKS_BY_PROFILE = {
    STANDARD_PROFILE: ("wp_cli_activation", "plugin_check", "container_browser"),
    ADVERSARIAL_PROFILE: (
        "container_artifact_manifest", "wp_cli_activation", "php_route_denials",
        "browser_network_denials", "runtime_gateway_denials", "generated_php_canary",
        "container_browser", "generated_browser_editor_js", "runtime_database_ceiling",
        "runtime_storage_ceiling", "runtime_inode_ceiling", "runtime_fd_ceiling",
        "runtime_pid_fork_ceiling", "runtime_cpu_hang_ceiling",
        "runtime_php_memory_ceiling", "runtime_browser_memory_ceiling",
        "runtime_php_stdout_ceiling", "runtime_php_log_ceiling",
        "runtime_browser_console_ceiling", "runtime_http_response_ceiling",
        "runtime_daemon_log_ceiling",
    ),
}
REQUIRED_ORACLE_CHECKS = REQUIRED_CHECKS_BY_PROFILE[STANDARD_PROFILE]
REQUIRED_RESULT_CHECKS = (*REQUIRED_ORACLE_CHECKS, "runtime_identity")
DIGEST = re.compile(r"[0-9a-f]{64}")


def dominant_status(statuses: list[str]) -> str:
    """Return the required blocked > fail > pass ordering."""
    if "blocked" in statuses:
        return "blocked"
    if "fail" in statuses:
        return "fail"
    return "pass"


def _normalized_status(value: Any) -> str:
    return str(value) if value in VALID_STATUSES else "blocked"


def profile_for_requested(requested: tuple[str, ...]) -> str:
    mapping = {
        STANDARD_REQUESTED_ORACLES: STANDARD_PROFILE,
        ADVERSARIAL_REQUESTED_ORACLES: ADVERSARIAL_PROFILE,
    }
    try:
        return mapping[tuple(requested)]
    except KeyError as exc:
        raise ValueError(f"unsupported exact runtime oracle profile: {tuple(requested)!r}") from exc


def _check_ids(checks: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(check.get("id")) for check in checks
        if isinstance(check, dict) and isinstance(check.get("id"), str)
    )


def profile_for_checks(checks: tuple[dict[str, Any], ...]) -> str | None:
    actual = _check_ids(checks)
    return next(
        (profile for profile, expected in REQUIRED_CHECKS_BY_PROFILE.items() if actual == expected),
        None,
    )


def require_exact_profile_checks(profile: str, checks: tuple[dict[str, Any], ...]) -> None:
    expected = REQUIRED_CHECKS_BY_PROFILE.get(profile)
    if expected is None or _check_ids(checks) != expected:
        raise RuntimeError(f"{profile} runtime check inventory drift")
    if _timing_status(checks) != "pass":
        raise RuntimeError(f"{profile} runtime check timing drift")


def _has_valid_duration(check: dict[str, Any]) -> bool:
    value = check.get("duration_sec")
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _timing_status(checks: tuple[dict[str, Any], ...]) -> str:
    return "pass" if checks and all(_has_valid_duration(check) for check in checks) else "blocked"


def _oracle_statuses(
    checks: tuple[dict[str, Any], ...], check_ids: tuple[str, ...]
) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for check_id in check_ids:
        matches = [
            check for check in checks
            if isinstance(check, dict) and check.get("id") == check_id
        ]
        statuses[check_id] = (
            _normalized_status(matches[0].get("status")) if len(matches) == 1 else "blocked"
        )
    return statuses


def _identity_status(
    runtime: RuntimeResult, request: RuntimeRequest, expected_manifest_digest: str
) -> tuple[str, str]:
    matches = (
        runtime.evidence_id == request.evidence_id
        and runtime.input_artifact_digest == request.input_artifact_digest
        and runtime.post_command_manifest_digest == expected_manifest_digest
    )
    if matches:
        return "pass", "runtime identity and pre/post manifest digest match"
    return "blocked", "runtime identity or pre/post manifest digest mismatch"


def _gate_status(requested: bool, gate: dict[str, Any] | None) -> str:
    if not requested:
        return "not_run"
    if not isinstance(gate, dict):
        return "blocked"
    return _normalized_status(gate.get("status"))


def _execution_proof_status(requested: bool, digest: str | None) -> str:
    if not requested:
        return "not_run"
    return "pass" if isinstance(digest, str) and DIGEST.fullmatch(digest) else "blocked"


def _named_check_status(gate: dict[str, Any] | None, check_id: str) -> str:
    matches = [
        check for check in (gate or {}).get("checks", [])
        if isinstance(check, dict) and check.get("id") == check_id
    ]
    return _normalized_status(matches[0].get("status")) if len(matches) == 1 else "blocked"


def _full_profile(runtime: RuntimeResult, wpcs_gate: dict[str, Any] | None) -> dict[str, Any]:
    statuses = _oracle_statuses(
        runtime.checks, ("wp_cli_activation", "plugin_check", "container_browser")
    )
    wpcs_status = dominant_status([
        _gate_status(True, wpcs_gate),
        _named_check_status(wpcs_gate, "phpcs_wpcs"),
    ])
    checks = [
        {"id": "phpcs_wpcs", "status": wpcs_status,
         "required": True},
        {"id": "plugin_check", "status": statuses["plugin_check"], "required": True},
        {"id": "wp_env_smoke", "status": dominant_status([
            statuses["wp_cli_activation"], statuses["container_browser"],
        ]), "required": True, "detail": "isolated activation and container browser"},
    ]
    status = dominant_status([check["status"] for check in checks])
    return {"status": status, "pass": status == "pass", "checks": checks,
            "profile": "isolated-plugin-full"}


def _required_gate_evidence(
    runtime: RuntimeResult, request: RuntimeRequest, expected_manifest_digest: str,
    build_requested: bool, build_gate: dict[str, Any] | None, phpunit_requested: bool,
    phpunit_gate: dict[str, Any] | None, full_profile_requested: bool,
    wpcs_gate: dict[str, Any] | None, runtime_artifact_requested: bool,
    runtime_artifact_gate: dict[str, Any] | None, execution_proof_digest: str | None,
    artifact_kind: str,
) -> dict[str, Any]:
    identity_status, identity_detail = _identity_status(runtime, request, expected_manifest_digest)
    profile = profile_for_checks(runtime.checks)
    expected = REQUIRED_CHECKS_BY_PROFILE.get(profile or "", REQUIRED_ORACLE_CHECKS)
    oracle_statuses = _oracle_statuses(runtime.checks, expected)
    inventory_status = "pass" if profile else "blocked"
    timing_status = _timing_status(runtime.checks)
    build_status = _gate_status(build_requested, build_gate)
    artifact_status = _gate_status(runtime_artifact_requested, runtime_artifact_gate)
    proof_status = _execution_proof_status(runtime_artifact_requested, execution_proof_digest)
    artifact_request_status = (
        "pass" if not runtime_artifact_requested
        or (artifact_kind == "block" and build_requested) else "blocked"
    )
    phpunit_status = _gate_status(phpunit_requested, phpunit_gate)
    full_profile = _full_profile(runtime, wpcs_gate) if full_profile_requested else None
    required = [
        _normalized_status(runtime.status), identity_status, inventory_status, timing_status,
        *oracle_statuses.values(),
    ]
    if build_requested:
        required.append(build_status)
    if runtime_artifact_requested:
        required.extend((artifact_request_status, artifact_status, proof_status))
    if phpunit_requested:
        required.append(phpunit_status)
    if full_profile_requested:
        required.append(str(full_profile["status"]))
    checks = [dict(check) for check in runtime.checks if isinstance(check, dict)]
    if not profile:
        checks.append({"id": "runtime_profile_contract", "status": "blocked", "required": True,
                       "detail": "runtime check inventory did not match an exact profile"})
    if timing_status != "pass":
        checks.append({"id": "runtime_timing_contract", "status": "blocked", "required": True,
                       "detail": "runtime check duration evidence is missing or invalid"})
    checks.append({"id": "runtime_identity", "status": identity_status, "required": True,
                   "detail": identity_detail})
    return {"status": dominant_status(required), "checks": checks, "oracles": oracle_statuses,
            "build": build_status, "runtime_artifact": artifact_status,
            "execution_proof": proof_status, "phpunit": phpunit_status,
            "full_profile": full_profile,
            "profile": profile or "invalid", "required_checks": expected}


def _negative_space(gates,phpunit_requested):
    result=[]
    if gates["oracles"].get("plugin_check")!="pass":
        result.append("not Plugin Check proof")
    if not gates["full_profile"] or gates["full_profile"]["status"]!="pass":
        result.append("not WPCS proof")
    if not phpunit_requested or gates["phpunit"]!="pass":
        result.append("not PHPUnit proof")
    return result


def _runtime_result_overlay(
    runtime, gates, artifact_kind, expected_manifest_digest, block_requested, block_gate,
    runtime_artifact_requested, runtime_artifact_gate, execution_proof_digest,
    phpunit_requested, phpunit_gate, full_requested, provisioning,
):
    status = gates["status"]
    return {
        "status": status,
        "pass": status == "pass",
        "artifact_kind": artifact_kind,
        "runtime_pre_command_manifest_digest": expected_manifest_digest,
        "runtime_profile_id": gates["profile"],
        "required_runtime_checks": list(gates["required_checks"]),
        "checks": gates["checks"],
        "wp_cli_activation_status": gates["oracles"]["wp_cli_activation"],
        "container_browser_status": gates["oracles"]["container_browser"],
        "block_build_smoke_requested": block_requested,
        "block_build_smoke_status": gates["build"],
        "block_build_gate": block_gate,
        "block_runtime_artifact_requested": runtime_artifact_requested,
        "block_runtime_artifact_gate_status": gates["runtime_artifact"],
        "block_runtime_artifact_gate": runtime_artifact_gate,
        "execution_proof_digest": execution_proof_digest,
        "phpunit_smoke_requested": phpunit_requested,
        "phpunit_smoke_status": gates["phpunit"],
        "phpunit_gate": phpunit_gate,
        "provision_full_profile": full_requested,
        "strict_full_profile": full_requested,
        "trusted_provisioning": provisioning or {},
        "full_plugin_runtime_profile": gates["full_profile"],
        "fixture_retained": False,
        "negative_space": _negative_space(gates,phpunit_requested),
        "sandbox_posture": {
            "generated_execution": {
                "php": _normalized_status(runtime.status),
                "browser": gates["oracles"]["container_browser"],
            },
            "host_fallback": False,
            "static_scan_root": "staged_copy",
        },
    }


def adapt_runtime_result(
    runtime: RuntimeResult, request: RuntimeRequest, *, artifact_kind: str,
    expected_manifest_digest: str, block_build_requested: bool,
    block_build_gate: dict[str, Any] | None, phpunit_requested: bool,
    phpunit_gate: dict[str, Any] | None = None, full_profile_requested: bool = False,
    wpcs_gate: dict[str, Any] | None = None,
    trusted_provisioning: dict[str, Any] | None = None,
    block_runtime_artifact_requested: bool = False,
    block_runtime_artifact_gate: dict[str, Any] | None = None,
    execution_proof_digest: str | None = None,
) -> dict[str, Any]:
    """Validate and enrich a runtime result without weakening any requested gate."""
    gates=_required_gate_evidence(
        runtime,request,expected_manifest_digest,block_build_requested,block_build_gate,
        phpunit_requested,phpunit_gate,full_profile_requested,wpcs_gate,
        block_runtime_artifact_requested,block_runtime_artifact_gate,
        execution_proof_digest,artifact_kind,
    )
    result=runtime.as_dict()
    result.update(_runtime_result_overlay(
        runtime,gates,artifact_kind,expected_manifest_digest,block_build_requested,
        block_build_gate,block_runtime_artifact_requested,block_runtime_artifact_gate,
        execution_proof_digest,phpunit_requested,phpunit_gate,
        full_profile_requested,trusted_provisioning,
    ))
    return result


def stopped_block_prerequisite_result(
    *, artifact_kind: str, digest: str, build_gate: dict[str, Any] | None,
    runtime_artifact_gate: dict[str, Any] | None, execution_proof_digest: str | None,
    receipts: list[Any], phpunit_requested: bool,
    runtime_artifact_requested: bool = True,
) -> dict[str, Any]:
    """Return both block prerequisite verdicts without starting WordPress."""
    build_status = _gate_status(True, build_gate)
    artifact_status = _gate_status(runtime_artifact_requested, runtime_artifact_gate)
    proof_status = _execution_proof_status(runtime_artifact_requested, execution_proof_digest)
    phpunit_status = "blocked" if phpunit_requested else "not_run"
    required = [build_status]
    if runtime_artifact_requested:
        required.extend((artifact_status, proof_status))
    if phpunit_requested:
        required.append(phpunit_status)
    checks = list((build_gate or {}).get("checks") or [])
    checks.extend((runtime_artifact_gate or {}).get("checks") or [])
    if phpunit_requested:
        checks.append({"id": "phpunit", "status": "blocked", "required": True,
                       "detail": "PHPUnit was requested but isolated runtime did not start"})
    status = dominant_status(required)
    return {
        "status": status, "pass": False,
        "reason": "block prerequisite did not pass; isolated runtime was not started",
        "checks": checks, "artifact_kind": artifact_kind,
        "input_artifact_digest": digest, "block_build_smoke_requested": True,
        "block_build_smoke_status": build_status, "block_build_gate": build_gate,
        "block_runtime_artifact_requested": runtime_artifact_requested,
        "block_runtime_artifact_gate_status": artifact_status,
        "block_runtime_artifact_gate": runtime_artifact_gate,
        "execution_proof_digest": execution_proof_digest,
        "phpunit_smoke_requested": phpunit_requested,
        "phpunit_smoke_status": phpunit_status,
        "negative_space": ["isolated runtime not executed", "not PHPUnit proof"],
        "sandbox_posture": {"generated_execution": {
            "npm_build": build_status, "runtime_artifact": artifact_status,
        }, "host_fallback": False},
        "_artifact_retention_receipts": receipts,
    }


def stopped_build_result(
    *, artifact_kind: str, digest: str, gate: dict[str, Any], receipts: list[Any],
    phpunit_requested: bool,
) -> dict[str, Any]:
    """Return a terminal build verdict without starting WordPress runtime."""
    return stopped_block_prerequisite_result(
        artifact_kind=artifact_kind, digest=digest, build_gate=gate,
        runtime_artifact_gate=None, execution_proof_digest=None, receipts=receipts,
        phpunit_requested=phpunit_requested, runtime_artifact_requested=False,
    )


def _persisted_timing_errors(checks, expected_checks):
    oracle_checks = tuple(
        check for check in checks
        if isinstance(check, dict) and check.get("id") in expected_checks
    )
    return [] if _timing_status(oracle_checks) == "pass" else [
        "runtime check timing evidence invalid"
    ]


def _persisted_execution_proof_errors(
    data: dict[str, Any], expected_digest: str | None,
) -> list[str]:
    if expected_digest is None:
        return []
    actual = data.get("execution_proof_digest")
    errors = []
    if (not isinstance(expected_digest, str) or not DIGEST.fullmatch(expected_digest)
            or actual != expected_digest):
        errors.append("execution proof digest mismatch")
    gate = data.get("block_runtime_artifact_gate")
    if (_gate_status(True, gate) != "pass"
            or data.get("block_runtime_artifact_gate_status") != "pass"
            or data.get("block_runtime_artifact_requested") is not True):
        errors.append("block runtime artifact gate did not pass")
    return errors


def persisted_runtime_errors(
    data: dict[str, Any], *, run_id: str, evidence_id: str,
    artifact_kind: str, input_digest: str, execution_proof_digest: str | None = None,
) -> list[str]:
    """Return exact-result contract errors for the repair-loop consumer."""
    errors = _persisted_execution_proof_errors(data, execution_proof_digest)
    expected = {
        "schema_version": 1,
        "run_id": run_id,
        "evidence_id": evidence_id,
        "artifact_kind": artifact_kind,
        "input_artifact_digest": input_digest,
    }
    errors.extend(f"{key} mismatch" for key, value in expected.items() if data.get(key) != value)
    pre = data.get("runtime_pre_command_manifest_digest")
    post = data.get("post_command_manifest_digest")
    if not isinstance(pre, str) or not DIGEST.fullmatch(pre) or post != pre:
        errors.append("post-command manifest digest mismatch")
    raw_checks = data.get("checks")
    checks = tuple(raw_checks) if isinstance(raw_checks, list) else ()
    profile = data.get("runtime_profile_id", STANDARD_PROFILE)
    expected_checks = REQUIRED_CHECKS_BY_PROFILE.get(profile)
    if expected_checks is None:
        errors.append("runtime profile is unknown")
        expected_checks = REQUIRED_ORACLE_CHECKS
    required_result = (*expected_checks, "runtime_identity")
    actual_ids = _check_ids(checks)
    for check_id in required_result:
        matches = [check for check in checks if isinstance(check, dict) and check.get("id") == check_id]
        if len(matches) != 1 or matches[0].get("status") != "pass":
            errors.append(f"{check_id} did not pass")
    errors.extend(_persisted_timing_errors(checks, expected_checks))
    extras = set(actual_ids) - set(required_result)
    duplicates = len(actual_ids) != len(set(actual_ids))
    if extras or duplicates:
        errors.append("runtime check inventory mismatch")
    if data.get("status") != "pass" or data.get("pass") is not True:
        errors.append("top-level runtime status did not pass")
    full = data.get("full_plugin_runtime_profile")
    full_checks = tuple((full or {}).get("checks") or ())
    expected_full = ("phpcs_wpcs", "plugin_check", "wp_env_smoke")
    if (not isinstance(full, dict) or full.get("status") != "pass"
            or full.get("pass") is not True or _check_ids(full_checks) != expected_full):
        errors.append("full plugin runtime profile did not pass")
    else:
        for check_id in expected_full:
            if _named_check_status(full, check_id) != "pass":
                errors.append(f"full profile {check_id} did not pass")
    return errors
