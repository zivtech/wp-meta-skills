#!/usr/bin/env python3
"""Measure Plan 010's exact reviewed artifact-certification boundary."""
from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import tarfile
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "evals" / "harness"
sys.path.insert(0, str(HARNESS))

import artifact_execution_gate  # noqa: E402
import artifact_execution_graph  # noqa: E402
import artifact_layout  # noqa: E402
import artifact_runtime_staging  # noqa: E402
import artifact_staging  # noqa: E402
import plan010_measurement_evidence  # noqa: E402
import plan010_measurement_fixture  # noqa: E402
import php_scanner_aliases  # noqa: E402
import runtime_artifact_pipeline  # noqa: E402
import wp_api_lint  # noqa: E402
import wp_security_gate  # noqa: E402
MIB = 1024 * 1024
EXPECTED_GATE_CHECKS = (
    "execution_graph",
    "metadata_json",
    "structural",
    "unsafe_commands",
    "hardcoded_secrets",
    "php_syntax",
    "wp_api",
    "wp_security",
    "scan_handoff_cleanup",
    "output_reproof",
)
EXPECTED_HOLD_BREAKDOWN = {
    "sandbox-output": 3,
    "scan-handoff": 4,
    "synthesized-runtime": 2,
}


FixtureSpec = plan010_measurement_fixture.FixtureSpec
_sizes = plan010_measurement_fixture.sizes
_asset_sizes = plan010_measurement_fixture.asset_sizes
_write_fixture = plan010_measurement_fixture.write_fixture


@dataclass(frozen=True)
class Ceilings:
    certification_wall_seconds: float
    end_to_end_wall_seconds: float
    max_observed_process_rss_bytes: int
    output_entries: int
    output_bytes: int
    runtime_entries: int
    runtime_bytes: int
    php_candidates: int
    php_candidate_bytes: int
    bounded_invocations: int
    synthesized_bytes: int


AGGREGATE_FIXTURE = FixtureSpec(
    name="aggregate",
    entry_count=artifact_execution_graph.MAX_BLOCK_ENTRIES,
    output_bytes=artifact_execution_graph.MAX_BLOCK_OUTPUT_BYTES,
    runtime_bytes=artifact_execution_graph.MAX_RUNTIME_CLOSURE_BYTES,
    php_candidate_count=artifact_execution_graph.MAX_PHP_CANDIDATES,
    php_candidate_bytes=artifact_execution_graph.MAX_PHP_BYTES,
    asset_count=(artifact_execution_graph.MAX_METADATA_EDGES - 2) // 2,
    metadata_bytes=artifact_execution_graph.MAX_METADATA_BYTES,
    metadata_edges=artifact_execution_graph.MAX_METADATA_EDGES,
    metadata_depth=artifact_execution_graph.MAX_JSON_DEPTH,
    outside_php_candidates=1,
)
AGGREGATE_CEILINGS = Ceilings(
    certification_wall_seconds=180.0,
    end_to_end_wall_seconds=210.0,
    max_observed_process_rss_bytes=1536 * MIB,
    output_entries=artifact_execution_graph.MAX_BLOCK_ENTRIES,
    output_bytes=artifact_execution_graph.MAX_BLOCK_OUTPUT_BYTES,
    runtime_entries=1 + artifact_execution_graph.MAX_PHP_CANDIDATES + 255,
    runtime_bytes=artifact_execution_graph.MAX_RUNTIME_CLOSURE_BYTES,
    php_candidates=artifact_execution_graph.MAX_PHP_CANDIDATES,
    php_candidate_bytes=artifact_execution_graph.MAX_PHP_BYTES,
    bounded_invocations=artifact_execution_graph.MAX_PHP_CANDIDATES + 4,
    synthesized_bytes=artifact_execution_graph.MAX_RUNTIME_CLOSURE_BYTES + MIB,
)

