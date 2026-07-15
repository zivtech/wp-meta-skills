"""Exact producer and consumer contract for isolated WordPress runtime evidence."""
from __future__ import annotations

import math
import hashlib
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Any

from wp_runtime_types import BlockRuntimeAssertion, RuntimeRequest, RuntimeResult


VALID_STATUSES = frozenset({"pass", "fail", "blocked"})
STANDARD_PROFILE = "standard"
BLOCK_PROFILE = "block-runtime"
ADVERSARIAL_PROFILE = "adversarial-test"
STANDARD_REQUESTED_ORACLES = ("activation", "browser")
BLOCK_REQUESTED_ORACLES = ("activation", "browser", "block_frontend")
# RuntimeRequest currently exposes only the two reviewed oracle capabilities.
# Reversing their exact requested order is the explicit test-only profile token;
# it does not widen the production capability vocabulary.
ADVERSARIAL_REQUESTED_ORACLES = ("browser", "activation")
REQUIRED_CHECKS_BY_PROFILE = {
    STANDARD_PROFILE: ("wp_cli_activation", "plugin_check", "container_browser"),
    BLOCK_PROFILE: (
        "wp_cli_activation", "plugin_check", "block_registration",
        "container_browser", "block_editor_frontend",
    ),
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
RUNTIME_SERVICES = frozenset({"database", "wordpress", "cli", "gateway", "browser"})
SERVICE_NETWORKS = {
    "database": frozenset({"backend"}),
    "wordpress": frozenset({"backend", "application"}),
    "cli": frozenset({"backend"}),
    "gateway": frozenset({"application", "frontend"}),
    "browser": frozenset({"frontend"}),
}
RUNTIME_NETWORKS = frozenset({"backend", "application", "frontend"})
BLOCK_GATE_KEYS = frozenset({
    "schema", "schema_version", "id", "status", "blocked_reason", "checks",
    "selected_root", "selected_block_json", "selection_reason", "edges", "files",
    "scan_files", "scanner_aliases", "scanner_evidence", "component_digests",
    "artifact_proof_digest", "output_manifest_sha256", "source_manifest_sha256",
    "core", "rule_digest", "wrapper_path", "wrapper_size", "wrapper_sha256",
    "wrapper_validation_digest", "wrapper_checks", "synthesized_manifest_sha256",
    "execution_proof_digest",
})


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
        BLOCK_REQUESTED_ORACLES: BLOCK_PROFILE,
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


def _execution_proof_status(
    requested: bool, digest: str | None, gate: dict[str, Any] | None,
) -> str:
    if not requested:
        return "not_run"
    gate_status = _gate_status(True, gate)
    if gate_status != "pass":
        return gate_status
    gate_digest = gate.get("execution_proof_digest") if isinstance(gate, dict) else None
    valid = (
        isinstance(digest, str)
        and DIGEST.fullmatch(digest) is not None
        and gate_digest == digest
    )
    return "pass" if valid else "blocked"


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
    proof_status = _execution_proof_status(runtime_artifact_requested, execution_proof_digest, runtime_artifact_gate)
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
    artifact_required = runtime_artifact_requested and build_status == "pass"
    artifact_status = _gate_status(artifact_required, runtime_artifact_gate)
    proof_status = _execution_proof_status(
        artifact_required, execution_proof_digest, runtime_artifact_gate,
    )
    phpunit_status = "blocked" if phpunit_requested else "not_run"
    required = [build_status]
    if artifact_required:
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
    gate = data.get("block_runtime_artifact_gate")
    gate_digest = gate.get("execution_proof_digest") if isinstance(gate, dict) else None
    if (not isinstance(expected_digest, str) or not DIGEST.fullmatch(expected_digest)
            or actual != expected_digest or gate_digest != expected_digest):
        errors.append("execution proof digest mismatch")
    if (_gate_status(True, gate) != "pass"
            or data.get("block_runtime_artifact_gate_status") != "pass"
            or data.get("block_runtime_artifact_requested") is not True):
        errors.append("block runtime artifact gate did not pass")
    return errors


def _persisted_block_gate_errors(data):
    gate=data.get("block_runtime_artifact_gate")
    if not isinstance(gate,dict): return ["block execution gate is missing"]
    digest=data.get("execution_proof_digest")
    required_digests=("artifact_proof_digest","output_manifest_sha256",
        "source_manifest_sha256","rule_digest","wrapper_sha256",
        "wrapper_validation_digest","synthesized_manifest_sha256","execution_proof_digest")
    errors=[]
    if (set(gate)!=BLOCK_GATE_KEYS
            or gate.get("schema")!="wp-meta-skills/block-execution-artifact-gate"
            or gate.get("schema_version")!=1 or gate.get("id")!="block_runtime_artifact_gate"):
        errors.append("block execution gate identity mismatch")
    if (not all(isinstance(gate.get(key),str) and DIGEST.fullmatch(gate[key])
                for key in required_digests) or gate.get("execution_proof_digest")!=digest):
        errors.append("block execution proof object is incomplete")
    root=gate.get("selected_root"); selected=gate.get("selected_block_json")
    safe_root=(isinstance(root,str) and root and not PurePosixPath(root).is_absolute()
               and PurePosixPath(root).as_posix()==root
               and all(part not in {"", ".", ".."} for part in PurePosixPath(root).parts))
    if (not safe_root or selected!=f"{root}/block.json"
            or gate.get("selection_reason")!="built_block_json"
            or not all(isinstance(gate.get(key),list)
                       for key in ("edges","files","scan_files","scanner_aliases"))):
        errors.append("block selected tree proof is incomplete")
    errors.extend(_persisted_block_gate_detail_errors(gate))
    if (data.get("block_build_smoke_requested") is not True
            or data.get("block_build_smoke_status")!="pass"
            or _gate_status(True,data.get("block_build_gate"))!="pass"):
        errors.append("block build gate did not pass")
    return errors


def _persisted_block_gate_detail_errors(gate):
    components=gate.get("component_digests")
    core=gate.get("core")
    checks=gate.get("checks")
    wrapper=gate.get("wrapper_checks")
    component_valid=(isinstance(components,dict)
        and set(components)=={"metadata_graph","php_set","scanner_aliases","artifact"}
        and all(isinstance(value,str) and DIGEST.fullmatch(value) for value in components.values())
        and components.get("artifact")==gate.get("artifact_proof_digest"))
    core_valid=(isinstance(core,dict) and set(core)=={"version","archive_sha256","blocks_php_sha256"}
        and isinstance(core.get("version"),str) and bool(core["version"])
        and all(isinstance(core.get(key),str) and DIGEST.fullmatch(core[key])
                for key in ("archive_sha256","blocks_php_sha256")))
    check_ids=[item.get("id") for item in checks] if isinstance(checks,list) else []
    checks_valid=(bool(check_ids) and len(check_ids)==len(set(check_ids))
        and all(isinstance(item,dict) and set(item)=={"id","status","detail"}
                and isinstance(item["id"],str) and item["id"]
                and item["status"]=="pass" and isinstance(item["detail"],str) for item in checks))
    wrapper_valid=(wrapper==[{"id":"bootstrap_exact","status":"pass"},
                              {"id":"php_syntax","status":"pass"}]
        and isinstance(gate.get("wrapper_path"),str) and gate["wrapper_path"].endswith(".php")
        and isinstance(gate.get("wrapper_size"),int) and 0<gate["wrapper_size"]<=1048576)
    mapping_valid=isinstance(gate.get("scanner_evidence"),dict)
    return [] if all((component_valid,core_valid,checks_valid,wrapper_valid,mapping_valid)) else [
        "block execution gate details are malformed"
    ]


def _normalized_block_text(value):
    return re.sub(r"\s+"," ",unicodedata.normalize("NFC",value)).strip()


def _persisted_block_frontend_errors(data,assertion):
    if not isinstance(assertion,BlockRuntimeAssertion):
        return ["block runtime assertion is missing"]
    checks=data.get("checks") if isinstance(data.get("checks"),list) else []
    matches=[item for item in checks if isinstance(item,dict)
             and item.get("id")=="block_editor_frontend"]
    proof=matches[0].get("proof") if len(matches)==1 else None
    keys={"status","block_name","frontend_selector","expected_text_sha256",
          "observed_text_sha256","match_count","visible","normalization"}
    digest=hashlib.sha256(
        _normalized_block_text(assertion.expected_frontend_text).encode("utf-8")
    ).hexdigest()
    valid=(isinstance(proof,dict) and set(proof)==keys and proof.get("status")=="pass"
        and proof.get("block_name")==assertion.block_name
        and proof.get("frontend_selector")==assertion.frontend_selector
        and proof.get("expected_text_sha256")==digest
        and proof.get("observed_text_sha256")==digest
        and proof.get("match_count")==1 and proof.get("visible") is True
        and proof.get("normalization")=="unicode-nfc-whitespace-collapse-trim")
    return [] if valid else ["block editor/frontend proof mismatch"]


def _persisted_topology_errors(data):
    inspection=data.get("inspection")
    required={"normalized","created","started","post_oracle","artifact_seal"}
    if not isinstance(inspection,dict) or set(inspection)!=required:
        return ["runtime topology inspection inventory mismatch"]
    errors=[]
    normalized=inspection.get("normalized")
    images=normalized.get("images") if isinstance(normalized,dict) else None
    if (not isinstance(normalized,dict) or set(normalized)!={"services","images","networks"}
            or set(normalized.get("services",[]))!=RUNTIME_SERVICES
            or set(normalized.get("networks",[]))!=RUNTIME_NETWORKS
            or not isinstance(images,dict) or set(images)!=RUNTIME_SERVICES
            or not all(isinstance(value,str) and value for value in images.values())):
        errors.append("normalized runtime topology inspection mismatch")
    for phase,running in (("created",False),("started",True),("post_oracle",True)):
        errors.extend(_persisted_live_topology_errors(phase,inspection.get(phase),images,running))
    seal=inspection.get("artifact_seal")
    valid_seal=(isinstance(seal,dict) and set(seal)=={
        "component","state","seed_started","seed_removed","artifact_mounts",
        "base_image","derived_image",
    } and seal.get("component")=="runtime_artifact_image" and seal.get("state")=="sealed"
        and seal.get("seed_started") is False and seal.get("seed_removed") is True
        and seal.get("artifact_mounts")==0
        and all(isinstance(seal.get(key),str) and seal[key]
                for key in ("base_image","derived_image")))
    if not valid_seal:
        errors.append("runtime artifact seal inspection is missing")
    return errors


def _persisted_live_topology_errors(phase,item,images,running):
    observed=item.get("services") if isinstance(item,dict) else None
    networks=item.get("networks") if isinstance(item,dict) else None
    valid=(isinstance(item,dict) and set(item)=={"services","networks","require_running"}
        and isinstance(observed,dict) and set(observed)==RUNTIME_SERVICES
        and item.get("require_running") is running)
    if valid:
        valid=all(_persisted_live_service_valid(name,value,images,running)
                  for name,value in observed.items())
    if valid:
        valid=_persisted_live_networks_valid(networks,observed,running)
    return [] if valid else [f"{phase} runtime topology inspection mismatch"]


def _persisted_live_service_valid(name,value,images,running):
    keys={"id","image","mounts","networks","addresses"}|({"seccomp"} if running else set())
    if not isinstance(value,dict) or set(value)!=keys:
        return False
    names=value.get("networks"); addresses=value.get("addresses")
    suffixes={item.rsplit("_",1)[-1] for item in names} if isinstance(names,list) else set()
    addresses_valid=(isinstance(addresses,dict) and set(addresses)==set(names or [])
        and all(isinstance(item,str) and (bool(item) is running) for item in addresses.values()))
    return (isinstance(value.get("id"),str) and bool(value["id"])
        and isinstance(images,dict) and value.get("image")==images.get(name)
        and value.get("mounts")==[] and suffixes==SERVICE_NETWORKS[name]
        and addresses_valid and (not running or value.get("seccomp")==2))


def _persisted_live_networks_valid(networks,services,running):
    if not running:
        return networks=={}
    if not isinstance(networks,dict):
        return False
    by_suffix={name.rsplit("_",1)[-1]:value for name,value in networks.items()}
    if set(by_suffix)!=RUNTIME_NETWORKS or len(by_suffix)!=len(networks):
        return False
    for name,value in by_suffix.items():
        members={service["id"] for service_name,service in services.items()
                 if name in SERVICE_NETWORKS[service_name]}
        if (not isinstance(value,dict) or set(value)!={
                "id","internal","members","gateway","gateway_mode","subnet"}
                or not isinstance(value.get("id"),str) or not value["id"]
                or value.get("internal") is not True or set(value.get("members",[]))!=members
                or value.get("gateway")!=[] or value.get("gateway_mode")!="isolated"
                or not isinstance(value.get("subnet"),str) or not value["subnet"]):
            return False
    return True


def _persisted_cleanup_errors(data,artifact_kind):
    cleanup=data.get("cleanup")
    errors=[]
    if not isinstance(cleanup,dict) or set(cleanup)!={"compose","images","export","workspace"}:
        errors.append("runtime cleanup inventory mismatch")
    elif not _persisted_cleanup_values_valid(cleanup):
        errors.append("runtime cleanup did not converge")
    retention=data.get("artifact_retention")
    resources=retention.get("resources") if isinstance(retention,dict) else None
    required={"input_copy","synthesized_runtime"}
    if artifact_kind=="block": required|={"sandbox_output","scan_handoff"}
    valid=(isinstance(resources,list) and bool(resources) and retention.get("retained") is False
           and all(_persisted_retention_resource_valid(item) for item in resources)
           and required<={item["component"] for item in resources})
    if not valid or data.get("artifact_execution_retained") is not False:
        errors.append("artifact retention cleanup did not converge")
    return errors


def _persisted_cleanup_values_valid(cleanup):
    compose=cleanup["compose"]; images=cleanup["images"]
    export=cleanup["export"]; workspace=cleanup["workspace"]
    remaining=compose.get("remaining") if isinstance(compose,dict) else None
    compose_valid=(isinstance(compose,dict) and set(compose)=={
        "component","state","errors","remaining","recovery"}
        and compose.get("component")=="compose" and compose.get("state")=="removed"
        and compose.get("errors")==[] and compose.get("recovery")==[]
        and isinstance(remaining,dict) and set(remaining)=={"containers","networks","volumes"}
        and all(value==[] for value in remaining.values()))
    images_valid=(isinstance(images,dict) and set(images)=={
        "component","state","error","remaining","recovery"}
        and images.get("component")=="runtime_images" and images.get("state")=="removed"
        and images.get("error") is None and images.get("remaining")==[]
        and images.get("recovery")==[])
    export_valid=(isinstance(export,dict) and set(export)=={"component","state","error","recovery"}
        and export.get("component")=="runtime_artifact_image" and export.get("state")=="released"
        and export.get("error") is None and export.get("recovery") is None)
    workspace_valid=(isinstance(workspace,dict) and set(workspace)=={"component","state","error"}
        and workspace.get("component")=="runtime_workspace" and workspace.get("state")=="removed"
        and workspace.get("error") is None)
    return all((compose_valid,images_valid,export_valid,workspace_valid))


def _persisted_retention_resource_valid(item):
    return (isinstance(item,dict) and set(item)=={
        "component","state","exists","live","resource_path","recovery_path","error"}
        and isinstance(item.get("component"),str) and bool(item["component"])
        and item.get("state")=="removed" and item.get("exists") is False
        and item.get("live") is False and isinstance(item.get("resource_path"),str)
        and bool(item["resource_path"]) and item.get("recovery_path") is None
        and item.get("error") is None)


def _persisted_posture_errors(data,artifact_kind):
    posture=data.get("sandbox_posture")
    generated=posture.get("generated_execution") if isinstance(posture,dict) else None
    required={"php":"pass","browser":"pass"}
    if artifact_kind=="block": required.update({"npm_build":"pass","block_runtime_artifact":"pass"})
    valid=(isinstance(posture,dict) and posture.get("host_fallback") is False
           and posture.get("static_scan_root")=="staged_copy"
           and isinstance(generated,dict)
           and all(generated.get(key)==value for key,value in required.items()))
    return [] if valid else ["sandbox posture did not pass"]


def _persisted_full_profile_errors(data):
    errors = []
    if data.get("provision_full_profile") is not True or data.get("strict_full_profile") is not True:
        errors.append("strict full profile was not requested")
    full = data.get("full_plugin_runtime_profile")
    full_checks = tuple((full or {}).get("checks") or ())
    expected = ("phpcs_wpcs", "plugin_check", "wp_env_smoke")
    if (not isinstance(full, dict) or full.get("status") != "pass"
            or full.get("pass") is not True or _check_ids(full_checks) != expected):
        errors.append("full plugin runtime profile did not pass")
        return errors
    errors.extend(
        f"full profile {check_id} did not pass" for check_id in expected
        if _named_check_status(full, check_id) != "pass"
    )
    return errors


def persisted_runtime_errors(
    data: dict[str, Any], *, run_id: str, evidence_id: str,
    artifact_kind: str, input_digest: str, execution_proof_digest: str | None = None,
    block_assertion: BlockRuntimeAssertion | None = None,
) -> list[str]:
    """Return exact-result contract errors for the repair-loop consumer."""
    errors = _persisted_execution_proof_errors(data, execution_proof_digest)
    if artifact_kind=="block":
        errors.extend(_persisted_execution_proof_errors(data,data.get("execution_proof_digest")))
        errors.extend(_persisted_block_gate_errors(data))
        errors.extend(_persisted_block_frontend_errors(data,block_assertion))
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
    errors.extend(_persisted_topology_errors(data))
    errors.extend(_persisted_cleanup_errors(data,artifact_kind))
    errors.extend(_persisted_posture_errors(data,artifact_kind))
    errors.extend(_persisted_full_profile_errors(data))
    return errors
