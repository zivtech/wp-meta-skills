"""Capability-preserving preparation of generated artifacts for runtime proof."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from shutil import which as find_executable

import artifact_execution
import artifact_execution_graph
import artifact_runtime_staging
import artifact_staging
import block_runtime_wrapper
import workspace_lease
from bounded_subprocess import BoundedProcessError, run_bounded


WRAPPER_OUTPUT_LIMIT = 64 * 1024


class BlockProofOrigin(str, Enum):
    """Authenticated artifact origin accepted for block runtime synthesis."""

    SOURCE_ONLY_CALLER_INPUT = "source-only-caller-input"
    BUILT_SANDBOX_OUTPUT = "built-sandbox-output"


@dataclass(frozen=True)
class BuildResult:
    status: str
    detail: str
    command: tuple[str, ...]
    output: artifact_staging.StagedTree | None
    staging_cleanup_receipts: tuple[artifact_staging.StagingCleanupReceipt, ...] = ()


@dataclass(frozen=True)
class SynthesizedRuntime:
    staged: artifact_staging.StagedTree
    source_role: artifact_staging.StageRole
    plugin_slug: str
    block_name: str | None = None
    textdomain: str | None = None
    block_relative: Path | None = None
    execution_proof: artifact_execution_graph.RuntimeExecutionProof | None = None
    block_proof_origin: BlockProofOrigin | None = None

    @property
    def plugin_dir(self) -> Path:
        return self.staged.root / self.plugin_slug


@dataclass(frozen=True)
class CleanupReceipt:
    component: str
    state: str
    exists: bool
    live: bool
    recovery_path: str | None
    error: str | None
    resource_path: str | None = None


def cleanup_receipt_from_staging(component: str, receipt: artifact_staging.StagingCleanupReceipt) -> CleanupReceipt:
    return CleanupReceipt(
        component,receipt.state,receipt.exists,receipt.live,
        receipt.recovery_path,receipt.error,str(receipt.root),
    )


class RuntimePreparationError(RuntimeError):
    def __init__(self, primary: Exception, receipts):
        self.primary=primary; self.receipts=tuple(receipts)
        super().__init__(f"{type(primary).__name__}: {primary}")


class RuntimeInputCleanupError(RuntimeError):
    def __init__(self, primary: Exception, receipt):
        self.primary=primary; self.receipt=receipt
        cleanup=receipt.error or f"input copy remains {receipt.state}"
        super().__init__(f"{type(primary).__name__}: {primary}; cleanup: {cleanup}")


def _authentic_role(staged: artifact_staging.StagedTree, role: artifact_staging.StageRole) -> bool:
    try:
        artifact_staging.verify_staged_tree(staged)
    except (TypeError, ValueError, RuntimeError, OSError):
        return False
    return artifact_staging.has_stage_authority(staged, role)


def build_block(staged: artifact_staging.StagedTree, timeout: int) -> BuildResult:
    artifact_staging.verify_staged_tree(staged)
    outcome = artifact_execution.run_generated(staged, "npm-build", timeout)
    if outcome.status != "pass":
        return BuildResult(outcome.status,outcome.detail,outcome.command,None,outcome.staging_cleanup_receipts)
    if outcome.output is None:
        return BuildResult(
            "blocked","npm-build passed without a sandbox output capability",outcome.command,None,
            outcome.staging_cleanup_receipts,
        )
    if not _authentic_role(outcome.output, artifact_staging.StageRole.SANDBOX_OUTPUT):
        return BuildResult(
            "blocked","npm-build returned an unauthenticated sandbox output",outcome.command,None,
            outcome.staging_cleanup_receipts,
        )
    return BuildResult("pass",outcome.detail,outcome.command,outcome.output,outcome.staging_cleanup_receipts)


def _safe_slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part)[:48] or "generated-block"


def _runtime_metadata(content: bytes) -> dict:
    metadata = json.loads(content.decode("utf-8"))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise ValueError("block.json must contain a block name")
    if not metadata["name"]:
        raise ValueError("block.json must contain a non-empty block name")
    if "textdomain" in metadata and not isinstance(metadata["textdomain"], str):
        raise ValueError("block.json textdomain must be a string")
    return metadata


def _php_single_quoted_literal(value: str) -> str:
    return block_runtime_wrapper.php_single_quoted_literal(value)


def _block_wrapper(textdomain: str, selected_block_json: str) -> bytes:
    return block_runtime_wrapper.build(textdomain, selected_block_json)


def _block_extras(proof, metadata: dict, textdomain: str):
    wrapper = Path(textdomain) / f"{textdomain}.php"
    wrapper_bytes = _block_wrapper(textdomain, proof.selected_block_json)
    readme_bytes = f"Generated runtime wrapper for {metadata['name']}.\n".encode()
    extras = (
        artifact_runtime_staging.ExtraFile(wrapper.as_posix(), wrapper_bytes),
        artifact_runtime_staging.ExtraFile(
            (Path(textdomain) / "readme.txt").as_posix(), readme_bytes
        ),
    )
    return extras, wrapper.as_posix(), wrapper_bytes


def _owned_synthesized(staged, *args) -> SynthesizedRuntime:
    try:
        return SynthesizedRuntime(staged,*args)
    except Exception as primary:
        receipt=cleanup_component("synthesized_runtime",staged)
        raise RuntimePreparationError(primary,[receipt]) from primary


def _stage_synthesized(snapshot, parent):
    try:
        return artifact_staging._stage_synthesized_snapshot(snapshot,parent)
    except artifact_staging.StagingCleanupError as error:
        receipt=cleanup_receipt_from_staging("synthesized_runtime",error.receipt)
        raise RuntimePreparationError(error.primary,[receipt]) from error


def _verify_block_proof(output, proof) -> BlockProofOrigin:
    if not isinstance(proof, artifact_execution_graph.BlockExecutionProof):
        raise TypeError("block synthesis requires a BlockExecutionProof")
    artifact_execution_graph._validate_artifact_proof(proof)
    digest = artifact_staging.manifest_sha256(output.manifest)
    if digest != proof.output_manifest_sha256:
        raise ValueError("block synthesis input manifest does not match execution proof")
    if _authentic_role(output, artifact_staging.StageRole.SANDBOX_OUTPUT):
        return BlockProofOrigin.BUILT_SANDBOX_OUTPUT
    if not _authentic_role(output, artifact_staging.StageRole.CALLER_INPUT):
        raise ValueError("block synthesis requires an authentic caller input or sandbox output")
    source_only = (
        proof.selection_reason == "source_block_json"
        and proof.output_manifest_sha256 == proof.source_manifest_sha256
    )
    if not source_only:
        raise ValueError(
            "caller-input block synthesis requires a source-only proof over the exact input manifest"
        )
    return BlockProofOrigin.SOURCE_ONLY_CALLER_INPUT


def _stream_proven_output(output, proof, parent, deadline=None):
    staged = None
    try:
        with artifact_staging.hold_staged_tree(
            output, proof_deadline=deadline
        ) as held:
            digest = artifact_staging.manifest_sha256(held.proof.manifest)
            if digest != proof.output_manifest_sha256:
                raise ValueError("held output manifest does not match execution proof")
            content = artifact_staging.read_held_member(
                held, proof.selected_block_json
            )
            metadata = _runtime_metadata(content)
            slug = _safe_slug(
                metadata.get("textdomain") or metadata["name"].split("/")[-1]
            )
            extras, wrapper_path, wrapper_bytes = _block_extras(
                proof, metadata, slug
            )
            staged = artifact_runtime_staging.stage_prefixed_runtime(
                held,
                f"{slug}/generated",
                (item.path for item in proof.files),
                extras,
                parent,
            )
    except Exception as primary:
        if staged is None:
            raise
        receipt = cleanup_component("synthesized_runtime", staged)
        raise RuntimePreparationError(primary, [receipt]) from primary
    return staged, metadata, slug, wrapper_path, wrapper_bytes


def _is_php_candidate(held, path: str) -> bool:
    lowered = path.casefold()
    if any(lowered.endswith(suffix) for suffix in artifact_execution_graph.PHP_SUFFIXES):
        return True
    return artifact_staging.held_member_has_php_tag(held, path)


def _expected_runtime_php(proof, slug, wrapper_path, wrapper_bytes):
    expected = {
        f"{slug}/generated/{item.path}": item.sha256
        for item in proof.php_candidates
    }
    expected[wrapper_path] = artifact_execution_graph.sha256_bytes(wrapper_bytes)
    return expected


def _verify_synthesized_closure(
    staged, proof, slug, wrapper_path, wrapper_bytes, deadline=None
):
    expected = _expected_runtime_php(proof, slug, wrapper_path, wrapper_bytes)
    with artifact_staging.hold_staged_tree(
        staged, proof_deadline=deadline
    ) as held:
        index = {item.path: item for item in held.proof.manifest}
        observed = {
            path for path in sorted(index) if _is_php_candidate(held, path)
        }
        if observed != set(expected):
            raise ValueError("synthesized executable-PHP closure does not match proof")
        if any(index[path].sha256 != digest for path, digest in expected.items()):
            raise ValueError("synthesized executable-PHP closure hash mismatch")


def _validate_wrapper(staged, proof, wrapper_path, wrapper_bytes, deadline=None):
    php = find_executable("php")
    if php is None:
        raise ValueError("wrapper PHP syntax validation requires php")
    process_deadline = deadline or time.monotonic() + 30
    with artifact_staging.hold_staged_tree(
        staged, proof_deadline=process_deadline
    ) as held:
        observed = artifact_staging.read_held_member(held, wrapper_path)
        if observed != wrapper_bytes:
            raise ValueError("synthesized wrapper bytes do not match proof input")
        try:
            result = run_bounded(
                [php, "-l", str(staged.root / wrapper_path)],
                deadline_monotonic=process_deadline,
                stdout_limit=WRAPPER_OUTPUT_LIMIT,
                stderr_limit=WRAPPER_OUTPUT_LIMIT,
            )
        except (BoundedProcessError, OSError) as exc:
            raise ValueError(f"wrapper PHP syntax validation blocked: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ValueError(f"wrapper PHP syntax failed: {detail[:200]}")
    return artifact_execution_graph.build_wrapper_validation(
        wrapper_bytes, proof.selected_block_json, php_syntax_passed=True
    )


def _finish_block_runtime(
    staged, output, proof, metadata, slug, wrapper_path, wrapper_bytes,
    proof_origin, deadline=None,
):
    try:
        _verify_synthesized_closure(
            staged, proof, slug, wrapper_path, wrapper_bytes, deadline
        )
        wrapper_validation = _validate_wrapper(
            staged, proof, wrapper_path, wrapper_bytes, deadline
        )
        manifest = artifact_staging.manifest_sha256(staged.manifest)
        execution_proof = artifact_execution_graph.bind_runtime_proof(
            proof, wrapper_path, wrapper_bytes, manifest, wrapper_validation
        )
        return SynthesizedRuntime(
            staged, output.role, slug, metadata["name"], slug,
            Path(proof.selected_root), execution_proof, proof_origin,
        )
    except Exception as primary:
        receipt = cleanup_component("synthesized_runtime", staged)
        raise RuntimePreparationError(primary, [receipt]) from primary


def synthesize_block_runtime(
    output: artifact_staging.StagedTree,
    proof: artifact_execution_graph.BlockExecutionProof,
    parent: Path | None = None,
    deadline: float | None = None,
) -> SynthesizedRuntime:
    proof_origin = _verify_block_proof(output, proof)
    try:
        staged, metadata, slug, wrapper_path, wrapper_bytes = _stream_proven_output(
            output, proof, parent, deadline
        )
    except artifact_staging.StagingCleanupError as error:
        receipt = cleanup_receipt_from_staging(
            "synthesized_runtime", error.receipt
        )
        raise RuntimePreparationError(error.primary, [receipt]) from error
    return _finish_block_runtime(
        staged, output, proof, metadata, slug, wrapper_path, wrapper_bytes,
        proof_origin, deadline,
    )


def synthesize_plugin_runtime(source: artifact_staging.StagedTree, plugin_slug: str, parent: Path | None = None) -> SynthesizedRuntime:
    slug = _safe_slug(plugin_slug)
    with artifact_staging.hold_staged_tree(source) as held:
        snapshot = [
            (Path(slug) / path, content, info)
            for path, content, info in artifact_staging.snapshot_held_tree(held)
        ]
    staged = _stage_synthesized(snapshot,parent)
    return _owned_synthesized(staged,source.role,slug)


def _retention_state(staged: artifact_staging.StagedTree) -> tuple[str, bool, bool]:
    exists = staged.lease.root.exists() or staged.lease.root.is_symlink()
    live = workspace_lease._LIVE_LEASES.get(staged.lease.lease_id) is staged.lease
    state = "retained" if exists else "unknown" if live else "removed"
    return state, exists, live


def _sanitized_recovery_path(staged: artifact_staging.StagedTree, retained: bool) -> str | None:
    if not retained:
        return None
    return str(staged.root)


def cleanup_component(component: str, staged: artifact_staging.StagedTree) -> CleanupReceipt:
    error = None
    try:
        workspace_lease.cleanup(staged.lease)
    except Exception as exc:
        error = f"{type(exc).__name__}: cleanup did not complete normally"
    state, exists, live = _retention_state(staged)
    retained = exists or live
    return CleanupReceipt(component, state, exists, live, _sanitized_recovery_path(staged, retained), error, str(staged.root))


def observe_component(component: str, staged: artifact_staging.StagedTree) -> CleanupReceipt:
    state, exists, live = _retention_state(staged)
    retained = exists or live
    return CleanupReceipt(component, state, exists, live, _sanitized_recovery_path(staged, retained), None, str(staged.root))


def cleanup_preparation(synthesized, output):
    receipts=[]
    if synthesized is not None:
        receipts.append(cleanup_component("synthesized_runtime",synthesized.staged))
    if output is not None:
        receipts.append(cleanup_component("sandbox_output",output))
    return receipts


def _receipt_dict(receipt: CleanupReceipt) -> dict:
    return {
        "component": receipt.component, "state": receipt.state,
        "exists": receipt.exists, "live": receipt.live,
        "resource_path": receipt.resource_path,
        "recovery_path": receipt.recovery_path, "error": receipt.error,
    }


def _component_summary(component: str, receipts: list[CleanupReceipt]) -> dict:
    matches = [receipt for receipt in receipts if receipt.component == component]
    if not matches:
        return _receipt_dict(CleanupReceipt(component,"not_created",False,False,None,None))
    retained = [receipt for receipt in matches if receipt.exists or receipt.live]
    selected = retained[0] if retained else matches[-1]
    summary = _receipt_dict(selected)
    summary["resources"] = [_receipt_dict(receipt) for receipt in matches]
    summary["errors"] = [receipt.error for receipt in matches if receipt.error]
    return summary


def retention_summary(receipts: list[CleanupReceipt]) -> dict:
    materialized = list(receipts)
    return {
        "retained": any(receipt.exists or receipt.live for receipt in materialized),
        "components": {
            component: _component_summary(component, materialized)
            for component in ("input_copy", "sandbox_output", "synthesized_runtime")
        },
        "resources": [_receipt_dict(receipt) for receipt in materialized],
    }


def staging_failure_result(
    *, artifact_type, artifact_path, source_path, profile, required_tools,
    runtime_roots, detail, receipts=(),
):
    items=list(receipts); retention=retention_summary(items)
    cleanup=[receipt for receipt in items if receipt.state!="removed" or receipt.error]
    checks=[{"id":"artifact_staging","status":"blocked","required":True,"detail":detail,"command":None}]
    checks.extend({
        "id":"artifact_cleanup","status":"blocked","required":True,
        "detail":receipt.error or f"input copy remains {receipt.state}","command":None,
    } for receipt in cleanup)
    execution_copy=(items[0].recovery_path or items[0].resource_path) if items else None
    return {
        "artifact_type":artifact_type,"artifact_path":artifact_path,"source_path":source_path,
        "execution_copy":execution_copy,"manifest_sha256":None,
        "sandbox_posture":{
            "generated_execution":"blocked","host_fallback":False,"static_scan_root":"unavailable",
        },
        "execution_retained":retention["retained"],"artifact_retention":retention,
        "profile":profile,"required_tools":required_tools,"runtime_roots":runtime_roots,
        "status":"blocked","pass":False,"checks":checks,
        "artifact_execution_cleanup_error":cleanup[0].error if cleanup else None,
    }