MAXIMUM_MEMBER_FIXTURE = FixtureSpec(
    name="maximum_member",
    entry_count=6,
    output_bytes=16 * MIB,
    runtime_bytes=9 * MIB,
    php_candidate_count=1,
    php_candidate_bytes=64,
    asset_count=2,
    metadata_bytes=1024,
    metadata_edges=5,
    metadata_depth=3,
    outside_php_candidates=0,
    maximum_asset_bytes=artifact_execution_graph.MAX_RUNTIME_FILE_BYTES,
)
MAXIMUM_MEMBER_CEILINGS = Ceilings(
    certification_wall_seconds=180.0,
    end_to_end_wall_seconds=210.0,
    max_observed_process_rss_bytes=1536 * MIB,
    output_entries=MAXIMUM_MEMBER_FIXTURE.entry_count,
    output_bytes=MAXIMUM_MEMBER_FIXTURE.output_bytes,
    runtime_entries=1 + MAXIMUM_MEMBER_FIXTURE.php_candidate_count
    + MAXIMUM_MEMBER_FIXTURE.asset_count,
    runtime_bytes=MAXIMUM_MEMBER_FIXTURE.runtime_bytes,
    php_candidates=MAXIMUM_MEMBER_FIXTURE.php_candidate_count,
    php_candidate_bytes=MAXIMUM_MEMBER_FIXTURE.php_candidate_bytes,
    bounded_invocations=MAXIMUM_MEMBER_FIXTURE.php_candidate_count + 4,
    synthesized_bytes=MAXIMUM_MEMBER_FIXTURE.runtime_bytes + MIB,
)
CI_PROFILES = (
    (AGGREGATE_FIXTURE, AGGREGATE_CEILINGS),
    (MAXIMUM_MEMBER_FIXTURE, MAXIMUM_MEMBER_CEILINGS),
)


def _import_sandbox(source: Path, archive_path: Path, parent: Path):
    with tarfile.open(archive_path, mode="w") as archive:
        archive.add(source, arcname=".")
    with archive_path.open("rb") as stream:
        return artifact_staging.import_tar_stream(
            stream, parent, dependency_policy="strict"
        )


def _rss_bytes(who: int) -> int:
    value = resource.getrusage(who).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _manifest_metrics(manifest) -> tuple[int, int]:
    entries = tuple(manifest)
    return len(entries), sum(item.size for item in entries)


def _receipt(receipt) -> dict[str, Any]:
    return {
        "state": receipt.state,
        "exists": receipt.exists,
        "live": receipt.live,
        "error": receipt.error,
    }


def _process_observer(label, original, calls):
    def observed(command, **kwargs):
        record = {
            "phase": label,
            "program": Path(str(command[0])).name,
            "argument_count": len(command),
        }
        started = time.perf_counter()
        calls.append(record)
        try:
            result = original(command, **kwargs)
        except Exception as exc:
            record.update({
                "status": "blocked",
                "error_type": type(exc).__name__,
                "elapsed_seconds": time.perf_counter() - started,
            })
            raise
        record.update({
            "status": "bounded",
            "returncode": result.returncode,
            "stdout_bytes": len(result.stdout.encode()),
            "stderr_bytes": len(result.stderr.encode()),
            "elapsed_seconds": time.perf_counter() - started,
        })
        return result
    return observed


def _hold_observer(original, entries, exits):
    @contextmanager
    def observed(staged, **kwargs):
        role = staged.role.value
        entries[role] += 1
        try:
            with original(staged, **kwargs) as held:
                yield held
        finally:
            exits[role] += 1
    return observed


def _copy_observer(label, original, copies):
    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        copies[label]["members"] += 1
        copies[label]["bytes"] += result.size
        return result
    return observed


def _alias_copy_observer(original, copies):
    def observed(*args, **kwargs):
        size, digest = original(*args, **kwargs)
        copies["php_scanner_alias"]["members"] += 1
        copies["php_scanner_alias"]["bytes"] += size
        return size, digest
    return observed


def _observed_processes():
    return {
        "artifact_php_lint": (
            artifact_execution_gate, artifact_execution_gate.run_bounded
        ),
        "api_phpstan": (wp_api_lint, wp_api_lint.run_bounded),
        "security_phpcs": (wp_security_gate, wp_security_gate.run_bounded),
        "wrapper_php_lint": (
            runtime_artifact_pipeline, runtime_artifact_pipeline.run_bounded
        ),
    }


