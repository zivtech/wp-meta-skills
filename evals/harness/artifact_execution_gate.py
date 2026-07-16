"""Bounded scanners for the authenticated post-build block execution proof."""
from __future__ import annotations

import copy
import dataclasses
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import artifact_execution_graph
import artifact_layout
import artifact_snapshot_scan
import artifact_staging
import wp_api_lint
import wp_security_gate
from bounded_subprocess import (
    BoundedProcessError,
    BoundedProcessOverflow,
    BoundedProcessTimeout,
    run_bounded,
)


GATE_SCHEMA = "wp-meta-skills/block-execution-artifact-gate"
GATE_SCHEMA_VERSION = 1
MAX_DETAIL_BYTES = 500
MAX_REPORTED_HITS = 8
MAX_TEXT_SCAN_BYTES = artifact_execution_graph.MAX_RUNTIME_CLOSURE_BYTES
PHP_LINT_OUTPUT_LIMIT = 64 * 1024


@dataclass(frozen=True)
class BlockExecutionValidation:
    proof: artifact_execution_graph.BlockExecutionProof | None
    gate: dict[str, Any]
    staging_receipts: tuple[artifact_staging.StagingCleanupReceipt, ...]


def _detail(value: object) -> str:
    rendered = " ".join(str(value).split())
    encoded = rendered.encode("utf-8", errors="replace")[:MAX_DETAIL_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def _check(check_id: str, status: str, detail: object) -> dict[str, str]:
    if status not in {"pass", "fail", "blocked"}:
        raise ValueError(f"invalid check status: {status}")
    return {"id": check_id, "status": status, "detail": _detail(detail)}


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("block execution artifact gate deadline exceeded")
    return remaining


def _dominant_status(checks: list[dict[str, str]]) -> str:
    statuses = {item["status"] for item in checks}
    if "blocked" in statuses:
        return "blocked"
    if "fail" in statuses:
        return "fail"
    return "pass"


def _gate_payload(
    proof: artifact_execution_graph.BlockExecutionProof | None,
    checks: list[dict[str, str]],
    scanner_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocked = next((item["detail"] for item in checks if item["status"] == "blocked"), None)
    payload: dict[str, Any] = {
        "schema": GATE_SCHEMA,
        "schema_version": GATE_SCHEMA_VERSION,
        "id": "block_runtime_artifact_gate",
        "status": _dominant_status(checks),
        "blocked_reason": blocked,
        "checks": copy.deepcopy(checks),
        "selected_root": None,
        "selected_block_json": None,
        "selection_reason": None,
        "edges": [],
        "files": [],
        "scan_files": [],
        "scanner_aliases": [],
        "scanner_evidence": copy.deepcopy(scanner_evidence or {}),
        "component_digests": {},
        "artifact_proof_digest": None,
    }
    if proof is None:
        return payload
    payload.update(
        {
            "output_manifest_sha256": proof.output_manifest_sha256,
            "source_manifest_sha256": proof.source_manifest_sha256,
            "selected_root": proof.selected_root,
            "selected_block_json": proof.selected_block_json,
            "selection_reason": proof.selection_reason,
            "core": dataclasses.asdict(proof.core),
            "rule_digest": proof.rule_digest,
            "edges": [dataclasses.asdict(item) for item in proof.edges],
            "files": [dataclasses.asdict(item) for item in proof.files],
            "scan_files": [dataclasses.asdict(item) for item in proof.scan_files],
            "scanner_aliases": list(artifact_execution_graph.scanner_aliases(proof)),
            "component_digests": {
                "metadata_graph": proof.metadata_graph_digest,
                "php_set": proof.php_set_digest,
                "scanner_aliases": artifact_execution_graph.scanner_alias_digest(proof),
                "artifact": proof.artifact_proof_digest,
            },
            "artifact_proof_digest": proof.artifact_proof_digest,
        }
    )
    return payload


def _scan_paths(proof, scan_id: str, root: Path) -> list[Path]:
    return [root / item.path for item in proof.scan_files if scan_id in item.scan_ids]


def _alias_names(proof, root: Path) -> dict[Path, str]:
    return {
        root / item["source_path"]: item["alias_name"]
        for item in artifact_execution_graph.scanner_aliases(proof)
    }


def _alias_members(proof, root: Path) -> dict[Path, tuple[int, str]]:
    return {
        root / item["source_path"]: (item["size"], item["sha256"])
        for item in artifact_execution_graph.scanner_aliases(proof)
    }


def _text_bound_failure(detail: str) -> list[dict[str, str]]:
    return [
        _check("unsafe_commands", "blocked", detail),
        _check("hardcoded_secrets", "blocked", detail),
    ]


def _text_bound_reason(entries) -> str | None:
    if any(item.size > artifact_staging.MAX_TARGET_MEMBER_BYTES for item in entries):
        return "exact text scan file exceeds the 8 MiB targeted-read bound"
    if sum(item.size for item in entries) > MAX_TEXT_SCAN_BYTES:
        return "exact text scan exceeds the 16 MiB aggregate bound"
    return None


def _proof_text_bound_failure(proof) -> list[dict[str, str]]:
    selected = {item.path for item in proof.scan_files if "secret" in item.scan_ids}
    entries = [item for item in proof.files if item.path in selected]
    reason = _text_bound_reason(entries)
    return _text_bound_failure(reason) if reason else []


def _bounded_text_checks(handoff, proof, deadline: float) -> list[dict[str, str]]:
    selected = {item.path for item in proof.scan_files if "secret" in item.scan_ids}
    manifest = {item.path: item for item in handoff.manifest}
    entries = [manifest[path] for path in sorted(selected)]
    reason = _text_bound_reason(entries)
    if reason:
        return _text_bound_failure(reason)
    unsafe: list[str] = []
    secrets: list[str] = []
    with artifact_staging.hold_staged_tree(handoff, proof_deadline=deadline) as held:
        for entry in entries:
            text = artifact_staging.read_held_member(held, entry.path).decode("utf-8", errors="replace")
            lower = text.lower()
            for pattern in artifact_snapshot_scan.BANNED:
                if re.search(pattern, lower):
                    unsafe.append(f"{entry.path}: {pattern}")
            if artifact_snapshot_scan.SECRETISH.search(text):
                secrets.append(entry.path)
    unsafe_detail = "no banned destructive command patterns found"
    secret_detail = "no long secret-like assignments found"
    if unsafe:
        unsafe_detail = "unsafe destructive patterns found: " + ", ".join(unsafe[:MAX_REPORTED_HITS])
    if secrets:
        secret_detail = "secret-like assignments found in: " + ", ".join(secrets[:MAX_REPORTED_HITS])
    return [
        _check("unsafe_commands", "fail" if unsafe else "pass", unsafe_detail),
        _check("hardcoded_secrets", "fail" if secrets else "pass", secret_detail),
    ]


def _reproved(handoff, deadline: float, scanner: Callable[[], Any]) -> Any:
    with artifact_staging.hold_staged_tree(handoff, proof_deadline=deadline):
        return scanner()


def _php_syntax_check(handoff, proof, deadline: float) -> dict[str, str]:
    php = shutil.which("php")
    if php is None:
        return _check("php_syntax", "blocked", "php executable not found on PATH")
    failures: list[str] = []
    for candidate in proof.php_candidates:
        path = handoff.root / candidate.path
        try:
            result = run_bounded(
                [php, "-l", str(path)],
                deadline_monotonic=deadline,
                stdout_limit=PHP_LINT_OUTPUT_LIMIT,
                stderr_limit=PHP_LINT_OUTPUT_LIMIT,
            )
        except BoundedProcessTimeout:
            return _check("php_syntax", "blocked", f"global deadline expired while linting {candidate.path}")
        except BoundedProcessOverflow as exc:
            return _check("php_syntax", "blocked", f"php -l output blocked: {exc}")
        except BoundedProcessError as exc:
            return _check("php_syntax", "blocked", f"php -l execution blocked: {exc}")
        except OSError as exc:
            return _check("php_syntax", "blocked", f"php -l could not run: {type(exc).__name__}")
        if result.returncode != 0:
            output = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            failures.append(f"{candidate.path}: {_detail(output)}")
            if len(failures) >= MAX_REPORTED_HITS:
                break
    if failures:
        return _check("php_syntax", "fail", "; ".join(failures))
    return _check("php_syntax", "pass", f"php -l passed for {len(proof.php_candidates)} exact candidate(s)")


def _api_check(handoff, proof, deadline: float, php_tools_root):
    selected = _scan_paths(proof, "wp_api", handoff.root)
    report = wp_api_lint.run_api_lint(
        handoff.root,
        timeout_sec=_remaining(deadline),
        deadline_monotonic=deadline,
        php_tools_root=php_tools_root,
        explicit_files=selected,
        explicit_alias_names=_alias_names(proof, handoff.root),
        explicit_alias_members=_alias_members(proof, handoff.root),
    )
    status = report.get("status")
    if status not in {"pass", "fail", "blocked"}:
        status = "pass" if status == "skip" and not selected else "blocked"
    evidence = {
        "status": report.get("status"),
        "analysis_usage": copy.deepcopy(report.get("analysis_usage") or {}),
        "scanner_aliases": copy.deepcopy(report.get("scanner_aliases") or []),
        "finding_count": len(report.get("findings") or []),
        "analysis_error_count": len(report.get("analysis_errors") or []),
        "findings": copy.deepcopy((report.get("findings") or [])[:MAX_REPORTED_HITS]),
        "analysis_errors": copy.deepcopy(
            (report.get("analysis_errors") or [])[:MAX_REPORTED_HITS]
        ),
    }
    return _check("wp_api", status, wp_api_lint.summarize_report(report)), evidence


def _security_runtime_evidence(report):
    findings = report.get("findings") or []
    suppressed = report.get("suppressed_annotations") or []
    prioritized_findings = sorted(
        enumerate(findings), key=lambda item: (not item[1].get("enforced"), item[0])
    )
    prioritized_suppressions = sorted(
        enumerate(suppressed),
        key=lambda item: (
            not item[1].get("security_relevant"),
            not bool(item[1].get("reviewed_safe_api")),
            item[0],
        ),
    )
    return {
        "status": report.get("status"),
        "summary": copy.deepcopy(report.get("summary") or {}),
        "analysis_usage": copy.deepcopy(report.get("analysis_usage") or {}),
        "scanner_aliases": copy.deepcopy(report.get("scanner_aliases") or []),
        "finding_count": len(findings),
        "suppressed_annotation_count": len(suppressed),
        "findings": copy.deepcopy(
            [item for _index, item in prioritized_findings[:MAX_REPORTED_HITS]]
        ),
        "suppressed_annotations": copy.deepcopy(
            [item for _index, item in prioritized_suppressions[:MAX_REPORTED_HITS]]
        ),
    }


def _security_check(handoff, proof, deadline: float, php_tools_root):
    selected = _scan_paths(proof, "wp_security", handoff.root)
    report = wp_security_gate.run_security_gate(
        handoff.root,
        timeout_sec=_remaining(deadline),
        deadline_monotonic=deadline,
        php_tools_root=php_tools_root,
        explicit_files=selected,
        explicit_alias_names=_alias_names(proof, handoff.root),
        explicit_alias_members=_alias_members(proof, handoff.root),
    )
    status = report.get("status")
    if status not in {"pass", "fail", "blocked"}:
        status = "pass" if status == "skip" and not selected else "blocked"
    evidence = _security_runtime_evidence(report)
    return _check("wp_security", status, wp_security_gate.summarize_report(report)), evidence


def _run_scanners(handoff, proof, deadline: float, php_tools_root):
    checks = [
        _check(
            "metadata_json",
            "pass",
            "selected block.json is strict bounded JSON with required metadata",
        ),
        _check(
            "structural",
            "pass",
            "all exact graph files are verified regular manifest members",
        ),
    ]
    checks.extend(_bounded_text_checks(handoff, proof, deadline))
    if any(item["status"] == "blocked" for item in checks):
        return checks, {}
    checks.append(_reproved(
        handoff, deadline, lambda: _php_syntax_check(handoff, proof, deadline)
    ))
    api_check, api_evidence = _reproved(
        handoff, deadline, lambda: _api_check(handoff, proof, deadline, php_tools_root)
    )
    checks.append(api_check)
    security_check, security_evidence = _reproved(
        handoff, deadline,
        lambda: _security_check(handoff, proof, deadline, php_tools_root),
    )
    checks.append(security_check)
    return checks, {"wp_api": api_evidence, "wp_security": security_evidence}


def _cleanup_handoff(handoff, checks, receipts) -> None:
    try:
        receipt = artifact_staging.cleanup_staged_tree(handoff)
    except Exception as exc:
        checks.append(_check("scan_handoff_cleanup", "blocked", f"cleanup raised {type(exc).__name__}"))
        return
    receipts.append(receipt)
    clean = receipt.state == "removed" and not receipt.error and not receipt.exists and not receipt.live
    detail = "scan handoff removed" if clean else receipt.error or f"scan handoff remains {receipt.state}"
    checks.append(_check("scan_handoff_cleanup", "pass" if clean else "blocked", detail))


def _build_proof(held, source_layout):
    layout = artifact_layout.select_post_build_layout(held.proof.manifest, source_layout)
    return artifact_execution_graph.build_execution_proof(held, layout)


def _validate_proof_scanners(
    held, proof, parent, deadline, php_tools_root, checks, receipts
):
    checks.append(_check(
        "execution_graph", "pass", "authenticated execution graph built"
    ))
    bound_failure = _proof_text_bound_failure(proof)
    if bound_failure:
        checks.extend(bound_failure)
        return {}
    handoff = None
    try:
        members = tuple(item.path for item in proof.scan_files)
        handoff = artifact_staging.stage_scan_handoff(held, parent, members)
        scanner_checks, evidence = _run_scanners(
            handoff, proof, deadline, php_tools_root
        )
        checks.extend(scanner_checks)
        return evidence
    finally:
        if handoff is not None:
            _cleanup_handoff(handoff, checks, receipts)


def validate_block_execution_artifact(
    output,
    source_layout,
    timeout_sec,
    php_tools_root=None,
    parent=None,
) -> BlockExecutionValidation:
    if not isinstance(timeout_sec, (int, float)) or isinstance(timeout_sec, bool) or timeout_sec <= 0:
        raise ValueError("timeout_sec must be a positive number")
    if not artifact_staging.has_stage_authority(output, artifact_staging.StageRole.SANDBOX_OUTPUT):
        checks = [_check(
            "output_authentication", "blocked",
            "post-build output is not an authentic SANDBOX_OUTPUT capability",
        )]
        return BlockExecutionValidation(None, _gate_payload(None, checks), ())
    deadline = time.monotonic() + timeout_sec
    proof = None
    checks: list[dict[str, str]] = []
    receipts: list[artifact_staging.StagingCleanupReceipt] = []
    scanner_evidence: dict[str, Any] = {}
    try:
        with artifact_staging.hold_staged_tree(output, proof_deadline=deadline) as held:
            try:
                proof = _build_proof(held, source_layout)
            except ValueError as exc:
                checks.append(_check("execution_graph", "fail", exc))
            if proof is not None:
                scanner_evidence = _validate_proof_scanners(
                    held, proof, parent, deadline, php_tools_root, checks, receipts
                )
        checks.append(_check("output_reproof", "pass", "held sandbox output remained unchanged"))
    except artifact_staging.StagingCleanupError as exc:
        receipts.append(exc.receipt)
        checks.append(_check("artifact_orchestration", "blocked", exc))
    except Exception as exc:
        checks.append(_check("artifact_orchestration", "blocked", f"{type(exc).__name__}: {exc}"))
    return BlockExecutionValidation(
        proof, _gate_payload(proof, checks, scanner_evidence), tuple(receipts)
    )


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def bind_runtime_gate(validation, runtime_proof) -> dict[str, Any]:
    if not isinstance(validation, BlockExecutionValidation):
        raise TypeError("validation must be a BlockExecutionValidation")
    if not isinstance(runtime_proof, artifact_execution_graph.RuntimeExecutionProof):
        raise TypeError("runtime proof must be a RuntimeExecutionProof")
    artifact_execution_graph.validate_runtime_proof(runtime_proof)
    proof = validation.proof
    if proof is None or validation.gate.get("status") != "pass":
        raise ValueError("only a passing artifact validation can be runtime-bound")
    expected = proof.artifact_proof_digest
    gate_digest = validation.gate.get("artifact_proof_digest")
    runtime_digest = runtime_proof.artifact.artifact_proof_digest
    if gate_digest != expected or runtime_digest != expected:
        raise ValueError("runtime proof artifact digest does not match validation")
    if runtime_proof.artifact != proof:
        raise ValueError("runtime proof artifact does not match validation proof")
    digests = (
        runtime_proof.wrapper_sha256,
        runtime_proof.wrapper_validation_digest,
        runtime_proof.synthesized_manifest_sha256,
        runtime_proof.execution_proof_digest,
    )
    if not all(_valid_digest(value) for value in digests):
        raise ValueError("runtime proof contains an invalid digest")
    bound = copy.deepcopy(validation.gate)
    bound.update(
        {
            "wrapper_path": runtime_proof.wrapper_path,
            "wrapper_size": runtime_proof.wrapper_size,
            "wrapper_sha256": runtime_proof.wrapper_sha256,
            "wrapper_validation_digest": runtime_proof.wrapper_validation_digest,
            "wrapper_checks": [
                {"id": "bootstrap_exact", "status": "pass"},
                {"id": "php_syntax", "status": "pass"},
            ],
            "synthesized_manifest_sha256": runtime_proof.synthesized_manifest_sha256,
            "execution_proof_digest": runtime_proof.execution_proof_digest,
        }
    )
    return bound