@contextmanager
def _observe_boundary():
    originals = _observed_processes()
    calls: list[dict[str, Any]] = []
    original_hold = artifact_staging.hold_staged_tree
    original_snapshot = artifact_staging.snapshot_held_tree
    original_scan_copy = artifact_staging._copy_held_file
    original_runtime_copy = artifact_runtime_staging._copy_member
    original_alias_copy = php_scanner_aliases._copy_verified
    hold_entries: Counter = Counter()
    hold_exits: Counter = Counter()
    copies = {
        "scan_handoff": {"members": 0, "bytes": 0},
        "runtime_stream": {"members": 0, "bytes": 0},
        "php_scanner_alias": {"members": 0, "bytes": 0},
    }
    materializations: list[str] = []

    def forbidden_snapshot(*_args, **_kwargs):
        materializations.append("snapshot_held_tree")
        raise RuntimeError("full-tree materialization is forbidden")

    for label, (module, original) in originals.items():
        module.run_bounded = _process_observer(label, original, calls)
    artifact_staging.hold_staged_tree = _hold_observer(
        original_hold, hold_entries, hold_exits
    )
    artifact_staging.snapshot_held_tree = forbidden_snapshot
    artifact_staging._copy_held_file = _copy_observer(
        "scan_handoff", original_scan_copy, copies
    )
    artifact_runtime_staging._copy_member = _copy_observer(
        "runtime_stream", original_runtime_copy, copies
    )
    php_scanner_aliases._copy_verified = _alias_copy_observer(
        original_alias_copy, copies
    )
    try:
        yield calls, hold_entries, hold_exits, copies, materializations
    finally:
        for module, original in originals.values():
            module.run_bounded = original
        artifact_staging.hold_staged_tree = original_hold
        artifact_staging.snapshot_held_tree = original_snapshot
        artifact_staging._copy_held_file = original_scan_copy
        artifact_runtime_staging._copy_member = original_runtime_copy
        php_scanner_aliases._copy_verified = original_alias_copy


def _cleanup(label: str, staged, cleanup: dict[str, Any]) -> None:
    if staged is None or label in cleanup:
        return
    if label == "synthesized_runtime":
        receipt = runtime_artifact_pipeline.cleanup_component(label, staged)
    else:
        receipt = artifact_staging.cleanup_staged_tree(staged)
    cleanup[label] = _receipt(receipt)


def _proof_metrics(proof) -> dict[str, Any]:
    prefix = proof.selected_root.rstrip("/") + "/"
    metadata = [
        item for item in proof.files if "metadata" in item.classifications
    ]
    return {
        "runtime_entries": len(proof.files),
        "runtime_bytes": sum(item.size for item in proof.files),
        "largest_runtime_member_bytes": max(item.size for item in proof.files),
        "metadata_bytes": metadata[0].size if len(metadata) == 1 else None,
        "metadata_edges": len(proof.edges),
        "php_candidate_count": len(proof.php_candidates),
        "php_candidate_bytes": sum(item.size for item in proof.php_candidates),
        "outside_selected_root_php_candidates": sum(
            not item.path.startswith(prefix) for item in proof.php_candidates
        ),
        "artifact_proof_digest": proof.artifact_proof_digest,
    }


def _prepare_fixture(spec, root, phases, metrics):
    phase = time.perf_counter()
    source, fixture = _write_fixture(root, spec)
    metadata_path = fixture / "blocks" / "card" / "build" / "block.json"
    metadata_value = json.loads(metadata_path.read_text(encoding="utf-8"))
    metrics["metadata_depth"] = plan010_measurement_fixture.json_depth(metadata_value)
    source_stage = artifact_staging.stage_tree(source, root / "source-stage")
    source_layout = artifact_layout.select_source_layout(source_stage.manifest)
    output = _import_sandbox(fixture, root / "fixture.tar", root / "sandbox-stage")
    phases["fixture_authentication_seconds"] = time.perf_counter() - phase
    metrics["authenticated_sandbox_output"] = artifact_staging.has_stage_authority(
        output, artifact_staging.StageRole.SANDBOX_OUTPUT
    )
    metrics["output_entries"], metrics["output_bytes"] = _manifest_metrics(
        output.manifest
    )
    return source_stage, source_layout, output


def _require_passing_gate(validation) -> None:
    if validation.proof is None or validation.gate.get("status") != "pass":
        raise RuntimeError(
            "artifact gate did not pass: "
            + json.dumps(validation.gate, sort_keys=True)[:1000]
        )


def _record_gate(validation, metrics, cleanup) -> None:
    metrics["gate_checks"] = [
        {"id": item["id"], "status": item["status"]}
        for item in validation.gate["checks"]
    ]
    if validation.proof is not None:
        metrics.update(_proof_metrics(validation.proof))
    for index, receipt in enumerate(validation.staging_receipts):
        cleanup[f"gate_handoff_{index}"] = _receipt(receipt)


def _record_observations(metrics, observations) -> None:
    calls, hold_entries, hold_exits, copies, materializations = observations
    breakdown = Counter(item["phase"] for item in calls)
    metrics.update({
        "bounded_invocation_count": len(calls),
        "bounded_invocation_breakdown": dict(sorted(breakdown.items())),
        "bounded_invocations": calls,
        "hold_entries": dict(sorted(hold_entries.items())),
        "hold_exits": dict(sorted(hold_exits.items())),
        "streamed_copies": copies,
        "full_tree_materialization_attempts": len(materializations),
    })


def _run_boundary(output, source_layout, root, deadline, phases, metrics, cleanup):
    observations = synthesized = None
    try:
        with _observe_boundary() as observations:
            phase = time.perf_counter()
            validation = artifact_execution_gate.validate_block_execution_artifact(
                output, source_layout, max(0.001, deadline - time.monotonic()),
                parent=root / "scan-handoff",
            )
            phases["artifact_gate_seconds"] = time.perf_counter() - phase
            _record_gate(validation, metrics, cleanup)
            _require_passing_gate(validation)
            phase = time.perf_counter()
            synthesized = runtime_artifact_pipeline.synthesize_block_runtime(
                output, validation.proof, root / "runtime", deadline
            )
            bound_gate = artifact_execution_gate.bind_runtime_gate(
                validation, synthesized.execution_proof
            )
            _record_runtime_proof(synthesized, bound_gate, phases, phase, metrics)
    except Exception:
        if synthesized is not None:
            _cleanup("synthesized_runtime", synthesized.staged, cleanup)
        raise
    finally:
        if observations is not None:
            _record_observations(metrics, observations)
    return synthesized


def _record_runtime_proof(synthesized, bound_gate, phases, phase, metrics):
    runtime_proof = synthesized.execution_proof
    phases["streamed_synthesis_seconds"] = time.perf_counter() - phase
    metrics["synthesized_entries"], metrics["synthesized_bytes"] = (
        _manifest_metrics(synthesized.staged.manifest)
    )
    metrics["execution_proof_digest"] = bound_gate["execution_proof_digest"]
    metrics["bound_artifact_digest"] = bound_gate["artifact_proof_digest"]
    metrics["runtime_artifact_digest"] = runtime_proof.artifact.artifact_proof_digest
    metrics["runtime_execution_proof_digest"] = runtime_proof.execution_proof_digest
    metrics["wrapper_validation_digest"] = runtime_proof.wrapper_validation_digest
    metrics["synthesized_manifest_sha256"] = runtime_proof.synthesized_manifest_sha256


def _record_resource_metrics(metrics, started) -> None:
    metrics["wall_time_seconds"] = time.perf_counter() - started
    self_rss = _rss_bytes(resource.RUSAGE_SELF)
    child_rss = _rss_bytes(resource.RUSAGE_CHILDREN)
    metrics.update({
        "self_peak_rss_bytes": self_rss,
        "child_peak_rss_bytes": child_rss,
        "max_observed_process_rss_bytes": max(self_rss, child_rss),
    })


def _measure_success(
    spec: FixtureSpec, ceilings: Ceilings, root: Path
) -> tuple[dict[str, Any], dict[str, float], dict[str, Any], Exception | None]:
    started = time.perf_counter()
    phases: dict[str, float] = {}
    cleanup: dict[str, Any] = {}
    metrics: dict[str, Any] = {}
    error = None
    source_stage = output = synthesized = None
    try:
        source_stage, source_layout, output = _prepare_fixture(
            spec, root, phases, metrics
        )
        certification_started = time.perf_counter()
        deadline = time.monotonic() + ceilings.certification_wall_seconds
        synthesized = _run_boundary(
            output, source_layout, root, deadline, phases, metrics, cleanup
        )
        metrics["certification_wall_seconds"] = (
            time.perf_counter() - certification_started
        )
    except Exception as exc:
        error = exc
    finally:
        phase = time.perf_counter()
        _cleanup(
            "synthesized_runtime", synthesized.staged if synthesized else None, cleanup
        )
        _cleanup("sandbox_output", output, cleanup)
        _cleanup("source_input", source_stage, cleanup)
        phases["cleanup_seconds"] = time.perf_counter() - phase
    _record_resource_metrics(metrics, started)
    return metrics, phases, cleanup, error


def _boundary(spec: FixtureSpec) -> dict[str, Any]:
    return {
        "name": f"plan010-{spec.name}-reviewed-boundary",
        "fixture_targets": asdict(spec),
        "exercises": [
            "authenticated SANDBOX_OUTPUT import",
            "exact execution graph and scan-handoff authentication",
            f"{spec.php_candidate_count} top-level bounded PHP syntax invocations",
            "one top-level bounded PHPStan invocation",
            "two top-level bounded PHPCS suppression-differential invocations",
            "two authenticated PHP scanner-alias copy passes",
            "proof-file-only streamed runtime synthesis and wrapper PHP lint",
            "artifact/wrapper/synthesized-runtime digest binding and cleanup",
        ],
        "does_not_exercise": [
            "Docker, wp-env, WordPress, browser, or database runtime",
            "production throughput, concurrency, or arbitrary workloads",
            "dynamic PHP includes, eval-generated code, or JavaScript reachability",
        ],
    }


def _expected_invocation_breakdown(spec: FixtureSpec) -> dict[str, int]:
    return {
        "artifact_php_lint": spec.php_candidate_count,
        "api_phpstan": 1,
        "security_phpcs": 2,
        "wrapper_php_lint": 1,
    }


def _expected_largest_member(spec: FixtureSpec) -> int:
    asset_bytes = spec.runtime_bytes - spec.php_candidate_bytes - spec.metadata_bytes
    return max(
        spec.metadata_bytes,
        max(_sizes(spec.php_candidate_bytes, spec.php_candidate_count, 32)),
        max(_asset_sizes(spec, asset_bytes)),
    )


def _exact_expectations(spec: FixtureSpec) -> dict[str, Any]:
    invocation_breakdown = _expected_invocation_breakdown(spec)
    runtime_entries = 1 + spec.php_candidate_count + spec.asset_count
    return {
        "output_entries": spec.entry_count,
        "output_bytes": spec.output_bytes,
        "runtime_entries": runtime_entries,
        "runtime_bytes": spec.runtime_bytes,
        "largest_runtime_member_bytes": _expected_largest_member(spec),
        "metadata_bytes": spec.metadata_bytes,
        "metadata_edges": spec.metadata_edges,
        "metadata_depth": spec.metadata_depth,
        "php_candidate_count": spec.php_candidate_count,
        "php_candidate_bytes": spec.php_candidate_bytes,
        "outside_selected_root_php_candidates": spec.outside_php_candidates,
        "bounded_invocation_count": sum(invocation_breakdown.values()),
        "bounded_invocation_breakdown": invocation_breakdown,
    }


def _limit_checks(metrics: dict[str, Any], ceilings: Ceilings) -> dict[str, Any]:
    mapping = {
        "certification_wall_seconds": ceilings.certification_wall_seconds,
        "wall_time_seconds": ceilings.end_to_end_wall_seconds,
        "max_observed_process_rss_bytes": ceilings.max_observed_process_rss_bytes,
        "output_entries": ceilings.output_entries,
        "output_bytes": ceilings.output_bytes,
        "runtime_entries": ceilings.runtime_entries,
        "runtime_bytes": ceilings.runtime_bytes,
        "php_candidate_count": ceilings.php_candidates,
        "php_candidate_bytes": ceilings.php_candidate_bytes,
        "bounded_invocation_count": ceilings.bounded_invocations,
        "synthesized_bytes": ceilings.synthesized_bytes,
    }
    return {
        key: {
            "observed": metrics.get(key),
            "ceiling": limit,
            "pass": isinstance(metrics.get(key), (int, float))
            and not isinstance(metrics.get(key), bool)
            and metrics[key] <= limit,
        }
        for key, limit in mapping.items()
    }


def _semantic_violations(record, metrics, spec) -> list[str]:
    violations = []
    gate_checks = tuple(item.get("id") for item in metrics.get("gate_checks", []))
    if gate_checks != EXPECTED_GATE_CHECKS or any(
        item.get("status") != "pass" for item in metrics.get("gate_checks", [])
    ):
        violations.append("gate_checks")
    if not metrics.get("authenticated_sandbox_output"):
        violations.append("output_authentication")
    artifact_digests = {
        metrics.get("artifact_proof_digest"),
        metrics.get("bound_artifact_digest"),
        metrics.get("runtime_artifact_digest"),
    }
    if len(artifact_digests) != 1 or None in artifact_digests:
        violations.append("artifact_digest_binding")
    if metrics.get("execution_proof_digest") != metrics.get("runtime_execution_proof_digest"):
        violations.append("execution_digest_binding")
    invocations = metrics.get("bounded_invocations", [])
    if len(invocations) != sum(_expected_invocation_breakdown(spec).values()) or any(
        item.get("status") != "bounded" or item.get("returncode") != 0
        for item in invocations
    ):
        violations.append("subprocess_observation")
    if metrics.get("hold_entries") != EXPECTED_HOLD_BREAKDOWN:
        violations.append("hold_entries")
    if metrics.get("hold_exits") != EXPECTED_HOLD_BREAKDOWN:
        violations.append("hold_exits")
    violations.extend(_copy_violations(metrics, spec))
    if metrics.get("full_tree_materialization_attempts") != 0:
        violations.append("full_tree_materialization")
    cleanup = record.get("cleanup", {})
    if not cleanup or any(
        item.get("state") != "removed"
        or item.get("exists")
        or item.get("live")
        or item.get("error")
        for item in cleanup.values()
    ):
        violations.append("cleanup")
    return violations


def _copy_violations(metrics, spec) -> list[str]:
    expected = {
        "members": 1 + spec.php_candidate_count + spec.asset_count,
        "bytes": spec.runtime_bytes,
    }
    alias = {
        "members": 2 * spec.php_candidate_count,
        "bytes": 2 * spec.php_candidate_bytes,
    }
    copies = metrics.get("streamed_copies", {})
    checks = {
        "scan_handoff_copy": copies.get("scan_handoff") == expected,
        "runtime_stream_copy": copies.get("runtime_stream") == expected,
        "php_scanner_alias_copy": copies.get("php_scanner_alias") == alias,
    }
    return [name for name, passed in checks.items() if not passed]


def assess(
    record: dict[str, Any], spec: FixtureSpec, ceilings: Ceilings
) -> dict[str, Any]:
    metrics = record.get("metrics", {})
    checks = _limit_checks(metrics, ceilings)
    violations = [key for key, check in checks.items() if not check["pass"]]
    for key, expected in _exact_expectations(spec).items():
        if metrics.get(key) != expected:
            violations.append(f"exact_{key}")
    violations.extend(_semantic_violations(record, metrics, spec))
    record["ceiling_checks"] = checks
    record["violations"] = sorted(set(violations))
    record["status"] = "pass" if not violations and "error" not in record else "fail"
    return record


def measure(spec: FixtureSpec, ceilings: Ceilings, parent: Path) -> dict[str, Any]:
    spec.validate()
    record = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "boundary": _boundary(spec),
        "ceilings": asdict(ceilings),
    }
    metrics, phases, cleanup, error = _measure_success(spec, ceilings, parent)
    record.update({"metrics": metrics, "phases": phases, "cleanup": cleanup})
    if error is not None:
        record["error"] = {
            "type": type(error).__name__,
            "detail": str(error)[:1000],
        }
    return assess(record, spec, ceilings)


def measure_profiles(profiles, parent: Path) -> dict[str, Any]:
    records = {}
    for spec, ceilings in profiles:
        profile_root = parent / spec.name
        profile_root.mkdir()
        records[spec.name] = measure(spec, ceilings, profile_root)
    toolchain = plan010_measurement_evidence.toolchain_evidence()
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "toolchain": toolchain,
        "profiles": records,
        "status": "pass"
        if toolchain["status"] == "pass"
        and records and all(item["status"] == "pass" for item in records.values())
        else "fail",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=("ci", "aggregate", "maximum_member"), default="ci"
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    temporary_parent = ROOT / "tmp"
    temporary_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="plan010-performance-", dir=temporary_parent
    ) as temporary:
        profiles = CI_PROFILES if args.profile == "ci" else tuple(
            item for item in CI_PROFILES if item[0].name == args.profile
        )
        record = measure_profiles(profiles, Path(temporary).resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if record["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
